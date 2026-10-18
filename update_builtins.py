#!/usr/bin/env python3
"""Refresh builtins.txt, builtins_txt.cc and lsltest/data/lsl_doc.json from secondlife/lsl-definitions.

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
writes lsltest/data/lsl_doc.json, the reference behind `lslcheck --doc`;
with --from-file and no --yaml-file that file is left as it was.

Exit status: 0 when every file was written; 3 when the builtins were refreshed
but lsltest/data/lsl_doc.json was left as it was because the reference could
not be built (a warning on stderr, and on the run under GitHub Actions, says
why); anything else is a failure, normally before anything was written.

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


MAX_DOWNLOAD = 5000000
EXIT_DOC_KEPT = 3     # builtins refreshed, lsl_doc.json left as it was


def _write(path, text):
    """LF line endings on every platform (Path.write_text has no newline= before Python 3.10)."""
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


class _TokenStaysHome(urllib.request.HTTPRedirectHandler):
    """A redirect to another host does not carry the GitHub token along."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


_OPENER = urllib.request.build_opener(_TokenStaysHome())


def _warn(message):
    """On stderr, and as an annotation on the run under GitHub Actions (the runner reads commands on stdout:
    one line, % encoded, so that no text from upstream can end the message or start another command)."""
    print("warning: " + message, file=sys.stderr)
    if os.environ.get("GITHUB_ACTIONS"):
        print("::warning::" + " ".join(message.split()).replace("%", "%25"))


