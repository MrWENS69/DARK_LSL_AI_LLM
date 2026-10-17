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
    ("-F", "--function-override", "let a later definition of a user function replace an earlier one"),
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
    if "SHA256SUMS.txt" not in assets:
        log("release %s has no SHA256SUMS.txt, refusing to install an unverified binary" % tag)
        return None
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", tag) or ".." in tag:
        log("release tag %r is not a safe directory name" % tag)
        return None
    log("downloading lslint %s (%s)" % (tag, name))
    try:
        blob = fetch(assets[name])
        sums = fetch(assets["SHA256SUMS.txt"]).decode("utf-8")
    except Exception as exc:
        log("download failed: %s" % exc)
        return None
    expected = {}
    for entry in sums.splitlines():
        parts = entry.split()
        if len(parts) == 2:
            expected[parts[1].lstrip("*")] = parts[0].lower()
    if expected.get(name) != hashlib.sha256(blob).hexdigest():
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
        partial = target + ".part"
        with archive.open(members[0]) as src, open(partial, "wb") as dst:
            shutil.copyfileobj(src, dst)
    os.chmod(partial, os.stat(partial).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(partial, target)   # an interrupted download never leaves a truncated binary behind
    log("installed %s" % target)
    return target


def find_lslint(explicit, allow_download, log):
    # An explicit choice is final: a typo must not fall back to another binary.
    for label, cand in (("--lslint", explicit), ("LSLINT", os.environ.get("LSLINT"))):
        if cand:
            if os.path.isfile(cand):
                return cand
            log("%s: no such file: %s" % (label, cand))
            return None
    local = os.path.join(HERE, BINARY)
    if os.path.isfile(local):
        return local
    found = shutil.which("lslint")
    # On Windows, which() may also look in the current directory: a checkout
    # that happens to contain lslint.exe must not be executed by accident.
    if found and os.path.dirname(os.path.abspath(found)) != os.getcwd():
        return found
    found = cached_binary()
    if found:
        return found
    if allow_download:
        return download_binary(log)
    return None


# --- running and parsing ---------------------------------------------------

def collect(paths):
    """Return (files, missing): .lsl files under the given paths, and paths that do not exist."""
    files, missing = [], []
    for path in paths:
        if os.path.isdir(path):
            for root, _dirs, names in os.walk(path):
                for name in sorted(names):
                    if name.lower().endswith(".lsl"):
                        files.append(os.path.join(root, name))
        elif os.path.isfile(path):
            files.append(path)
        else:
            missing.append(path)
    return files, missing


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
    # A path starting with "-" would be read by lslint as an option.
    cmd = [lslint] + flags + [path if os.path.isabs(path) else os.path.join(".", path)]
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=60,
        )
    except OSError as exc:
        return None, "cannot run %s: %s" % (lslint, exc)
    except subprocess.TimeoutExpired:
        return None, "lslint timed out after 60 s"
    messages, errors, warnings = parse_output(proc.stdout)
    # lslint's exit code is its error count, so only a missing TOTAL line (or
    # a signal) tells a crash from a script full of errors.
    saw_total = any(TOTAL_RE.match(line.rstrip()) for line in proc.stdout.splitlines())
    if not saw_total and (proc.returncode < 0 or proc.returncode > 1 or not messages):
        return None, proc.stdout.strip() or ("lslint exited with code %d" % proc.returncode)
    return {"path": path, "errors": errors, "warnings": warnings, "messages": messages}, None


LEVELS = {"ERROR": "error", "WARN": "warning", "INFO": "note"}


def format_text(result):
    out = []
    for m in result["messages"]:
        level = LEVELS.get(m["level"], "note")
        where = result["path"]
        if m["line"] is not None:
            where += ":%d:%d" % (m["line"], m["col"])
        code = ("[%s] " % m["code"]) if m["code"] else ""
        out.append("%s: %s: %s%s" % (where, level, code, m["message"]))
    return out


# --- --doc: the offline reference ------------------------------------------------------

_UNPRINTABLE = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def doc_file():
    """lsl_doc.json: next to this script in a checkout, inside the lsltest package when installed."""
    local = os.path.join(HERE, "lsltest", "data", "lsl_doc.json")
    if os.path.isfile(local):
        return local
    try:
        import lsltest
    except ImportError:
        return None
    installed = os.path.join(os.path.dirname(os.path.abspath(lsltest.__file__)), "data", "lsl_doc.json")
    return installed if os.path.isfile(installed) else None


def doc_lookup(doc, query):
    """The entries for one query, each the lsl_doc.json entry plus kind and name: the exact name, else the
    names equal to it ignoring case, else every name starting with it (ignoring case)."""
    entries = [dict(entry, kind=kind, name=name)
               for kind, table in (("function", doc["functions"]), ("event", doc["events"]), ("constant", doc["constants"]))
               for name, entry in table.items()]
    exact = [e for e in entries if e["name"] == query]
    if exact:
        return exact
    folded = query.lower()
    same = [e for e in entries if e["name"].lower() == folded]
    if same:
        return same
    return sorted((e for e in entries if e["name"].lower().startswith(folded)), key=lambda e: (e["kind"], e["name"]))


