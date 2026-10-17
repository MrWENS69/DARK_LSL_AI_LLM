#!/usr/bin/env python3
"""Unit tests for lsltest: parser, LSL semantics, simulator. Run: python -m unittest -v test_lsltest"""

import unittest

from lsltest import LslTestCase, ScriptError, Simulator
from lsltest.parser import parse
from lsltest.values import Key, Vector, Rotation, NULL_KEY, to_string, cast, binary


def run_expr(expr, prelude=""):
    """Evaluate an LSL expression inside state_entry and return the owner-say text."""
    source = "%s\ndefault { state_entry() { llOwnerSay((string)(%s)); } }" % (prelude, expr)
    sim = Simulator()
    sim.load(source)
    sim.start()
    if sim.errors:
        raise sim.errors[0][1]
    return [c.text for c in sim.chat if c.kind == "ownersay"][-1]


class ParserTest(unittest.TestCase):
    def test_minimal_script(self):
        program = parse("default { state_entry() { } }")
        self.assertIn("default", program.states)
        self.assertIn("state_entry", program.states["default"].events)

    def test_vector_literal_versus_comparison(self):
        self.assertEqual(run_expr("<1.0, 2.0, 3.0> == <1.0, 2.0, 3.0>"), "1")
        self.assertEqual(run_expr("1 < 2"), "1")
        self.assertEqual(run_expr("<1, 2, 3> * <1, 2, 3>"), "14.000000")

    def test_assignment_inside_operand(self):
        self.assertEqual(run_expr("a + (a = 5)", "integer a = 1;"), "10")
        self.assertEqual(run_expr("0 < e = 3", "integer e;"), "1")

    def test_syntax_error_has_position(self):
        from lsltest import LslSyntaxError
        with self.assertRaises(LslSyntaxError) as ctx:
            parse("default { state_entry() { integer x = ; } }")
        self.assertEqual(ctx.exception.line, 1)


