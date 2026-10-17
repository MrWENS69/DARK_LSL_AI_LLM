# LSL facts for AI assistants

Every statement below was read on the official Second Life wiki on 2026-10-17;
the page is given in parentheses. Facts the wiki does not state are listed at
the end and must not be presented as true. Numbers are the wiki's numbers.

Read this once before writing LSL. The first section is the one that breaks
code written by people, and models, who know C, JavaScript or Lua.

## 1. Evaluation order and operators

- Operands are evaluated from right to left. (LSL_Operators)
- `&&` and `||` never short-circuit: both operands are always evaluated.
  `if (TRUE || 1/0)` raises a Math Error instead of taking the branch.
  Simulate short-circuit with nested `if`. (LSL_Operators, If)
- `&&` and `||` have the same precedence: `1 || 1 && 0` parses as
  `(1 || 1) && 0` and yields 0. Parenthesize mixed conditions. (LSL_Operators)
- Precedence, high to low: `()` `[]`; `(type)` cast; `!` `~` `++` `--`;
  `*` `/` `%`; `-`; `+`; `<<` `>>`; `<` `<=` `>` `>=`; `==` `!=`; `&`; `^`;
  `|`; `&&` `||`; assignments. (LSL_Operators)
- Integer division truncates; `%` is defined as `a - (a/b) * b` and keeps the
  sign of the first operand (`-7 % 3 == -1`). `%` takes integers (modulus) or
  vectors (cross product) only. (LSL_Operators)
- `/` and `%` by zero raise "Script run-time error: Math Error" for floats and
  integers alike, under Mono too. `llSqrt` of a negative number and `llPow`
  with an imaginary result also raise Math Error. (LSL_Operators, Mono, LSL_Errors)
- `++count` increments before the test, `count++` after. (LSL_Operators)
- There is no ternary operator, no `switch`, no `break`, no `continue`, no
  arrays, no structs. Flow control is `if` `else` `for` `while` `do while`
  `jump` `return` `state`. (Category:LSL_Flow_Control)
- Assignment needs a variable on the left. Writing `if (llGetOwner() == id)`
  with the call first turns an accidental `=` into a compile error. (If)
- A semicolon right after a condition, `if (a == b);`, runs the following
  block unconditionally. (If)

## 2. Types, truthiness, casts

- `if (x)` is true for: integer not 0, float not 0, string of length not 0,
  key that is a valid UUID and not NULL_KEY, vector not ZERO_VECTOR, rotation
  not ZERO_ROTATION, list of length not 0 (Mono). (If)
- `list == list` compares lengths only; `!=` returns the length difference.
  To compare contents, compare `llList2CSV(a) == llList2CSV(b)` (types are
  lost) or walk both lists element by element. (List)
- String `==` compares length and characters; `!=` behaves like C `strcmp`,
  non-zero when different. Do not test float equality directly, use a
  tolerance. (String, Float)
- Integer: signed 32 bit, `-2147483648` to `2147483647`, hex literals such as
  `0x7FFFFFFF` are valid, out-of-range literals wrap silently. (Integer)
- Float: 32-bit IEEE 754; integers are exact only up to 16,777,216;
  `(string)float` gives six decimals; `(string)vector` five. (Float, Typecast)
- Key: 36 hex characters with dashes. "Keys cannot be converted to integers",
  so `!key`, `key && x` do not compile; write `if (uuid) ; else ...`.
  A key variable can hold any string; invalid keys behave like NULL_KEY in
  most places. NULL_KEY is declared as a string: as a string it is true in a
  condition, as a key it is false. (Key, NULL_KEY)
- Implicit casts exist only from string to key and integer to float. Every
  other conversion needs an explicit `(type)` cast. (Typecast)
- `(integer)"0123"` is 123, `(integer)"0x12A"` is 298, `(integer)"105 deg"`
  is 105, `(integer)"abc"` is 0, never an error. `(float)"6.2e1"` is 62.0.
  `(vector)"<1.0, 2.3>"` is ZERO_VECTOR. (Typecast)
- `(string)[1, 2.3, "a"]` is `"12.300000a"`, no separators. `(list)""` is
  `[""]`, one element. (Typecast)
- Mono strings are UTF-16: 2 bytes per character, 4 above U+FFFF.
  `llStringLength` counts characters, not bytes, while chat, hovertext and
  dialog limits are in bytes. (String, LlStringLength)
- Escape sequences are compile-time only: `\n`, `\"`, `\\`, and `\t` which
  becomes four spaces. Text from notecards or chat is never unescaped. (String)
