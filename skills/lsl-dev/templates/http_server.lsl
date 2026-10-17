// HTTP-in server v1.0 - serves a small JSON API from an in-world object.
// Template: URL requested on every rez, region change and region restart,
// released when replaced, every request answered within the 25 s limit.
// Write "debug" in the object description for request logging.
string VERSION = "1.0";

integer gDebug;
key gUrlRequest = NULL_KEY;
string gUrl = "";
integer gHits = 0;

dbg(string msg)
{
    if (gDebug) llOwnerSay("[server] " + msg);
}

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
        gDebug = (llSubStringIndex(llGetObjectDesc(), "debug") >= 0);
        llOwnerSay("HTTP server " + VERSION);
        urlRequest();
    }

    on_rez(integer start_param)
    {
        urlRequest();
    }

    changed(integer changes)
    {
        if (changes & (CHANGED_REGION | CHANGED_REGION_START | CHANGED_TELEPORT)) urlRequest();
        if (changes & CHANGED_OWNER) llResetScript();
    }

    http_request(key id, string method, string body)
    {
        if (id == gUrlRequest)
        {
            if (method == URL_REQUEST_GRANTED)
            {
                gUrl = body;
                llOwnerSay("Serving at " + gUrl);
            }
            else
            {
                llOwnerSay("No URL available: " + body);
            }
            return;
        }
        gHits = gHits + 1;
        string path = llGetHTTPHeader(id, "x-path-info");
        dbg(method + " " + path + " (" + (string)llStringLength(body) + " bytes)");
        if (method == "GET")
        {
            llSetContentType(id, CONTENT_TYPE_JSON);
            llHTTPResponse(id, 200, llList2Json(JSON_OBJECT,
                ["version", VERSION,
                 "hits", gHits,
                 "region", llGetRegionName(),
                 "position", (string)llGetPos()]));
            return;
        }
        if (method == "POST")
        {
            string text = llJsonGetValue(body, ["say"]);
            if (text == JSON_INVALID)
            {
                llHTTPResponse(id, 400, "expected {\"say\": \"...\"}");
                return;
            }
            llSay(0, llGetSubString(text, 0, 255));
            llHTTPResponse(id, 200, "said");
            return;
        }
        llHTTPResponse(id, 405, "GET or POST");
    }
}
