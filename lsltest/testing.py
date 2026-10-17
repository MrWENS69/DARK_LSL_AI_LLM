"""unittest helpers for LSL scripts.

    from lsltest import LslTestCase

    class DoorTest(LslTestCase):
        def test_opens_for_owner(self):
            self.load("door.lsl")
            self.sim.start()
            self.sim.touch()
            self.assertOwnerSaid("ready")

Every test gets a fresh Simulator in self.sim (override setUp? call the
inherited one first). Chat assertions look at what scripts said on a channel
(llSay, llWhisper, llShout, llRegionSay, llRegionSayTo): what an avatar said
through sim.say(), owner-only messages and instant messages have their own
assertions, so a test cannot pass because of its own input. Every text
assertion takes exact=True to match the whole line instead of a substring.
"""

import unittest

from .sim import Simulator
from .values import f32, lsl_repr

SCRIPT_CHAT = ("say", "whisper", "shout", "regionsay", "regionsayto")


class LslTestCase(unittest.TestCase):
    """A TestCase with a fresh Simulator per test and assertions on what the script did."""

    seed = 42          # the simulator's random seed: keys, llFrand and llListRandomize are reproducible
    strict = False     # True: a builtin the simulator does not model fails the test instead of being recorded

    def setUp(self):
        self.sim = Simulator(seed=self.seed, strict=self.strict)

    def load(self, source, name=None, obj=None):
        return self.sim.load(source, name=name, obj=obj)

    # --- chat ----------------------------------------------------------------

    def _lines(self, channel=None, kinds=SCRIPT_CHAT):
        return [c.text for c in self.sim.chat
                if (channel is None or c.channel == channel) and c.kind in kinds]

    @staticmethod
    def _found(text, lines, exact):
        return any(line == text if exact else text in line for line in lines)

    def assertSaid(self, text, channel=0, exact=False):
        """A script said text on the channel (channel=None: on any channel)."""
        lines = self._lines(channel)
        if not self._found(text, lines, exact):
            self.fail("no script said %r on channel %s; script chat there: %r" % (text, channel, lines))

    def assertNotSaid(self, text, channel=0, exact=False):
        """No script said text on the channel (channel=None: on any channel)."""
        lines = self._lines(channel)
        if self._found(text, lines, exact):
            self.fail("%r was said on channel %s: %r" % (text, channel, lines))

    def assertOwnerSaid(self, text, exact=False):
        lines = self._lines(kinds=("ownersay",))
        if not self._found(text, lines, exact):
            self.fail("no llOwnerSay containing %r; the owner heard: %r" % (text, lines))

    def assertNotOwnerSaid(self, text, exact=False):
        lines = self._lines(kinds=("ownersay",))
        if self._found(text, lines, exact):
            self.fail("llOwnerSay said %r: %r" % (text, lines))

    def assertSaidTo(self, avatar, text, exact=False):
        """llRegionSayTo or llInstantMessage reached this avatar with text."""
        lines = [c.text for c in self.sim.chat if c.kind in ("regionsayto", "im") and c.target == avatar.key]
        if not self._found(text, lines, exact):
            self.fail("nothing said to %s containing %r; it received: %r" % (avatar.name, text, lines))

    # --- dialogs and listens -----------------------------------------------

    def _dialogs_text(self):
        return [(d.text, d.buttons) for d in self.sim.dialogs]

    def assertDialog(self, buttons=None, contains=None, avatar=None):
        """The latest matching llDialog; returns it (attributes avatar, text, buttons, channel, script)."""
        for dialog in reversed(self.sim.dialogs):
            if avatar is not None and dialog.avatar != avatar.key:
                continue
            if contains is not None and contains not in dialog.text:
                continue
            if buttons is not None and list(buttons) != dialog.buttons:
                continue
            return dialog
        self.fail("no matching dialog; dialogs shown: %r" % self._dialogs_text())

    def assertNoDialog(self):
        if self.sim.dialogs:
            self.fail("a dialog was shown: %r" % self._dialogs_text())

    def _active_listens(self, script=None, channel=None):
        scripts = [script] if script else self.sim.all_scripts()
        return [(s, l) for s in scripts for l in s.listens.values()
                if l.active and (channel is None or l.channel == channel)]

    def assertListening(self, channel=None, script=None):
        """Some script (or this one) has an active listen (on the channel); returns the listen."""
        active = self._active_listens(script, channel)
        if not active:
            self.fail("no active listen%s" % ("" if channel is None else " on channel %d" % channel))
        return active[0][1]

    def assertNoListens(self, script=None):
        active = self._active_listens(script)
        if active:
            self.fail("still listening: %r" % [(s.name, l) for s, l in active])

    # --- errors and recorded calls -----------------------------------------

    def _errors_text(self):
        return [(n, str(e)) for n, e in self.sim.errors]

    def assertNoErrors(self):
        if self.sim.errors:
            self.fail("script run-time errors: %r" % self._errors_text())

    def assertError(self, kind, script=None):
        """A script (a Script or its name) died with this error kind ("Math Error"...); returns the error."""
        wanted = getattr(script, "name", script)
        for name, err in self.sim.errors:
            if err.kind == kind and (wanted is None or name == wanted):
                return err
        self.fail("no %r error; errors: %r" % (kind, self._errors_text()))

    def assertCalled(self, builtin, *args):
        """A builtin the simulator only records was called (with these leading arguments); returns the arguments.

        Recorded: every builtin without a model (llSetColor, llSetPrimitiveParams...), the RECORD_ONLY ones
        (controls, animations, llGiveInventory), llDie and llRezObject."""
        for _, name, recorded in self.sim.calls:
            if name == builtin and (not args or list(args) == recorded[:len(args)]):
                return recorded
        self.fail("%s was not called%s; recorded calls: %r"
                  % (builtin, " with %r" % (args,) if args else "", self.sim.calls))

    def assertNotCalled(self, builtin):
        for _, name, recorded in self.sim.calls:
            if name == builtin:
                self.fail("%s was called with %r" % (builtin, recorded))

    # --- HTTP and link messages -------------------------------------------

    def assertHttpOut(self, url_contains=None, method=None, body_contains=None):
        """A script sent a matching llHTTPRequest; returns the HttpOutRequest."""
        for request in self.sim.http_out:
            if url_contains is not None and url_contains not in request.url:
                continue
            if method is not None and request.method != method:
                continue
            if body_contains is not None and body_contains not in request.body:
                continue
            return request
        self.fail("no matching HTTP request; requests sent: %r" % self.sim.http_out)

    def assertNoHttpOut(self):
        if self.sim.http_out:
            self.fail("HTTP requests were sent: %r" % self.sim.http_out)

    def assertLinkMessage(self, num=None, str_contains=None):
        """A script sent a matching llMessageLinked; returns it (attributes script, sender, link, num, str, id)."""
        for message in self.sim.link_messages:
            if num is not None and message.num != num:
                continue
            if str_contains is not None and str_contains not in message.str:
                continue
            return message
        self.fail("no matching link message; messages: %r" % self.sim.link_messages)

    # --- state ---------------------------------------------------------------

    def assertState(self, script, name):
        self.assertEqual(script.state, name, "%s is in state %s, expected %s" % (script.name, script.state, name))

    def assertGlobal(self, script, name, expected):
        """The script's global equals expected (a float is compared at single precision, like LSL)."""
        if name not in script.globals:
            self.fail("%s has no global %r; globals: %s" % (script.name, name, sorted(script.globals)))
        actual = script.globals[name]
        if isinstance(actual, float) and isinstance(expected, (int, float)):
            expected = f32(expected)
        self.assertEqual(actual, expected, "%s.%s is %s, expected %s"
                         % (script.name, name, lsl_repr(actual), lsl_repr(expected)))
