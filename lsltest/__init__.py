"""lsltest - run LSL scripts and their unit tests outside Second Life.

A tree-walking interpreter for the LSL subset found in typical scripts, with
LSL semantics (strict types, integer division, both operands of && and ||
evaluated right to left, six-decimal floats), and a fake simulator that
captures chat, dialogs, timers, listens, link messages, notecards, HTTP and
permissions so that an assistant can assert on what a script did.

Public API:
    from lsltest import Simulator, LslTestCase, Script, ScriptError, LslSyntaxError, UnsupportedError
Records returned by the simulator and the assertions: Chat and HttpOut (sim.py),
and SimpleNamespace objects for dialogs, textboxes, listens and link messages.
"""

from ._version import __version__
from .errors import LslSyntaxError, ScriptError, UnsupportedError
from .interp import Script
from .sim import Simulator
from .testing import LslTestCase

__all__ = ["Simulator", "LslTestCase", "Script", "ScriptError", "LslSyntaxError", "UnsupportedError", "__version__"]
