"""Command line: run LSL test files.

    python -m lsltest tests/             # every test_*.py under tests/
    python -m lsltest tests/test_door.py
    lsltest script.lsl                   # no test: parse and run state_entry, report what happened
"""

import argparse
import os
import sys
import unittest


def run_tests(paths, verbosity):
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for path in paths:
        path = os.path.abspath(path)
        if os.path.isdir(path):
            parent = os.path.dirname(path)
            if parent not in sys.path:
                sys.path.insert(0, parent)
            suite.addTests(loader.discover(path, pattern="test_*.py", top_level_dir=path))
        else:
            folder = os.path.dirname(path)
            if folder not in sys.path:
                sys.path.insert(0, folder)
            module = os.path.splitext(os.path.basename(path))[0]
            suite.addTests(loader.loadTestsFromName(module))
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    return 0 if result.wasSuccessful() else 1


def smoke(path):
    """Load a script, run its state_entry, touch it once, and print what the simulator saw."""
    from .sim import Simulator
    sim = Simulator()
    script = sim.load(path)
    sim.start()
    sim.touch()
    print("state: %s" % script.state)
    for line in sim.chat:
        print("chat[%d] %s: %s" % (line.channel, line.kind, line.text))
    for dialog in sim.dialogs:
        print("dialog on %d: %s %r" % (dialog["channel"], dialog["text"], dialog["buttons"]))
    for request in sim.http_requests:
        print("http %s %s" % (request.method, request.url))
    for name, builtin, args in sim.calls:
        print("recorded %s%r" % (builtin, tuple(args)))
    for name, err in sim.errors:
        print("ERROR in %s: %s" % (name, err))
    return 1 if sim.errors else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lsltest", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", default=["tests"], help="test folders or files, or a .lsl script for a smoke run")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if len(args.paths) == 1 and args.paths[0].lower().endswith(".lsl"):
        return smoke(args.paths[0])
    missing = [p for p in args.paths if not os.path.exists(p)]
    if missing:
        sys.stderr.write("lsltest: no such path: %s\n" % ", ".join(missing))
        return 2
    return run_tests(args.paths, 2 if args.verbose else 1)


if __name__ == "__main__":
    sys.exit(main())
