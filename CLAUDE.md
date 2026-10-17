@AGENTS.md

Claude Code specifics: the `skills/lsl-dev/` folder is a skill for writing and
linting LSL in other projects. Working on lslint itself does not need it; use
`AGENTS.md` above, build with `build_win64.cmd dev` (Windows) or `make`
(POSIX), and run `sh test.sh` before every commit.
