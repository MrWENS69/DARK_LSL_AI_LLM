// HTTP client v1.0 - sends a JSON POST to a web API and reads the JSON answer.
// Template: one request in flight, request key matched in http_response,
// throttle handled, JSON validated before use, memory logged in debug mode
// (write "debug" in the object description to switch it on).
string VERSION = "1.0";
string API_URL = "https://example.invalid/api/ping";

integer gDebug;
key gRequest = NULL_KEY;

dbg(string msg)
{
    if (gDebug) llOwnerSay("[http] " + msg);
}

apiPost(string json)
{
    if (gRequest != NULL_KEY)
    {
        dbg("busy, request dropped");
        return;
    }
    gRequest = llHTTPRequest(API_URL,
        [HTTP_METHOD, "POST",
         HTTP_MIMETYPE, "application/json",
         HTTP_BODY_MAXLENGTH, 16384,
         HTTP_VERIFY_CERT, TRUE],
        json);
    if (gRequest == NULL_KEY)
    {
        llOwnerSay("HTTP throttled by the simulator, try again in a minute.");
    }
}

default
{
    state_entry()
    {
        gDebug = (llSubStringIndex(llGetObjectDesc(), "debug") >= 0);
        llOwnerSay("HTTP client " + VERSION);
    }

    on_rez(integer start_param)
    {
        llResetScript();
    }

    touch_start(integer num_detected)
    {
        string json = llList2Json(JSON_OBJECT,
            ["who", (string)llDetectedKey(0),
             "object", (string)llGetKey(),
             "version", VERSION]);
        apiPost(json);
    }

    http_response(key request_id, integer status, list metadata, string body)
    {
        if (request_id != gRequest) return;
        gRequest = NULL_KEY;
        dbg("status " + (string)status + ", free memory " + (string)llGetFreeMemory());
        if (status != 200)
        {
            llOwnerSay("API error " + (string)status + ": " + llGetSubString(body, 0, 199));
            return;
        }
        string message = llJsonGetValue(body, ["message"]);
        if (message == JSON_INVALID)
        {
            llOwnerSay("API answered something that is not the expected JSON.");
            return;
        }
        llOwnerSay("API says: " + message);
    }
}
