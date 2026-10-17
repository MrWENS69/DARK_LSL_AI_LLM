# LSL patterns that survive the simulator

Each pattern is lint-clean (`lslcheck --strict`, including the `&&` / `||`
check) and follows the facts in `lsl-for-ai.md`. Copy the shape, rename the
pieces. Complete scripts built from these patterns are in `../templates/`.

## Script skeleton

```lsl
// Door v1.0 - opens for group members, closes after a delay
string VERSION = "1.0";
float OPEN_SECONDS = 8.0;

integer gDebug;
integer gOpen;

dbg(string msg)
{
    if (gDebug) llOwnerSay("[door] " + msg);
}

default
{
    state_entry()
    {
        // debug output is switched on by writing "debug" in the object description;
        // a constant global would be folded by the linter and flagged "always false"
        gDebug = (llSubStringIndex(llGetObjectDesc(), "debug") >= 0);
        llOwnerSay("Door " + VERSION + " ready");
        gOpen = FALSE;
    }

    on_rez(integer start_param)
    {
        llResetScript();
    }

    changed(integer changes)
    {
        if (changes & CHANGED_OWNER) llResetScript();
    }

    touch_start(integer num_detected)
    {
        if (llSameGroup(llDetectedKey(0)))
        {
            gOpen = TRUE;
            llSetTimerEvent(OPEN_SECONDS);
            dbg("opened");
        }
    }

    timer()
    {
        llSetTimerEvent(0.0);
        gOpen = FALSE;
        dbg("closed");
    }
}
```

Why: `on_rez` resets so that nothing from the previous rez survives;
`changed` with `CHANGED_OWNER` resets because `llGetOwner()` and granted
permissions do not follow a sale; the timer is stopped as soon as it fires.
Globals that never change are constants to the linter: `integer DEBUG =
FALSE;` makes every `if (DEBUG)` a "condition always false" warning, so a
flag that is meant to be flipped is set at runtime instead.

## Guard with nested if, never with && and a call

```lsl
// WRONG: both sides run, llGetNotecardLine fires even when the name is empty
// if (gConfigName != "" && llGetNotecardLine(gConfigName, 0) != NULL_KEY) ...

// RIGHT
if (gConfigName != "")
{
    gQuery = llGetNotecardLine(gConfigName, 0);
}
```

Same for divisions: `if (count != 0) { average = total / count; }`.

## Menu with llDialog, one listener, a timeout

```lsl
integer gMenuChannel;
integer gMenuHandle = 0;
key gMenuUser = NULL_KEY;

menuOpen(key user, string text, list buttons)
{
    menuClose();
    gMenuChannel = -1000000 - (integer)llFrand(1000000.0);
    gMenuHandle = llListen(gMenuChannel, "", user, "");
    gMenuUser = user;
    llDialog(user, text, buttons, gMenuChannel);
    llSetTimerEvent(60.0);
}

menuClose()
{
    if (gMenuHandle) llListenRemove(gMenuHandle);
    gMenuHandle = 0;
    gMenuUser = NULL_KEY;
    llSetTimerEvent(0.0);
}

default
{
    touch_start(integer num_detected)
    {
        menuOpen(llDetectedKey(0), "Choose:", ["Open", "Close", "Status"]);
    }

    listen(integer channel, string name, key id, string message)
    {
        if (channel != gMenuChannel) return;
        if (id != gMenuUser) return;
        menuClose();
        if (message == "Open") { /* ... */ }
        else if (message == "Close") { /* ... */ }
        else if (message == "Status") { /* ... */ }
    }

    timer()
    {
        menuClose();
    }
}
```

Why: a random negative channel avoids collisions with other objects; the
listener is filtered on the user and removed on answer or timeout, so the
script never reaches 65 listens; the answer is compared to the button text,
and anything else is ignored because a viewer can send free text.

Buttons: at most 12, each label at most 24 bytes, message under 512 bytes.
Buttons fill from the bottom row. For more than 12 choices, add "Next" and
"Back" buttons and keep a page index.

