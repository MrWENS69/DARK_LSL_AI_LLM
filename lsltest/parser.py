"""Recursive-descent parser for LSL, following the lslint grammar (lslmini.y).

Precedence, lowest to highest, as declared in lslmini.y:
    = += -= *= /= %=           (right)
    && ||                      (left, SAME level)
    |
    ^
    &
    == !=
    < <= > >=
    << >>
    + -
    * / %
    unary ! ~ ++ -- -
A '<' at the start of an operand opens a vector or rotation literal.
"""

import sys

from . import nodes
from .limits import MAX_NESTING, MAX_VECTOR_TRY, PARSER_RECURSION_LIMIT
from .errors import LslSyntaxError
from .lexer import tokenize

TYPES = ("integer", "float", "string", "key", "vector", "rotation", "quaternion", "list")

_BINARY_LEVELS = [
    ("&&", "||"),
    ("|",),
    ("^",),
    ("&",),
    ("==", "!="),
    ("<", "<=", ">", ">="),
    ("<<", ">>"),
    ("+", "-"),
    ("*", "/", "%"),
]
_ASSIGN_OPS = ("=", "+=", "-=", "*=", "/=", "%=")


class Parser(object):
    def __init__(self, source):
        self.nesting = 0
        self.vector_depth = 0
        self.tokens = tokenize(source)
        self.pos = 0

    # --- helpers ---------------------------------------------------------

    @property
    def tok(self):
        return self.tokens[self.pos]

    def peek(self, offset=1):
        index = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[index]

    def error(self, message, tok=None):
        tok = tok or self.tok
        raise LslSyntaxError(message, tok.line, tok.col)

    def advance(self):
        tok = self.tokens[self.pos]
        if tok.kind != "eof":
            self.pos += 1
        return tok

    def at(self, kind, value=None):
        tok = self.tok
        return tok.kind == kind and (value is None or tok.value == value)

    def at_op(self, *values):
        return self.tok.kind == "op" and self.tok.value in values

    def expect(self, kind, value=None):
        if not self.at(kind, value):
            want = value if value is not None else kind
            got = self.tok.value if self.tok.kind != "eof" else "end of file"
            self.error("expected %r, found %r" % (want, got))
        return self.advance()

    def expect_op(self, value):
        return self.expect("op", value)

    def at_type(self):
        return self.tok.kind == "keyword" and self.tok.value in TYPES

    def type_name(self):
        tok = self.advance()
        return "rotation" if tok.value == "quaternion" else tok.value

    # --- program -------------------------------------------------------------

    def parse_program(self):
        globals_ = []
        functions = {}
        states = {}
        # globals and functions, in any order, until the default state
        while not (self.at("keyword", "default") or self.at("eof")):
            if self.at_type():
                # "type name = expr ;" is a global, "type name(" a function
                if self.peek().kind == "ident" and self.peek(2).kind == "op" and self.peek(2).value == "(":
                    f = self.parse_function()
                    functions[f.name] = f
                else:
                    globals_.append(self.parse_declaration())
                    self.expect_op(";")
            elif self.at("ident") and self.peek().kind == "op" and self.peek().value == "(":
                f = self.parse_function()
                functions[f.name] = f
            else:
                self.error("expected a global variable, a function or the default state")
        if self.at("eof"):
            self.error("a script needs a default state")
        states["default"] = self.parse_state()
        while self.at("keyword", "state"):
            s = self.parse_state()
            if s.name in states:
                self.error("state %s defined twice" % s.name)
            states[s.name] = s
        if not self.at("eof"):
            self.error("unexpected %r after the last state" % self.tok.value)
        return nodes.Program(globals_, functions, states)

    def parse_function(self):
        start = self.tok
        return_type = self.type_name() if self.at_type() else None
        name = self.expect("ident").value
        self.expect_op("(")
        params = []
        if not self.at_op(")"):
            while True:
                if not self.at_type():
                    self.error("expected a parameter type")
                ptype = self.type_name()
                pname = self.expect("ident").value
                params.append((ptype, pname))
                if self.at_op(","):
                    self.advance()
                    continue
                break
        self.expect_op(")")
        body = self.parse_block()
        return nodes.Function(name, return_type, params, body, start.line, start.col)

    def parse_state(self):
        start = self.tok
        if self.at("keyword", "default"):
            self.advance()
            name = "default"
        else:
            self.expect("keyword", "state")
            name = self.expect("ident").value
        self.expect_op("{")
        events = {}
        while not self.at_op("}"):
            if self.at("eof"):
                self.error("unterminated state %s" % name)
            if not self.at("ident"):
                self.error("expected an event handler in state %s" % name)
            handler = self.parse_function()
            if handler.return_type is not None:
                self.error("an event handler has no return type", start)
            if handler.name in events:
                self.error("event %s handled twice in state %s" % (handler.name, name))
            events[handler.name] = handler
        self.expect_op("}")
        return nodes.State(name, events, start.line, start.col)

    # --- statements ----------------------------------------------------------

    def parse_block(self):
        self.nesting += 1
        if self.nesting > MAX_NESTING:
            self.error("blocks nested too deeply")
        try:
            return self._parse_block()
        finally:
            self.nesting -= 1

    def _parse_block(self):
        start = self.expect_op("{")
        statements = []
        while not self.at_op("}"):
            if self.at("eof"):
                self.error("unterminated block", start)
            statements.append(self.parse_statement())
        self.expect_op("}")
        return nodes.Block(statements, start.line, start.col)

    def parse_declaration(self):
        start = self.tok
        type_ = self.type_name()
        name = self.expect("ident").value
        value = None
        if self.at_op("="):
            self.advance()
            value = self.parse_expression()
        return nodes.Declaration(type_, name, value, start.line, start.col)

    def parse_statement(self):
        tok = self.tok
        line, col = tok.line, tok.col
        if self.at_op(";"):
            self.advance()
            return nodes.Empty(line, col)
        if self.at_op("{"):
            return self.parse_block()
        if self.at_op("@"):
            self.advance()
            name = self.expect("ident").value
            self.expect_op(";")
            return nodes.Label(name, line, col)
        if tok.kind == "keyword":
            kw = tok.value
            if kw in TYPES:
                decl = self.parse_declaration()
                self.expect_op(";")
                return decl
            if kw == "if":
                self.advance()
                self.expect_op("(")
                cond = self.parse_expression()
                self.expect_op(")")
                then = self.parse_statement()
                otherwise = None
                if self.at("keyword", "else"):
                    self.advance()
                    otherwise = self.parse_statement()
                return nodes.If(cond, then, otherwise, line, col)
            if kw == "while":
                self.advance()
                self.expect_op("(")
                cond = self.parse_expression()
                self.expect_op(")")
                return nodes.While(cond, self.parse_statement(), line, col)
            if kw == "do":
                self.advance()
                body = self.parse_statement()
                self.expect("keyword", "while")
                self.expect_op("(")
                cond = self.parse_expression()
                self.expect_op(")")
                self.expect_op(";")
                return nodes.DoWhile(body, cond, line, col)
            if kw == "for":
                self.advance()
                self.expect_op("(")
                init = self.parse_expression_list(";")
                self.expect_op(";")
                cond = self.parse_expression()
                self.expect_op(";")
                step = self.parse_expression_list(")")
                self.expect_op(")")
                return nodes.For(init, cond, step, self.parse_statement(), line, col)
            if kw == "return":
                self.advance()
                value = None
                if not self.at_op(";"):
                    value = self.parse_expression()
                self.expect_op(";")
                return nodes.Return(value, line, col)
            if kw == "state":
                self.advance()
                if self.at("keyword", "default"):
                    self.advance()
                    name = "default"
                else:
                    name = self.expect("ident").value
                self.expect_op(";")
                return nodes.StateChange(name, line, col)
            if kw == "jump":
                self.advance()
                name = self.expect("ident").value
                self.expect_op(";")
                return nodes.Jump(name, line, col)
            if kw == "else":
                self.error("else without if")
            if kw == "default":
                self.error("default is a state, not a statement")
        expr = self.parse_expression()
        self.expect_op(";")
        return nodes.ExprStatement(expr, line, col)

    def parse_expression_list(self, terminator):
        items = []
        if self.at_op(terminator):
            return items
        while True:
            items.append(self.parse_expression())
            if self.at_op(","):
                self.advance()
                continue
            return items

    # --- expressions ---------------------------------------------------------

    def parse_expression(self):
        return self.parse_assignment()

    def parse_assignment(self):
        # lvalue op expression  (right associative), otherwise a binary expression
        if self.at("ident"):
            save = self.pos
            target = self.parse_lvalue_opt()
            if target is not None and self.tok.kind == "op" and self.tok.value in _ASSIGN_OPS:
                op_tok = self.advance()
                value = self.parse_assignment()
                return nodes.Assign(op_tok.value, target, value, op_tok.line, op_tok.col)
            self.pos = save
        return self.parse_binary(0)

    def parse_lvalue_opt(self):
        tok = self.tok
        if tok.kind != "ident":
            return None
        self.advance()
        member = None
        if self.at_op(".") and self.peek().kind == "ident":
            self.advance()
            member = self.advance().value
        return nodes.Name(tok.value, member, tok.line, tok.col)

    def parse_binary(self, level):
        if level >= len(_BINARY_LEVELS):
            return self.parse_unary()
        ops = _BINARY_LEVELS[level]
        left = self.parse_binary(level + 1)
        while self.tok.kind == "op" and self.tok.value in ops:
            op_tok = self.advance()
            right = self.parse_binary(level + 1)
            left = nodes.Binary(op_tok.value, left, right, op_tok.line, op_tok.col)
        return left

    def parse_unary(self):
        # every nesting level of an expression passes through here: bound it so that a hostile
        # script cannot exhaust the Python stack, whatever the platform's limit is
        self.nesting += 1
        if self.nesting > MAX_NESTING:
            self.error("expression nested too deeply")
        try:
            return self._parse_unary()
        finally:
            self.nesting -= 1

    def _parse_unary(self):
        tok = self.tok
        if self.at_op("-", "!", "~"):
            self.advance()
            return nodes.Unary(tok.value, self.parse_unary(), tok.line, tok.col)
        if self.at_op("++", "--"):
            self.advance()
            target = self.parse_lvalue_opt()
            if target is None:
                self.error("%s needs a variable" % tok.value, tok)
            return nodes.IncDec(tok.value, target, True, tok.line, tok.col)
        if self.at_op("(") and self.peek().kind == "keyword" and self.peek().value in TYPES and self.peek(2).kind == "op" and self.peek(2).value == ")":
            self.advance()
            type_ = self.type_name()
            self.expect_op(")")
            # (type) applies to a unary operand: a negative literal, a postfix expression or a parenthesis
            if self.at_op("-"):
                minus = self.advance()
                operand = nodes.Unary("-", self.parse_postfix(), minus.line, minus.col)
            else:
                operand = self.parse_postfix()
            return nodes.Cast(type_, operand, tok.line, tok.col)
        return self.parse_postfix()

    def parse_postfix(self):
        tok = self.tok
        line, col = tok.line, tok.col
        if self.at_op("("):
            self.advance()
            expr = self.parse_expression()
            self.expect_op(")")
            return expr
        if tok.kind == "int" or tok.kind == "float" or tok.kind == "string":
            self.advance()
            return nodes.Literal(tok.value, line, col)
        if self.at_op("<"):
            self.advance()
            self.vector_depth += 1
            try:
                items = [self.parse_vector_component()]
                while self.at_op(","):
                    self.advance()
                    items.append(self.parse_vector_component())
            finally:
                self.vector_depth -= 1
            self.expect_op(">")
            if len(items) not in (3, 4):
                self.error("a vector has 3 components, a rotation 4", tok)
            return nodes.VectorLit(items, line, col)
        if self.at_op("["):
            self.advance()
            items = self.parse_expression_list("]")
            self.expect_op("]")
            return nodes.ListLit(items, line, col)
        if tok.kind == "ident":
            if self.peek().kind == "op" and self.peek().value == "(":
                self.advance()
                self.advance()
                args = self.parse_expression_list(")")
                self.expect_op(")")
                return nodes.Call(tok.value, args, line, col)
            target = self.parse_lvalue_opt()
            if self.at_op("++", "--"):
                op_tok = self.advance()
                return nodes.IncDec(op_tok.value, target, False, line, col)
            if self.tok.kind == "op" and self.tok.value in _ASSIGN_OPS:
                # an assignment can sit inside an operand: a + (b = c), 0 < (e = f())
                op_tok = self.advance()
                value = self.parse_assignment()
                return nodes.Assign(op_tok.value, target, value, op_tok.line, op_tok.col)
            return target
        if tok.kind == "keyword" and tok.value in TYPES:
            self.error("unexpected type name %s here" % tok.value)
        if tok.kind == "eof":
            self.error("unexpected end of file")
        self.error("unexpected %r" % tok.value)

    def parse_vector_component(self):
        # Inside < ... > a '>' closes the literal. Like the lslint grammar, a component followed by
        # ',' may be any expression; the last one stops before comparisons (shift level and above).
        # The first attempt parses a nested literal again, so past MAX_VECTOR_TRY levels only the
        # second form is tried: the cost would otherwise double at each level.
        if self.vector_depth <= MAX_VECTOR_TRY:
            save = self.pos
            try:
                expr = self.parse_expression()
                if self.at_op(","):
                    return expr
            except LslSyntaxError:
                pass
            self.pos = save
        return self.parse_binary(6)


def parse(source):
    """Parse LSL source text into an nodes.Program."""
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, PARSER_RECURSION_LIMIT))
    try:
        return Parser(source).parse_program()
    except RecursionError:
        raise LslSyntaxError("expression or block nested too deeply", 0, 0)
    finally:
        sys.setrecursionlimit(old)
