#!/usr/bin/env python3
"""Unit tests for the lsl_definitions.yaml reader, the lsl_doc.json builder and the whole offline run.
Run: python -m unittest test_update_builtins"""

import io
import json
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

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


BUILTINS_TXT = """// a header line
integer llListen(integer channel, string name)
void llSleep(float sec)
event state_entry()
event listen(integer channel, string msg)
const integer CHANGED_INVENTORY = 0x1
"""


class MainTest(unittest.TestCase):
    """The whole run, offline, in a scratch tree: the builtins are refreshed even when the --doc reference fails (#27)."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        data = self.root / "lsltest" / "data"
        data.mkdir(parents=True)
        (data / "lsl_doc.json").write_text("previous reference", encoding="utf-8")

    def read(self, *parts):
        return self.root.joinpath(*parts).read_text(encoding="utf-8")

    def run_main(self, yaml_text, builtins_text=BUILTINS_TXT, actions=False):
        """(exit status, stdout, stderr); GITHUB_ACTIONS is set only on request, whatever the machine has."""
        (self.root / "in.txt").write_text(builtins_text, encoding="utf-8")
        (self.root / "in.yaml").write_text(yaml_text, encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.multiple(ub, ROOT=self.root, BUILTINS_TXT=self.root / "builtins.txt",
                                 BUILTINS_CC=self.root / "builtins_txt.cc", VERSION_TXT=self.root / "builtins_version.txt",
                                 DOC_JSON=self.root / "lsltest" / "data" / "lsl_doc.json"), \
                mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true" if actions else ""}), \
                redirect_stdout(out), redirect_stderr(err):
            code = ub.main(["--from-file", str(self.root / "in.txt"), "--yaml-file", str(self.root / "in.yaml")])
        return code, out.getvalue(), err.getvalue()

    def test_full_refresh(self):
        code, out, err = self.run_main(SAMPLE)
        self.assertEqual(code, 0, err)
        self.assertIn("integer llListen(integer channel, string name)", self.read("builtins.txt"))
        self.assertEqual(sorted(json.loads(self.read("lsltest", "data", "lsl_doc.json"))),
                         ["constants", "events", "functions", "source"])
        self.assertIn("lsl_doc.json (2 functions, 2 events", out)

    def test_broken_yaml_keeps_the_reference_and_refreshes_the_builtins(self):
        broken = SAMPLE.replace("tooltip: Sleeps. # trailing comment", "tooltip: &anchor Sleeps.")
        code, out, err = self.run_main(broken)
        self.assertEqual(code, ub.EXIT_DOC_KEPT)
        self.assertIn("integer llListen(integer channel, string name)", self.read("builtins.txt"))
        self.assertEqual(self.read("lsltest", "data", "lsl_doc.json"), "previous reference")
        self.assertIn("warning: lsltest/data/lsl_doc.json left as it was", err)
        self.assertIn("unsupported YAML syntax", err)
        self.assertNotIn("::warning", out)

    def test_signature_mismatch_is_reported_the_same_way_and_annotated_under_actions(self):
        wrong = BUILTINS_TXT.replace("string name", "key name")
        code, out, err = self.run_main(SAMPLE, wrong, actions=True)
        self.assertEqual(code, ub.EXIT_DOC_KEPT)
        self.assertIn("integer llListen(integer channel, key name)", self.read("builtins.txt"))
        self.assertEqual(self.read("lsltest", "data", "lsl_doc.json"), "previous reference")
        self.assertIn("the YAML signature differs from builtins.txt", err)
        self.assertIn("::warning::lsltest/data/lsl_doc.json left as it was", out)

    def test_annotation_is_one_line_and_cannot_start_another_command(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), redirect_stdout(out), redirect_stderr(io.StringIO()):
            ub._warn("line one\n::error::forged\nkey %0A::error::decoded")
        lines = out.getvalue().splitlines()
        self.assertEqual(lines, ["::warning::line one ::error::forged key %250A::error::decoded"])


class BundledFilesTest(unittest.TestCase):
    """The bundled files are valid, whatever upstream wrote in them (the tests never
    assert on their content, a kept lsl_doc.json may lag behind builtins.txt by design, see #27)."""

    def test_bundled_reference_is_valid(self):
        doc = json.loads(ub.DOC_JSON.read_text(encoding="utf-8"))
        self.assertEqual(sorted(doc), ["constants", "events", "functions", "source"])
        for section in ub.DOC_SECTIONS:
            self.assertTrue(doc[section], section)

    def test_bundled_builtins_parse(self):
        functions, events, constants = ub.parse((ub.ROOT / "lsltest" / "data" / "builtins.txt").read_text(encoding="utf-8"))
        self.assertTrue(functions and events and constants)


if __name__ == "__main__":
    unittest.main()
