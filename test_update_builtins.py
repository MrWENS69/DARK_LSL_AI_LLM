#!/usr/bin/env python3
"""Unit tests for the lsl_definitions.yaml reader and the lsl_doc.json builder. Run: python -m unittest test_update_builtins"""

import io
import json
import os
import tempfile
import unittest

import update_builtins as ub

SAMPLE = """%YAML 1.2
---
# a comment line
llsd-lsl-syntax-version: 2
enums:
  Channel:
    special-members: [PUBLIC_CHANNEL] # not read
constants:
  CHANGED_INVENTORY:
    member-of: [ChangeType]
    tooltip: Prim inventory has changed by someone who has modification rights
      to it.
    type: integer
    value: '0x1'
  ATTACH_RPEC:
    deprecated:
      use: ATTACH_RIGHT_PEC
    tooltip: "Right pectoral (deprecated, use ATTACH_RIGHT_PEC)."
    type: integer
    value: 30
  QUOTED:
    tooltip: 'It''s quoted with a trailing
      line and a comment' # here
    type: string
    value: "a \\"b\\" c"
  APOSTROPHE:
    tooltip: # TODO
    type: string
    value: '0x2' # don't change
  BLOCK:
    tooltip: |
      line one
      line two
    type: integer
    value: 1
  FOLDED:
    tooltip: >-
      folded one
      folded two

      after a blank
    type: integer
    value: 2
events:
  state_entry:
    event-id: 1
    arguments: []
    tooltip: Triggered when a state is entered.
  listen:
    arguments:
    - channel:
        tooltip: Chat channel where the message appeared.
        type: integer
    -   msg:
          tooltip: Spoken text.
          type: string
    tooltip: Triggered on chat.
functions:
  llListen:
    arguments:
    - channel:
        tooltip: Chat channel to listen on.
        type: integer
    - name:
        tooltip: Name filter.
        type: string
    energy: 10.0
    func-id: 25
    return: integer
    sleep: 0.0
    tooltip: Creates a listener.
    requires-permission: [PERMISSION_DEBIT,
      PERMISSION_ATTACH]
    uses-enum:
      [
        Channel,
      ]
    pure: false
  llSleep:
    arguments:
    - sec:
        tooltip: Seconds.
        type: float
    energy: 0.0
    return: void
    sleep: 0.0
    mono-sleep: 0.2
    tooltip: Sleeps. # trailing comment
    deprecated: true
types:
  integer: {}
"""

BUILTINS = {
    "functions": {"llListen": ("integer", "integer channel, string name"), "llSleep": ("void", "float sec")},
    "events": {"state_entry": "", "listen": "integer channel, string msg"},
    "constants": {name: ("integer", "0") for name in ("CHANGED_INVENTORY", "ATTACH_RPEC", "QUOTED", "BLOCK", "FOLDED", "APOSTROPHE")},
}


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.defs = ub.read_definitions(SAMPLE)

    def test_sections_and_scalars(self):
        c = self.defs["constants"]
        self.assertEqual(c["CHANGED_INVENTORY"]["tooltip"], "Prim inventory has changed by someone who has modification rights to it.")
        self.assertEqual(c["CHANGED_INVENTORY"]["value"], "0x1")
        self.assertEqual(c["CHANGED_INVENTORY"]["member-of"], ["ChangeType"])
        self.assertEqual(c["ATTACH_RPEC"]["deprecated"], {"use": "ATTACH_RIGHT_PEC"})
        self.assertEqual(c["QUOTED"]["tooltip"], "It's quoted with a trailing line and a comment")
        self.assertEqual(c["QUOTED"]["value"], 'a "b" c')
        self.assertEqual(c["BLOCK"]["tooltip"], "line one\nline two")
        self.assertEqual(c["FOLDED"]["tooltip"], "folded one folded two after a blank")
        self.assertEqual((c["APOSTROPHE"]["tooltip"], c["APOSTROPHE"]["value"]), ("", "0x2"))

    def test_lists_and_arguments(self):
        e = self.defs["events"]
        self.assertEqual(e["state_entry"]["arguments"], [])
        self.assertEqual([list(a)[0] for a in e["listen"]["arguments"]], ["channel", "msg"])
        self.assertEqual(e["listen"]["arguments"][1]["msg"]["type"], "string")
        f = self.defs["functions"]["llListen"]
        self.assertEqual(f["requires-permission"], ["PERMISSION_DEBIT", "PERMISSION_ATTACH"])
        self.assertEqual(f["uses-enum"], ["Channel"])
        self.assertEqual(self.defs["functions"]["llSleep"]["tooltip"], "Sleeps.")

    def test_unsupported_syntax_is_refused(self):
        with self.assertRaises(ValueError):
            ub.read_definitions("constants:\n  A:\n    tooltip: &anchor text\n")
        with self.assertRaises(ValueError):
            ub.read_definitions("constants:\n  A:\n    tooltip: 'never closed\n")


class BuildDocTest(unittest.TestCase):
    def build(self, text=SAMPLE, builtins=BUILTINS):
        return ub.build_doc(ub.read_definitions(text), builtins["functions"], builtins["events"], builtins["constants"])

    def test_shapes(self):
        doc = self.build()
        listen = doc["functions"]["llListen"]
        self.assertEqual(listen["args"], [["channel", "integer", "Chat channel to listen on."], ["name", "string", "Name filter."]])
        self.assertEqual((listen["return"], listen["sleep"], listen["energy"]), ("integer", 0.0, 10.0))
        self.assertEqual(listen["requires-permission"], ["PERMISSION_DEBIT", "PERMISSION_ATTACH"])
        self.assertNotIn("pure", listen)
        self.assertTrue(doc["functions"]["llSleep"]["deprecated"])
        self.assertEqual(doc["functions"]["llSleep"]["mono-sleep"], 0.2)
        self.assertEqual(doc["constants"]["ATTACH_RPEC"]["use"], "ATTACH_RIGHT_PEC")
        self.assertEqual(doc["events"]["listen"]["args"][1][:2], ["msg", "string"])
        self.assertEqual(doc["source"], ub.REPO)

    def test_signature_mismatch_and_missing_entries_fail(self):
        wrong = dict(BUILTINS, functions={"llListen": ("integer", "integer channel, key name"), "llSleep": ("void", "float sec")})
        with self.assertRaises(ValueError):
            self.build(builtins=wrong)
        more = dict(BUILTINS, functions=dict(BUILTINS["functions"], llNew=("void", "")))
        with self.assertRaises(ValueError):
            self.build(builtins=more)
        with self.assertRaises(ValueError):
            ub._flag("no")

    def test_control_characters_are_refused(self):
        with self.assertRaises(ValueError):
            self.build(text=SAMPLE.replace("Sleeps.", "Sleeps.\x1b[31m"))

    def test_write_doc_round_trip_one_entry_per_line(self):
        doc = self.build()
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "lsl_doc.json")
            ub.write_doc(doc, path)
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        self.assertEqual(json.loads(text), doc)
        self.assertIn('\n"llListen": {', text)


if __name__ == "__main__":
    unittest.main()
