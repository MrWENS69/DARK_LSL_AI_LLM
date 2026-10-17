"""Tree-walking interpreter for one LSL script.

Semantics implemented here (see skills/lsl-dev/references/lsl-for-ai.md):
- strict types, implicit conversions only integer->float and string<->key;
- both operands of a binary operator are evaluated, right one first;
- function arguments and list elements are evaluated left to right, vector
  components right to left (the grid documents neither: a script must not
  depend on it);
- && and || never short-circuit;
- integer arithmetic wraps to 32 bits, division truncates, / and % by zero
  raise "Math Error";
- floats are single precision;
- state changes run state_exit, clear the event queue, release listens,
  then state_entry of the new state;
- jump/labels within a function or event handler.
"""

import sys
import time as _time

from . import nodes
from .errors import ResetSignal, ScriptError, UnsupportedError
from .lexer import tokenize
from .limits import MAX_CALL_DEPTH, MAX_QUEUE, RECURSION_LIMIT
from .parser import parse
from .signatures import CONSTANTS
from .values import (Vector, Rotation, binary, cast, coerce, default_value, truthy, type_of, unary, f32, NULL_KEY)


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
        self.dead = False              # stopped by a run-time error (recorded in sim.errors)
        self.line = 0                  # script line of the statement being run, for error messages
        self.code_size = sum(len(str(tok.value)) for tok in tokenize(source) if tok.kind != "eof")
        self.listens = {}              # handle -> SimpleNamespace(channel, name, id, msg, active)
        self.next_listen = 1
        self.timer_interval = 0.0
        self.timer_due = None
        self.sensor_repeat = None
        self.queue = []                # pending events: (name, args, detected)
        self.dropped_events = 0
        self.permissions = 0
        self.permissions_key = NULL_KEY
        self.pending_permissions = (0, NULL_KEY)   # applied when run_time_permissions runs, as on the grid
        self.start_param = 0
        self.start_time = sim.time
        self.memory_limit = 65536
        self.detected = []             # llDetected* data of the running event
        self.link = 1                  # prim the script sits in
        self.urls = set()
        self.depth = 0
        self.statements_run = 0
        self.deadline = float("inf")
        self.scopes = ()               # scope chain of the running statement, for memory_used()
        self._guard(self.reset_globals)

    def __repr__(self):
        return "Script(%s)" % self.name

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
        self.listens = {}
        self.timer_interval = 0.0
        self.timer_due = None
        self.sensor_repeat = None
        self.queue = []
        self.permissions = 0
        self.permissions_key = NULL_KEY
        self.state = "default"
        self.dead = False
        self.running = True
        self.start_time = self.sim.time
        for url in list(self.urls):
            self.sim.ll_ReleaseURL(self, url)
        self._guard(self.reset_globals)
        self.post("state_entry", [])

    def handles_event(self, name):
        state_node = self.program.states.get(self.state)
        return state_node is not None and name in state_node.events

    def post(self, name, args, detected=None):
        """Queue an event. Nothing is queued for a stopped or dead script, for an event the current
        state does not handle, or when the queue already holds MAX_QUEUE events (dropped_events counts those)."""
        if not self.running or self.dead or not self.handles_event(name):
            return
        if len(self.queue) >= MAX_QUEUE:
            self.dropped_events += 1
            return
        self.queue.append((name, list(args), list(detected or [])))

    def dispatch(self, name, args, detected):
        """Run one event handler. A script failure kills the script instead of raising, as on the grid."""
        handler = self.program.states[self.state].events[name]
        if name == "run_time_permissions":
            self.permissions, self.permissions_key = self.pending_permissions
        self.detected = detected
        try:
            self._guard(lambda: self._run_event(handler, args))
        finally:
            self.detected = []
            self.scopes = ()
        if not self.dead and self.memory_used() > self.memory_limit:
            self.die(ScriptError("Stack-Heap Collision", "about %d bytes in use" % self.memory_used()))

    def _run_event(self, handler, args):
        try:
            self.call_function(handler, args, event=True)
        except StateChangeSignal as change:
            self.detected = []            # llDetected* is for the event that detected, not for state_exit
            self.change_state(change.name)

    def _guard(self, action):
        """Run action() under the script's limits; ScriptError and Python failures kill the script."""
        self.statements_run = 0
        self.deadline = _time.monotonic() + self.sim.max_handler_seconds
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, RECURSION_LIMIT))
        try:
            action()
        except ScriptError as err:
            self.die(err)
        except RecursionError:
            self.die(ScriptError("Stack-Heap Collision", "nesting too deep"))
        except (ResetSignal, UnsupportedError):
            raise
        except Exception as exc:      # a Python limit or type error reached by a script value, never a traceback
            self.die(ScriptError("Script run-time error", "%s: %s" % (type(exc).__name__, exc)))
        finally:
            sys.setrecursionlimit(old_limit)

    def die(self, err):
        if not err.line:
            err.line = self.line
        self.dead = True
        self.sim.errors.append((self.name, err))

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
        self.listens = {}
        self.sensor_repeat = None
        self.state = name
        # state_entry of the new state runs next, ahead of anything else
        if self.handles_event("state_entry"):
            self.queue.insert(0, ("state_entry", [], []))

    # --- functions -----------------------------------------------------------

    def call_function(self, func, args, event=False):
        if len(args) != len(func.params):
            raise ScriptError("Type mismatch", "%s expects %d arguments" % (func.name, len(func.params)))
        scope = {}
        for (ptype, pname), value in zip(func.params, args):
            scope[pname] = coerce(value, ptype)
        if self.depth >= MAX_CALL_DEPTH:
            raise ScriptError("Stack-Heap Collision", "call depth over %d" % MAX_CALL_DEPTH)
        self.depth += 1
        try:
            self.exec_block(func.body, [scope])
        except ReturnSignal as ret:
            if func.return_type is None:
                if event and ret.value is not None:
                    raise ScriptError("Script run-time error", "return with a value in an event handler")
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
        scopes = scopes + [{}]
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
            if isinstance(stmt, nodes.Label) and stmt.name == label:
                return i
        return None

    def exec_stmt(self, stmt, scopes):
        self.line = stmt.line
        self.scopes = scopes
        self.statements_run += 1
        if self.statements_run > self.sim.max_statements:
            raise ScriptError("Script run-time error", "lsltest: over %d statements in one handler, the script is looping"
                              % self.sim.max_statements)
        if self.statements_run & 4095 == 0:
            if _time.monotonic() > self.deadline:
                raise ScriptError("Script run-time error", "lsltest: the handler ran over %g seconds"
                                  % self.sim.max_handler_seconds)
            used = self.memory_used(scopes)
            if used > self.memory_limit:
                raise ScriptError("Stack-Heap Collision", "about %d bytes in use" % used)
        kind = type(stmt)
        if kind is nodes.ExprStatement:
            self.eval_expr(stmt.expr, scopes)
        elif kind is nodes.Declaration:
            value = default_value(stmt.type)
            if stmt.value is not None:
                value = coerce(self.eval_expr(stmt.value, scopes), stmt.type)
            scopes[-1][stmt.name] = value
        elif kind is nodes.Block:
            self.exec_block(stmt, scopes)
        elif kind is nodes.If:
            if truthy(self.eval_expr(stmt.cond, scopes)):
                self.exec_stmt(stmt.then, scopes)
            elif stmt.otherwise is not None:
                self.exec_stmt(stmt.otherwise, scopes)
        elif kind is nodes.While:
            while truthy(self.eval_expr(stmt.cond, scopes)):
                self.exec_stmt(stmt.body, scopes)
        elif kind is nodes.DoWhile:
            while True:
                self.exec_stmt(stmt.body, scopes)
                if not truthy(self.eval_expr(stmt.cond, scopes)):
                    break
        elif kind is nodes.For:
            for expr in stmt.init:
                self.eval_expr(expr, scopes)
            while truthy(self.eval_expr(stmt.cond, scopes)):
                self.exec_stmt(stmt.body, scopes)
                for expr in stmt.step:
                    self.eval_expr(expr, scopes)
        elif kind is nodes.Return:
            value = None if stmt.value is None else self.eval_expr(stmt.value, scopes)
            raise ReturnSignal(value)
        elif kind is nodes.StateChange:
            raise StateChangeSignal(stmt.name)
        elif kind is nodes.Jump:
            raise JumpSignal(stmt.label)
        elif kind is nodes.Label or kind is nodes.Empty:
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
        const = CONSTANTS.get(name)
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
        self.member(current, target.member)          # Type mismatch when the member does not exist
        component = coerce(value, "float")
        parts = list(current)
        parts["xyzs".index(target.member)] = component
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
        if kind is nodes.Literal:
            value = expr.value
            return f32(value) if isinstance(value, float) else value
        if kind is nodes.Name:
            return self.read_target(expr, scopes)
        if kind is nodes.Binary:
            # right operand first, then left: LSL evaluates right to left and never short-circuits
            right = self.eval_expr(expr.right, scopes)
            left = self.eval_expr(expr.left, scopes)
            return binary(expr.op, left, right)
        if kind is nodes.Unary:
            return unary(expr.op, self.eval_expr(expr.operand, scopes))
        if kind is nodes.Assign:
            value = self.eval_expr(expr.value, scopes)
            if expr.op != "=":
                current = self.read_target(expr.target, scopes)
                value = binary(expr.op[0], current, value)
            return self.write_target(expr.target, value, scopes)
        if kind is nodes.IncDec:
            current = self.read_target(expr.target, scopes)
            updated = binary("+" if expr.op == "++" else "-", current, 1)
            self.write_target(expr.target, updated, scopes)
            return updated if expr.prefix else current
        if kind is nodes.Cast:
            return cast(self.eval_expr(expr.expr, scopes), expr.type)
        if kind is nodes.VectorLit:
            items = [coerce(self.eval_expr(item, scopes), "float") for item in reversed(expr.items)]
            items.reverse()
            return Vector(*items) if len(items) == 3 else Rotation(*items)
        if kind is nodes.ListLit:
            items = []
            for item in expr.items:
                value = self.eval_expr(item, scopes)
                if isinstance(value, list):
                    raise ScriptError("Lists may not contain lists")
                items.append(value)
            return items
        if kind is nodes.Call:
            return self.call(expr, scopes)
        raise UnsupportedError("expression %s" % kind.__name__)

    def call(self, expr, scopes):
        args = [self.eval_expr(arg, scopes) for arg in expr.args]
        func = self.program.functions.get(expr.name)
        if func is not None:
            return self.call_function(func, args)
        return self.sim.call_builtin(self, expr.name, args)

    # --- introspection for the simulator ---------------------------------

    def memory_used(self, scopes=None):
        """Rough estimate of the bytes this script uses: code without comments, globals, and the locals of
        the running function (the scope chain given, or the current one). For llGetFreeMemory too."""
        data = sum(value_size(value) for value in self.globals.values())
        for scope in (self.scopes if scopes is None else scopes):
            data += sum(value_size(value) for value in scope.values())
        return self.code_size + data + 1024

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
