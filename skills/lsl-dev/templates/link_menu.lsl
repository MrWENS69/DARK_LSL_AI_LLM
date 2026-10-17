// Link protocol, menu v1.0 - shows a dialog and forwards the choice to link_core.lsl.
// Protocol (same numbers as in link_core.lsl):
//   num 100  menu -> core   str = "open" | "close" | "status", id = user
//   num 200  core -> menu   str = text to show the user, id = user
string VERSION = "1.0";
integer MSG_COMMAND = 100;
integer MSG_STATUS = 200;

integer gChannel;
integer gHandle = 0;
key gUser = NULL_KEY;

menuClose()
{
    if (gHandle) llListenRemove(gHandle);
    gHandle = 0;
    gUser = NULL_KEY;
    llSetTimerEvent(0.0);
}

menuOpen(key user)
{
    menuClose();
    gChannel = -2000000 - (integer)llFrand(1000000.0);
    gHandle = llListen(gChannel, "", user, "");
    gUser = user;
    llDialog(user, "Door control " + VERSION, ["open", "close", "status"], gChannel);
    llSetTimerEvent(60.0);
}

default
{
    state_entry()
    {
        llOwnerSay("Menu " + VERSION);
    }

    on_rez(integer start_param)
    {
        llResetScript();
    }

    touch_start(integer num_detected)
    {
        menuOpen(llDetectedKey(0));
    }

    listen(integer channel, string name, key id, string message)
    {
        if (channel != gChannel) return;
        if (id != gUser) return;
        menuClose();
        llMessageLinked(LINK_SET, MSG_COMMAND, message, id);
    }

    timer()
    {
        menuClose();
    }

    link_message(integer sender, integer num, string str, key id)
    {
        if (num != MSG_STATUS) return;
        llRegionSayTo(id, 0, str);
    }
}
