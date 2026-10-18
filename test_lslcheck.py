#!/usr/bin/env python3
"""Unit tests for lslcheck.py. Run with: python -m unittest -v test_lslcheck

The integration test needs a built lslint binary next to lslcheck.py and is
skipped otherwise.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import lslcheck

HERE = os.path.dirname(os.path.abspath(__file__))
BINARY = os.path.join(HERE, lslcheck.BINARY)


class ParseOutputTest(unittest.TestCase):
    def test_messages_with_codes_ranges_and_total(self):
        text = (
            "ERROR:: ( 12,  5)-( 12, 20): [E10026] Not all code paths return a value.\n"
            " WARN:: ( 22,  9): [E20009] variable `x' declared but never used.\n"
            "TOTAL:: Errors: 1  Warnings: 1\n"
        )
        messages, errors, warnings = lslcheck.parse_output(text)
        self.assertEqual((errors, warnings), (1, 1))
        self.assertEqual(len(messages), 2)
        first = messages[0]
        self.assertEqual((first["level"], first["line"], first["col"], first["end_line"], first["end_col"]), ("ERROR", 12, 5, 12, 20))
        self.assertEqual(first["code"], "E10026")
        self.assertEqual(messages[1]["message"], "variable `x' declared but never used.")

    def test_message_without_location_and_continuation(self):
        text = (
            " WARN:: (  3,  1): [E20017] No default label in switch statement.\n"
            "      See: https://example.invalid/FIRE-17710\n"
            "ERROR:: Assertion failed: error 10033 on line 41.\n"
            "TOTAL:: Errors: 1  Warnings: 1\n"
        )
        messages, errors, warnings = lslcheck.parse_output(text)
        self.assertEqual(len(messages), 2)
        self.assertIn("See: https://example.invalid/FIRE-17710", messages[0]["message"])
        self.assertIsNone(messages[1]["line"])
        self.assertEqual(messages[1]["message"], "Assertion failed: error 10033 on line 41.")

    def test_counts_without_total_line(self):
        text = "ERROR:: (  1,  1): [E10001] bad\nERROR:: (  2,  1): [E10001] bad\n WARN:: (  3,  1): meh\n"
        _, errors, warnings = lslcheck.parse_output(text)
        self.assertEqual((errors, warnings), (2, 1))

    def test_empty_output(self):
        self.assertEqual(lslcheck.parse_output(""), ([], 0, 0))


class FormatTextTest(unittest.TestCase):
    def test_gcc_style_lines(self):
        result = {"path": "a.lsl", "messages": [
            {"level": "ERROR", "line": 3, "col": 7, "end_line": None, "end_col": None, "code": "E10033", "message": "break outside switch"},
            {"level": "WARN", "line": None, "col": None, "end_line": None, "end_col": None, "code": None, "message": "no location"},
        ]}
        self.assertEqual(lslcheck.format_text(result), [
            "a.lsl:3:7: error: [E10033] break outside switch",
            "a.lsl: warning: no location",
        ])


class PlatformTest(unittest.TestCase):
    def test_asset_suffix_is_known_or_none(self):
        suffix = lslcheck.platform_asset()
        self.assertIn(suffix, (None, "win64", "linux64", "macos-arm64", "macos-x64"))

    def test_cache_dir_is_absolute(self):
        self.assertTrue(os.path.isabs(lslcheck.cache_dir()))


class FindBinaryTest(unittest.TestCase):
    def test_explicit_path_wins(self):
        self.assertEqual(lslcheck.find_lslint(__file__, False, lambda _: None), __file__)

    def test_missing_without_download_returns_none(self):
        env = os.environ.get("LSLINT")
        os.environ["LSLINT"] = os.path.join(HERE, "does-not-exist")
        try:
            if os.path.isfile(BINARY) or lslcheck.shutil.which("lslint") or lslcheck.cached_binary():
                self.skipTest("a binary is available, lookup would succeed")
            self.assertIsNone(lslcheck.find_lslint(None, False, lambda _: None))
        finally:
            if env is None:
                del os.environ["LSLINT"]
            else:
                os.environ["LSLINT"] = env


DOC_FIXTURE = {
    "source": "fixture",
    "functions": {
        "llListen": {"return": "integer", "sleep": 0.0, "energy": 10.0,
                     "tooltip": "Sets a callback for msg on channel from name and id.",
                     "args": [["channel", "integer", "Channel to listen on."], ["name", "string", ""],
                              ["id", "key", ""], ["msg", "string", ""]]},
        "llSleep": {"return": "void", "sleep": 0.0, "energy": 0.0,
                    "tooltip": "Puts the script to sleep for sec seconds.", "args": [["sec", "float", "Seconds to pause."]]},
    },
    "events": {
        "listen": {"tooltip": "Triggered by chat on a channel the script listens to.",
                   "args": [["channel", "integer", ""], ["name", "string", ""], ["id", "key", ""], ["msg", "string", ""]]},
        "changed": {"tooltip": "Triggered when something about the object changes.", "args": [["changes", "integer", ""]]},
    },
    "constants": {
        "CHANGED_INVENTORY": {"type": "integer", "value": "0x1", "tooltip": "The inventory changed."},
        "CHANGED_REGION_START": {"type": "integer", "value": "0x400", "tooltip": "The region restarted."},
        "ATTACH_RPEC": {"type": "integer", "value": "29", "tooltip": "Attachment point for the avatar's left pectoral.",
                        "deprecated": True, "use": "ATTACH_LEFT_PEC"},    # the real quirk: RPEC is the left one
    },
}


class DocTest(unittest.TestCase):
    """--doc needs no binary. The tests read DOC_FIXTURE, so an upstream tooltip rewrite cannot turn them red."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.fixture = os.path.join(cls.folder.name, "lsl_doc.json")
        with open(cls.fixture, "w", encoding="utf-8") as handle:
            json.dump(DOC_FIXTURE, handle)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        patcher = mock.patch.object(lslcheck, "doc_file", lambda: self.fixture)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_doc(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = lslcheck.main(["--doc"] + list(argv))
        return code, out.getvalue()

    def test_exact_function(self):
        code, out = self.run_doc("llListen")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("integer llListen(integer channel, string name, key id, string msg)"), out)
        self.assertIn("channel:", out)
        self.assertIn("wiki.secondlife.com/wiki/LlListen", out)

    def test_event_constant_and_prefix(self):
        code, out = self.run_doc("listen", "CHANGED_INVENTORY", "CHANGED_")
        self.assertEqual(code, 0, out)
        self.assertIn("event listen(integer channel", out)
        self.assertIn("integer CHANGED_INVENTORY = 0x1", out)
        self.assertIn("CHANGED_: ", out)
        self.assertIn("CHANGED_REGION_START", out)

    def test_a_word_that_is_an_event_also_lists_the_constants(self):
        code, out = self.run_doc("CHANGED")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("event changed(integer "), out)
        self.assertIn("CHANGED_INVENTORY", out)

    def test_doc_mixed_with_paths_is_a_usage_error(self):
        for argv in (["--doc", "llSay", "script.lsl"], ["script.lsl", "--doc", "llSay"]):
            with self.assertRaises(SystemExit):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    lslcheck.main(argv)

    def test_unknown_name_fails(self):
        code, out = self.run_doc("llNoSuchThing")
        self.assertEqual(code, 1)
        self.assertIn("no function, event or constant", out)

    def test_json(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = lslcheck.main(["--json", "--doc", "llSleep"])
        report = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        hit = report["results"][0]["matches"][0]
        self.assertEqual(hit["kind"], "function")
        self.assertEqual(hit["args"][0][:2], ["sec", "float"])
        self.assertIn("sleep", hit["tooltip"].lower())

    def test_no_paths_and_no_doc_is_a_usage_error(self):
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()):
                lslcheck.main([])

    def test_deprecated_constant_names_its_replacement(self):
        code, out = self.run_doc("ATTACH_RPEC")
        self.assertEqual(code, 0, out)
        self.assertIn("deprecated, use ATTACH_LEFT_PEC", out)