## Timer that does one job

```lsl
float POLL_SECONDS = 30.0;

default
{
    state_entry()
    {
        llSetTimerEvent(POLL_SECONDS);
    }

    timer()
    {
        // one short task; never llSleep here
    }
}
```

There is only one timer per script. A script that needs a menu timeout and a
polling loop keeps a countdown integer in the timer, or splits into two
scripts that talk with `llMessageLinked`.

## Reading a notecard

```lsl
string CONFIG = "config";
key gQuery;
integer gLine;
list gSettings;   // strided: name, value

configRead()
{
    gSettings = [];
    gLine = 0;
    if (llGetInventoryType(CONFIG) == INVENTORY_NOTECARD)
    {
        gQuery = llGetNotecardLine(CONFIG, gLine);
    }
    else
    {
        llOwnerSay("No notecard named " + CONFIG);
    }
}

default
{
    state_entry()
    {
        configRead();
    }

    changed(integer changes)
    {
        if (changes & CHANGED_INVENTORY) configRead();
    }

    dataserver(key query, string data)
    {
        if (query != gQuery) return;
        if (data == EOF)
        {
            llOwnerSay((string)(llGetListLength(gSettings) / 2) + " settings loaded");
            return;
        }
        string line = llStringTrim(data, STRING_TRIM);
        if (line != "")
        {
            if (llGetSubString(line, 0, 0) != "#")
            {
                integer eq = llSubStringIndex(line, "=");
                if (eq > 0)
                {
                    string name = llStringTrim(llGetSubString(line, 0, eq - 1), STRING_TRIM);
                    string value = llStringTrim(llGetSubString(line, eq + 1, -1), STRING_TRIM);
                    gSettings += [name, value];
                }
            }
        }
        gLine = gLine + 1;
        gQuery = llGetNotecardLine(CONFIG, gLine);
    }
}
```

Why: `dataserver` fires for every script in the prim, so the query key is
checked; `EOF` ends the loop; lines are capped at 1024 bytes; reading
restarts on `CHANGED_INVENTORY` so that editing the notecard reloads it.

## HTTP request with a matched response

```lsl
string API = "https://example.invalid/api";
key gRequest = NULL_KEY;

apiCall(string path, string body)
{
    if (gRequest != NULL_KEY) return;   // one request in flight
    gRequest = llHTTPRequest(API + path,
        [HTTP_METHOD, "POST",
         HTTP_MIMETYPE, "application/json",
         HTTP_BODY_MAXLENGTH, 16384,
         HTTP_VERIFY_CERT, TRUE],
        body);
    if (gRequest == NULL_KEY) llOwnerSay("HTTP throttled, try again later");
}

default
{
    http_response(key request_id, integer status, list metadata, string body)
    {
        if (request_id != gRequest) return;
        gRequest = NULL_KEY;
        if (status != 200)
        {
            llOwnerSay("API error " + (string)status);
            return;
        }
        string value = llJsonGetValue(body, ["result"]);
        if (value == JSON_INVALID)
        {
            llOwnerSay("Bad JSON from API");
            return;
        }
        // use value
    }
}
```

Why: `http_response` fires in every script of the prim; the throttle returns
`NULL_KEY` instead of raising; 2048 bytes is the default body cap, raised
here to the Mono maximum; JSON must be checked for `JSON_INVALID` before use.
The simulator adds `X-SecondLife-Owner-Key` and `X-SecondLife-Object-Key`
headers that the server can trust; never send a secret in the body that the
server could derive from them.

## HTTP-in server that survives restarts

