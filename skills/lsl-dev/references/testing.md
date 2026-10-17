# Testing and debugging LSL scripts

There is no LSL interpreter outside Second Life. Testing is a ladder: each
rung catches what the one below cannot, and an assistant climbs as far as it
can before handing the script to a human for the in-world rungs.

## 1. Lint, every time

```sh
lslcheck --strict script.lsl
```

Zero errors, zero unexplained warnings. This catches syntax, types, unknown
functions, unused variables, wrong event signatures, `break` outside a
switch, both-operands evaluation in `&&` / `||` (warning 20024), and every
other diagnostic in `error-codes.md`. It cannot catch logic, timing, memory
at runtime, or simulator limits.

Use `--json` when you need to act on the result programmatically, `-q` for a
one-line verdict, `--lso` to check a script that must also run on the legacy
engine.

## 2. Read it like the simulator does

Before any in-world test, walk the script with these questions. They cover
the bugs the linter is blind to.

- Conditions: is there a call, an assignment, a division inside `&&` / `||`?
  Both sides run, right side first.
- Every asynchronous call has its event handler, and the handler checks the
  request key (`http_response`, `dataserver`, `run_time_permissions`,
  `http_request` with `URL_REQUEST_GRANTED`).
- Every `llListen` has a matching `llListenRemove` or a state change; a
  timeout timer closes menus that nobody answers.
- `on_rez` and `changed` (`CHANGED_OWNER`, `CHANGED_REGION_START`,
  `CHANGED_INVENTORY`) re-create what cannot survive: listens, URLs, timers,
  cached owner key.
- Nothing grows without bound: lists appended in a loop, strings built with
  `+=`, notecard lines kept in memory.
- Limits: 12 dialog buttons of 24 bytes, 1024-byte chat, 254-byte hovertext,
  65 listens, 64 queued events, 25 HTTP requests per 20 s per object,
  2048-byte incoming HTTP body, 128 KiB linkset data.
- Timing: `llSleep` inside an event blocks every other event; a forced delay
  (`llSetPrimitiveParams` 0.2 s, `llEmail` 20 s) inside a loop multiplies.

## 3. Make the script testable

- One `DEBUG` integer global at the top and a `dbg(string msg)` function
  that calls `llOwnerSay` only when it is TRUE. Keep the calls in the final
  script; they cost nothing when off.
- Print state transitions, request keys, and the first 200 bytes of any
  payload received. Truncate with `llGetSubString(body, 0, 199)` to stay
  under the chat limit.
- A `VERSION` string constant, said in `state_entry`, so the human can tell
  which build they are looking at.
- For HTTP work, log the status code and `llGetFreeMemory()` after each
  response; memory pressure shows up here first.
- For menus, log the channel and the listen handle; most menu bugs are a
  listen on the wrong channel or one that was removed too early.

## 4. In-world test plan to hand to the human

Write it as a numbered list of actions and expected observations, one line
each, that a non-programmer can follow. Always include:

1. Rez (or wear) a fresh copy: expect the version line in local chat.
2. The main feature, once, by the owner.
3. The same feature by another avatar (permissions, group, owner-only paths).
4. The failure path: cancel the dialog, wrong input, no answer for a minute.
5. Reset the script (`Reset Scripts` in the viewer): expect a clean restart,
   no duplicate listeners, no stale URL.
6. Take the object into inventory and rez it again; for attachments, detach
   and re-attach; for HTTP-in, ask the human to test after a region restart
   if they can.
7. Watch the script memory in the viewer (Advanced, Script Info) or ask for
   `llGetFreeMemory()` in the debug output after the heaviest action.

Ask for the exact text of any error that appears in local chat. Script
run-time errors name the cause ("Math Error", "Stack-Heap Collision", "Too
Many Listens").

## 5. Reading a runtime error

| Message | Meaning | First thing to check |
| --- | --- | --- |
| Math Error | division or modulo by zero, negative square root | a guard that used `&&` instead of a nested `if` |
| Stack-Heap Collision | out of memory | lists that only grow, big strings, too much code |
| Too Many Listens | more than 65 listens | `llListen` in a loop or in a timer without `llListenRemove` |
| Lists may not contain lists | `[a, [b]]` | a cast or a `(list)` where a flat list was meant |
| Bounds Check Error | index outside a list or string in a strict function | negative or out-of-range index |
| Hit Sandbox Limit | object moved beyond 10 m while sandboxed | `llSetPos` loops |
| Script compile error with a line number | the viewer compiler is stricter than the linter in a few places | compare with the linter's output, then the `error-codes.md` table |

## 6. Testing HTTP without the grid

- Outbound: point `llHTTPRequest` at a request-logging endpoint you control
  before the real API, and check the `X-SecondLife-*` headers the simulator
  adds: they are the only trustworthy identity of the object.
- Inbound: an `http_request` handler can be exercised with any HTTP client
  once the URL is known; the body is capped at 2048 bytes, so test exactly
  that size.
- Rate limits are per object and per owner: a test loop that fires 30
  requests in 20 seconds will get `NULL_KEY` back and prove nothing.

## 7. When the behaviour differs from the documentation

The wiki is the reference, but pages age. If a human reports behaviour that
contradicts `lsl-for-ai.md`, say so, ask them to confirm with the exact
message and the simulator version (`llGetEnv("sim_version")`), and prefer the
observed behaviour in the script. Never invent a limit or a function; check
`builtins.txt` for the exact signature.
