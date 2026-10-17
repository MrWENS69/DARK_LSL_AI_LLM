"""unittest helpers for LSL scripts.

    from lsltest import LslTestCase

    class DoorTest(LslTestCase):
        def test_opens_for_owner(self):
            self.load("door.lsl")
            self.sim.start()
            self.sim.touch()
            self.assertOwnerSaid("ready")
"""

import unittest

from .sim import Simulator
from .values import lsl_repr


class LslTestCase(unittest.TestCase):
    """A TestCase with a fresh Simulator per test and assertions on what the script did."""

    seed = 42

    def setUp(self):
        self.sim = Simulator(seed=self.seed)

    def load(self, source, name=None, obj=None):
        return self.sim.load(source, name=name, obj=obj)

    # --- chat ----------------------------------------------------------------

    def _chat_texts(self, channel=None, kind=None):
        return [c.text for c in self.sim.chat
                if (channel is None or c.channel == channel) and (kind is None or c.kind == kind)]

    def assertSaid(self, text, channel=0, exact=False):
        for line in self._chat_texts(channel):
            if line == text if exact else text in line:
                return
        self.fail("nothing said on channel %d containing %r; chat was: %r" % (channel, text, self._chat_texts(channel)))

    def assertNotSaid(self, text, channel=None):
        for line in self._chat_texts(channel):
            if text in line:
                self.fail("%r was said: %r" % (text, line))

    def assertOwnerSaid(self, text, exact=False):
        for line in self._chat_texts(kind="ownersay"):
            if line == text if exact else text in line:
                return
        self.fail("no llOwnerSay containing %r; owner heard: %r" % (text, self._chat_texts(kind="ownersay")))

    def assertSaidTo(self, avatar, text):
        for c in self.sim.chat:
            if c.kind == "regionsayto" and c.target == avatar.key and text in c.text:
                return
        self.fail("nothing said to %s containing %r" % (avatar.name, text))

    # --- dialogs and listens -----------------------------------------------

    def assertDialog(self, buttons=None, contains=None, avatar=None):
        for dialog in reversed(self.sim.dialogs):
            if avatar is not None and dialog["avatar"] != avatar.key:
                continue
            if contains is not None and contains not in dialog["text"]:
                continue
            if buttons is not None and list(buttons) != dialog["buttons"]:
                continue
            return dialog
        self.fail("no matching dialog; dialogs shown: %r" % [(d["text"], d["buttons"]) for d in self.sim.dialogs])

    def assertNoDialog(self):
        if self.sim.dialogs:
            self.fail("a dialog was shown: %r" % [(d["text"], d["buttons"]) for d in self.sim.dialogs])

    def assertListening(self, channel=None, script=None):
        scripts = [script] if script else self.sim.all_scripts()
        for s in scripts:
            for listen in s.listens.values():
                if listen["active"] and (channel is None or listen["channel"] == channel):
                    return listen
        self.fail("no active listen%s" % ("" if channel is None else " on channel %d" % channel))

    def assertNoListens(self, script=None):
        scripts = [script] if script else self.sim.all_scripts()
        for s in scripts:
            active = [l for l in s.listens.values() if l["active"]]
            if active:
                self.fail("%s still listens: %r" % (s.name, active))

    # --- errors and recorded calls -----------------------------------------

    def assertNoErrors(self):
        if self.sim.errors:
            self.fail("script run-time errors: %r" % [(n, str(e)) for n, e in self.sim.errors])

    def assertError(self, kind, script=None):
        for name, err in self.sim.errors:
            if err.kind == kind and (script is None or name == script):
                return err
        self.fail("no %r error; errors: %r" % (kind, [(n, str(e)) for n, e in self.sim.errors]))

    def assertCalled(self, builtin, *args):
        for _, name, recorded in self.sim.calls:
            if name == builtin and (not args or list(args) == recorded[:len(args)]):
                return recorded
        self.fail("%s was not called%s; recorded calls: %r" % (builtin, " with %r" % (args,) if args else "", self.sim.calls))

    def assertNotCalled(self, builtin):
        for _, name, recorded in self.sim.calls:
            if name == builtin:
                self.fail("%s was called with %r" % (builtin, recorded))

    # --- HTTP and link messages -------------------------------------------

    def assertHttpRequest(self, url_contains=None, method=None, body_contains=None):
        for request in self.sim.http_requests:
            if url_contains is not None and url_contains not in request.url:
                continue
            if method is not None and request.method != method:
                continue
            if body_contains is not None and body_contains not in request.body:
                continue
            return request
        self.fail("no matching HTTP request; requests: %r" % self.sim.http_requests)

    def assertNoHttpRequest(self):
        if self.sim.http_requests:
            self.fail("HTTP requests were sent: %r" % self.sim.http_requests)

    def assertLinkMessage(self, num=None, str_contains=None):
        for message in self.sim.link_messages:
            if num is not None and message["num"] != num:
                continue
            if str_contains is not None and str_contains not in message["str"]:
                continue
            return message
        self.fail("no matching link message; messages: %r" % self.sim.link_messages)

    # --- state ---------------------------------------------------------------

    def assertState(self, script, name):
        self.assertEqual(script.state, name, "%s is in state %s, expected %s" % (script.name, script.state, name))

    def assertGlobal(self, script, name, expected):
        actual = script.globals.get(name)
        self.assertEqual(actual, expected, "%s.%s is %s, expected %s" % (script.name, name, lsl_repr(actual), lsl_repr(expected)))
