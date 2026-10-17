#!/usr/bin/env python3
"""Refresh builtins.txt from secondlife/lsl-definitions and regenerate builtins_txt.cc.

Linden Lab publishes the canonical LSL definitions at
https://github.com/secondlife/lsl-definitions and already renders them in the
lslint builtins.txt format (generated/builtins.txt). This script downloads that
file, stamps it with the source commit, writes builtins_version.txt and
regenerates builtins_txt.cc exactly as the Makefile sed rule would.

Usage:
    python update_builtins.py            # fetch generated/builtins.txt from main
    python update_builtins.py --ref v1.2 # any git ref of lsl-definitions
    python update_builtins.py --from-file path/to/builtins.txt   # offline

Requires Python 3.8+, standard library only.
"""

import argparse
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request

REPO = "secondlife/lsl-definitions"
ROOT = pathlib.Path(__file__).resolve().parent
BUILTINS_TXT = ROOT / "builtins.txt"
BUILTINS_CC = ROOT / "builtins_txt.cc"
VERSION_TXT = ROOT / "builtins_version.txt"

# Every line ends up inside a C string literal in builtins_txt.cc and in a
# 1024-byte buffer in builtins.cc. Allowed: printable ASCII plus the JSON_*
# noncharacter constants (U+FDD0..U+FDEF) and the control character inside
# NAK, a sane length, no backslash other
# than the \n of EOF and NAK, no quote outside a string constant's value.
SAFE_LINE = re.compile(r"[\x15\x20-\x7e\ufdd0-\ufdef]{1,1000}")  # \x15: the NAK constant


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "lslint-update-builtins"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read(5000000)


def check_line(line):
    if not SAFE_LINE.fullmatch(line):
        raise ValueError("unsafe builtins line: %r" % line)
    if re.search(r"\\(?!n)", line) or "??" in line or "*/" in line:
        raise ValueError("unexpected backslash or trigraph: %r" % line)
    body = re.sub(r'^const string \w+ = "(.*)"$', r"\1", line)
    if '"' in body:
        raise ValueError("unexpected quote: %r" % line)


def parse(text):
    """Return dicts of functions, events and constants keyed by name."""
    functions, events, constants = {}, {}, {}
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.startswith("//"):
            continue
        check_line(line)
        m = re.match(r"const (\w+) (\w+) = (.*)$", line)
        if m:
            constants[m.group(2)] = (m.group(1), m.group(3))
            continue
        m = re.match(r"event (\w+)\((.*)\)$", line)
        if m:
            events[m.group(1)] = m.group(2).strip()
            continue
        m = re.match(r"(\w+) (\w+)\((.*)\)$", line)
        if m:
            functions[m.group(2)] = (m.group(1), m.group(3).strip())
            continue
        raise ValueError("unrecognized builtins line: %r" % line)
    return functions, events, constants


def render_cc(text):
    """Mirror the Makefile rule: drop // lines, escape quotes, wrap each line."""
    out = [
        "#ifdef _MSC_VER",
        '#pragma execution_character_set("utf-8")',
        "#endif",
        "const char *builtins_txt[] = {",
    ]
    for line in text.splitlines():
        if line.startswith("//") or not line.strip():
            continue
        out.append('"%s",' % line.replace("\\", "\\\\").replace('"', '\\"'))
    out.append("(char*)0 };")
    return "\n".join(out) + "\n"


def report(old_text, new_text):
    old = parse(old_text) if old_text else ({}, {}, {})
    new = parse(new_text)
    for label, o, n in zip(("functions", "events", "constants"), old, new):
        added = sorted(set(n) - set(o))
        removed = sorted(set(o) - set(n))
        changed = sorted(k for k in o if k in n and o[k] != n[k])
        print("%-10s %4d  (+%d -%d ~%d)" % (label, len(n), len(added), len(removed), len(changed)))
        for name in added:
            print("   + " + name)
        for name in removed:
            print("   - " + name)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref", default="main", help="git ref of %s (default: main)" % REPO)
    ap.add_argument("--from-file", help="use a local builtins.txt instead of downloading")
    args = ap.parse_args()

    if args.from_file:
        source = pathlib.Path(args.from_file)
        text = source.read_text(encoding="utf-8")
        stamp = "local file %s" % source.name
        version_body = "Source: local file %s\n" % source.name
    else:
        ref = urllib.parse.quote(args.ref, safe="/")
        commit = json.loads(fetch("https://api.github.com/repos/%s/commits/%s" % (REPO, ref)))
        sha = commit["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            sys.exit("unexpected commit sha from the GitHub API: %r" % sha)
        date = commit["commit"]["committer"]["date"][:10]
        text = fetch("https://raw.githubusercontent.com/%s/%s/generated/builtins.txt" % (REPO, sha)).decode("utf-8")
        stamp = "%s commit %s (%s)" % (REPO, sha[:12], date)
        version_body = (
            "Source: https://github.com/%s\n"
            "Commit: %s\n"
            "Date: %s\n"
            "File: generated/builtins.txt\n" % (REPO, sha, date)
        )

    body = "\n".join(l for l in text.splitlines() if l.strip() and not l.startswith("//"))
    new_text = "// Generated from %s by update_builtins.py\n%s\n" % (stamp, body)
    parse(new_text)  # validate before writing anything

    old_text = BUILTINS_TXT.read_text(encoding="utf-8") if BUILTINS_TXT.exists() else ""
    report(old_text, new_text)

    BUILTINS_TXT.write_text(new_text, encoding="utf-8", newline="\n")
    BUILTINS_CC.write_text(render_cc(new_text), encoding="utf-8", newline="\n")
    VERSION_TXT.write_text(version_body, encoding="utf-8", newline="\n")
    bundled = ROOT / "lsltest" / "data" / "builtins.txt"      # the copy shipped inside the lsltest package
    if bundled.parent.is_dir():
        bundled.write_text(new_text, encoding="utf-8", newline="\n")
    print("wrote %s, %s, %s" % (BUILTINS_TXT.name, BUILTINS_CC.name, VERSION_TXT.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
