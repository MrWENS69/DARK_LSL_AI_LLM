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
        vector p = <1.0, 2.0, 3.0>;

        s = pair(i, i + 1);                                       // reads only: fine
        s = pair(i++, j);                                         // written in one, j in the other: fine
        v = <i, i, i>;                                            // reads only: fine
        data = [next(), next()];                                  // $[E20025] $[E20025] next() writes gCount in both elements
        s = pair(next(), gCount);                                 // $[E20025] written through a call, read directly
        s = pair(llAbs(i), i);                                    // a builtin writes nothing: fine
        v = <p.x = 1.0, p.y, p.z>;                                // different components: fine
        v = <p.x = 1.0, p.x, 0.0>;                                // $[E20025] the same component twice
        data = [p.x = 1.0, p];                                    // $[E20025] a component and the whole vector
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
