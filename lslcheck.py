#!/usr/bin/env python3
"""lslcheck - run lslint over LSL files and report in a compact, machine-friendly way.

Designed for scripted use (CI, editors, AI coding assistants): one line per
finding in GCC style, a one-line summary, a meaningful exit code, and an
optional JSON mode.

Usage:
    python lslcheck.py script.lsl
    python lslcheck.py src/ other.lsl          # directories are scanned for *.lsl
    python lslcheck.py --json src/ > report.json
    python lslcheck.py --strict script.lsl     # warnings also fail
    python lslcheck.py -w -z script.lsl        # pass lslint flags through

Exit codes: 0 clean, 1 findings (errors, or warnings with --strict), 2 lslint
not found or crashed.

The lslint binary is looked up in this order: --lslint, the LSLINT environment
variable, lslint(.exe) next to this script, then PATH.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

MESSAGE_RE = re.compile(
    r"^\s*(?P<level>ERROR|WARN|INFO)::\s*"
    r"(?:\(\s*(?P<line>\d+),\s*(?P<col>\d+)\)"
    r"(?:-\(\s*(?P<end_line>\d+),\s*(?P<end_col>\d+)\))?:\s*)?"
    r"(?:\[(?P<code>E\d{5})\]\s*)?(?P<message>.*)$"
)
TOTAL_RE = re.compile(r"^TOTAL::\s*Errors:\s*(?P<errors>\d+)\s+Warnings:\s*(?P<warnings>\d+)")

PASSTHROUGH = [
    # (short flag, long flag, help)
    ("-w", "--switch", "enable switch statements"),
    ("-z", "--lazy-lists", "enable lazy list syntax"),
    ("-i", "--ignore-preproc", "ignore preprocessor directives"),
    ("-u", "--unused-params", "warn about unused event parameters"),
    ("-G", "--god-mode", "enable god mode"),
    ("-F", "--function-override", "allow overriding builtin functions"),
]


def dest_name(long_flag):
    return long_flag.lstrip("-").replace("-", "_")


def find_lslint(explicit):
    candidates = []
    if explicit:
        candidates.append(explicit)
    if os.environ.get("LSLINT"):
        candidates.append(os.environ["LSLINT"])
    candidates.append(os.path.join(HERE, "lslint.exe"))
    candidates.append(os.path.join(HERE, "lslint"))
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return shutil.which("lslint")


def collect(paths):
    files = []
    for path in paths:
        if os.path.isdir(path):
            for root, _dirs, names in os.walk(path):
                for name in sorted(names):
                    if name.lower().endswith(".lsl"):
                        files.append(os.path.join(root, name))
        elif os.path.isfile(path):
            files.append(path)
        else:
            sys.stderr.write("lslcheck: no such file or directory: %s\n" % path)
    return files


def parse_output(text):
    messages = []
    errors = warnings = None
    for raw in text.splitlines():
        line = raw.rstrip()
        total = TOTAL_RE.match(line)
        if total:
            errors = int(total.group("errors"))
            warnings = int(total.group("warnings"))
            continue
        m = MESSAGE_RE.match(line)
        if m:
            d = m.groupdict()
            for key in ("line", "col", "end_line", "end_col"):
                d[key] = int(d[key]) if d[key] is not None else None
            messages.append(d)
        elif messages and line.strip():
            # continuation line of a multi-line message
            messages[-1]["message"] += " " + line.strip()
    if errors is None:
        errors = sum(1 for m in messages if m["level"] == "ERROR")
        warnings = sum(1 for m in messages if m["level"] == "WARN")
    return messages, errors, warnings


def run_one(lslint, flags, path):
    cmd = [lslint] + flags + [path]
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        return None, "cannot run %s: %s" % (lslint, exc)
    messages, errors, warnings = parse_output(proc.stdout)
    crashed = proc.returncode not in (0, 1) and not messages and errors == 0 and warnings == 0
    if crashed:
        return None, proc.stdout.strip() or ("lslint exited with code %d" % proc.returncode)
    return {"path": path, "errors": errors, "warnings": warnings, "messages": messages}, None


def format_text(result):
    out = []
    for m in result["messages"]:
        if m["level"] == "ERROR":
            level = "error"
        elif m["level"] == "WARN":
            level = "warning"
        else:
            level = "note"
        where = result["path"]
        if m["line"] is not None:
            where += ":%d:%d" % (m["line"], m["col"])
        code = ("[%s] " % m["code"]) if m["code"] else ""
        out.append("%s: %s: %s%s" % (where, level, code, m["message"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="lslcheck",
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("paths", nargs="+", help="LSL files or directories")
    ap.add_argument("--lslint", help="path to the lslint binary")
    ap.add_argument("-b", "--builtins", help="alternate builtins.txt")
    ap.add_argument("--lso", action="store_true", help="use LSO rules instead of Mono")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    ap.add_argument("--json", action="store_true", help="emit a JSON report instead of text")
    ap.add_argument("-q", "--quiet", action="store_true", help="only print the summary line")
    for short, long_, help_ in PASSTHROUGH:
        ap.add_argument(short, long_, dest=dest_name(long_), action="store_true", help=help_)
    args = ap.parse_args(argv)

    lslint = find_lslint(args.lslint)
    if not lslint:
        sys.stderr.write("lslcheck: lslint binary not found (use --lslint, LSLINT env var, or build it first)\n")
        return 2

    flags = ["-#", "-l", "-m-" if args.lso else "-m"]
    for short, long_, _ in PASSTHROUGH:
        if getattr(args, dest_name(long_)):
            flags.append(short)
    if args.builtins:
        flags += ["-b", args.builtins]

    files = collect(args.paths)
    if not files:
        sys.stderr.write("lslcheck: no .lsl files found\n")
        return 2

    results, failures = [], []
    for path in files:
        result, failure = run_one(lslint, flags, path)
        if failure:
            failures.append({"path": path, "error": failure})
        else:
            results.append(result)

    total_errors = sum(r["errors"] for r in results)
    total_warnings = sum(r["warnings"] for r in results)
    failed = total_errors > 0 or (args.strict and total_warnings > 0) or bool(failures)

    if args.json:
        json.dump({
            "lslint": lslint,
            "flags": flags,
            "files": results,
            "failures": failures,
            "total": {"files": len(files), "errors": total_errors, "warnings": total_warnings},
            "ok": not failed,
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        if not args.quiet:
            for r in results:
                for line in format_text(r):
                    print(line)
        for f in failures:
            print("%s: error: lslint failed: %s" % (f["path"], f["error"]))
        status = " -> FAIL" if failed else ""
        print("%d file(s), %d error(s), %d warning(s)%s" % (len(files), total_errors, total_warnings, status))

    if failures:
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
