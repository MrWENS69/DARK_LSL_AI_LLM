"""lsltest - run LSL scripts and their unit tests outside Second Life.

A tree-walking interpreter for the LSL subset found in typical scripts, with
LSL semantics (strict types, integer division, both operands of && and ||
evaluated right to left, six-decimal floats), and a fake simulator that
captures chat, dialogs, timers, listens, link messages, notecards, HTTP and
permissions so that an assistant can assert on what a script did.

Public API:
    from lsltest import Simulator, LslTestCase, Script, ScriptError, LslSyntaxError, UnsupportedError
Records the simulator hands back: Chat, HttpOutRequest, Avatar and SimObject
(classes in lsltest/world.py), and SimpleNamespace objects for dialogs, textboxes, listens,
link messages and emails (attributes listed in skills/lsl-dev/references/testing.md).
"""

from ._version import __version__
from .errors import LslSyntaxError, ScriptError, UnsupportedError
from .interp import Script
from .sim import Simulator
from .testing import LslTestCase
from .world import Avatar, Chat, HttpOutRequest, SimObject

__all__ = ["Simulator", "LslTestCase", "Script", "ScriptError", "LslSyntaxError", "UnsupportedError",
           "Chat", "HttpOutRequest", "Avatar", "SimObject", "__version__"]
