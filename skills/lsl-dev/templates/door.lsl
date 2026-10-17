// Door v1.0 - opens on touch for the owner and group members, closes by itself.
// Template: skeleton, owner-change reset, single timer, debug output switched
// on by writing the word "debug" in the object description.
string VERSION = "1.0";
float OPEN_SECONDS = 8.0;
float OPEN_ANGLE = 90.0;

integer gDebug;
integer gOpen;
rotation gClosedRot;

dbg(string msg)
{
    if (gDebug) llOwnerSay("[door] " + msg);
}

doorSet(integer open)
{
    rotation delta = llEuler2Rot(<0.0, 0.0, OPEN_ANGLE * DEG_TO_RAD>);
    if (open)
    {
        llSetRot(gClosedRot * delta);
    }
    else
    {
        llSetRot(gClosedRot);
    }
    gOpen = open;
}

integer allowed(key who)
{
    if (who == llGetOwner()) return TRUE;
    return llSameGroup(who);
}

default
{
    state_entry()
    {
        gDebug = (llSubStringIndex(llGetObjectDesc(), "debug") >= 0);
        gClosedRot = llGetRot();
        gOpen = FALSE;
        llOwnerSay("Door " + VERSION + " ready");
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
        key who = llDetectedKey(0);
        if (!allowed(who))
        {
            llRegionSayTo(who, 0, "This door is for group members.");
            return;
        }
        if (gOpen)
        {
            llSetTimerEvent(0.0);
            doorSet(FALSE);
            dbg("closed by touch");
        }
        else
        {
            doorSet(TRUE);
            llSetTimerEvent(OPEN_SECONDS);
            dbg("opened");
        }
    }

    timer()
    {
        llSetTimerEvent(0.0);
        doorSet(FALSE);
        dbg("closed by timer");
    }
}
