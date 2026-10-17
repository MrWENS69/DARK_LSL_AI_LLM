// Checks for -s: side effects in && / || operands.
// LSL never short-circuits: both operands are always evaluated, right one first.

integer gCount;

integer bump() {
    gCount++;
    return TRUE;
}

default
{
    state_entry()
    {
        integer a = 1;
        integer b = 2;
        key req = NULL_KEY;

        if (a == 1 && b == 2) a = 3;                              // pure operands: fine
        if (a == 1 && llAbs(b) == 2) a = 3;                       // pure builtin: fine
        if (a == 1 && llGetListLength([]) == 0) a = 3;            // pure getter: fine
        if (a == 1 || llList2Integer([1], 0) == 1) a = 3;         // pure list access: fine

        if (req == NULL_KEY && bump()) a = 4;                     // $[E20024] user function call on the right
        if (bump() || a == 1) a = 5;                              // $[E20024] user function call on the left
        if (a == 1 && (b = 3)) a = 6;                             // $[E20024] assignment
        if (a == 1 && b++) a = 7;                                 // $[E20024] increment
        if (b != 0 && a / b > 1) a = 8;                           // $[E20024] division is not guarded
        if (b != 0 || a % b == 1) a = 8;                          // $[E20024] modulo is not guarded
        if (a == 1 && b / 2 == 1) a = 8;                          // literal divisor: fine
        if (a == 1 && llGetNotecardLine("cfg", 0) != NULL_KEY) a = 9; // $[E20024] llGet* that sends a request
        if (a == 1 && llListen(5, "", NULL_KEY, "")) a = 9;       // $[E20024] builtin with side effect
        if (a == 1 && (b == 2 || bump())) a = 10;                 // $[E20024] nested on the right of ||
    }
}
