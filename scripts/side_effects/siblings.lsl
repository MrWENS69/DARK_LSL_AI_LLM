// Checks for -s: a variable written in one argument, list element or vector
// component and used in another. LSL does not document the evaluation order
// of those siblings, so the result depends on the compiler.

integer gCount;

integer next()
{
    return ++gCount;
}

string pair(integer a, integer b)
{
    return (string)a + "," + (string)b;
}

default
{
    state_entry()
    {
        integer i = 0;
        integer j = 5;
        list data = [1, 2, 3];
        vector v;
        rotation r;
        string s;

        s = pair(i, i + 1);                                       // reads only: fine
        s = pair(i++, j);                                         // written in one, j in the other: fine
        v = <i, i, i>;                                            // reads only: fine
        data = [next(), next()];                                  // calls, no direct write: fine (W20024 territory)
        s = pair(i++, i);                                         // $[E20025] i written in one argument, read in another
        s = pair(i, (i = 2));                                     // $[E20025] assignment in one argument
        data = [i++, i];                                          // $[E20025] list elements
        data = [j, j += 1, 0];                                    // $[E20025] compound assignment
        v = <i++, i, 0.0>;                                        // $[E20025] vector components
        r = <0.0, 0.0, (float)j, j-->;                            // $[E20025] rotation components
        s = pair(llList2Integer(data, i++), llList2Integer(data, i)); // $[E20025] nested inside the arguments
        s = pair(i++, 0) + pair(i, 0);                            // operands of +, not siblings: fine
        if (i == 0 && (j = 1)) s = "";                            // $[E20024] the first rule still applies
    }
}