def fetch(url):
    headers = {"User-Agent": "lslint-update-builtins"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = "Bearer " + token          # 5000 requests an hour instead of 60
    with _OPENER.open(urllib.request.Request(url, headers=headers), timeout=60) as resp:
        data = resp.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError("download over %d bytes: %s" % (MAX_DOWNLOAD, url))
    return data


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
# subset (the standard library has no YAML parser) and raises ValueError on
# anything else, so that the daily refresh fails loudly instead of writing a
# wrong reference. The result is then checked against builtins.txt.

DOC_JSON = ROOT / "lsltest" / "data" / "lsl_doc.json"
DOC_SECTIONS = ("constants", "events", "functions")
_QUOTED = {"'": re.compile(r"'((?:[^']|'')*)'(\s+#.*)?"), '"': re.compile(r'"((?:[^"\\]|\\.)*)"(\s+#.*)?')}
_FORBIDDEN = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")


def _content_lines(text):
    """(indent, text, is_content) per line; blank and comment lines are not content but keep their indent."""
    out = []
    for raw in text.splitlines():
        stripped = raw.strip()
        out.append((len(raw) - len(raw.lstrip(" ")), stripped, bool(stripped) and not stripped.startswith("#")))
    return out


def _next_content(lines, i):
    while i < len(lines) and not lines[i][2]:
        i += 1
    return i


def _gather(lines, i, rest, done):
    """Join line i's `rest` with the following lines until done(text) says the scalar is closed."""
    parts, j = [rest], i
    while not done(" ".join(parts)):
        j += 1
        if j >= len(lines):
            raise ValueError("unterminated scalar at line %d: %r" % (i + 1, rest))
        parts.append(lines[j][1])
    return " ".join(p.strip() for p in parts), j + 1


def _plain(text):
    return re.sub(r"(^|\s+)#.*$", "", text).strip()       # drops a trailing comment, or a value that is one


def _scalar(lines, i, indent, rest):
    """The scalar that starts with `rest` on line i (whose key sits at `indent`); returns (value, next_i)."""
    if rest.startswith("["):                            # flow sequence, inline or spread over lines
        text, j = _gather(lines, i, rest, lambda t: "]" in t)
        inner = text[text.index("[") + 1:text.rindex("]")]
        return [s.strip().strip("'\"") for s in inner.split(",") if s.strip()], j
    if rest[0] in _QUOTED:
        text, j = _gather(lines, i, rest, lambda t: _QUOTED[rest[0]].fullmatch(t) is not None)
        body = _QUOTED[rest[0]].fullmatch(text).group(1)
        if rest[0] == "'":
            return body.replace("''", "'"), j
        try:
            return json.loads('"' + body + '"'), j
        except ValueError:
            raise ValueError("unsupported escape in a double-quoted scalar at line %d" % (i + 1))
    if re.fullmatch(r"[|>]-?", rest):                   # block scalar: literal or folded, kept or clipped
        block, j = [], i + 1
        while j < len(lines) and (not lines[j][1] or lines[j][0] > indent):
            block.append(lines[j][1])
            j += 1
        if rest[0] == "|":
            return "\n".join(block).strip("\n"), j
        return " ".join(b for b in block if b), j
    if rest[0] in "|>&*!{%@`":
        raise ValueError("unsupported YAML syntax at line %d: %r" % (i + 1, rest))
    parts, j = [_plain(rest)], i + 1                      # plain scalar, folded over its continuation lines
    while j < len(lines) and lines[j][2] and lines[j][0] > indent:
        parts.append(_plain(lines[j][1]))
        j += 1
    return " ".join(parts), j


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
        key = key.strip().strip("'\"")                        # 'TRUE' and 'FALSE' are quoted keys
        if not sep or (rest and not rest.startswith(" ")) or " " in key:
            raise ValueError("unexpected YAML line %d: %r" % (i + 1, lines[i][1]))
        rest = rest.strip()
        if rest:
            result[key], i = _scalar(lines, i, indent, rest)
            continue
        j = _next_content(lines, i + 1)
        if j < len(lines) and lines[j][0] > indent and lines[j][1].startswith("["):
            result[key], i = _scalar(lines, j, indent, lines[j][1])     # a flow sequence on its own lines
        elif j < len(lines) and (lines[j][0] > indent or (lines[j][0] == indent and lines[j][1].startswith("- "))):
            result[key], i = _parse_block(lines, j, lines[j][0])
        else:
            result[key], i = "", i + 1


def _parse_list(lines, i, indent):
    result = []
    while True:
        i = _next_content(lines, i)
        if i >= len(lines) or lines[i][0] != indent or not (lines[i][1].startswith("- ") or lines[i][1] == "-"):
            return result, i
        text = lines[i][1]
        rest = text[1:].lstrip()
        item_indent = indent + len(text) - len(rest)           # where the item's first key sits
        if _plain(rest).endswith(":") or ": " in _plain(rest):
            lines[i] = (item_indent, rest, True)                 # the first key is on the dash line
            item, i = _parse_mapping(lines, i, item_indent)
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
        if lines[i][0] == 0 and lines[i][2] and lines[i][1].endswith(":") and lines[i][1][:-1] in DOC_SECTIONS:
            name = lines[i][1][:-1]
            found[name], i = _parse_block(lines, i + 1, 2)
        else:
            i += 1
    missing = [s for s in DOC_SECTIONS if s not in found]
    if missing:
        raise ValueError("sections missing from lsl_definitions.yaml: %s" % ", ".join(missing))
    return found


def _flag(value):
    """true / false / absent, or a mapping such as deprecated: {use: X} which counts as true."""
    if isinstance(value, dict):
        return True
    if value in ("true", "false", ""):
        return value == "true"
    raise ValueError("unexpected flag value %r" % (value,))


def _text(where, value):
    if not isinstance(value, str):
        raise ValueError("%s: expected text, got %r" % (where, value))
    if _FORBIDDEN.search(value):
        raise ValueError("%s: control or direction character in the text" % where)
    return value


def _types(signature):
    """Parameter types of a builtins.txt signature, quaternion spelled rotation."""
    return [p.split()[0].replace("quaternion", "rotation") for p in signature.split(",") if p.strip()]


def _arguments(where, entry):
    out = []
    for arg in entry.get("arguments") or []:
        if not isinstance(arg, dict) or len(arg) != 1:
            raise ValueError("%s: unexpected argument entry %r" % (where, arg))
        name, spec = next(iter(arg.items()))
        spec = spec if isinstance(spec, dict) else {}
        out.append([name, _text(where, spec.get("type", "")), _text(where, spec.get("tooltip", ""))])
    return out


def build_doc(defs, functions, events, constants):
    """The reference shipped as lsl_doc.json, checked entry by entry against builtins.txt."""
    doc = {"source": REPO, "functions": {}, "events": {}, "constants": {}}
    for name, entry in defs["functions"].items():
        if not isinstance(entry, dict):
            raise ValueError("function %s: not a mapping" % name)
        item = {"return": _text(name, entry.get("return", "")).replace("quaternion", "rotation"),
                "args": _arguments(name, entry), "tooltip": _text(name, entry.get("tooltip", "")),
                "sleep": float(entry.get("sleep", "x")), "energy": float(entry.get("energy", "x"))}
        if "mono-sleep" in entry:
            item["mono-sleep"] = float(entry["mono-sleep"])  # the delay under Mono when it differs from LSO
        for flag in ("deprecated", "pure", "god-mode", "experience"):
            if _flag(entry.get(flag, "")):
                item[flag] = True
        if entry.get("requires-permission"):
            item["requires-permission"] = list(entry["requires-permission"])
        if name in functions:
            ret, params = functions[name]
            if item["return"] != ret.replace("quaternion", "rotation") or [a[1] for a in item["args"]] != _types(params):
                raise ValueError("function %s: the YAML signature differs from builtins.txt" % name)
        doc["functions"][name] = item
    for name, entry in defs["events"].items():
        if not isinstance(entry, dict):
            raise ValueError("event %s: not a mapping" % name)
        doc["events"][name] = {"args": _arguments(name, entry), "tooltip": _text(name, entry.get("tooltip", ""))}
        if name in events and [a[1] for a in doc["events"][name]["args"]] != _types(events[name]):
            raise ValueError("event %s: the YAML signature differs from builtins.txt" % name)
    for name, entry in defs["constants"].items():
        if not isinstance(entry, dict):
            raise ValueError("constant %s: not a mapping" % name)
        item = {"type": _text(name, entry.get("type", "")), "value": _text(name, str(entry.get("value", ""))),
                "tooltip": _text(name, entry.get("tooltip", ""))}
        if _flag(entry.get("deprecated", "")):
            item["deprecated"] = True
            if isinstance(entry["deprecated"], dict) and entry["deprecated"].get("use"):
                item["use"] = _text(name, entry["deprecated"]["use"])
        doc["constants"][name] = item
    for label, names, section in (("functions", functions, "functions"), ("events", events, "events"),
                                  ("constants", constants, "constants")):
        undocumented = sorted(set(names) - set(doc[section]))
        if undocumented:
            raise ValueError("%s of builtins.txt without an entry in lsl_definitions.yaml: %s"
                             % (label, ", ".join(undocumented)))
    return doc


def write_doc(doc, path):
    """One entry per line, so that the daily pull request shows what changed."""
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("{\n")
        for section in DOC_SECTIONS:
            handle.write('"%s": {\n' % section)
            names = sorted(doc[section])
            for k, name in enumerate(names):
                entry = json.dumps(doc[section][name], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                handle.write("%s: %s%s\n" % (json.dumps(name), entry, "," if k + 1 < len(names) else ""))
            handle.write("},\n")
        handle.write('"source": %s\n}\n' % json.dumps(doc["source"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref", default="main", help="git ref of %s (default: main)" % REPO)
    ap.add_argument("--from-file", help="use a local builtins.txt instead of downloading")
    ap.add_argument("--yaml-file", help="use a local lsl_definitions.yaml instead of downloading")
    args = ap.parse_args(argv)

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
    doc, doc_error = None, None
    if yaml_text is not None:
        try:
            doc = build_doc(read_definitions(yaml_text), functions, events, constants)
        except Exception as exc:        # the reference is secondary: the builtins are refreshed all the same (#27)
            doc_error = "%s: %s" % (type(exc).__name__, exc)

    old_text = BUILTINS_TXT.read_text(encoding="utf-8") if BUILTINS_TXT.exists() else ""
    report(old_text, new_text)

    _write(BUILTINS_TXT, new_text)
    _write(BUILTINS_CC, render_cc(new_text))
    _write(VERSION_TXT, version_body)
    bundled = ROOT / "lsltest" / "data" / "builtins.txt"      # the copy shipped inside the lsltest package
    written = [BUILTINS_TXT.name, BUILTINS_CC.name, VERSION_TXT.name]
    if bundled.parent.is_dir():
        _write(bundled, new_text)
        written.append("lsltest/data/builtins.txt")
    if doc is not None:
        write_doc(doc, DOC_JSON)
        written.append("lsltest/data/lsl_doc.json (%d functions, %d events, %d constants)"
                       % (len(doc["functions"]), len(doc["events"]), len(doc["constants"])))
    elif doc_error:
        _warn("lsltest/data/lsl_doc.json left as it was, the --doc reference could not be built: " + doc_error)
    else:
        print("no lsl_definitions.yaml given: lsltest/data/lsl_doc.json left as it was")
    print("wrote " + ", ".join(written))
    return EXIT_DOC_KEPT if doc_error else 0


if __name__ == "__main__":
    sys.exit(main())