@unittest.skipUnless(os.path.isfile(BINARY), "lslint binary not built")
class IntegrationTest(unittest.TestCase):
    def run_main(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = lslcheck.main(["--lslint", BINARY, "--no-download"] + list(argv))
        return code, out.getvalue()

    def test_clean_script_exits_zero(self):
        code, out = self.run_main(os.path.join(HERE, "scripts", "test1.lsl"))
        self.assertEqual(code, 0, out)
        self.assertTrue(out.strip().endswith("0 error(s), 0 warning(s)"), out)

    def test_side_effects_corpus_reports_w20024(self):
        code, out = self.run_main("--strict", os.path.join(HERE, "scripts", "side_effects", "logical_ops.lsl"))
        # the $[E20024] markers in the corpus suppress the expected warnings (-a is on by default)
        self.assertEqual(code, 0, out)

    def test_sibling_writes_corpus_is_clean_under_strict(self):
        # every W20025 of siblings.lsl is marked, so -s under --strict reports nothing unmarked
        code, out = self.run_main("--strict", os.path.join(HERE, "scripts", "side_effects", "siblings.lsl"))
        self.assertEqual(code, 0, out)

    def test_json_report_shape(self):
        code, out = self.run_main("--json", os.path.join(HERE, "scripts", "test1.lsl"))
        report = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(report["ok"])
        self.assertEqual(report["total"]["files"], 1)
        self.assertIn("-s", report["flags"])
        self.assertEqual(report["files"][0]["errors"], 0)

    def test_directory_scan_and_missing_path(self):
        code, out = self.run_main("-q", os.path.join(HERE, "scripts", "uep"))
        self.assertIn("file(s)", out)
        code, _ = self.run_main(os.path.join(HERE, "no-such-dir"))
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
