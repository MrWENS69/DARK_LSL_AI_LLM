"""Tree-walking interpreter for one LSL script.

Semantics implemented here (see skills/lsl-dev/references/lsl-for-ai.md):
- strict types, implicit conversions only integer->float and string<->key;
- both operands of a binary operator are evaluated, right one first;
- && and || never short-circuit;
- integer arithmetic wraps to 32 bits, division truncates, / and % by zero
  raise "Math Error";
- floats are single precision;
- state changes run state_exit, clear the event queue, release listens,
  then state_entry of the new state;
- jump/labels within a function or event handler.
"""

from . import ast
from .errors import ScriptError, UnsupportedError
from .parser import parse
from .values import (Key, Vector, Rotation, binary, cast, coerce, default_value, truthy, type_of, unary,
                     to_int32, f32, ZERO_VECTOR, ZERO_ROTATION, NULL_KEY)


class ReturnSignal(Exception):
    def __init__(self, value):
        Exception.__init__(self)
        self.value = value


class JumpSignal(Exception):
    def __init__(self, label):
        Exception.__init__(self)
        self.label = label


class StateChangeSignal(Exception):
    def __init__(self, name):
        Exception.__init__(self)
        self.name = name


class ScriptDied(Exception):
    """Raised to unwind after a ScriptError has been recorded."""


MAX_CALL_DEPTH = 150


