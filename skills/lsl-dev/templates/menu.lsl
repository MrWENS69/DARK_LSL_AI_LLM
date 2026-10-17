// Menu v1.0 - paged llDialog menu with one listener and a timeout.
// Template: random negative channel, listener removed on answer or timeout,
// "Next" / "Back" paging for more than 12 choices.
string VERSION = "1.0";
float MENU_TIMEOUT = 60.0;
integer PAGE_SIZE = 10;   // 12 buttons minus Next and Back

list gChoices = ["Red", "Green", "Blue", "Yellow", "Black", "White",
                 "Orange", "Purple", "Pink", "Grey", "Brown", "Cyan"];

integer gChannel;
integer gHandle = 0;
key gUser = NULL_KEY;
integer gPage = 0;

menuClose()
{
    if (gHandle) llListenRemove(gHandle);
    gHandle = 0;
    gUser = NULL_KEY;
    llSetTimerEvent(0.0);
}

menuShow(key user)
{
    integer total = llGetListLength(gChoices);
    integer first = gPage * PAGE_SIZE;
    integer last = first + PAGE_SIZE - 1;
    if (last > total - 1) last = total - 1;
    list buttons = llList2List(gChoices, first, last);
    if (total > PAGE_SIZE) buttons = ["Back", "Next"] + buttons;
    if (gHandle == 0)
    {
        gChannel = -1000000 - (integer)llFrand(1000000.0);
        gHandle = llListen(gChannel, "", user, "");
    }
    gUser = user;
    llDialog(user, "Pick a colour (" + VERSION + "):", buttons, gChannel);
    llSetTimerEvent(MENU_TIMEOUT);
}

default
{
    state_entry()
    {
        gPage = 0;
    }

    on_rez(integer start_param)
    {
        llResetScript();
    }

    touch_start(integer num_detected)
    {
        key who = llDetectedKey(0);
        if (gUser != NULL_KEY)
        {
            if (who != gUser)
            {
                llRegionSayTo(who, 0, "Someone else is using the menu, try again in a minute.");
                return;
            }
        }
        menuClose();
        gPage = 0;
        menuShow(who);
    }

    listen(integer channel, string name, key id, string message)
    {
        if (channel != gChannel) return;
        if (id != gUser) return;
        integer pages = (llGetListLength(gChoices) + PAGE_SIZE - 1) / PAGE_SIZE;
        if (message == "Next")
        {
            gPage = (gPage + 1) % pages;
            menuShow(id);
            return;
        }
        if (message == "Back")
        {
            gPage = (gPage + pages - 1) % pages;
            menuShow(id);
            return;
        }
        menuClose();
        if (llListFindList(gChoices, [message]) < 0) return;   // free text, not a button
        llRegionSayTo(id, 0, "You picked " + message);
    }

    timer()
    {
        if (gUser != NULL_KEY) llRegionSayTo(gUser, 0, "Menu closed.");
        menuClose();
    }
}