- Vector `*` vector is a dot product (float), `%` is a cross product, vector
  `*` rotation rotates. Rotation components are `.x .y .z .s`. Never add or
  subtract rotations; compose with `*`, invert with `ZERO_ROTATION / r`.
  Euler angles are radians; `DEG_TO_RAD`, `RAD_TO_DEG` exist. (Vector, Rotation)
- You cannot read a component of a literal or of a function result:
  `llGetPos().z` does not compile, assign to a variable first. (Vector)
- All parameters are passed by value. (Category:LSL_Types)

## 3. Script structure, states, functions

- Globals and user functions come before the first state; a function placed
  after a state is a syntax error. Global initializers must be constants:
  no function calls, no `+` concatenation. (User-defined_functions, String, List)
- Names are case sensitive, may not be defined twice in the same scope, an
  inner scope may shadow an outer name. `event` is reserved. (LSL_Variables)
- The `default` state is mandatory and must be first. States contain only
  event handlers. User functions cannot change state: "Global functions
  can't change state" is a compile error. (State, Default)
- `state other;` runs `state_exit`, clears the event queue, releases all
  listens and repeating sensors, then runs `state_entry` of the new state.
  The timer is NOT cleared and will fire in the new state. URLs and granted
  permissions survive the change. `state same;` does nothing. (State,
  LlRequestURL, LlRequestPermissions)
- `state_entry` runs on save, reset, state change and rez without saved
  state. It does NOT run when an object with saved script state is rezzed,
  attached, moved to another region, on owner change or region restart. Use
  `on_rez`, `attach` and `changed` for those. (State_entry, Default)
- `llResetScript()` stops the current event immediately, resets globals,
  clears timers, listens, sensors, the event queue and releases URLs. (LlResetScript)
- `jump label;` targets `@label;` in the same function or event only.
  Duplicate labels make the script fail to compile silently. Code after an
  unconditional `return` is a dead-code compile error. (Jump, Return)
- A value returned from an event handler compiles and crashes the script. (Return)

## 4. Lists and strings

- A list may not contain a list: `[(list)1]` compiles and crashes at
  runtime. Elements keep their type; negative indexes count from the end,
  -1 is the last element. (List)
- `llList2Integer`, `llList2Float`, `llList2String`, `llList2Key` convert and
  never fail: an element of another type is cast when possible, otherwise the
  result is 0 or ""; an out-of-range index returns 0 or "" with no error. A
  float read with `llList2Integer` is truncated, a string "abc" gives 0.
- `llList2Vector` and `llList2Rot` convert nothing: an element that is not a
  vector (rotation), the string "<1,2,3>" included, gives ZERO_VECTOR
  (ZERO_ROTATION). Cast `llList2String` to read a vector stored as text.
  (LlList2Vector)
- `llHMAC(key, message, algorithm)` returns the Base64 of the digest;
  algorithms md5, sha1, sha224, sha256, sha384, sha512. (LlHMAC)
  Check with `llGetListEntryType`. (LlList2Integer, LlList2Float, LlList2String)
- `llListFindList` is type-strict and case-sensitive: `"1"` does not match
  `1`, a string UUID does not match a key UUID. Returns -1 if absent. The
  idiom `if (~llListFindList(l, (list)x))` tests presence. (LlListFindList)
- `llList2List(l, start, end)` and `llGetSubString` are inclusive; when
  `start > end` the result is `[0..end] + [start..-1]`, not a wrap. (LlList2List)
- `llParseString2List` uses only the first 8 separators and 8 spacers, drops
  empty strings (use `llParseStringKeepNulls` to keep them), and returns
  strings only. `llCSV2List("")` returns `[""]`. (LlParseString2List, LlCSV2List)
- `llListReplaceList`, `llDeleteSubList`, `llList2List`, `llListSort` can
  need two to four times the list's memory while they run; concatenation
  makes temporary copies. `llListSort` sorts on the first element of each
  stride. (List)
- `llFrand(n)` returns `[0, n)`; `(integer)llFrand(n)` is the unbiased way to
  get an integer in `[0, n-1]`. (LlFrand)
- JSON: `llJsonGetValue` returns `JSON_INVALID` for a malformed document or
  a missing path, every value comes back as a string, nested objects as JSON
  text. `JSON_INVALID`, `JSON_OBJECT`, `JSON_ARRAY`, `JSON_NULL`, `JSON_TRUE`
  and `JSON_FALSE` are single Unicode characters, not integers; `JSON_APPEND`
  is the integer -1. Negative array indexes are not supported; `JSON_APPEND`
  appends. `llList2Json` renders floats with six decimals. Literals are
  case-sensitive: `"True"` is invalid. (LlJsonGetValue, Json_usage_in_LSL)
