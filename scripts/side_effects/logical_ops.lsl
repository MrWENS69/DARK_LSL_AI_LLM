// Checks for -s: operands of && / || that act or can fail.
// LSL never short-circuits: both operands are always evaluated, right one first.

integer gCount;

integer bump()
{
    gCount++;
    return TRUE;
}

default
{
    state_entry()
    {
        integer a = 1;
        integer b = 2;
        integer z;
        vector v1 = <1.0, 0.0, 0.0>;
        vector v2 = <0.0, 1.0, 0.0>;
        key req = NULL_KEY;

        if (a == 1 && b == 2) a = 3;                              // pure operands: fine
        if (a == 1 && llAbs(b) == 2) a = 3;                       // pure builtin: fine
        if (a == 1 && llGetListLength([]) == 0) a = 3;            // pure getter: fine
        if (a == 1 || llList2Integer([1], 0) == 1) a = 3;         // pure list access: fine
        if (a == 1 && llAvatarOnSitTarget() == NULL_KEY) a = 3;   // pure, not covered by a prefix: fine
        if (a == 1 && (v1 % v2) == ZERO_VECTOR) a = 3;            // vector cross product: fine
        if (a == 1 && b / 2 == 1) a = 3;                          // non-zero literal divisor: fine

        if (req == NULL_KEY && bump()) a = 4;                     // $[E20024] user function call on the right
        if (bump() || a == 1) a = 5;                              // $[E20024] user function call on the left
        if (a == 1 && (b = 3)) a = 6;                             // $[E20024] assignment
        if (a == 1 && b++) a = 7;                                 // $[E20024] increment
        if (b != 0 && a / b > 1) a = 8;                           // $[E20024] division by a variable
        if (b != 0 || a % b == 1) a = 8;                          // $[E20024] modulo by a variable
        if (a == 1 && a / z > 0) a = 8;                           // $[E20024] division by a constant zero
        if (a == 1 && llGetNotecardLine("cfg", 0) != NULL_KEY) a = 9; // $[E20024] llGet* that sends a request
        if (a == 1 && llListen(5, "", NULL_KEY, "")) a = 9;       // $[E20024] builtin with side effect
        if (a == 1 && (b == 2 || bump())) a = 10;                 // $[E20024] nested on the right of ||
        if (a == 1 && b == 2 && bump()) a = 11;                   // $[E20024] chained &&
        if (!(bump() && a == 1)) a = 12;                          // $[E20024] under a negation
        if (<bump(), 0, 0> == ZERO_VECTOR) a = 13;                // ok: not inside && or ||
        if (a == 1
            && bump()) a = 14;                                    // $[E20024] marker on the operand's line
    }
}
