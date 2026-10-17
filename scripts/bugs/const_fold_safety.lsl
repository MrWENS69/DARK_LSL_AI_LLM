// Constant folding must neither crash nor invent diagnostics.
default
{
    state_entry()
    {
        // a never-assigned local is the constant 0: folding total / count used to divide by zero
        integer total;
        integer count;
        integer avg = total / count;
        integer rem = total % count;
        integer big = -2147483647 - 1;
        integer neg = big / -1;
        integer wrap = big % -1;
        // builtin integer constants are integers, not floats: "1" == "1" is always true,
        // it used to fold to "1.000000" == "1" and be reported as always false
        if ((string)TRUE == "1") llOwnerSay("TRUE prints as 1");                    // $[E20011]
        if ((string)CHANGED_OWNER == "128") llOwnerSay("CHANGED_OWNER prints as 128"); // $[E20011]
        llOwnerSay((string)avg + (string)rem + (string)neg + (string)wrap);
    }
}
