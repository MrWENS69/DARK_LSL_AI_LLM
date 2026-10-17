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
then it prints the state, the chat, dialogs, textboxes, link messages, HTTP
requests, emails, recorded calls and errors.

Words: the *grid* is Second Life; the *simulator* is `self.sim`, the fake
one lsltest runs the script in. Every method that injects an event or moves
the clock runs the queued events before it returns, so an assertion right
after it sees the result. `LslTestCase.setUp` creates the simulator: a test
class that overrides `setUp` calls the inherited one first.

What you can drive: `sim.start()` (state_entry of every script, like a fresh
rez), `sim.touch(avatar)` (the owner when omitted; touch_start, touch and
touch_end run one after the other), `sim.collision(avatar)`, `sim.say(avatar,
channel, text)`, `sim.dialog_reply(avatar, button)`, `sim.textbox_reply(avatar,
text)`, `sim.tick(seconds)` (the clock moves, timers and repeating sensors
fire), `sim.changed(flags)`, `sim.on_rez(start_param)`, `sim.attach(avatar)` /
`sim.detach()`, `sim.link_message(num, text, id, sender=0)` (a message from
another prim), `sim.money(avatar, amount)`, `sim.reset(script)`,
`sim.http_respond(status, body)` for the oldest unanswered `llHTTPRequest`,
`sim.http_handler = lambda request: (200, body)` to answer every request
during the run (return None to leave one pending), `sim.http_in_request(url,
method, body)` for the script's own URL (returns `(status, body,
content_type)`: 404 for an unknown URL, 500 when the script did not answer),
`sim.notecard(name, text, cached=False)` to put a notecard in the object,
`sim.permission_policy` (True, False, or a function of avatar and mask),
`sim.avatar(name, group=...)` to create other residents, `sim.rez(name, desc,
owner, group)` for more objects (`obj=` on `load` and on the drivers picks
one). `sim.owner` is the Avatar that owns every object by default, the
default object is `sim.objects[0]` (`.name`, `.desc`, `.group`, `.pos`,
`.text`), `sim.constants["CHANGED_INVENTORY"]` gives any LSL constant.
Attributes named `avatar`, `owner`, `speaker` and `target` on records hold
keys; `sim.owner` and the return of `sim.avatar()` are Avatar objects (use
`.key`).

What you can assert: `assertSaid(text, channel=0)` and `assertNotSaid` look
at script chat on a channel (`llSay`, `llWhisper`, `llShout`, `llRegionSay`,
`llRegionSayTo`; `channel=None` for any channel), never at what the test
itself said through `sim.say`; `assertOwnerSaid` / `assertNotOwnerSaid` for
`llOwnerSay`; `assertSaidTo(avatar, text)` for `llRegionSayTo` and
`llInstantMessage`; every text assertion takes `exact=True` to match the
whole line. `assertDialog(buttons=, contains=, avatar=)` returns the dialog
(`.avatar`, `.text`, `.buttons`, `.channel`, `.script`), `assertNoDialog()`,
`assertListening(channel, script=)`, `assertNoListens(script=)`,
`assertHttpOut(url_contains=, method=, body_contains=)` returns the request
(`.url`, `.method`, `.body`, `.params`, `.script`), `assertNoHttpOut()`,
`assertLinkMessage(num=, str_contains=)` returns it (`.script`, `.sender`,
`.link`, `.num`, `.str`, `.id`), `assertCalled("llSetColor", args...)` for
builtins whose call is only recorded (every unmodelled one, plus
`llTakeControls`, `llReleaseControls`, `llStartAnimation`,
`llStopAnimation`, `llGiveInventory`, `llDie`, `llRezObject`),
`assertNotCalled`, `assertState(script, "name")`, `assertGlobal(script,
"name", value)` (a float is compared at single precision), `assertNoErrors()`,
`assertError("Math Error", script)` returns the error (`.kind`, `.detail`,
`.line`). The raw records: `sim.chat` (`.channel`, `.text`, `.kind`,
`.speaker`, `.speaker_name`, `.target`, `.time`; kinds `say`, `whisper`,
`shout`, `regionsay`, `regionsayto`, `ownersay`, `im`, `debug` for the grid's
DEBUG_CHANNEL shouts such as llDialog errors, `avatar` for `sim.say`),
`sim.dialogs`, `sim.textboxes`, `sim.http_out`, `sim.link_messages`,
`sim.emails` (`.to`, `.subject`, `.body`, `.object`), `sim.calls` (tuples
`(script_name, builtin, args)`), `sim.errors` (tuples `(script_name,
ScriptError)`), `script.dropped_events`.

What the simulator enforces, like the grid: strict types and implicit
conversions, both operands of `&&` and `||` run, right operand first, an
integer mixed with a float goes through single precision, integer division
truncates, `/` and `%` by zero kill the script with "Math Error", 32-bit
integer wrap, 64 queued events then silent drops, 65 listens then "Too Many
Listens" (the same filter again returns the existing handle), about 64 KiB
of memory for code and globals then "Stack-Heap Collision", `llDialog`
errors (empty or long message, more than 12 buttons, labels not 1 to 24
bytes) are shouted on DEBUG_CHANNEL and no dialog shows, chat is cut at 1024
bytes, hover text at 254, incoming HTTP bodies at 2048 bytes, HTTP responses
at HTTP_BODY_MAXLENGTH (2048 by default; the metadata then starts with
`HTTP_BODY_TRUNCATED` and the limit), 25 `llHTTPRequest` per 20 seconds then
`NULL_KEY`, a Content-Type custom header is a run-time error, `http_response`
and `dataserver` reach every script of the prim, permissions arrive with
`run_time_permissions` and not inside the calling handler,
`llGetNotecardLineSync` answers NAK until the notecard was read once
asynchronously (or `sim.notecard(..., cached=True)`), HTTP-in URLs die on rez
and on region restart, link messages are delivered by prim (LINK_ALL_OTHERS
from the only prim reaches nobody, the sender number is 0 there), sensors
return the nearest 32, linkset data at 128 KiB, `llSleep`, `llDialog` (1 s),
`llInstantMessage` (2 s), `llEmail` (20 s), `llSetPos` and `llSetRot`
(0.2 s), notecard and agent-data reads (0.1 s), among others, move the
clock; timers shorter than one frame (0.022 s) are rounded up; a state
change releases listens and the repeating sensor but not the timer; a value
returned from an event handler is an error.

lsltest's own guards, not grid limits: a call depth of 150 (the event
handler counts as the first), a string or list over 65536 items, two million
statements or 20 seconds in one handler, 10000 rounds of scripts posting
events to each other in one `run()`, 100000 timer or sensor steps in one
`tick()`, 100000 records of one kind (chat lines, requests...). The first
three kill the script with a `ScriptError`; the `run()` and `tick()` guards
raise `RuntimeError` in the test: shorten the tick or the timer, or fix the
loop. Error messages name the script line.

What it does not model: physics, movement, chat range (every listener in the
region hears), rendering, region crossings, avatar animations beyond
recording the call, prim parameters (recorded), sensors beyond distance to
the avatars and objects you created, money beyond the event, memory beyond a
rough count of the code and the globals. A builtin it does not model is
recorded with its arguments and returns the type's default value; `strict =
True` on the test class (or `Simulator(strict=True)`) raises instead, when a
test must not pass by accident.

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