def wiki_url(hit):
    page = hit["name"] if hit["kind"] == "constant" or not hit["name"] else hit["name"][0].upper() + hit["name"][1:]
    return "https://wiki.secondlife.com/wiki/" + page


def doc_signature(hit):
    if hit["kind"] == "constant":
        return "%s %s = %s" % (hit["type"], hit["name"], hit["value"])
    params = ", ".join("%s %s" % (arg[1], arg[0]) for arg in hit["args"])
    if hit["kind"] == "event":
        return "event %s(%s)" % (hit["name"], params)
    return "%s %s(%s)" % (hit["return"], hit["name"], params)


def doc_card(hit):
    lines = [doc_signature(hit)]
    if hit.get("tooltip"):
        lines.append("    " + hit["tooltip"])
    for arg in hit.get("args", []):
        if arg[2]:
            lines.append("    %s: %s" % (arg[0], arg[2]))
    if hit["kind"] == "function":
        notes = ["forced delay %g s" % hit["sleep"], "energy %g" % hit["energy"]]
        notes += [flag for flag in ("deprecated", "pure", "god-mode", "experience") if hit.get(flag)]
        if hit.get("requires-permission"):
            notes.append("needs %s" % ", ".join(hit["requires-permission"]))
        lines.append("    " + ", ".join(notes))
    elif hit["kind"] == "constant" and hit.get("deprecated") and "use" not in hit.get("tooltip", "").lower():
        lines.append("    deprecated" + (", use %s" % hit["use"] if hit.get("use") else ""))
    lines.append("    " + wiki_url(hit))
    return "\n".join(lines)


def show_doc(queries, as_json, log):
    """--doc: exit 0 when every name was found, 1 when one matched nothing, 2 without lsl_doc.json."""
    path = doc_file()
    if not path:
        log("lsl_doc.json not found (run update_builtins.py, or install the package)")
        return 2
    with open(path, "r", encoding="utf-8") as handle:
        doc = json.load(handle)
    results = [{"query": query, "matches": [dict(hit, signature=doc_signature(hit), url=wiki_url(hit))
                                            for hit in doc_lookup(doc, query)]} for query in queries]
    missing = sum(1 for item in results if not item["matches"])
    if as_json:
        print(json.dumps({"source": doc.get("source", ""), "results": results}, indent=2, ensure_ascii=False))
        return 1 if missing else 0
    for item in results:
        hits = item["matches"]
        if not hits:
            print("%s: no function, event or constant with that name or prefix" % item["query"])
        elif len(hits) == 1 or hits[0]["name"] == item["query"]:
            print(_UNPRINTABLE.sub("?", doc_card(hits[0])))
        else:
            print("%s: %d names" % (item["query"], len(hits)))
            for hit in hits[:60]:
                print("  " + _UNPRINTABLE.sub("?", hit["signature"]))
            if len(hits) > 60:
                print("  ... %d more, narrow the prefix" % (len(hits) - 60))
    return 1 if missing else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="lslcheck",
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("paths", nargs="*", help="LSL files or directories")
    ap.add_argument("--doc", nargs="+", metavar="NAME",
                    help="print the reference of LSL functions, events or constants (exact name or prefix) and exit")
    ap.add_argument("--lslint", help="path to the lslint binary")
    ap.add_argument("-b", "--builtins", help="alternate builtins.txt")
    ap.add_argument("--lso", action="store_true", help="use LSO rules instead of Mono")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    ap.add_argument("--json", action="store_true", help="emit a JSON report instead of text")
    ap.add_argument("-q", "--quiet", action="store_true", help="only print the summary line")
    ap.add_argument("--no-side-effects", dest="side_effects", action="store_false",
                    help="disable the -s checks (side effects in && / ||, writes across siblings), on by default")
    ap.add_argument("--no-download", action="store_true",
                    help="never download the binary from GitHub releases")
    for short, long_, help_ in PASSTHROUGH:
        ap.add_argument(short, long_, dest=dest_name(long_), action="store_true", help=help_)
    args = ap.parse_args(argv)

    def log(text):
        sys.stderr.write("lslcheck: %s\n" % text)

    # A path with characters outside the console code page must not crash the report.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")

    if args.doc:
        return show_doc(args.doc, args.json, log)
    if not args.paths:
        ap.error("give LSL files or directories to check, or --doc NAME")

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

    files, missing = collect(args.paths)
    for path in missing:
        log("no such file or directory: %s" % path)
    if not files:
        log("no .lsl files found")
        return 2

    results = []
    failures = [{"path": path, "error": "no such file or directory"} for path in missing]
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
