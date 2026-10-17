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

## 1b. Run it: unit tests with lsltest

`lsltest` runs a script outside Second Life: a Python interpreter with LSL
semantics and a fake simulator that captures what the script does. Write a
test file next to the script, drive it through the simulator, assert on the
outcome. Every example in `templates/tests/test_templates.py` follows this
shape:

```python
from lsltest import LslTestCase

class DoorTest(LslTestCase):
    def test_owner_opens_and_timer_closes(self):
        script = self.load("door.lsl")        # attaches the script to a default object
        self.sim.start()                      # runs state_entry
        self.sim.touch()                      # touch_start/touch/touch_end by the owner
        self.assertGlobal(script, "gOpen", 1)
        self.sim.tick(9.0)                    # the clock moves, timers fire
        self.assertGlobal(script, "gOpen", 0)
        self.assertNoErrors()
```

Run with `python -m lsltest tests/` (or `lsltest tests/` when installed).
`lsltest script.lsl` with no test does a smoke run: state_entry, one touch,
and prints what the simulator saw.

Words: the *grid* is Second Life; the *simulator* is `self.sim`, the fake
one lsltest runs the script in. Every method below runs the queued events
before it returns, so an assertion right after it sees the result.

What you can drive: `sim.start()` (state_entry of every script, like a fresh
rez), `sim.touch(avatar)` (the owner when omitted), `sim.say(avatar, channel,
text)`, `sim.dialog_reply(avatar, button)`, `sim.textbox_reply(avatar, text)`,
`sim.tick(seconds)` (the clock moves, timers and repeating sensors fire),
`sim.changed(flags)`, `sim.on_rez(param)`, `sim.attach(avatar)` /
`sim.detach()`, `sim.link_message(num, text, id)`, `sim.money(avatar,
amount)`, `sim.reset(script)`, `sim.http_respond(status, body)` for the
oldest unanswered `llHTTPRequest`, `sim.http_handler = lambda request: (200,
body)` to answer every request during the run, `sim.http_in_request(url,
method, body)` for the script's own URL, `sim.notecard(name, text)` to put a
notecard in the object, `sim.permission_policy` (True, False, or a function
of avatar and mask), `sim.avatar(name, group=...)` to create other
residents. `sim.owner` is the avatar that owns every object by default and
`sim.constants["CHANGED_INVENTORY"]` gives any LSL constant.

What you can assert: `assertSaid(text, channel=0)` and `assertNotSaid` look
at public script chat only (`llSay`, `llWhisper`, `llShout`, `llRegionSay`,
`llRegionSayTo`), never at what the test itself said through `sim.say`;
`assertOwnerSaid` / `assertNotOwnerSaid` for `llOwnerSay`;
`assertSaidTo(avatar, text)` for `llRegionSayTo` and `llInstantMessage`;
`assertDialog(buttons=, contains=)` (returns the dialog: `.channel`,
`.buttons`, `.text`), `assertListening(channel)`, `assertNoListens()`,
`assertHttpOut(url_contains=, method=, body_contains=)` (returns the request:
`.url`, `.method`, `.body`, `.params`), `assertNoHttpOut()`,
`assertLinkMessage(num=, str_contains=)`, `assertCalled("llSetColor", args...)`
for builtins the simulator does not model (it records them instead of
failing), `assertNotCalled`, `assertState(script, "name")`,
`assertGlobal(script, "name", value)`, `assertNoErrors()`,
`assertError("Math Error")`. The raw records are on the simulator too:
`sim.chat` (`.channel`, `.text`, `.kind`, `.speaker_name`), `sim.dialogs`,
`sim.http_out`, `sim.link_messages`, `sim.emails`, `sim.calls`, `sim.errors`.

What the simulator enforces, like the grid: strict types and implicit
conversions, both operands of `&&` and `||` run, right operand first, integer
division truncates, `/` and `%` by zero kill the script with "Math Error",
32-bit integer wrap, single-precision floats, 64 queued events then silent
drops, 65 listens then "Too Many Listens", a function call nesting over 150
or a string or list over 65536 items dies with "Stack-Heap Collision",
dialogs with more than 12 buttons or labels over 24 bytes fail, chat is cut
at 1024 bytes, hover text at 254, incoming HTTP bodies at 2048, 25
`llHTTPRequest` per 20 seconds then `NULL_KEY`, linkset data at 128 KiB,
`llSleep`, `llDialog` (1 s), `llInstantMessage` (2 s), `llEmail` (20 s) and
`llSetPos` (0.2 s) move the clock, timers shorter than one frame (0.022 s)
are rounded up, a state change releases listens and the repeating sensor but
not the timer, a handler running over two million statements is killed as a
runaway.

What it does not model: physics, movement, rendering, region crossings,
avatar animations beyond recording the call, prim parameters (recorded),
sensors beyond distance to the avatars and objects you created, money beyond
the event, memory beyond a rough count of the globals. A builtin it does not
model is recorded with its arguments and returns the type's default value;
`strict = True` on the test class (or `Simulator(strict=True)`) raises
instead, when a test must not pass by accident. A `tick()` that would fire
more than 100000 timers raises `RuntimeError`: shorten the tick or the timer.

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