class Script(object):
    """One script instance: program, globals, current state, and a link to its simulator."""

    def __init__(self, sim, obj, source, name="script"):
        self.sim = sim
        self.obj = obj
        self.name = name
        self.source = source
        self.program = parse(source)
        self.globals = {}
        self.state = "default"
        self.running = True            # llSetScriptState / run-time error
        self.dead = False              # stopped by a run-time error
        self.error = None              # ScriptError that killed it
        self.listens = {}              # handle -> dict(channel, name, id, msg, active)
        self.next_listen = 1
        self.timer_interval = 0.0
        self.timer_due = None
        self.sensor_repeat = None
        self.queue = []                # pending events: (name, args, detected)
        self.dropped_events = 0
        self.permissions = 0
        self.permissions_key = NULL_KEY
        self.start_param = 0
        self.start_time = sim.time
        self.memory_limit = 65536
        self.detected = []             # llDetected* data of the running event
        self.current_event = None
        self.http_requests = set()
        self.urls = set()
        self.depth = 0
        self.statements_run = 0
        self.max_statements = 2000000
        self.reset_globals()

    # --- lifecycle ---------------------------------------------------------

    def reset_globals(self):
        self.globals = {}
        for decl in self.program.globals:
            value = default_value(decl.type)
            if decl.value is not None:
                value = coerce(self.eval_expr(decl.value), decl.type)
            self.globals[decl.name] = value

    def reset(self):
        """llResetScript / Reset Scripts: globals, listens, timers, queue, default state."""
        self.release_listens()
        self.timer_interval = 0.0
        self.timer_due = None
        self.sensor_repeat = None
        self.queue = []
        self.permissions = 0
        self.permissions_key = NULL_KEY
        self.state = "default"
        self.dead = False
        self.error = None
        self.running = True
        self.start_time = self.sim.time
        for url in list(self.urls):
            self.sim.release_url(self, url)
        self.reset_globals()
        self.post("state_entry", [])

    def release_listens(self):
        self.listens = {}

    def handles_event(self, name, state=None):
        state_node = self.program.states.get(state or self.state)
        return state_node is not None and name in state_node.events

    def post(self, name, args, detected=None):
        """Queue an event. The queue holds 64 events; more are dropped silently."""
        if not self.running or self.dead:
            return False
        if not self.handles_event(name):
            return False
        if len(self.queue) >= 64:
            self.dropped_events += 1
            return False
        self.queue.append((name, list(args), list(detected or [])))
        return True

    def run_pending(self):
        """Run queued events in order until the queue is empty. Returns the number run."""
        count = 0
        while self.queue and self.running and not self.dead:
            name, args, detected = self.queue.pop(0)
            self.dispatch(name, args, detected)
            count += 1
        return count

    def dispatch(self, name, args, detected):
        state_node = self.program.states[self.state]
        handler = state_node.events.get(name)
        if handler is None:
            return
        self.detected = detected
        self.current_event = name
        try:
            self.call_function(handler, args)
        except StateChangeSignal as change:
            self.change_state(change.name)
        except ScriptError as err:
            self.die(err)
        finally:
            self.current_event = None
            self.detected = []

    def die(self, err):
        self.dead = True
        self.error = err
        self.sim.record_error(self, err)

    def change_state(self, name):
        if name == self.state:
            return
        if name not in self.program.states:
            raise ScriptError("Script run-time error", "unknown state %s" % name)
        if self.handles_event("state_exit"):
            handler = self.program.states[self.state].events["state_exit"]
            try:
                self.call_function(handler, [])
            except StateChangeSignal:
                pass
        self.queue = []
        self.release_listens()
        self.sensor_repeat = None
        self.state = name
        # state_entry of the new state runs next, ahead of anything else
        if self.handles_event("state_entry"):
            self.queue.insert(0, ("state_entry", [], []))

    # --- functions -----------------------------------------------------------

    def call_function(self, func, args):
        if len(args) != len(func.params):
            raise ScriptError("Type mismatch", "%s expects %d arguments" % (func.name, len(func.params)))
        scope = {}
        for (ptype, pname), value in zip(func.params, args):
            scope[pname] = coerce(value, ptype)
        self.depth += 1
        if self.depth > MAX_CALL_DEPTH:
            self.depth = 0
            raise ScriptError("Stack-Heap Collision", "call depth over %d" % MAX_CALL_DEPTH)
        try:
            self.exec_block(func.body, [scope])
        except ReturnSignal as ret:
            if func.return_type is None:
                return None
            if ret.value is None:
                return default_value(func.return_type)
            return coerce(ret.value, func.return_type)
        except JumpSignal as jump:
            raise ScriptError("Script run-time error", "jump to unknown label %s" % jump.label)
        finally:
            self.depth -= 1
        if func.return_type is not None:
            return default_value(func.return_type)
        return None

    # --- statements ----------------------------------------------------------

    def exec_block(self, block, scopes):
        statements = block.statements
        index = 0
        scopes = scopes + [{}] if block is not None else scopes
        while index < len(statements):
            stmt = statements[index]
            try:
                self.exec_stmt(stmt, scopes)
                index += 1
            except JumpSignal as jump:
                target = self.find_label(statements, jump.label)
                if target is None:
                    raise
                index = target + 1

    @staticmethod
    def find_label(statements, label):
        for i, stmt in enumerate(statements):
            if isinstance(stmt, ast.Label) and stmt.name == label:
                return i
        return None

    def exec_stmt(self, stmt, scopes):
        self.statements_run += 1
        if self.statements_run > self.max_statements:
            raise ScriptError("Script run-time error", "statement budget exhausted (infinite loop?)")
        kind = type(stmt)
        if kind is ast.ExprStatement:
            self.eval_expr(stmt.expr, scopes)
        elif kind is ast.Declaration:
            value = default_value(stmt.type)
            if stmt.value is not None:
                value = coerce(self.eval_expr(stmt.value, scopes), stmt.type)
            scopes[-1][stmt.name] = value
        elif kind is ast.Block:
            self.exec_block(stmt, scopes)
        elif kind is ast.If:
            if truthy(self.eval_expr(stmt.cond, scopes)):
                self.exec_stmt(stmt.then, scopes + [{}])
            elif stmt.otherwise is not None:
                self.exec_stmt(stmt.otherwise, scopes + [{}])
        elif kind is ast.While:
            while truthy(self.eval_expr(stmt.cond, scopes)):
                self.exec_stmt(stmt.body, scopes + [{}])
        elif kind is ast.DoWhile:
            while True:
                self.exec_stmt(stmt.body, scopes + [{}])
                if not truthy(self.eval_expr(stmt.cond, scopes)):
                    break
        elif kind is ast.For:
            for expr in stmt.init:
                self.eval_expr(expr, scopes)
            while truthy(self.eval_expr(stmt.cond, scopes)):
                self.exec_stmt(stmt.body, scopes + [{}])
                for expr in stmt.step:
                    self.eval_expr(expr, scopes)
        elif kind is ast.Return:
            value = None if stmt.value is None else self.eval_expr(stmt.value, scopes)
            raise ReturnSignal(value)
        elif kind is ast.StateChange:
            raise StateChangeSignal(stmt.name)
        elif kind is ast.Jump:
            raise JumpSignal(stmt.label)
        elif kind is ast.Label or kind is ast.Empty:
            pass
        else:
            raise UnsupportedError("statement %s" % kind.__name__)

    # --- variables -----------------------------------------------------------

    def lookup(self, name, scopes):
        for scope in reversed(scopes):
            if name in scope:
                return scope[name]
        if name in self.globals:
            return self.globals[name]
        const = self.sim.constants.get(name)
        if const is not None:
            return const
        raise ScriptError("Script run-time error", "unknown variable %s" % name)

    def store(self, name, value, scopes):
        for scope in reversed(scopes):
            if name in scope:
                scope[name] = coerce(value, type_of(scope[name]))
                return scope[name]
        if name in self.globals:
            self.globals[name] = coerce(value, type_of(self.globals[name]))
            return self.globals[name]
        raise ScriptError("Script run-time error", "assignment to unknown variable %s" % name)

    def read_target(self, target, scopes):
        value = self.lookup(target.name, scopes)
        if target.member is None:
            return value
        return self.member(value, target.member)

    def write_target(self, target, value, scopes):
        if target.member is None:
            return self.store(target.name, value, scopes)
        current = self.lookup(target.name, scopes)
        component = coerce(value, "float")
        index = "xyzs".index(target.member)
        parts = list(current)
        parts[index] = component
        rebuilt = Vector(*parts) if isinstance(current, Vector) else Rotation(*parts)
        self.store(target.name, rebuilt, scopes)
        return component

    @staticmethod
    def member(value, name):
        if isinstance(value, Vector) and name in "xyz":
            return value["xyz".index(name)]
        if isinstance(value, Rotation) and name in "xyzs":
            return value["xyzs".index(name)]
        raise ScriptError("Type mismatch", "no member .%s on %s" % (name, type_of(value)))

    # --- expressions ---------------------------------------------------------

    def eval_expr(self, expr, scopes=None):
        if scopes is None:
            scopes = []
        kind = type(expr)
        if kind is ast.Literal:
            value = expr.value
            return f32(value) if isinstance(value, float) else value
        if kind is ast.Name:
            return self.read_target(expr, scopes)
        if kind is ast.Binary:
            # right operand first, then left: LSL evaluates right to left and never short-circuits
            right = self.eval_expr(expr.right, scopes)
            left = self.eval_expr(expr.left, scopes)
            return binary(expr.op, left, right)
        if kind is ast.Unary:
            return unary(expr.op, self.eval_expr(expr.operand, scopes))
        if kind is ast.Assign:
            value = self.eval_expr(expr.value, scopes)
            if expr.op != "=":
                current = self.read_target(expr.target, scopes)
                value = binary(expr.op[0], current, value)
            return self.write_target(expr.target, value, scopes)
        if kind is ast.IncDec:
            current = self.read_target(expr.target, scopes)
            updated = binary("+" if expr.op == "++" else "-", current, 1)
            self.write_target(expr.target, updated, scopes)
            return updated if expr.prefix else current
        if kind is ast.Cast:
            return cast(self.eval_expr(expr.expr, scopes), expr.type)
        if kind is ast.VectorLit:
            items = [coerce(self.eval_expr(item, scopes), "float") for item in reversed(expr.items)]
            items.reverse()
            return Vector(*items) if len(items) == 3 else Rotation(*items)
        if kind is ast.ListLit:
            items = []
            for item in expr.items:
                value = self.eval_expr(item, scopes)
                if isinstance(value, list):
                    raise ScriptError("Lists may not contain lists")
                items.append(value)
            return items
        if kind is ast.Call:
            return self.call(expr, scopes)
        raise UnsupportedError("expression %s" % kind.__name__)

    def call(self, expr, scopes):
        args = [self.eval_expr(arg, scopes) for arg in expr.args]
        func = self.program.functions.get(expr.name)
        if func is not None:
            return self.call_function(func, args)
        return self.sim.call_builtin(self, expr.name, args)

    # --- introspection for the simulator ---------------------------------

    def memory_used(self):
        """Rough estimate of the bytes this script uses, for llGetFreeMemory."""
        code = len(self.source)
        data = 0
        for value in self.globals.values():
            data += value_size(value)
        return code + data + 1024

    def time_since_start(self):
        return f32(self.sim.time - self.start_time)


def value_size(value):
    t = type_of(value)
    if t == "integer" or t == "float":
        return 16
    if t == "vector":
        return 24
    if t == "rotation":
        return 28
    if t == "key":
        return 102
    if t == "string":
        return 18 + 2 * len(value)
    return 8 + sum(value_size(item) for item in value)