```lsl
key gUrlRequest = NULL_KEY;
string gUrl = "";

urlRequest()
{
    if (gUrl != "") llReleaseURL(gUrl);
    gUrl = "";
    gUrlRequest = llRequestURL();
}

default
{
    state_entry()
    {
        urlRequest();
    }

    on_rez(integer start_param)
    {
        urlRequest();
    }

    changed(integer changes)
    {
        if (changes & (CHANGED_REGION | CHANGED_REGION_START | CHANGED_TELEPORT)) urlRequest();
    }

    http_request(key id, string method, string body)
    {
        if (id == gUrlRequest)
        {
            if (method == URL_REQUEST_GRANTED)
            {
                gUrl = body;
                llOwnerSay("URL: " + gUrl);   // or register it with your server
            }
            else
            {
                llOwnerSay("No URL available: " + body);
            }
            return;
        }
        if (method == "POST")
        {
            string path = llGetHTTPHeader(id, "x-path-info");
            llHTTPResponse(id, 200, "ok " + path);
        }
        else
        {
            llHTTPResponse(id, 405, "POST only");
        }
    }
}
```

Why: the URL changes on rez, region change and region restart, and must be
released explicitly; the grant arrives in `http_request`, not in a return
value; every request must be answered within 25 seconds, by this script.

## Script-to-script protocol with llMessageLinked

```lsl
// In every script of the object:
//   num 100  menu -> core   "open"|"close"|"status"
//   num 200  core -> menu   status text
integer MSG_COMMAND = 100;
integer MSG_STATUS = 200;

default
{
    link_message(integer sender, integer num, string str, key id)
    {
        if (num == MSG_COMMAND)
        {
            if (str == "open") { /* ... */ }
            llMessageLinked(LINK_SET, MSG_STATUS, "opened", NULL_KEY);
        }
    }
}
```

Why: the sender hears its own `LINK_SET` messages, so every handler filters
on `num`; 64 messages can queue, so a burst must be throttled by the sender;
`id` can carry any string, not only a key.

## Permissions and attachments

```lsl
default
{
    attach(key id)
    {
        if (id != NULL_KEY)
        {
            llRequestPermissions(id, PERMISSION_TAKE_CONTROLS | PERMISSION_TRIGGER_ANIMATION);
        }
    }

    run_time_permissions(integer perm)
    {
        if (perm & PERMISSION_TAKE_CONTROLS)
        {
            llTakeControls(CONTROL_FWD | CONTROL_BACK, TRUE, TRUE);
        }
        if (perm & PERMISSION_TRIGGER_ANIMATION)
        {
            // llStartAnimation(...)
        }
    }
}
```

Why: a script holds permissions for one agent; the answer is a bit mask and
is 0 when refused; `attach` with `NULL_KEY` means detached. Owner-change
handling belongs in `changed`, not here.

## Linkset data as persistent storage

```lsl
integer saveSetting(string name, string value)
{
    integer rc = llLinksetDataWrite(name, value);
    if (rc == LINKSETDATA_EMEMORY) llOwnerSay("Linkset data full");
    return rc;
}

string loadSetting(string name, string fallback)
{
    string value = llLinksetDataRead(name);
    if (value == "") return fallback;
    return value;
}
```

Why: the store survives script reset and deletion, lives in the root prim,
holds 128 KiB; an empty value means "absent" and writing an empty value
deletes the pair.

## Lists: strided access without arrays

```lsl
// name, price, stock
list gItems = ["Hat", "250", "3", "Boots", "400", "0"];
integer STRIDE = 3;

integer itemIndex(string name)
{
    integer i;
    integer n = llGetListLength(gItems);
    for (i = 0; i < n; i = i + STRIDE)
    {
        if (llList2String(gItems, i) == name) return i;
    }
    return -1;
}

integer itemStock(string name)
{
    integer i = itemIndex(name);
    if (i < 0) return 0;
    return llList2Integer(gItems, i + 2);
}
```

Why: there are no arrays or structs; a flat list with a stride and small
accessor functions is the idiom; `llList2Integer` on the string "3" gives 3.

## Strings: build once, say once

```lsl
string report = llDumpList2String(["Stock:", (string)stock, "Price:", (string)price], " ");
llRegionSayTo(user, 0, report);
```

Why: `+=` on a string in a loop copies the string each time; chat is capped
at 1024 bytes; `llRegionSayTo` reaches the one avatar anywhere in the region
without channel-0 throttling for the whole object.
