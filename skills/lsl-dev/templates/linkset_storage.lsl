// Linkset storage v1.0 - persistent counters and settings in linkset data.
// Template: write with return code check, read with fallback, change event,
// survives script reset and script replacement.
string VERSION = "1.0";
string KEY_COUNT = "touch_count";
string KEY_LABEL = "label";

integer storeInt(string name, integer value)
{
    integer rc = llLinksetDataWrite(name, (string)value);
    if (rc == LINKSETDATA_EMEMORY) llOwnerSay("Linkset data is full");
    return rc;
}

integer loadInt(string name, integer fallback)
{
    string value = llLinksetDataRead(name);
    if (value == "") return fallback;
    return (integer)value;
}

string loadString(string name, string fallback)
{
    string value = llLinksetDataRead(name);
    if (value == "") return fallback;
    return value;
}

default
{
    state_entry()
    {
        llOwnerSay("Storage " + VERSION + ", " + (string)llLinksetDataAvailable() + " bytes free, "
                   + "label " + loadString(KEY_LABEL, "(none)") + ", touches so far "
                   + (string)loadInt(KEY_COUNT, 0));
    }

    touch_start(integer num_detected)
    {
        integer count = loadInt(KEY_COUNT, 0) + 1;
        storeInt(KEY_COUNT, count);
        llRegionSayTo(llDetectedKey(0), 0, "Touch number " + (string)count);
    }

    linkset_data(integer action, string name, string value)
    {
        if (action == LINKSETDATA_UPDATE)
        {
            if (name == KEY_LABEL) llOwnerSay("Label is now " + value);
        }
        else if (action == LINKSETDATA_RESET)
        {
            llOwnerSay("Storage was wiped");
        }
    }
}
