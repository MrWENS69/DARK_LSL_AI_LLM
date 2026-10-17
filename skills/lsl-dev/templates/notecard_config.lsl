// Notecard config v1.0 - reads "name = value" lines from a notecard into a strided list.
// Template: dataserver with request key check, EOF, reload on inventory change,
// accessors instead of arrays.
string VERSION = "1.0";
string CONFIG = "config";

key gQuery = NULL_KEY;
integer gLine = 0;
list gSettings;   // strided: name, value

string setting(string name, string fallback)
{
    integer i = llListFindList(gSettings, [name]);
    if (i < 0) return fallback;
    if (i % 2 != 0) return fallback;   // matched a value, not a name
    return llList2String(gSettings, i + 1);
}

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
        gQuery = NULL_KEY;
        llOwnerSay("No notecard named " + CONFIG);
    }
}

configLine(string data)
{
    string line = llStringTrim(data, STRING_TRIM);
    if (line == "") return;
    if (llGetSubString(line, 0, 0) == "#") return;
    integer eq = llSubStringIndex(line, "=");
    if (eq <= 0) return;
    string name = llStringTrim(llGetSubString(line, 0, eq - 1), STRING_TRIM);
    string value = llStringTrim(llGetSubString(line, eq + 1, -1), STRING_TRIM);
    gSettings += [name, value];
}

default
{
    state_entry()
    {
        llOwnerSay("Config reader " + VERSION);
        configRead();
    }

    on_rez(integer start_param)
    {
        llResetScript();
    }

    changed(integer changes)
    {
        if (changes & CHANGED_INVENTORY) configRead();
        if (changes & CHANGED_OWNER) llResetScript();
    }

    dataserver(key query, string data)
    {
        if (query != gQuery) return;
        if (data == EOF)
        {
            gQuery = NULL_KEY;
            llOwnerSay((string)(llGetListLength(gSettings) / 2) + " settings loaded, greeting is: "
                       + setting("greeting", "(none)"));
            return;
        }
        configLine(data);
        gLine = gLine + 1;
        gQuery = llGetNotecardLine(CONFIG, gLine);
    }
}
