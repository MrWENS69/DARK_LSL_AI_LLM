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
    python update_builtins.py --from-file path/to/builtins.txt --yaml-file path/to/lsl_definitions.yaml   # offline

The same run reads lsl_definitions.yaml (tooltips, parameters, delays) and
writes lsltest/data/lsl_doc.json, the reference behind `lslcheck --doc`.

Requires Python 3.8+, standard library only.
"""

import argparse
import json
import os
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
    headers = {"User-Agent": "lslint-update-builtins"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = "Bearer " + token          # 5000 requests an hour instead of 60
    req = urllib.request.Request(url, headers=headers)
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




# --- lsl_definitions.yaml: the reference text behind `lslcheck --doc` -----------------
#
# The YAML file is regular: two-space indents, one scalar per line, block or
# quoted scalars for the long tooltips. The reader below covers exactly that
# subset (the standard library has no YAML parser), and the result is checked
# against builtins.txt: every function and event of the linter must have its
# documentation, or the refresh fails.

DOC_JSON = ROOT / "lsltest" / "data" / "lsl_doc.json"
DOC_SECTIONS = ("constants", "events", "functions")


def _content_lines(text):
    """(indent, text) per line; blank and comment lines keep indent None and their raw text."""
    out = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            out.append((None, raw))
        else:
            out.append((len(raw) - len(raw.lstrip(" ")), stripped))
    return out


def _next_content(lines, i):
    while i < len(lines) and lines[i][0] is None:
        i += 1
    return i


def _scalar(lines, i, indent, rest):
    """The scalar that starts with `rest` on line i (whose key sits at `indent`); returns (value, next_i)."""
    if rest.startswith("["):
        # a flow sequence, [A, B] or spread over lines, possibly followed by a comment
        parts, j = [rest], i
        while "]" not in " ".join(parts):
            j += 1
            parts.append(lines[j][1] if lines[j][0] is not None else "")
        text = " ".join(p.strip() for p in parts)
        inner = text[text.index("[") + 1:text.rindex("]")]
        return [s.strip().strip("'\"") for s in inner.split(",") if s.strip()], j + 1
    if rest in ("|", "|-", ">", ">-", "|+", ">+"):
        block, j = [], i + 1
        while j < len(lines) and (lines[j][0] is None or lines[j][0] > indent):
            block.append(lines[j][1] if lines[j][0] is None else lines[j][1])
            j += 1
        raw = [l for l in block]
        if rest.startswith("|"):
            value = "\n".join(s.strip() for s in raw).strip("\n")
        else:
            value = " ".join(s.strip() for s in raw if s.strip())
        return value, j
    if rest.startswith("'") or rest.startswith('"'):
        quote = rest[0]
        parts, j = [rest], i
        while not _closed(parts, quote):
            j += 1
            parts.append(lines[j][1] if lines[j][0] is not None else "")
        text = " ".join(p.strip() for p in parts)
        body = text[1:-1]
        if quote == "'":
            body = body.replace("''", "'")
        else:
            body = body.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
        return body, j + 1
    parts, j = [rest], i + 1
    while j < len(lines) and lines[j][0] is not None and lines[j][0] > indent:
        parts.append(lines[j][1])
        j += 1
    return " ".join(parts), j


def _closed(parts, quote):
    text = " ".join(parts)
    if len(text) < 2 or not text.endswith(quote):
        return False
    if quote == "'":
        return not text.endswith("''") or text == "''"
    return not text.endswith('\\"')


def _parse_block(lines, i, indent):
    """The mapping or list whose entries sit at `indent`; returns (value, next_i)."""
    i = _next_content(lines, i)
    if i >= len(lines) or lines[i][0] < indent:
        return "", i
    if lines[i][1].startswith("- ") or lines[i][1] == "-":
        return _parse_list(lines, i, lines[i][0])
    return _parse_mapping(lines, i, lines[i][0])


def _parse_mapping(lines, i, indent):
    result = {}
    while True:
        i = _next_content(lines, i)
        if i >= len(lines) or lines[i][0] != indent or lines[i][1].startswith("- "):
            return result, i
        key, sep, rest = lines[i][1].partition(":")
        if not sep or (rest and not rest.startswith(" ")):
            raise ValueError("unexpected YAML line %d: %r" % (i + 1, lines[i][1]))
        rest = rest.strip()
        if rest == "":
            j = _next_content(lines, i + 1)
            if j < len(lines) and lines[j][0] is not None and lines[j][0] > indent and lines[j][1].startswith("["):
                result[key], i = _scalar(lines, j, indent, lines[j][1])      # a flow sequence on its own lines
            elif j < len(lines) and lines[j][0] is not None and (
                    lines[j][0] > indent or (lines[j][0] == indent and lines[j][1].startswith("- "))):
                result[key], i = _parse_block(lines, j, lines[j][0])
            else:
                result[key], i = "", i + 1
        elif rest == "[]":
            result[key], i = [], i + 1
        else:
            result[key], i = _scalar(lines, i, indent, rest)


def _parse_list(lines, i, indent):
    result = []
    while True:
        i = _next_content(lines, i)
        if i >= len(lines) or lines[i][0] != indent or not (lines[i][1].startswith("- ") or lines[i][1] == "-"):
            return result, i
        rest = lines[i][1][2:].strip()
        if rest and ":" in rest and (rest.endswith(":") or ": " in rest):
            # a mapping whose first key sits on the dash line, the others two columns in
            lines[i] = (indent + 2, rest)
            item, i = _parse_mapping(lines, i, indent + 2)
            result.append(item)
        elif rest:
            value, i = _scalar(lines, i, indent, rest)
            result.append(value)
        else:
            value, i = _parse_block(lines, i + 1, indent + 2)
            result.append(value)


def read_definitions(text):
    """The constants, events and functions sections of lsl_definitions.yaml as plain dicts."""
    lines = _content_lines(text)
    found = {}
    i = 0
    while i < len(lines):
        if lines[i][0] == 0 and lines[i][1].rstrip(":") in DOC_SECTIONS and lines[i][1].endswith(":"):
            name = lines[i][1][:-1]
            found[name], i = _parse_block(lines, i + 1, 2)
        else:
            i += 1
    missing = [s for s in DOC_SECTIONS if s not in found]
    if missing:
        raise ValueError("sections missing from lsl_definitions.yaml: %s" % ", ".join(missing))
    return found


def _flag(value):
    return bool(value) and value != "false"


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _arguments(entry):
    out = []
    for arg in entry.get("arguments") or []:
        if isinstance(arg, dict) and arg:
            name, spec = next(iter(arg.items()))
            spec = spec if isinstance(spec, dict) else {}
            out.append([name, spec.get("type", ""), spec.get("tooltip", "")])
    return out


def build_doc(defs, functions, events, constants, source):
    """The compact reference shipped as lsl_doc.json, checked against builtins.txt."""
    doc = {"source": source, "functions": {}, "events": {}, "constants": {}}
    for name, entry in defs["functions"].items():
        if not isinstance(entry, dict):
            continue
        item = {"return": entry.get("return", "void"), "args": _arguments(entry), "tooltip": entry.get("tooltip", ""),
                "sleep": _number(entry.get("sleep")), "energy": _number(entry.get("energy"), 10.0)}
        for flag in ("deprecated", "pure", "god-mode", "experience"):
            if _flag(entry.get(flag)):
                item[flag] = True
        if entry.get("requires-permission"):
            item["requires-permission"] = entry["requires-permission"]
        doc["functions"][name] = item
    for name, entry in defs["events"].items():
        if isinstance(entry, dict):
            doc["events"][name] = {"args": _arguments(entry), "tooltip": entry.get("tooltip", "")}
    for name, entry in defs["constants"].items():
        if not isinstance(entry, dict):
            continue
        item = {"type": entry.get("type", ""), "value": str(entry.get("value", "")), "tooltip": entry.get("tooltip", "")}
        if _flag(entry.get("deprecated")):
            item["deprecated"] = True
            if isinstance(entry["deprecated"], dict) and entry["deprecated"].get("use"):
                item["use"] = entry["deprecated"]["use"]
        doc["constants"][name] = item
    for label, names, section in (("functions", functions, "functions"), ("events", events, "events")):
        undocumented = sorted(set(names) - set(doc[section]))
        if undocumented:
            raise ValueError("%s of builtins.txt without documentation: %s" % (label, ", ".join(undocumented)))
    undocumented = sorted(set(constants) - set(doc["constants"]))
    if undocumented:
        print("constants of builtins.txt without a tooltip in the YAML: %s" % ", ".join(undocumented))
    return doc


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref", default="main", help="git ref of %s (default: main)" % REPO)
    ap.add_argument("--from-file", help="use a local builtins.txt instead of downloading")
    ap.add_argument("--yaml-file", help="use a local lsl_definitions.yaml instead of downloading")
    args = ap.parse_args()

    yaml_text = None
    if args.yaml_file:
        yaml_text = pathlib.Path(args.yaml_file).read_text(encoding="utf-8")
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
        if yaml_text is None:
            yaml_text = fetch("https://raw.githubusercontent.com/%s/%s/lsl_definitions.yaml" % (REPO, sha)).decode("utf-8")
        stamp = "%s commit %s (%s)" % (REPO, sha[:12], date)
        version_body = (
            "Source: https://github.com/%s\n"
            "Commit: %s\n"
            "Date: %s\n"
            "File: generated/builtins.txt\n" % (REPO, sha, date)
        )

    body = "\n".join(l for l in text.splitlines() if l.strip() and not l.startswith("//"))
    new_text = "// Generated from %s by update_builtins.py\n%s\n" % (stamp, body)
    functions, events, constants = parse(new_text)  # validate before writing anything
    doc = build_doc(read_definitions(yaml_text), functions, events, constants, stamp) if yaml_text else None

    old_text = BUILTINS_TXT.read_text(encoding="utf-8") if BUILTINS_TXT.exists() else ""
    report(old_text, new_text)

    BUILTINS_TXT.write_text(new_text, encoding="utf-8", newline="\n")
    BUILTINS_CC.write_text(render_cc(new_text), encoding="utf-8", newline="\n")
    VERSION_TXT.write_text(version_body, encoding="utf-8", newline="\n")
    bundled = ROOT / "lsltest" / "data" / "builtins.txt"      # the copy shipped inside the lsltest package
    if bundled.parent.is_dir():
        bundled.write_text(new_text, encoding="utf-8", newline="\n")
    if doc is not None:
        with open(DOC_JSON, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(doc, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
        print("wrote %s (%d functions, %d events, %d constants)" % (DOC_JSON.name, len(doc["functions"]),
                                                                    len(doc["events"]), len(doc["constants"])))
    else:
        print("no lsl_definitions.yaml given: %s not refreshed" % DOC_JSON.name)
    print("wrote %s, %s, %s" % (BUILTINS_TXT.name, BUILTINS_CC.name, VERSION_TXT.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
