---
name: lsl-dev
description: Write, fix, review and lint Second Life LSL scripts (Linden Scripting Language, also OpenSimulator). Use whenever a task involves an LSL script, a Second Life object, HUD, vendor, door, security or any in-world scripting question, including "why does my script not compile" and "make this script do X". Runs lslint through lslcheck.py before any script is shown to a human.
---

# LSL development with lslint

LSL is not C, not JavaScript, not Lua. Code that looks right in those languages
compiles and misbehaves in Second Life, or does not compile at all. This skill
gives you a checker and the facts you need. Follow the loop, every time.

## The loop

1. **Read `references/lsl-for-ai.md` once per session** before writing LSL.
   It is short and every line of it was verified on the official wiki.
2. **Write the script** following the rules below.
3. **Lint it**: `python <lslint-dir>/lslcheck.py --strict path/to/script.lsl`
   (`<lslint-dir>` is where `lslcheck.py` and the `lslint` binary live; set
   `LSLINT=/path/to/lslint` if the binary is elsewhere). The output is one line
   per finding, `file:line:col: error: [E10033] message`, then a summary.
4. **Fix every error. Read every warning** and either fix it or explain in one
   sentence why it is intended. `--strict` makes warnings fail on purpose.
5. **Repeat until the summary says `0 error(s), 0 warning(s)`**, then give the
   script to the human together with that last line. Never hand over a script
   you have not linted.

If `lslcheck.py` says the binary is missing, build it (`build_win64.cmd` on
Windows, `make` elsewhere, see the repository README) or ask the human for the
binary. Do not skip the lint.

## Rules that are not negotiable

- `&&` and `||` evaluate **both** operands, **right one first**. Never put a
  function call, an assignment, `++`/`--`, a division or a modulo inside a
  compound condition. Use nested `if`. The linter reports this as W20024.
- No ternary operator, no `switch` (unless the project enables the
  preprocessor extension), no arrays, no structs, no classes, no closures.
  Use `list`, `llList2*`, strided lists, and plain functions.
- Every script has a `default` state. Events go inside states. Functions and
  globals go before the first state. Globals are initialized with constants
  only, never with a function call.
- `integer / integer` truncates. Divide by a `float` (write `2.0`) when you
  need a fraction. Division or modulo by zero is a runtime error that stops
  the script.
- `float` to `string` gives six decimals. `(integer)"abc"` is 0, not an error.
  `llList2Integer` on a list element that holds a float returns 0: list
  accessors are type-strict.
- Keys: `if (k)` is TRUE only for a valid, non-null UUID. Compare to
  `NULL_KEY`, not to `""`.
- Comparing two lists with `==` compares their lengths, nothing else.
- Memory is 64 KiB for the whole script under Mono, code and data together.
  A list of 2000 strings is already a problem. Watch `llGetFreeMemory()`.
- One timer per script (`llSetTimerEvent`), one `sensor` at a time, 65 open
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
Error codes are explained in `references/error-codes.md`.

## Style for generated scripts

- Header comment: name, version, one line of purpose. Short comments, only
  where the code is not obvious.
- Constants in UPPER_CASE at the top, globals prefixed `g`, functions in
  camelCase, events as given by LSL.
- One responsibility per script. Several scripts in one object talk with
  `llMessageLinked`; a numbered protocol in a comment at the top of each.
- Always a `state_entry()` that puts the object in a known state, and an
  `on_rez()` that resets what depends on the rez (listens, URLs, timers).
- Clean up what you open: `llListenRemove`, `llSetTimerEvent(0.0)`,
  `llReleaseURL` on state change and in `state_exit()`.
- Prefer `llRegionSayTo` over `llSay` for messages to one avatar or object,
  and `llOwnerSay` for the owner. Never spam channel 0.
- Keep strings and lists small; build big text with `llDumpList2String` once,
  not with `+=` in a loop.

## When reviewing someone else's script

Run the linter first. Then read for the rules above, in this order: evaluation
order in conditions, asynchronous events handled, listeners and timers cleaned,
memory growth, owner change, region restart. Report findings with line
numbers and the fix, not just the problem.