class SemanticsTest(unittest.TestCase):
    def test_integer_division_truncates(self):
        self.assertEqual(run_expr("7 / 2"), "3")
        self.assertEqual(run_expr("-7 / 2"), "-3")
        self.assertEqual(run_expr("7 / 2.0"), "3.500000")

    def test_modulo_keeps_the_sign_of_the_left_operand(self):
        self.assertEqual(run_expr("-7 % 3"), "-1")
        self.assertEqual(run_expr("7 % -3"), "1")

    def test_division_by_zero_is_a_math_error(self):
        with self.assertRaises(ScriptError) as ctx:
            run_expr("1 / z", "integer z;")
        self.assertEqual(ctx.exception.kind, "Math Error")

    def test_integer_wraps_at_32_bits(self):
        self.assertEqual(run_expr("2147483647 + 1"), "-2147483648")
        self.assertEqual(run_expr("0x7FFFFFFF"), "2147483647")

    def test_float_to_string_six_decimals(self):
        self.assertEqual(run_expr("1.0 / 3.0"), "0.333333")
        self.assertEqual(run_expr("(string)-PI"), "-3.141593")
        self.assertEqual(run_expr("(string)<1.0, 2.3, 4.56>"), "<1.00000, 2.30000, 4.56000>")

    def test_both_operands_evaluated_right_first(self):
        source = """
            integer order = 0;
            integer left() { order = order * 10 + 1; return 1; }
            integer right() { order = order * 10 + 2; return 1; }
            default { state_entry() { if (left() && right()) llOwnerSay((string)order); } }
        """
        sim = Simulator()
        sim.load(source)
        sim.start()
        self.assertEqual([c.text for c in sim.chat][-1], "21")

    def test_and_never_short_circuits(self):
        source = """
            integer calls = 0;
            integer bump() { calls++; return TRUE; }
            default { state_entry() { if (FALSE && bump()) ; llOwnerSay((string)calls); } }
        """
        sim = Simulator()
        sim.load(source)
        sim.start()
        self.assertEqual([c.text for c in sim.chat][-1], "1")

    def test_casts(self):
        self.assertEqual(run_expr('(integer)"0123"'), "123")
        self.assertEqual(run_expr('(integer)"0x12A"'), "298")
        self.assertEqual(run_expr('(integer)"105 degrees"'), "105")
        self.assertEqual(run_expr('(integer)"abc"'), "0")
        self.assertEqual(run_expr('(float)"6.2e1"'), "62.000000")
        self.assertEqual(run_expr('(string)[1, 2.3, "a"]'), "12.300000a")
        self.assertEqual(run_expr('(vector)"<1.0, 2.3>" == ZERO_VECTOR'), "1")
        self.assertEqual(run_expr('llGetListLength((list)"")'), "1")

    def test_key_truthiness(self):
        self.assertEqual(run_expr('(integer)(k != "")', 'key k = NULL_KEY;'), "1")
        source = """
            default { state_entry() {
                key k = NULL_KEY; if (k) llOwnerSay("null is true"); else llOwnerSay("null is false");
                key v = "12345678-1234-1234-1234-123456789abc"; if (v) llOwnerSay("valid is true");
                string s = NULL_KEY; if (s) llOwnerSay("string null is true");
            } }
        """
        sim = Simulator()
        sim.load(source)
        sim.start()
        texts = [c.text for c in sim.chat]
        self.assertEqual(texts, ["null is false", "valid is true", "string null is true"])

    def test_list_equality_compares_lengths(self):
        self.assertEqual(run_expr("[1, 2] == [3, 4]"), "1")
        self.assertEqual(run_expr("[1, 2] != [3]"), "1")

    def test_list_accessors_are_lenient(self):
        self.assertEqual(run_expr("llList2Integer([2.7], 0)"), "2")
        self.assertEqual(run_expr('llList2Integer(["abc"], 0)'), "0")
        self.assertEqual(run_expr("llList2String([1, 2], 5)"), "")
        self.assertEqual(run_expr('llList2List([0,1,2,3,4,5,6,7,8,9], 8, 1) == [0, 1, 8, 9]'), "1")
        self.assertEqual(run_expr('llListFindList([1, "1"], ["1"])'), "1")

    def test_lists_may_not_contain_lists(self):
        with self.assertRaises(ScriptError) as ctx:
            run_expr("llGetListLength([(list)1])")
        self.assertEqual(ctx.exception.kind, "Lists may not contain lists")

    def test_string_functions(self):
        self.assertEqual(run_expr('llGetSubString("hello", 1, 3)'), "ell")
        self.assertEqual(run_expr('llGetSubString("hello", 3, 1)'), "helo")   # [0..1] + [3..4], no wrap
        self.assertEqual(run_expr('llSubStringIndex("hello", "")'), "0")
        self.assertEqual(run_expr('llStringLength("héllo")'), "5")
        self.assertEqual(run_expr('llDumpList2String(["a", 1, 2.5], "|")'), "a|1|2.500000")
        self.assertEqual(run_expr('llGetListLength(llParseString2List("a,,b", [","], []))'), "2")
        self.assertEqual(run_expr('llGetListLength(llParseStringKeepNulls("a,,b", [","], []))'), "3")
        self.assertEqual(run_expr('llGetListLength(llCSV2List(""))'), "1")

    def test_json(self):
        self.assertEqual(run_expr('llJsonGetValue("{\\"a\\": {\\"b\\": 5}}", ["a", "b"])'), "5")
        self.assertEqual(run_expr('llJsonGetValue("{\\"a\\": 1}", ["z"]) == JSON_INVALID'), "1")
        self.assertEqual(run_expr('llJsonGetValue("not json", []) == JSON_INVALID'), "1")
        self.assertEqual(run_expr('llList2Json(JSON_OBJECT, ["a", 1, "b", "x"])'), '{"a":1,"b":"x"}')
        self.assertEqual(run_expr('llJsonValueType("[1]", [0]) == JSON_NUMBER'), "1")

    def test_vector_math(self):
        self.assertEqual(run_expr("llVecMag(<3.0, 4.0, 0.0>)"), "5.000000")
        self.assertEqual(run_expr("(<1,0,0> % <0,1,0>) == <0,0,1>"), "1")
        self.assertEqual(run_expr("v.z", "vector v = <1, 2, 3>;"), "3.000000")

    def test_member_assignment(self):
        source = "default { state_entry() { vector v = <1, 2, 3>; v.x = 9.0; llOwnerSay((string)v); } }"
        sim = Simulator()
        sim.load(source)
        sim.start()
        self.assertEqual(sim.chat[-1].text, "<9.00000, 2.00000, 3.00000>")

    def test_jump_and_labels(self):
        source = """
            default { state_entry() {
                integer i = 0;
                @again;
                i++;
                if (i < 3) jump again;
                llOwnerSay((string)i);
            } }
        """
        sim = Simulator()
        sim.load(source)
        sim.start()
        self.assertEqual(sim.chat[-1].text, "3")

    def test_for_while_do(self):
        source = """
            default { state_entry() {
                integer i; integer total = 0;
                for (i = 0; i < 4; i++) total += i;
                while (i > 0) { i--; total += 1; }
                do { total += 100; } while (FALSE);
                llOwnerSay((string)total);
            } }
        """
        sim = Simulator()
        sim.load(source)
        sim.start()
        self.assertEqual(sim.chat[-1].text, "110")


