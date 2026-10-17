# lslint, AI-assisted edition

One project, three names: the repository is `DARK_LSL_AI_LLM`, the checker it
builds is `lslint`, and the command most people will type is `lslcheck`.

`lslint` is a *linter* for Second Life LSL scripts (Linden Scripting
Language): it reads a script without running it and lists every mistake with
its line, column and a code. It runs offline, in a fraction of a second, on
Windows, macOS and Linux.

This repository is a maintained fork of [Makopo/lslint](https://github.com/Makopo/lslint)
(itself a fork of pclewis/lslint). It stays compatible with upstream and adds
what is needed to make `lslint` the reference checker for **AI coding
assistants** and for the people, beginners or experts, who build Second Life
content with them.

LLM-oriented development by **Wens Darkheart / Dark Creations**. Code is public
domain like upstream, see the License section.

## Why this fork

LSL looks like C or JavaScript, and that is exactly the problem. An AI
assistant trained mostly on mainstream languages will write `if (x != 0 && f(x))`
and expect `f()` to be skipped, use a ternary, build an array, or rely on a
short-circuit guard against a division by zero. All of this compiles nowhere,
or worse, compiles and misbehaves in-world. A beginner cannot tell the
difference and will spend hours on it.

The idea is simple:

- **The linter says what is wrong**, exactly, with a code and a position, in a
  format a program can read.
- **The docs say why**, in a form an assistant can load into its context:
  verified facts about the language and the simulator limits, not folklore.
- **The skill says how to work**: write, lint, fix, repeat, and only then hand
  the script to the human.

A novice who opens an AI assistant and says "make my door open when a group
member touches it" should get a script that compiles and behaves the first
time. An experienced scripter gets the same tool in CI, with a JSON report and
exit codes. Both get builtins that match the live grid.

## Words used here

- **Diagnostic**: one error or warning. An **error** (`E1xxxx`) means the
  script will not compile in Second Life. A **warning** (`E2xxxx`) means it
  compiles but very likely does not do what you meant. Codes are printed with
  `-#`, which `lslcheck` always passes.
- **Builtins**: the functions, events and constants Second Life provides
  (`llSay`, `touch_start`, `TRUE`). They live in `builtins.txt`.
- **Mono / LSO**: the current and the legacy script engines of Second Life.
  Mono gives a script 64 KiB, LSO 16 KiB. `-m` (default) checks Mono rules,
  `-m-` LSO rules.
- **Skill**: a ready-made instruction set for an AI assistant (Claude Code
  reads `skills/*/SKILL.md`; any assistant can read it as a checklist).
- **In-world**: inside Second Life, on the live servers (the "grid").

## What this fork adds

- **Current builtins.** `builtins.txt` is generated from Linden Lab's official
  [lsl-definitions](https://github.com/secondlife/lsl-definitions) repository.
  `python update_builtins.py` refreshes it, `builtins_version.txt` records the
  exact source commit. The previous source (kwdb) is retired.
- **New check `-s`** (warning 20024, printed `[E20024]`): LSL evaluates both
  operands of `&&` and `||` unconditionally, right operand first. The check
  reports an operand that acts or can fail: a call to one of your own
  functions, a call to a builtin that acts (`llSay`, `llListen`,
  `llGetNotecardLine`...), an assignment, `++`/`--`, a division or a modulo
  by a non-literal. Pure reads and computations (`llGetOwner`, `llList2*`,
  `llAbs`...) are not reported.
- **Three bug fixes** in the analyzer: an uninitialized switch-depth counter
  made error 10033 (break outside switch) appear or vanish depending on the
  environment, a dangling symbol pointer in `-F` mode produced random "Not all
  code paths return a value" errors at line 1, and `isprint()` was called
  with parser token codes (undefined behaviour). On Windows, aborts and
  assertions now go to stderr instead of a modal dialog.
- **`lslcheck`**, a front end for automation (CI, editors) and assistants:
  GCC-style `file:line:col: error: [E10033] message` lines, directory scan,
  `--json`, `--strict`, exit codes, `-s` on by default. Installable with `uvx`
  or `pipx`; downloads and caches the release binary for the platform when
  none is installed, after checking its SHA-256 against the release's
  `SHA256SUMS.txt`.
- **`build_win64.cmd`**: builds on Windows with the free Visual Studio Build
  Tools and winflexbison, no IDE.
- **GitHub Actions**: build and test on Linux, macOS and Windows for every
  push; daily builtins refresh that opens a pull request when Linden Lab
  changed something; release binaries for the four platforms on a tag. The
  upstream CircleCI configuration is removed.
- **Knowledge for assistants**: `skills/lsl-dev/` is a ready-to-install
  skill for Claude Code and a readable checklist for any other assistant. Its
  `references/` folder holds the verified LSL facts (`lsl-for-ai.md`), the
  patterns that survive the simulator (`patterns.md`), the testing ladder
  from linter to in-world plan (`testing.md`) and the diagnostic code table
  (`error-codes.md`). `templates/` holds complete scripts, lint-clean in CI,
  to start from. `AGENTS.md` explains the repository to an agent working on
  it.

## Quick start

No compiler needed. [uv](https://docs.astral.sh/uv/) is a Python tool runner
(one-line install on every platform, see its site); `pipx` works the same way.

```sh
uvx --from git+https://github.com/MrWENS69/DARK_LSL_AI_LLM lslcheck script.lsl
```

`lslcheck` finds `lslint` next to it, on `PATH`, or downloads the binary
published for your platform (Windows x64, Linux x64, macOS Intel and Apple
Silicon) from the latest release, verifies its SHA-256 and caches it. No
Visual C++ runtime, no Homebrew, nothing to install by hand.

From a clone:

```sh
lslint -m script.lsl                  # Mono rules (default), plain output
lslint -m -# -s script.lsl            # with codes and the && / || check
python lslcheck.py src/               # every .lsl under src/, GCC-style lines
python lslcheck.py --json src/ > report.json
python lslcheck.py --strict script.lsl   # warnings fail too (CI)
```

AI assistants:

1. Run `lslcheck` as above, or build `lslint` and keep it next to
   `lslcheck.py` (or set `LSLINT`).
2. Claude Code: copy `skills/lsl-dev/` into `.claude/skills/` of the project
   (or `~/.claude/skills/` for every project). Other assistants: paste
   `skills/lsl-dev/SKILL.md` and `skills/lsl-dev/references/lsl-for-ai.md`
   into the context.
3. Every script goes through `lslcheck --strict script.lsl` before it is
   shown to a human. Zero errors, every warning read.

## lslcheck reference

```
lslcheck [options] PATH...        files, or directories scanned for *.lsl
  --strict          warnings fail too
  --json            JSON report on stdout instead of text
  -q, --quiet       only the summary line
  --lso             LSO rules instead of Mono
  -b FILE           alternate builtins.txt
  --no-side-effects do not pass -s to lslint
  --lslint PATH     the lslint binary (also: LSLINT environment variable)
  --no-download     never fetch the binary (also: LSLCHECK_NO_DOWNLOAD=1)
  -w -z -i -u -G -F forwarded to lslint (switch, lazy lists, ignore
                    preprocessor, unused event parameters, god mode,
                    later user function definitions replace earlier ones)
```

Exit codes: 0 clean, 1 at least one error (or a warning with `--strict`),
2 tool failure (binary missing, a path that does not exist, lslint crashed
or timed out, no `.lsl` file found).

JSON report: `{"lslint": path, "flags": [...], "files": [{"path", "errors",
"warnings", "messages": [{"level": "ERROR"|"WARN"|"INFO", "line", "col",
"end_line", "end_col", "code", "message"}]}], "failures": [{"path",
"error"}], "total": {"files", "errors", "warnings"}, "ok": bool}`. Positions
and `code` are `null` when lslint printed none. `ok` is true exactly when the
exit code is 0.

## Building

POSIX (Linux, macOS): `flex`, `bison` and a C++ compiler, then

```sh
make DEBUG= BUILD_VERSION_NUMBER=1.2.0
sh test.sh
```

Windows: install the free
[Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
with the "Desktop development with C++" workload, unpack
[winflexbison](https://github.com/lexxmark/winflexbison/releases) into
`C:\flexandbison` (or set `WINFLEXBISON`), then

```bat
rem release build, lslint.exe in the repository root
build_win64.cmd 1.2.0
rem debuggable build (debug CRT, symbols)
build_win64.cmd 1.2.0 debug
```

and run the tests from Git Bash with `sh test.sh`.

## Tests

`sh test.sh` runs every script under `scripts/` (the corpus). A corpus
script declares the diagnostics it expects with markers in comments,
`$[E20024]` for instance, and `-A` fails the run on any missing or unexpected
diagnostic. Each option has its own folder (`scripts/switch/`,
`scripts/side_effects/`, ...) and its own line in `test.sh`.
`python -m unittest test_lslcheck` covers the front end.

## Updating the builtins

```sh
python update_builtins.py            # from the main branch of lsl-definitions
python update_builtins.py --ref <tag-or-sha>
```

The script rewrites `builtins.txt`, `builtins_txt.cc` and
`builtins_version.txt`, and prints the added and removed names plus a count
of changed signatures. Rebuild and run the tests afterwards. The daily GitHub
Actions job does the same and opens a pull request.

## Options of lslint

```
-m          Use Mono rules (default on, -m- for LSO)
-b <file>   Load builtin functions from file
-t          Show tree structure
-l          Show line/column information as range
-p          Add the file path to the result
-v          Be verbose
-S          Don't sort log messages
-#          Show diagnostic codes
-A          Check the $[E...] assertion markers (tests)
-a          Don't report marked warnings/errors (default on)
-i          Ignore preprocessor directives
-u          Warn about unused event parameters
-s          Warn about calls, assignments, ++/-- and divisions in && / || operands
-w          Enable switch statements
-z          Enable lazy list syntax
-G          Enable god mode
-F          Allow a later definition of a user function to replace an earlier one
-V          Long version info
--version   Short version info
--help      This list
```

Flags accept a trailing `-` to disable them (`-m-`).

## Sources and related projects

- [Makopo/lslint](https://github.com/Makopo/lslint): the upstream this fork
  tracks. Fixes that make sense for everybody are offered back as pull
  requests.
- [mikelittman/lslint](https://github.com/mikelittman/lslint): an active fork
  that moved the builtins to lsl-definitions (as a pinned submodule) and the
  CI to GitHub Actions first, with daily builtins updates. Taken from it: the
  `fabs()` fix in the float-to-string conversion (`values.cc`), the macOS CI
  job, the daily cadence, and the decision to drop CircleCI.
- [secondlife/lsl-definitions](https://github.com/secondlife/lsl-definitions):
  Linden Lab's canonical YAML description of LSL. Its `generated/builtins.txt`
  is what `update_builtins.py` fetches, pinned to an exact commit in
  `builtins_version.txt`. Everything the linter knows about functions, events
  and constants comes from there.
- [Second Life wiki, LSL Portal](https://wiki.secondlife.com/wiki/LSL_Portal):
  the source of every fact in `skills/lsl-dev/references/lsl-for-ai.md`. Each
  entry names the page it was read from.
- [Sei-Lisa/kwdb](https://github.com/Sei-Lisa/kwdb): the keyword database
  that fed `builtins.txt` for years, and the syntax-highlighting files of
  several editors. Its author retired it in September 2026 in favour of
  lsl-definitions, which now generates those files too. Still used by
  LSL-PyOptimizer.
- [Sei-Lisa/LSL-PyOptimizer](https://github.com/Sei-Lisa/LSL-PyOptimizer):
  a complementary tool (optimizer and another parser) that uses the same
  `builtins.txt` format.

## Contributing

Fixes and checks that help everybody are welcome as pull requests to `master`.
Keep the upstream style (C++98 compatible, three-space indent), add a corpus
script with assertion markers for every new diagnostic, never edit
`builtins.txt` by hand. See `AGENTS.md` for the full checklist.

## Credits

Original `lslint` by masa, Doran Zemlja and the W-Hat crew. Later work by
Makopoppo (nmake support, `-p`), Xenhat (VS2015 support) and Sei-Lisa (Mono
mode, switch and lazy lists, god mode, many fixes). AI-assisted edition by
Wens Darkheart / Dark Creations.

Special thanks: Strife Onizuka, Howie Lament, Cory Linden, Huns Valen,
Doran Zemlja / Adam Wozniak. Shout outs: Daniel Linden, Bakuzelas Khan,
One Song, Otacon Falcone, Shokra Patel.

## License

All code is public domain unless otherwise noted. LSL scripts in `scripts/`
are from various sources and the property of their respective owners. The
`.l` and `.y` files are based on samples provided by Linden Lab. `builtins.txt`
is derived from Linden Lab's lsl-definitions (MIT license).

**Warning** (from upstream, still true): `lslint` faithfully reproduces the
quirks of the LSL compiler circa 2006, with constants as lexer tokens, events
in the grammar and lots of right recursion. It is a lint tool, not a base for a
compiler.
