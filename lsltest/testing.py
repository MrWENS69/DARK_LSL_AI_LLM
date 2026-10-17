"""unittest helpers for LSL scripts.

    from lsltest import LslTestCase

    class DoorTest(LslTestCase):
        def test_opens_for_owner(self):
            self.load("door.lsl")
            self.sim.start()
            self.sim.touch()
            self.assertOwnerSaid("ready")

Every test gets a fresh Simulator in self.sim. Chat assertions look at what
scripts said in public (say, whisper, shout, regionsay, regionsayto): what an
avatar said through sim.say(), owner-only messages and instant messages have
their own assertions, so a test cannot pass because of its own input.
"""

import unittest

from .sim import Simulator
from .values import lsl_repr

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
        """A script said text (substring, or the whole line with exact=True) on the channel."""
        lines = self._lines(channel)
        if not self._found(text, lines, exact):
            self.fail("no script said %r on channel %d; script chat there: %r" % (text, channel, lines))

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

    def assertDialog(self, buttons=None, contains=None, avatar=None):
        """The latest matching llDialog; returns it (attributes avatar, text, buttons, channel)."""
        for dialog in reversed(self.sim.dialogs):
            if avatar is not None and dialog.avatar != avatar.key:
                continue
            if contains is not None and contains not in dialog.text:
                continue
            if buttons is not None and list(buttons) != dialog.buttons:
                continue
            return dialog
        self.fail("no matching dialog; dialogs shown: %r" % [(d.text, d.buttons) for d in self.sim.dialogs])

    def assertNoDialog(self):
        if self.sim.dialogs:
            self.fail("a dialog was shown: %r" % [(d.text, d.buttons) for d in self.sim.dialogs])

    def assertListening(self, channel=None, script=None):
        """Some script (or this one) has an active listen (on the channel); returns the listen."""
        scripts = [script] if script else self.sim.all_scripts()
        for s in scripts:
            for listen in s.listens.values():
                if listen.active and (channel is None or listen.channel == channel):
                    return listen
        self.fail("no active listen%s" % ("" if channel is None else " on channel %d" % channel))

    def assertNoListens(self, script=None):
        scripts = [script] if script else self.sim.all_scripts()
        for s in scripts:
            active = [l for l in s.listens.values() if l.active]
            if active:
                self.fail("%s still listens: %r" % (s.name, active))

    # --- errors and recorded calls -----------------------------------------

    def assertNoErrors(self):
        if self.sim.errors:
            self.fail("script run-time errors: %r" % [(n, str(e)) for n, e in self.sim.errors])

    def assertError(self, kind, script=None):
        """A script died with this error kind ("Math Error", "Stack-Heap Collision"...); returns the error."""
        for name, err in self.sim.errors:
            if err.kind == kind and (script is None or name == script):
                return err
        self.fail("no %r error; errors: %r" % (kind, [(n, str(e)) for n, e in self.sim.errors]))

    def assertCalled(self, builtin, *args):
        """An unmodelled builtin was called (with these leading arguments); returns the recorded arguments."""
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
        """A script sent a matching llMessageLinked; returns it (attributes sender, link, num, str, id)."""
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
        actual = script.globals.get(name)
        self.assertEqual(actual, expected, "%s.%s is %s, expected %s"
                         % (script.name, name, lsl_repr(actual), lsl_repr(expected)))
