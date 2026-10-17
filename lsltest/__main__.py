"""Command line: run LSL test files, or smoke-run one script.

    python -m lsltest tests/             # every test_*.py under tests/ (the default folder)
    python -m lsltest tests/test_door.py
    lsltest script.lsl                   # no test: parse, run state_entry, touch once, report what happened

Exit codes: 0 when every test passed (or the smoke run had no script error),
1 when a test failed, no test was found or the smoke run hit a script error,
2 when a path is missing, is not a folder or a test_*.py file, cannot be
read, or the script does not parse.
"""

import argparse
import os
import sys
import unicodedata
import unittest

from .errors import LslSyntaxError
from .sim import Simulator


def _safe(text):
    """Printable form of text: control and format characters escaped, so a script cannot drive the terminal."""
    out = []
    for c in text:
        if unicodedata.category(c)[0] == "C" or c in "  ":
            out.append(repr(c)[1:-1])
        else:
            out.append(c)
    encoding = sys.stdout.encoding or "utf-8"
    return "".join(out).encode(encoding, "backslashreplace").decode(encoding)


def run_tests(paths, verbosity):
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for path in paths:
        path = os.path.abspath(path)
        is_dir = os.path.isdir(path)
        if not is_dir and not path.lower().endswith(".py"):
            sys.stderr.write("lsltest: %s is neither a folder nor a test_*.py file\n" % path)
            return 2
        folder = os.path.dirname(path)
        if folder not in sys.path:
            sys.path.append(folder)
        if is_dir:
            suite.addTests(loader.discover(path, pattern="test_*.py", top_level_dir=path))
        else:
            suite.addTests(loader.loadTestsFromName(os.path.splitext(os.path.basename(path))[0]))
    if suite.countTestCases() == 0:
        sys.stderr.write("lsltest: no test found under %s (looked for test_*.py)\n" % ", ".join(paths))
        return 1
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    return 0 if result.wasSuccessful() else 1


def smoke(path):
    """Load a script, run its state_entry, touch it once, and print what the simulator saw."""
    sim = Simulator()
    try:
        script = sim.load(path)
    except (LslSyntaxError, OSError, UnicodeDecodeError) as err:
        sys.stderr.write("%s: %s\n" % (path, _safe(str(err))))
        return 2
    sim.start()
    sim.touch()
    print("state: %s" % script.state)
    for line in sim.chat:
        print("chat[%d] %s: %s" % (line.channel, line.kind, _safe(line.text)))
    for dialog in sim.dialogs:
        print("dialog on %d: %s %r" % (dialog.channel, _safe(dialog.text), [_safe(b) for b in dialog.buttons]))
    for box in sim.textboxes:
        print("textbox on %d: %s" % (box.channel, _safe(box.text)))
    for message in sim.link_messages:
        print("link_message %d %s %s" % (message.num, _safe(message.str), _safe(message.id)))
    for request in sim.http_out:
        print("http %s %s" % (_safe(request.method), _safe(request.url)))
    for mail in sim.emails:
        print("email to %s: %s" % (_safe(mail.to), _safe(mail.subject)))
    for _, builtin, args in sim.calls:
        print("recorded %s%s" % (builtin, _safe(repr(tuple(args)))))
    for name, err in sim.errors:
        print("ERROR in %s: %s" % (name, _safe(str(err))))
    return 1 if sim.errors else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lsltest", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", default=["tests"], help="test folders or test_*.py files, or one .lsl script for a smoke run")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    missing = [p for p in args.paths if not os.path.exists(p)]
    if missing:
        sys.stderr.write("lsltest: no such path: %s\n" % ", ".join(missing))
        return 2
    if len(args.paths) == 1 and args.paths[0].lower().endswith(".lsl"):
        return smoke(args.paths[0])
    return run_tests(args.paths, 2 if args.verbose else 1)


if __name__ == "__main__":
    sys.exit(main())
