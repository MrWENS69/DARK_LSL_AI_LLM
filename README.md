# lslint, AI-assisted edition

`lslint` checks the syntactic and semantic validity of Second Life LSL scripts
(Linden Scripting Language). It runs offline, in a fraction of a second, and
reports every problem with its line, column and an error code.

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

## What this fork adds

- **Current builtins.** `builtins.txt` is generated from Linden Lab's official
  [lsl-definitions](https://github.com/secondlife/lsl-definitions) repository.
  `python update_builtins.py` refreshes it, `builtins_version.txt` records the
  source commit. The previous source (kwdb) is no longer maintained.
- **New check `-s`** (warning 20024): side effects in `&&` / `||` operands.
  LSL evaluates both operands unconditionally, right operand first. A function
  call, an assignment, an increment or a division inside a logical condition
  is reported, so nobody relies on a short-circuit that does not exist.
- **Two bug fixes** in the analyzer: an uninitialized switch-depth counter
  made error 10033 (break outside switch) appear or vanish depending on the
  environment, and a dangling symbol pointer in `-F` mode produced random
  "Not all code paths return a value" errors at line 1.
- **`lslcheck.py`**, a front end for scripts and assistants: GCC-style
  `file:line:col: error: [E10033] message` output, directory scan, `--json`,
  `--strict`, meaningful exit codes, `-s` on by default.
- **`build_win64.cmd`**: builds on Windows with the free Visual Studio Build
  Tools and winflexbison, no IDE.
- **GitHub Actions**: build and test on Linux and Windows for every push,
  weekly builtins refresh, release binaries on tags. The upstream CircleCI
  configuration is removed.
- **Documentation for assistants**: `skills/lsl-dev/` is a ready-to-install
  skill for Claude Code and a readable checklist for any other assistant. Its
  `references/` folder holds the verified LSL facts (`lsl-for-ai.md`) and the
  error code reference (`error-codes.md`). `AGENTS.md` explains the repository
  to an agent working on it.

## Quick start

Humans:

```sh
lslint -m script.lsl                  # Mono rules (default), plain output
lslint -m -# -s script.lsl            # with error codes and the side-effect check
python lslcheck.py src/               # every .lsl under src/, GCC-style lines
python lslcheck.py --json src/ > report.json
python lslcheck.py --strict script.lsl   # warnings fail too (CI)
```

AI assistants:

1. Build or download `lslint`, keep it next to `lslcheck.py` (or set `LSLINT`).
2. Claude Code: copy `skills/lsl-dev/` into `.claude/skills/` of the project
   (or `~/.claude/skills/` for every project). Other assistants: paste
   `skills/lsl-dev/SKILL.md` and `skills/lsl-dev/references/lsl-for-ai.md`
   into the context.
3. Every script goes through `python lslcheck.py --strict script.lsl` before
   it is shown to a human. Zero errors, every warning read.

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
build_win64.cmd 1.2.0          :: lslint.exe
build_win64.cmd 1.2.0 debug    :: debuggable build
sh test.sh                     :: from Git Bash
```

## Tests

`sh test.sh` runs every script under `scripts/`. A test script declares the
diagnostics it expects with markers in comments, `$[E20024]` for instance, and
`-A` fails the run on any missing or unexpected diagnostic. Each option has its
own folder (`scripts/switch/`, `scripts/side_effects/`, ...) and its own line
in `test.sh`.

## Updating the builtins

```sh
python update_builtins.py            # from the main branch of lsl-definitions
python update_builtins.py --ref <tag-or-sha>
```

The script rewrites `builtins.txt`, `builtins_txt.cc` and
`builtins_version.txt`, and prints what was added, removed or changed. Rebuild
and run the tests afterwards. The weekly GitHub Actions job does the same.

## Options

```
-m          Use Mono rules (default on, -m- for LSO)
-b <file>   Load builtin functions from file
-t          Show tree structure
-l          Show line/column information as range
-p          Add the file path to the result
-v          Be verbose
-S          Don't sort log messages
-#          Show error codes
-A          Check error assertions (tests)
-a          Don't report marked warnings/errors (default on)
-i          Ignore preprocessor directives
-u          Warn about unused event parameters
-s          Warn about side effects in && / || operands
-w          Enable switch statements
-z          Enable lazy list syntax
-G          Enable god mode
-F          Allow a user function to override a builtin
-V          Long version info
```

Flags accept a trailing `-` to disable them (`-m-`).

## Sources and related projects

- [Makopo/lslint](https://github.com/Makopo/lslint): the upstream this fork
  tracks. Fixes that make sense for everybody are offered back as pull
  requests.
- [mikelittman/lslint](https://github.com/mikelittman/lslint): an active fork
  that moved the builtins to lsl-definitions and the CI to GitHub Actions
  first. Taken from it: the `fabs()` fix in the float-to-string conversion
  (`values.cc`), the macOS CI job, and the decision to drop CircleCI.
- [secondlife/lsl-definitions](https://github.com/secondlife/lsl-definitions):
  Linden Lab's canonical YAML description of LSL. Its `generated/builtins.txt`
  is what `update_builtins.py` fetches. Everything the linter knows about
  functions, events and constants comes from there.
- [Second Life wiki, LSL Portal](https://wiki.secondlife.com/wiki/LSL_Portal):
  the source of every fact in `skills/lsl-dev/references/lsl-for-ai.md`. Each
  entry links to the page it was read from.
- [Sei-Lisa/kwdb](https://github.com/Sei-Lisa/kwdb): the previous keyword
  database, now retired by its author in favour of lsl-definitions.
- [Sei-Lisa/LSL-PyOptimizer](https://github.com/Sei-Lisa/LSL-PyOptimizer):
  a complementary tool (optimizer and another parser) that uses the same
  `builtins.txt` format.

## Contributing

Fixes and checks that help everybody are welcome as pull requests to `master`.
Keep the upstream style (C++98 compatible, three-space indent), add a test
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
