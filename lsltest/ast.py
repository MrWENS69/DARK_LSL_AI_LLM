"""AST node classes. Plain objects with positional fields; see parser.py for the shapes."""


class Node(object):
    __slots__ = ("line", "col")

    def __init__(self, line=0, col=0):
        self.line = line
        self.col = col


# --- program structure -----------------------------------------------------

class Program(Node):
    __slots__ = ("globals", "functions", "states")

    def __init__(self, globals_, functions, states, line=0, col=0):
        Node.__init__(self, line, col)
        self.globals = globals_        # list of Declaration
        self.functions = functions     # dict name -> Function
        self.states = states           # dict name -> State ("default" included)


class Function(Node):
    __slots__ = ("name", "return_type", "params", "body")

    def __init__(self, name, return_type, params, body, line=0, col=0):
        Node.__init__(self, line, col)
        self.name = name
        self.return_type = return_type   # type name or None
        self.params = params             # list of (type, name)
        self.body = body                 # Block


class State(Node):
    __slots__ = ("name", "events")

    def __init__(self, name, events, line=0, col=0):
        Node.__init__(self, line, col)
        self.name = name
        self.events = events             # dict event name -> Function (return_type None)


# --- statements --------------------------------------------------------------

class Block(Node):
    __slots__ = ("statements",)

    def __init__(self, statements, line=0, col=0):
        Node.__init__(self, line, col)
        self.statements = statements


class Declaration(Node):
    __slots__ = ("type", "name", "value")

    def __init__(self, type_, name, value, line=0, col=0):
        Node.__init__(self, line, col)
        self.type = type_
        self.name = name
        self.value = value               # expression or None


class ExprStatement(Node):
    __slots__ = ("expr",)

    def __init__(self, expr, line=0, col=0):
        Node.__init__(self, line, col)
        self.expr = expr


class If(Node):
    __slots__ = ("cond", "then", "otherwise")

    def __init__(self, cond, then, otherwise, line=0, col=0):
        Node.__init__(self, line, col)
        self.cond = cond
        self.then = then
        self.otherwise = otherwise


class While(Node):
    __slots__ = ("cond", "body")

    def __init__(self, cond, body, line=0, col=0):
        Node.__init__(self, line, col)
        self.cond = cond
        self.body = body


class DoWhile(Node):
    __slots__ = ("body", "cond")

    def __init__(self, body, cond, line=0, col=0):
        Node.__init__(self, line, col)
        self.body = body
        self.cond = cond


class For(Node):
    __slots__ = ("init", "cond", "step", "body")

    def __init__(self, init, cond, step, body, line=0, col=0):
        Node.__init__(self, line, col)
        self.init = init                 # list of expressions
        self.cond = cond
        self.step = step                 # list of expressions
        self.body = body


class Return(Node):
    __slots__ = ("value",)

    def __init__(self, value, line=0, col=0):
        Node.__init__(self, line, col)
        self.value = value


class StateChange(Node):
    __slots__ = ("name",)

    def __init__(self, name, line=0, col=0):
        Node.__init__(self, line, col)
        self.name = name


class Jump(Node):
    __slots__ = ("label",)

    def __init__(self, label, line=0, col=0):
        Node.__init__(self, line, col)
        self.label = label


class Label(Node):
    __slots__ = ("name",)

    def __init__(self, name, line=0, col=0):
        Node.__init__(self, line, col)
        self.name = name


class Empty(Node):
    __slots__ = ()


# --- expressions -------------------------------------------------------------

class Literal(Node):
    __slots__ = ("value",)

    def __init__(self, value, line=0, col=0):
        Node.__init__(self, line, col)
        self.value = value


class Name(Node):
    __slots__ = ("name", "member")

    def __init__(self, name, member=None, line=0, col=0):
        Node.__init__(self, line, col)
        self.name = name
        self.member = member             # "x", "y", "z", "s" or None


class VectorLit(Node):
    __slots__ = ("items",)

    def __init__(self, items, line=0, col=0):
        Node.__init__(self, line, col)
        self.items = items               # 3 or 4 expressions


class ListLit(Node):
    __slots__ = ("items",)

    def __init__(self, items, line=0, col=0):
        Node.__init__(self, line, col)
        self.items = items


class Call(Node):
    __slots__ = ("name", "args")

    def __init__(self, name, args, line=0, col=0):
        Node.__init__(self, line, col)
        self.name = name
        self.args = args


class Unary(Node):
    __slots__ = ("op", "operand")

    def __init__(self, op, operand, line=0, col=0):
        Node.__init__(self, line, col)
        self.op = op                     # "-", "!", "~"
        self.operand = operand


class IncDec(Node):
    __slots__ = ("op", "target", "prefix")

    def __init__(self, op, target, prefix, line=0, col=0):
        Node.__init__(self, line, col)
        self.op = op                     # "++" or "--"
        self.target = target             # Name
        self.prefix = prefix


class Binary(Node):
    __slots__ = ("op", "left", "right")

    def __init__(self, op, left, right, line=0, col=0):
        Node.__init__(self, line, col)
        self.op = op
        self.left = left
        self.right = right


class Assign(Node):
    __slots__ = ("op", "target", "value")

    def __init__(self, op, target, value, line=0, col=0):
        Node.__init__(self, line, col)
        self.op = op                     # "=", "+=", "-=", "*=", "/=", "%="
        self.target = target             # Name
        self.value = value


class Cast(Node):
    __slots__ = ("type", "expr")

    def __init__(self, type_, expr, line=0, col=0):
        Node.__init__(self, line, col)
        self.type = type_
        self.expr = expr