class SimulatorTest(LslTestCase):
    def test_state_change_runs_exit_and_entry_and_releases_listens(self):
        self.load("""
            default {
                state_entry() { llListen(5, "", NULL_KEY, ""); llOwnerSay("enter default"); state two; }
                state_exit() { llOwnerSay("exit default"); }
            }
            state two {
                state_entry() { llOwnerSay("enter two"); }
            }
        """)
        self.sim.start()
        self.assertEqual([c.text for c in self.sim.chat], ["enter default", "exit default", "enter two"])
        self.assertNoListens()
        self.assertNoErrors()

    def test_timer_fires_on_tick(self):
        script = self.load("""
            integer ticks;
            default {
                state_entry() { llSetTimerEvent(2.0); }
                timer() { ticks++; if (ticks == 3) llSetTimerEvent(0.0); }
            }
        """)
        self.sim.start()
        self.sim.tick(10.0)
        self.assertGlobal(script, "ticks", 3)

    def test_listen_and_dialog_round_trip(self):
        self.load("""
            integer gChan = -77;
            default {
                touch_start(integer n) { llListen(gChan, "", llDetectedKey(0), ""); llDialog(llDetectedKey(0), "Pick", ["A", "B"], gChan); }
                listen(integer c, string n, key id, string m) { llOwnerSay("picked " + m); }
            }
        """)
        self.sim.start()
        self.sim.touch()
        dialog = self.assertDialog(buttons=["A", "B"])
        self.assertEqual(dialog.channel, -77)
        self.sim.dialog_reply(self.sim.owner, "B")
        self.assertOwnerSaid("picked B")

    def test_event_queue_drops_beyond_64(self):
        script = self.load("default { state_entry() { } link_message(integer s, integer n, string t, key k) { } }")
        for i in range(70):
            script.post("link_message", [1, i, "", NULL_KEY])
        self.assertEqual(len(script.queue), 64)
        self.assertEqual(script.dropped_events, 6)

    def test_too_many_listens(self):
        self.load("""
            default { state_entry() { integer i; for (i = 0; i < 70; i++) llListen(i + 1, "", NULL_KEY, ""); } }
        """)
        self.sim.start()
        self.assertError("Too Many Listens")

    def test_notecard_dataserver(self):
        self.load("""
            key q; integer n;
            default {
                state_entry() { q = llGetNotecardLine("cfg", 0); }
                dataserver(key id, string data) {
                    if (id != q) return;
                    if (data == EOF) { llOwnerSay("lines " + (string)n); return; }
                    n++; q = llGetNotecardLine("cfg", n);
                }
            }
        """)
        self.sim.notecard("cfg", "a = 1\nb = 2\n# comment")
        self.sim.start()
        self.assertOwnerSaid("lines 3")

    def test_http_out_and_response(self):
        self.load("""
            key req;
            default {
                state_entry() { req = llHTTPRequest("https://example.invalid/x", [HTTP_METHOD, "POST"], "{}"); }
                http_response(key id, integer status, list meta, string body) {
                    if (id != req) return;
                    llOwnerSay((string)status + " " + llJsonGetValue(body, ["ok"]));
                }
            }
        """)
        self.sim.start()
        request = self.assertHttpOut(url_contains="example.invalid", method="POST")
        self.assertEqual(request.body, "{}")
        self.sim.http_respond(200, '{"ok": "yes"}')
        self.assertOwnerSaid("200 yes")

    def test_http_in(self):
        self.load("""
            string url;
            default {
                state_entry() { llRequestURL(); }
                http_request(key id, string method, string body) {
                    if (method == URL_REQUEST_GRANTED) { url = body; llOwnerSay("url " + url); return; }
                    llSetContentType(id, CONTENT_TYPE_JSON);
                    llHTTPResponse(id, 200, "hello " + method + " " + llGetHTTPHeader(id, "x-path-info"));
                }
            }
        """)
        self.sim.start()
        url = list(self.sim.http_in)[0]
        status, body, ctype = self.sim.http_in_request(url + "/path?q=1", "POST", "data")
        self.assertEqual((status, body, ctype), (200, "hello POST /path", "application/json"))

    def test_link_messages_between_scripts(self):
        self.load('default { link_message(integer s, integer n, string t, key k) { if (n == 100) llMessageLinked(LINK_SET, 200, "pong " + t, k); } }', name="core")
        self.load('default { touch_start(integer n) { llMessageLinked(LINK_SET, 100, "ping", llDetectedKey(0)); } link_message(integer s, integer n, string t, key k) { if (n == 200) llOwnerSay(t); } }', name="menu")
        self.sim.start()
        self.sim.touch()
        self.assertLinkMessage(num=200, str_contains="pong ping")
        self.assertOwnerSaid("pong ping")

    def test_permissions_policy(self):
        self.load("""
            default {
                attach(key id) { if (id != NULL_KEY) llRequestPermissions(id, PERMISSION_TAKE_CONTROLS); }
                run_time_permissions(integer perm) { llOwnerSay("perm " + (string)perm); }
            }
        """)
        self.sim.start()
        self.sim.permission_policy = False
        self.sim.attach()
        self.assertOwnerSaid("perm 0")

    def test_linkset_data_persists_across_reset(self):
        script = self.load("""
            default {
                state_entry() { integer n = (integer)llLinksetDataRead("n") + 1; llLinksetDataWrite("n", (string)n); llOwnerSay("n=" + (string)n); }
            }
        """)
        self.sim.start()
        self.sim.reset(script)
        self.assertOwnerSaid("n=2")

    def test_unmodelled_builtin_is_recorded(self):
        self.load('default { state_entry() { llSetColor(<1,0,0>, ALL_SIDES); } }')
        self.sim.start()
        self.assertCalled("llSetColor")
        self.assertNoErrors()

    def test_reset_script_restarts_in_default(self):
        self.load("""
            integer n;
            default {
                state_entry() { n++; llOwnerSay("start " + (string)n); }
                touch_start(integer k) { n = 50; llResetScript(); llOwnerSay("never printed"); }
            }
        """)
        self.sim.start()
        self.sim.touch()
        self.assertEqual([c.text for c in self.sim.chat], ["start 1", "start 1"])

    def test_chat_assertions_ignore_the_test_own_input(self):
        self.load("""
            default {
                state_entry() { llListen(0, "", NULL_KEY, ""); }
                listen(integer c, string n, key id, string m) { llOwnerSay("heard " + m); }
            }
        """)
        self.sim.start()
        self.sim.say(self.sim.owner, 0, "hello")
        self.assertOwnerSaid("heard hello")
        self.assertNotSaid("hello")                 # the avatar said it, no script did
        with self.assertRaises(AssertionError):
            self.assertSaid("hello")
        with self.assertRaises(AssertionError):
            self.assertSaid("heard hello")          # llOwnerSay is not public chat

    def test_recursion_dies_with_stack_heap_collision(self):
        self.load("""
            integer down(integer n) { return down(n + 1); }
            default { state_entry() { llOwnerSay((string)down(0)); } }
        """)
        self.sim.start()
        self.assertError("Stack-Heap Collision")
        self.load("""
            integer depth(integer n) { if (n == 0) return 0; return 1 + depth(n - 1); }
            default { state_entry() { llOwnerSay((string)depth(100)); } }
        """, name="shallow")
        self.sim.errors = []
        self.sim.start()
        self.assertOwnerSaid("100", exact=True)

    def test_values_cannot_grow_without_bound(self):
        self.load("""
            string s = "x";
            default { state_entry() { integer i; for (i = 0; i < 40; i++) s += s; llOwnerSay("done"); } }
        """)
        self.sim.start()
        self.assertError("Stack-Heap Collision")

    def test_timers_are_rounded_up_to_a_frame_and_runaway_ticks_are_refused(self):
        script = self.load("""
            integer n;
            default { state_entry() { llSetTimerEvent(0.000001); } timer() { n++; } }
        """)
        self.sim.start()
        self.sim.tick(1.0)
        self.assertLess(script.globals["n"], 50)
        with self.assertRaises(RuntimeError):
            self.sim.tick(5000.0)

    def test_linkset_find_keys_refuses_catastrophic_patterns(self):
        self.load("""
            default { state_entry() {
                llLinksetDataWrite("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa!", "1");
                llOwnerSay((string)llLinksetDataCountFound("^(a+)+$"));
                llOwnerSay((string)llLinksetDataCountFound("^a+!$"));
            } }
        """)
        self.sim.start()
        self.assertEqual(self._lines(kinds=("ownersay",)), ["0", "1"])

    def test_missing_script_file_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            self.load("no_such_file.lsl")

    def test_deeply_nested_expression_is_a_syntax_error_not_a_crash(self):
        from lsltest import LslSyntaxError
        source = "default { state_entry() { integer x = %s1%s; } }" % ("(" * 20000, ")" * 20000)
        with self.assertRaises(LslSyntaxError):
            parse(source)

    def test_every_handler_and_pure_builtin_names_a_real_builtin(self):
        import inspect
        from lsltest import pure
        from lsltest.signatures import SIGNATURES
        handlers = [n for n, _ in inspect.getmembers(Simulator, inspect.isfunction) if n.startswith("ll_")]
        self.assertTrue(handlers)
        self.assertEqual([n for n in handlers if "ll" + n[3:] not in SIGNATURES], [])
        self.assertEqual([n for n in pure.PURE if n not in SIGNATURES], [])

    def test_constants_come_from_builtins_txt(self):
        self.assertEqual(run_expr("EOF == \"\\n\\n\\n\""), "1")
        self.assertEqual(run_expr("JSON_INVALID"), "\ufdd0")
        self.assertIs(self.sim.constants, __import__("lsltest.signatures", fromlist=["CONSTANTS"]).CONSTANTS)


class CliTest(unittest.TestCase):
    def test_exit_codes(self):
        import io
        import os
        import tempfile
        from contextlib import redirect_stderr, redirect_stdout
        from lsltest.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            bad = os.path.join(folder, "bad.lsl")
            with open(bad, "w") as handle:
                handle.write("default { state_entry() { integer x = ; } }")
            good = os.path.join(folder, "good.lsl")
            with open(good, "w") as handle:
                handle.write("default { state_entry() { llOwnerSay(\"\\x1b[31mred\"); } }")
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(main([os.path.join(folder, "missing.lsl")]), 2)
                self.assertEqual(main([bad]), 2)
                self.assertEqual(main([folder]), 1)            # no test_*.py there
                self.assertEqual(main([good]), 0)
            self.assertNotIn("\x1b", out.getvalue())           # control characters are escaped


if __name__ == "__main__":
    unittest.main()
