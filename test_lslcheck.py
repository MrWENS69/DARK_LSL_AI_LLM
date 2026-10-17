#!/usr/bin/env python3
"""Unit tests for lslcheck.py. Run with: python -m unittest -v test_lslcheck

The integration test needs a built lslint binary next to lslcheck.py and is
skipped otherwise.
"""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

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
