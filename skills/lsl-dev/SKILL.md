---
name: lsl-dev
description: Write, fix, review and lint Second Life LSL scripts (Linden Scripting Language, also OpenSimulator). Use whenever a task involves an LSL script, a Second Life object, HUD, vendor, door, security or any in-world scripting question, including "why does my script not compile" and "make this script do X". Runs lslint through lslcheck before any script is shown to a human.
---

# LSL development with lslint

LSL is not C, not JavaScript, not Lua. Code that looks right in those languages
compiles and misbehaves in Second Life, or does not compile at all. This skill
gives you a checker and the facts you need. Follow the loop, every time.

Words used here: a *diagnostic* is one error or warning from the linter. An
*error* means the script will not compile in Second Life. A *warning* means it
compiles but very likely does not do what the author meant. The linter prints
both with an `E` prefix and a five-digit code: `E1xxxx` is an error, `E2xxxx`
a warning.

## The loop

1. **Read `references/lsl-for-ai.md` once per session** before writing LSL.
   It is short and every line of it was verified on the official wiki.
2. **Write the script** following the rules below.
3. **Lint it**: `lslcheck --strict path/to/script.lsl` if `lslcheck` is
   installed (`uvx --from git+https://github.com/MrWENS69/DARK_LSL_AI_LLM
   lslcheck`), otherwise `python <lslint-dir>/lslcheck.py --strict
   path/to/script.lsl` from a clone of the repository. `lslcheck` fetches the
   `lslint` binary for the platform by itself when none is installed. The
   output is one line per diagnostic, `file:line:col: error: [E10033]
   message`, then a summary line.
4. **Fix every error. Read every warning** and either fix it or explain in one
   sentence why it is intended. `--strict` makes warnings fail on purpose.
5. **Repeat until the summary says `0 error(s), 0 warning(s)`**, then give the
   script to the human together with that last line. Never hand over a script
   you have not linted.

If `lslcheck` exits with code 2 and says the binary is missing, it could not
download it: build it (`build_win64.cmd` on Windows, `make` elsewhere, see the
repository README) or ask the human for the binary. Do not skip the lint.

## Rules that are not negotiable

- `&&` and `||` evaluate **both** operands, **right one first**. Inside a
  compound condition put nothing that acts or can fail: no call to one of
  your own functions, no call to a builtin that acts (`llSay`, `llListen`,
  `llGetNotecardLine`...), no assignment, no `++`/`--`, no division or
  modulo. Pure reads and computations (`llGetOwner`, `llList2String`,
  `llAbs`) are fine. Use nested `if` for everything else. The linter reports
  this as warning 20024, printed `[E20024]`.
- No ternary operator, no `switch` (the `-w` option of lslint accepts one
  only for toolchains that translate it before upload), no `break`, no
  `continue`, no arrays, no structs, no classes, no closures. Use `list`,
  `llList2*`, strided lists, and plain functions.
- Every script has a `default` state. Events go inside states. Functions and
  globals go before the first state. Globals are initialized with constants
  only, never with a function call or a `+` concatenation.
- `integer / integer` truncates. Divide by a `float` (write `2.0`) when you
  need a fraction. Division or modulo by zero is a runtime error that stops
  the script.
- `float` to `string` gives six decimals. `(integer)"abc"` is 0, not an
  error. `llList2Integer` on a float element casts it (2.7 gives 2); an
  element that cannot be cast gives 0 with no error. Check types with
  `llGetListEntryType` when it matters.
- Keys: `if (k)` is TRUE only for a valid, non-null UUID. A key cannot be
  negated or combined with `&&`; write `if (k) ; else ...`.
- Comparing two lists with `==` compares their lengths, nothing else.
- Memory is 64 KiB for the whole script under Mono, code and data together.
  Large lists of strings eat it fast. Watch `llGetFreeMemory()`.
- One timer per script (`llSetTimerEvent`), one repeating sensor, 65 open
  listens per script, 64 queued events, then events are dropped silently.
- `llSleep()` freezes the script and its event queue. Prefer timers.
- Chat is limited (1024 bytes per message, 254 bytes for `llSetText`), dialog
  buttons are limited (12 buttons, 24 bytes per label). Hard limits produce
  runtime errors or silent truncation, not compiler errors.
- Anything that talks to the outside world is asynchronous: `llHTTPRequest`
  answers in `http_response`, `llGetNotecardLine` in `dataserver`,
  `llRequestPermissions` in `run_time_permissions`. Keep the request key and
  match it in the event. Never wait with `llSleep`.
- An HTTP-in URL from `llRequestURL` dies on region restart and when the
  object is moved to another region: handle `changed` with
  `CHANGED_REGION_START` and `CHANGED_REGION`, and re-request.
- Reset on owner change (`changed` with `CHANGED_OWNER`) when the script
  stores owner-specific data or permissions.

The full, sourced list with numbers is in `references/lsl-for-ai.md`.
Diagnostic codes are explained in `references/error-codes.md`.

## Where to start from

- `references/patterns.md`: the correct shape for the things every script
  needs (skeleton, guards, menus, timers, notecards, HTTP out and in, link
  messages, permissions, linkset data, strided lists). Copy the shape.
- `templates/*.lsl`: complete, lint-clean scripts (door, paged menu,
  notecard config, HTTP client, HTTP-in server, core + menu over link
  messages, HUD attachment, linkset storage). Start from the closest one
  rather than from a blank file; keep its structure, rename, extend.
- `references/testing.md`: how to test an LSL script, from the linter to the
  in-world plan you hand to the human, and how to read runtime errors.

## Style for generated scripts

- Header comment: name, version, one line of purpose. Short comments, only
  where the code is not obvious.
- Constants in UPPER_CASE at the top, globals prefixed `g`, functions in
  camelCase, events as given by LSL.
- One responsibility per script. Several scripts in one object talk with
  `llMessageLinked`; a numbered protocol in a comment at the top of each.
- Always a `state_entry()` that puts the object in a known state, and an
  `on_rez()` that resets what depends on the rez (listens, URLs, timers).
- Clean up what you open: `llListenRemove` when you stop listening,
  `llReleaseURL` when you stop serving, `llSetTimerEvent(0.0)` when the timer
  is done. A state change releases listens by itself but not URLs, and the
  timer keeps running into the next state.
- Prefer `llRegionSayTo` over `llSay` for messages to one avatar or object,
  and `llOwnerSay` for the owner. Never spam channel 0.
- Keep strings and lists small; build big text with `llDumpList2String` once,
  not with `+=` in a loop.

## When reviewing someone else's script

Run the linter first. Then read for the rules above, in this order: evaluation
order in conditions, asynchronous events handled, listeners and timers cleaned,
memory growth, owner change, region restart. Report findings with line
numbers and the fix, not just the problem.