- `llGetUnixTime` is an integer that overflows on 2038-01-19; `llGetTimestamp`
  is an ISO 8601 UTC string with sub-second precision. (LlGetUnixTime, LlGetTimestamp)

## 5. Memory

- Mono scripts get 64 KiB (65,536 bytes) for code and data together; LSO
  scripts 16 KiB. Source is capped at 65,536 characters by the viewer.
  (LSL_Script_Memory, Limits)
- When the stack and the heap meet the script dies with "Stack-Heap
  Collision". Too much code is a frequent cause: bytecode shares the memory.
  (LlGetFreeMemory, LSL_Errors)
- `llGetFreeMemory()` reports free bytes before garbage collection;
  `llGetUsedMemory()` is updated once per server frame. `llSetMemoryLimit()`
  can lower the limit, never raise it above 64 KiB. (LlGetFreeMemory,
  LlGetUsedMemory, LlSetMemoryLimit)
- Rough global sizes under Mono: integer and float 16 bytes, vector 24,
  rotation 28, key 102, string 18 + 2 per character. The wiki flags this
  table as approximate. (LSL_Script_Memory)
- Fewer scripts is better; timers under 5 seconds and a listener in every
  prim are listed as inefficient patterns. (LSL_Script_Efficiency)

## 6. Events

- Events are queued FIFO and never interrupt each other. The queue holds 64
  events; beyond that new events are discarded silently. (Category:LSL_Events)
- `llSleep` blocks the script and its queue. Default delay between events is
  one frame (0.022 s). (LlSleep, LSL_Delay)
- Order on wear or login: `on_rez` then `attach(key avatar)` with a real
  key, plus `changed(CHANGED_OWNER)` after an owner change. Detach gives
  `attach` with NULL_KEY. Rez on ground: `on_rez`. (Event_Order)
- `on_rez(start_param)`: the parameter is 0 unless rezzed by
  `llRezObject`/`llRezAtRoot`; `state_entry` runs before `on_rez` when it has
  not run yet. (On_rez)
- `attach` does not fire on teleport or region change. (Attach)
- `changed(integer changes)` is a bit mask, test with `&`, never `==`:
  CHANGED_INVENTORY 0x1, CHANGED_LINK 0x20, CHANGED_OWNER 0x80,
  CHANGED_REGION 0x100, CHANGED_TELEPORT 0x200, CHANGED_REGION_START 0x400.
  Several flags can arrive in one event. CHANGED_INVENTORY is not raised by
  script-driven inventory changes. (Changed)
- `llGetOwner()` does not update by itself after a sale or transfer: handle
  CHANGED_OWNER, re-register listens and permissions, usually reset. For a
  deeded object it returns the group key. (LlGetOwner)
- Changing state inside `touch_start` can lose the next touch; change state
  in `touch_end`. (State, Touch_start)
- `llDetected*` functions work only inside collision, sensor and touch
  events (or functions they call); elsewhere they return unusable values.
  (LlDetectedKey)

## 7. Chat, listen, dialog, link messages

- Ranges: whisper 10 m, say 20 m, shout 100 m, `llRegionSay` region-wide,
  `llRegionSayTo` region-wide to one target. Messages are capped at 1024
  bytes. A prim cannot hear its own chat. (LlListen, LlSay)
- Channel 0 and DEBUG_CHANNEL are throttled: 200 messages per 10 s per
  region per owner, dropped messages still count. `llRegionSay` cannot use
  channel 0. (LlSay, LlRegionSay)
- `llRegionSayTo` on channel 0 goes to the avatar's chat window; on another
  channel it is heard by all the avatar's attachments. Order of arrival of a
  burst is not guaranteed. (LlRegionSayTo)
- `llOwnerSay` fails silently about 45 s after the owner leaves the region
  and always for a group-deeded object. (LlOwnerSay)
- A script may hold at most 65 listens; the 66th raises "Too Many Listens".
  Filters are fixed at registration; handles are not reused; all listens are
  removed on state change and reset. `llListen(0, "", NULL_KEY, "")` is a
  known lag source. The listening position is the root prim. (LlListen, Listen)
- Viewer chat on negative channels is limited to 254 bytes. (LlSay, LlListen)
- Every `llDialog` mistake (empty or long message, more than 12 buttons, a
  label not 1 to 24 bytes, a button that is not a string) is a DEBUG_CHANNEL
  shout, not a run-time error: no dialog shows and the script goes on.
  (LlDialog)
