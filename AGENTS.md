# Working on this repository (guide for agents and contributors)

This is `lslint`, a syntax and semantic checker for Second Life LSL, written in
C++ with flex and bison. This fork keeps upstream compatibility and adds
tooling for AI coding assistants. The repository is public: never commit
personal data, credentials, or anything that belongs to a private project.

## Layout

| Path | Role |
| --- | --- |
| `lslmini.l`, `lslmini.y` | Lexer and grammar. Tokens such as `BOOLEAN_AND`, `ADD_ASSIGN` come from the generated `lslmini.tab.h`. |
| `lslmini.hh`, `ast.hh` | AST classes (`LLASTNode`, `LLScriptExpression`, statements, identifiers). |
| `lslmini.cc` | `main()`, option parsing, symbol definition and resolution, tree walks. |
| `final_walk.cc` | Last pass: `final_pre_checks()` / `final_post_checks()` per node, where most diagnostics live. |
| `types.cc`, `values.cc`, `operators.cc` | Type rules, constant folding, operator result types. |
| `logger.hh`, `logger.cc` | Error and warning codes (`E_*` 1xxxx, `W_*` 2xxxx), message table, assertion checking. |
| `builtins.txt`, `builtins_txt.cc`, `builtins_version.txt` | Functions, events and constants. Generated, never hand-edited. |
| `update_builtins.py` | Refreshes the three files above from secondlife/lsl-definitions. |
| `lslcheck.py` | Front end: GCC-style or JSON output, directory scan, exit codes. |
| `scripts/` | Test corpus. One folder per option that needs a flag. |
| `test.sh` | Runs the corpus with `-A` assertion checking. |
| `skills/lsl-dev/` | Installable skill for Claude Code, readable by any assistant. `references/` holds the LSL facts and the error code table. |
| `gen_error_codes.py` | Regenerates `skills/lsl-dev/references/error-codes.md` from the logger tables. |
| `.github/workflows/` | CI, weekly builtins refresh, releases. |

## Build and test

```sh
# POSIX
make DEBUG= BUILD_VERSION_NUMBER=dev
sh test.sh

# Windows (Git Bash for the tests)
build_win64.cmd dev
sh test.sh
```

`sh test.sh` must print `passed` for every script and exit 0 before any
commit. Run it twice when touching symbol handling or the walks: two of the
bugs fixed in this fork only showed up under certain environment sizes
because of uninitialized memory.

Debug builds (`build_win64.cmd dev debug`, `make` with the default `DEBUG`)
use the debug CRT on Windows, which asserts on undefined behaviour such as
`isprint()` with a token code. Those assertions are real bugs: fix them, do
not silence them. `main()` routes assertions and aborts to stderr on MSVC so
that no modal dialog can block a script or a CI runner.

## Adding a diagnostic

1. Append the code at the end of the enum in `logger.hh`, right before
   `E_LAST` or `W_LAST`. Never renumber or reuse a code.
2. Append the message at the end of the matching table in `logger.cc`. The
   message is a printf format; keep it one sentence, say what to do instead.
3. Implement the check in `final_walk.cc` (or `lslmini.cc` for symbol-level
   checks). Prefer a `final_pre_checks()` override on the node that owns the
   construct.
4. If the check can be noisy, put it behind a flag: `extern bool` in
   `lslmini.hh`, definition and `case` in `lslmini.cc`, usage line in
   `usage()`, and list it in `lslcheck.py` if assistants should have it.
5. Add `scripts/<feature>/<name>.lsl` with `$[Exxxxx]` markers on the lines
   where the diagnostic must fire, and a branch in `test.sh` that runs the
   folder with the right flag. Every expected diagnostic needs a marker, and
   `-A` fails on unexpected ones.
6. Regenerate the error code table with `python gen_error_codes.py`.
7. Mention the new option in `README.md`.

## Style

- C++98 compatible (upstream builds with `-std=c++98 -pedantic-errors` on
  Linux and macOS): declare variables at the top of the block, no `auto`, no
  range-for, no `nullptr`.
- Three-space indentation in `.cc` and `.hh`, Allman-ish braces as in the
  surrounding code.
- Initialize every member in every constructor. Grep for the pattern that bit
  us: a second constructor added later without the initializer list.
- Python helpers: standard library only, Python 3.8+, no third-party packages.
- Line endings are LF in the repository (git normalizes). Windows checkouts
  may show CRLF locally; do not commit conversions.

## Builtins

Never edit `builtins.txt`, `builtins_txt.cc` or `builtins_version.txt` by
hand. Run `python update_builtins.py`, rebuild, run the tests, commit the
three files together with a message that names the lsl-definitions commit.

## Commits and releases

- One topic per commit, imperative subject, body explains why.
- Pull requests target `master`. Development happens on feature branches;
  `DARK_PROJECTS` is the integration branch of the maintainer.
- A tag `vX.Y.Z` triggers the release workflow, which builds Linux and Windows
  binaries and attaches them to a GitHub release.

## Keeping up with the other forks

Two remotes are worth tracking: `upstream` (Makopo/lslint, the parent) and
`mikelittman` (https://github.com/mikelittman/lslint, the most active fork:
daily builtins from lsl-definitions, GitHub Actions). Before a release:

```sh
git fetch upstream mikelittman
git log --oneline DARK_PROJECTS..upstream/master
git diff --stat mikelittman/master DARK_PROJECTS -- '*.cc' '*.hh' '*.y' '*.l'
```

Cherry-pick code fixes, credit them in the README "Sources" section, and
leave their builtins alone: ours come from the same lsl-definitions file
through `update_builtins.py`.

## Public repository rules

- No real names, UUIDs, region names, URLs of private services, API keys, or
  scripts from private projects, not even in tests or examples.
- Test scripts must be self-contained and generic.
- Issues and commit messages describe the change, not the person.
