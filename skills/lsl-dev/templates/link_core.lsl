// Link protocol, core v1.0 - owns the state, answers commands from other scripts.
// Pair with link_menu.lsl in the same object. Protocol:
//   num 100  menu -> core   str = "open" | "close" | "status", id = user
//   num 200  core -> menu   str = text to show the user, id = user
string VERSION = "1.0";
integer MSG_COMMAND = 100;
integer MSG_STATUS = 200;

integer gOpen;

string statusText()
{
    if (gOpen) return "The door is open";
    return "The door is closed";
}

default
{
    state_entry()
    {
        gOpen = FALSE;
        llOwnerSay("Core " + VERSION);
    }

    on_rez(integer start_param)
    {
        llResetScript();
    }

    link_message(integer sender, integer num, string str, key id)
    {
        if (num != MSG_COMMAND) return;
        if (str == "open") gOpen = TRUE;
        else if (str == "close") gOpen = FALSE;
        else if (str != "status")
        {
            llMessageLinked(LINK_SET, MSG_STATUS, "Unknown command " + str, id);
            return;
        }
        llMessageLinked(LINK_SET, MSG_STATUS, statusText(), id);
    }
}