- `llDialog`: at most 12 buttons, each label 1 to 24 bytes, message under 512
  bytes and not empty, sleeps 1.0 s. Buttons fill from the bottom row (1-3
  bottom, 4-6 above). The answer arrives as chat on the channel from the
  avatar, at the root prim position: a listener in another object must be
  within 20 m. The answer is not necessarily one of the buttons. `llTextBox`
  input is limited to 250 bytes and may carry a trailing newline. (LlDialog, LlTextBox)
- `llMessageLinked(link, num, str, id)`: LINK_SET -1, LINK_ALL_OTHERS -2,
  LINK_ALL_CHILDREN -3, LINK_THIS -4, LINK_ROOT 1. A script hears its own
  message when the target includes its prim. 64 link messages can queue,
  more are dropped silently; a state change deletes queued ones. `id` can
  carry any string. (LlMessageLinked, Link_message)
- `llInstantMessage` sleeps 2.0 s, truncates at 1023 bytes, objects cannot
  receive IMs; `llEmail` sleeps 20.0 s and the whole message is capped at
  4096 bytes. Both are throttled per owner. (LlInstantMessage, LlEmail)
- `llSetText` is capped at 254 bytes; clear it with
  `llSetText("", ZERO_VECTOR, 0)`; the text persists after script removal. (LlSetText)

## 8. HTTP

- `llHTTPRequest`: 25 requests per 20 s per object, 1000 per 20 s per
  owner, five 5xx errors per 60 s per script; a throttled call returns
  NULL_KEY; requests time out after 60 s with status 499. (LlHTTPRequest)
- Response body is truncated to HTTP_BODY_MAXLENGTH, default 2048 bytes,
  maximum 16384 under Mono. Redirects are followed for GET only. Setting
  Content-Type via HTTP_CUSTOM_HEADER is a runtime error, use HTTP_MIMETYPE.
  Custom headers total under 4096 characters. (LlHTTPRequest)
- `http_response` fires in every script of the prim: always match
  `request_id` with the key you stored. (LlHTTPRequest)
- HTTP-in: `llRequestURL` answers in `http_request` with
  URL_REQUEST_GRANTED, the URL is the body. URLs die on rez, reset, region
  change, teleport to another region and region restart
  (CHANGED_REGION_START). They survive state changes and must be released
  with `llReleaseURL`. (LlRequestURL, LSL_HTTP_server)
- Incoming body is truncated at 2048 bytes, each header at 255; at most 64
  pending requests; `llHTTPResponse` must be sent within 25 s by the script
  that owns the event. `llGetHTTPHeader` names are lowercase (`x-path-info`,
  `x-query-string`, `x-remote-ip`). (Http_request, LlHTTPResponse, LSL_HTTP_server)
- URL quota: per parcel equal to its prim allowance, 38 per resident for
  attachments; `llGetFreeURLs` reports it. (LSL_HTTP_server)

## 9. Timers, sleep, forced delays

- One timer per script. `llSetTimerEvent(sec)` replaces the previous timer
  and restarts the clock; `0.0` stops it; calling it more often than its
  interval means it never fires. It survives state changes, not resets. The
  timer waits for the running event to finish. (LlSetTimerEvent, Timer)
- `llSleep` sleeps at least until the next server frame (1/45 s). (LlSleep)
- `llGetWallclock` is seconds since midnight Pacific time (SLT), whole
  seconds; `llGetGMTclock` is UTC. (LlGetWallclock)
- Forced delays after a call, in seconds: `llEmail` 20.0, `llLoadURL` 10.0,
  `llTeleportAgentHome` 5.0, `llGiveInventoryList` 3.0, `llInstantMessage`
  2.0, `llDialog` and `llTextBox` 1.0, `llSetPos`, `llSetRot`, `llSetTexture`,
  `llSetPrimitiveParams`, `llSetLinkPrimitiveParams` 0.2, `llRezObject` and
  `llGetNotecardLine` 0.1. `llSetLinkPrimitiveParamsFast` has no delay but
  updates may arrive out of order. (LSL_Delay, LlSetLinkPrimitiveParamsFast)
- `llSetPos` moves at most 10 m per call on an unattached root prim. (LlSetPos)
- `llRezObject` rezzes at most `10 + half the object's size` metres away and
  fails silently beyond that or without build rights. (LlRezObject)

## 10. Sensors

- `llSensor` range is 0 to 96 m, arc 0 to PI, at most 32 results (16 before
  March 2024), nearest
  first. It does not cross region borders, does not detect attachments, and
  an object never detects itself. Nothing found raises `no_sensor`, not an
  empty `sensor`. (LlSensor, Sensor)
- One repeating sensor per script; a new `llSensorRepeat` replaces the old;
  it does not survive a state change; the first scan happens after `rate`
  seconds. (LlSensorRepeat)
