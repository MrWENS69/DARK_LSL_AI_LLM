#!/usr/bin/env python3
"""lslcheck - run lslint over LSL files and report in a compact, machine-friendly way.

Designed for scripted use (CI, editors, AI coding assistants): one line per
finding in GCC style, a one-line summary, a meaningful exit code, and an
optional JSON mode. When no lslint binary is available, the one published
for this platform on the project's GitHub releases is downloaded once and
cached.

Usage:
    python lslcheck.py script.lsl
    python lslcheck.py src/ other.lsl          # directories are scanned for *.lsl
    python lslcheck.py --json src/ > report.json
    python lslcheck.py --strict script.lsl     # warnings also fail
    python lslcheck.py -w -z script.lsl        # pass lslint flags through
    uvx --from git+https://github.com/MrWENS69/DARK_LSL_AI_LLM lslcheck script.lsl

Exit codes: 0 clean, 1 findings (errors, or warnings with --strict), 2 lslint
not found or crashed.

The lslint binary is looked up in this order: --lslint, the LSLINT environment
variable, lslint(.exe) next to this script, PATH, the download cache, and
finally a download from the latest GitHub release (disable with
--no-download or LSLCHECK_NO_DOWNLOAD=1).
"""

import argparse
import hashlib
import io
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("LSLCHECK_REPO", "MrWENS69/DARK_LSL_AI_LLM")
BINARY = "lslint.exe" if os.name == "nt" else "lslint"

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


# --- locating or fetching the binary -------------------------------------

def cache_dir():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "lslcheck")


def platform_asset():
    """Suffix of the release asset for this machine, or None when unsupported."""
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows" and machine in ("amd64", "x86_64"):
        return "win64"
    if system == "Linux" and machine in ("x86_64", "amd64"):
        return "linux64"
    if system == "Darwin":
        return "macos-arm64" if machine in ("arm64", "aarch64") else "macos-x64"
    return None


def cached_binary():
    """Newest binary in the download cache, or None."""
    root = cache_dir()
    if not os.path.isdir(root):
        return None
    candidates = []
    for tag in os.listdir(root):
        path = os.path.join(root, tag, BINARY)
        if os.path.isfile(path):
            candidates.append((os.path.getmtime(path), path))
    return max(candidates)[1] if candidates else None


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "lslcheck"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def download_binary(log):
    """Download the latest release binary for this platform into the cache."""
    suffix = platform_asset()
    if not suffix:
        log("no prebuilt lslint for %s %s" % (platform.system(), platform.machine()))
        return None
    try:
        release = json.loads(fetch("https://api.github.com/repos/%s/releases/latest" % REPO))
    except Exception as exc:  # network, 404 when no release yet, bad JSON
        log("cannot query releases of %s: %s" % (REPO, exc))
        return None
    tag = release.get("tag_name", "")
    assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
    wanted = [name for name in assets if name.endswith("_%s.zip" % suffix)]
    if not wanted:
        log("release %s has no asset for %s" % (tag, suffix))
        return None
    name = wanted[0]
    log("downloading lslint %s (%s)" % (tag, name))
    try:
        blob = fetch(assets[name])
        sums = fetch(assets["SHA256SUMS.txt"]).decode("utf-8") if "SHA256SUMS.txt" in assets else ""
    except Exception as exc:
        log("download failed: %s" % exc)
        return None
    if sums:
        expected = dict(line.split()[::-1] for line in sums.splitlines() if line.strip())
        actual = hashlib.sha256(blob).hexdigest()
        if expected.get(name) != actual:
            log("checksum mismatch for %s, refusing to use it" % name)
            return None
    target_dir = os.path.join(cache_dir(), tag)
    os.makedirs(target_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        members = [m for m in archive.namelist() if os.path.basename(m) == BINARY]
        if not members:
            log("%s does not contain %s" % (name, BINARY))
            return None
        target = os.path.join(target_dir, BINARY)
        with archive.open(members[0]) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
    os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    log("installed %s" % target)
    return target


def find_lslint(explicit, allow_download, log):
    candidates = []
    if explicit:
        candidates.append(explicit)
    if os.environ.get("LSLINT"):
        candidates.append(os.environ["LSLINT"])
    candidates.append(os.path.join(HERE, BINARY))
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    found = shutil.which("lslint")
    if found:
        return found
    found = cached_binary()
    if found:
        return found
    if allow_download:
        return download_binary(log)
    return None


# --- running and parsing ---------------------------------------------------

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
    ap.add_argument("--no-side-effects", dest="side_effects", action="store_false",
                    help="disable the && / || side-effect check (lslint -s), on by default")
    ap.add_argument("--no-download", action="store_true",
                    help="never download the binary from GitHub releases")
    for short, long_, help_ in PASSTHROUGH:
        ap.add_argument(short, long_, dest=dest_name(long_), action="store_true", help=help_)
    args = ap.parse_args(argv)

    def log(text):
        sys.stderr.write("lslcheck: %s\n" % text)

    allow_download = not args.no_download and not os.environ.get("LSLCHECK_NO_DOWNLOAD")
    lslint = find_lslint(args.lslint, allow_download, log)
    if not lslint:
        log("lslint binary not found (use --lslint, LSLINT env var, or build it first)")
        return 2

    flags = ["-#", "-l", "-m-" if args.lso else "-m"]
    if args.side_effects:
        flags.append("-s")
    for short, long_, _ in PASSTHROUGH:
        if getattr(args, dest_name(long_)):
            flags.append(short)
    if args.builtins:
        flags += ["-b", args.builtins]

    files = collect(args.paths)
    if not files:
        log("no .lsl files found")
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
