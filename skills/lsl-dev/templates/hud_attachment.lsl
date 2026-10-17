// HUD v1.0 - attachment that asks for permissions, tracks its wearer and talks to the owner.
// Template: attach / detach handling, permission mask, owner change, wearer key cached.
string VERSION = "1.0";

key gWearer = NULL_KEY;
integer gPerms = 0;

hudStart(key wearer)
{
    gWearer = wearer;
    gPerms = 0;
    llRequestPermissions(wearer, PERMISSION_TAKE_CONTROLS | PERMISSION_TRIGGER_ANIMATION);
    llSetText("HUD " + VERSION, <1.0, 1.0, 1.0>, 1.0);
}

hudStop()
{
    if (gPerms & PERMISSION_TAKE_CONTROLS) llReleaseControls();
    gWearer = NULL_KEY;
    gPerms = 0;
    llSetText("", ZERO_VECTOR, 0.0);
}

default
{
    state_entry()
    {
        if (llGetAttached() != 0) hudStart(llGetOwner());
    }

    on_rez(integer start_param)
    {
        llResetScript();
    }

    attach(key id)
    {
        if (id == NULL_KEY)
        {
            hudStop();
        }
        else
        {
            hudStart(id);
        }
    }

    changed(integer changes)
    {
        if (changes & CHANGED_OWNER) llResetScript();
    }

    run_time_permissions(integer perm)
    {
        gPerms = perm;
        if (perm & PERMISSION_TAKE_CONTROLS)
        {
            llTakeControls(CONTROL_ML_LBUTTON, TRUE, TRUE);
        }
        if (!(perm & PERMISSION_TRIGGER_ANIMATION))
        {
            llOwnerSay("Animation permission refused, the HUD will not animate you.");
        }
    }

    control(key id, integer level, integer edge)
    {
        if (id != gWearer) return;
        if ((level & edge & CONTROL_ML_LBUTTON) != 0)
        {
            llOwnerSay("Mouselook click");
        }
    }

    touch_start(integer num_detected)
    {
        if (llDetectedKey(0) != gWearer) return;
        llOwnerSay("HUD " + VERSION + ", permissions " + (string)gPerms);
    }
}
