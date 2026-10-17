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
    """A Second Life script run-time error: the script stops, as on the grid.

    kind is the in-world message: "Math Error", "Stack-Heap Collision",
    "Too Many Listens", "Lists may not contain lists", "Bounds Check Error".
    line is the script line that was running, set by the interpreter when known.
    """

    def __init__(self, kind, detail="", line=0):
        Exception.__init__(self, kind)
        self.kind = kind
        self.detail = detail
        self.line = line

    def __str__(self):
        text = "Script run-time error: " + self.kind
        if self.detail:
            text += " (" + self.detail + ")"
        if self.line:
            text += " at line %d" % self.line
        return text


class ResetSignal(Exception):
    """llResetScript was called: unwinds to the simulator, which restarts the script."""
