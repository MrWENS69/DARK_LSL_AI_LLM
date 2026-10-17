"""Exceptions raised by lsltest."""


class LslSyntaxError(Exception):
    """The script does not parse. Run lslint first: it explains the error better."""

    def __init__(self, message, line=0, col=0):
        Exception.__init__(self, "line %d:%d: %s" % (line, col, message))
        self.line = line
        self.col = col


class UnsupportedError(Exception):
    """A construct or a builtin that lsltest does not implement (yet)."""


class ScriptError(Exception):
    """A Second Life script run-time error: the script stops, as in-world.

    kind is the in-world message: "Math Error", "Stack-Heap Collision",
    "Too Many Listens", "Lists may not contain lists", "Bounds Check Error".
    """

    def __init__(self, kind, detail=""):
        Exception.__init__(self, "Script run-time error: %s%s" % (kind, (" (" + detail + ")") if detail else ""))
        self.kind = kind
        self.detail = detail