- `llCastRay` returns at most 256 hits (set with the `RC_MAX_HITS` option)
  and negative error codes when the simulator is busy
  (RCERR_SIM_PERF_LOW -2). (LlCastRay)

## 11. Notecards and dataserver

- `llGetNotecardLine(name, line)` returns a request key, sleeps 0.1 s, and
  the line arrives in `dataserver(key queryid, string data)`; `EOF` (three
  newlines) means past the end. Lines are capped at 1024 bytes. A missing
  notecard shouts on DEBUG_CHANNEL. (LlGetNotecardLine, EOF)
- `llGetNumberOfNotecardLines` also answers through `dataserver`, as a
  string. `dataserver` fires in every script of the prim; always match the
  request key. Only one request from an event is answered until that event
  completes. (LlGetNumberOfNotecardLines, Dataserver)
- `llGetNotecardLineSync` is synchronous but returns NAK when the notecard
  is not cached; never assume it is. (LlGetNotecardLineSync)

## 12. Linkset data

- The store holds 131,072 bytes (128 KiB) per linkset, lives in the root
  prim, survives script reset and deletion. Writing an empty value deletes
  the pair. Return codes: LINKSETDATA_OK 0, EMEMORY 1, ENOKEY 2,
  EPROTECTED 3, NOTFOUND 4, NOUPDATE 5. (LlLinksetDataWrite)
- `linkset_data(action, name, value)` fires in every script of the linkset
  on a real change: LINKSETDATA_RESET 0, UPDATE 1, DELETE 2,
  MULTIDELETE 3. (Linkset_data)

## 13. Permissions and attachments

- `llRequestPermissions(agent, mask)` answers in `run_time_permissions
  (integer perm)`; `perm` is 0 when refused, test with `perm &
  PERMISSION_X`. A script holds permissions for one agent at a time and the
  last answer replaces the previous set. PERMISSION_TAKE_CONTROLS,
  TRIGGER_ANIMATION, TRACK_CAMERA, CONTROL_CAMERA and ATTACH are granted
  automatically for a worn or sat-on object. (LlRequestPermissions,
  Run_time_permissions)
- Permission dialogs never time out; the viewer allows 5 requests per 10 s
  per agent. (LlRequestPermissions)
- Limits: 38 attachments, 47 attachment points, 256 prims per linkset,
  64 m linking distance, prim name 63 bytes, description 127 bytes. (Limits)

## 14. Runtime errors you will meet

- "Math Error": division or modulo by zero, negative square root.
- "Stack-Heap Collision": out of memory, often too much code.
- "Too Many Listens": more than 65 listens in one script.
- "Lists may not contain lists".
- "Bounds Check Error", "Heap Error", "Hit Sandbox Limit" (object moved
  beyond 10 m under STATUS_SANDBOX). (Category:LSL_Error, LSL_Errors)
- Compile time: "Type mismatch" when assigning a whole vector from a list
  (set `.x` `.y` `.z` one by one), "Byte code assembly failed -- out of
  memory" when the script is too big (long else-if chains). (LSL_Errors)

## 15. Deprecated but still compiling

`llMakeExplosion`, `llMakeFire`, `llMakeSmoke`, `llMakeFountain` (use
`llParticleSystem`), `llSound` and `llSoundPreload` (use `llPlaySound`,
`llPreloadSound`), `llXorBase64Strings` and `llXorBase64StringsCorrect` (use
`llXorBase64`), `llRemoteLoadScript` (use `llRemoteLoadScriptPin`), XML-RPC
functions (use HTTP-in), `llCloud` (returns 0.0), `llTakeCamera` and
`llPointAt` (never implemented). (Category:LSL_Deprecated)

## Not verified on the wiki

Do not present these as facts without checking in-world:

- Runtime integer overflow behaviour in arithmetic (only literal wrapping
  is documented).
- The evaluation order of function arguments, list elements and vector
  components (only "operands" are documented as right to left). Never let
  two of them write the same variable. lsltest evaluates arguments and list
  elements left to right and vector components right to left.
- Minimum timer interval and whether queued timer events coalesce.
- Maximum `num_detected` for touch and collision events.
- Default values of uninitialized local variables.
- Whether a variable may be declared in a `for` header.
- Key versus string `==` semantics beyond the NULL_KEY note.
- Maximum URL length for `llHTTPRequest` and the list of blocked headers.
- Whether `llGetOwner` returns the wearer for attachments.
- Object IM cap: 2,500 per 30 min (llInstantMessage page) versus 5,000 per
  hour (Limits page).

Page names refer to https://wiki.secondlife.com/wiki/<Page>.
