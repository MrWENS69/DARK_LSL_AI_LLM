"""lsltest - run LSL scripts and their unit tests outside Second Life.

A tree-walking interpreter for the LSL subset found in typical scripts, with
LSL semantics (strict types, integer division, both operands of && and ||
evaluated right to left, six-decimal floats), and a fake simulator that
captures chat, dialogs, timers, listens, link messages, notecards, HTTP and
permissions so that an assistant can assert on what a script did.

Public API:
    from lsltest import Simulator, LslTestCase, ScriptError
"""

from .errors import LslSyntaxError, ScriptError, UnsupportedError
from .sim import Simulator
from .testing import LslTestCase

__version__ = "0.1.0"
__all__ = ["Simulator", "LslTestCase", "ScriptError", "LslSyntaxError", "UnsupportedError", "__version__"]
