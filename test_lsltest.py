#!/usr/bin/env python3
"""Unit tests for lsltest: parser, LSL semantics, simulator. Run: python -m unittest -v test_lsltest"""

import unittest

from lsltest import LslSyntaxError, LslTestCase, ScriptError, Simulator, UnsupportedError
from lsltest.parser import parse
from lsltest.signatures import CONSTANTS
from lsltest.values import NULL_KEY, Vector


def run_script(source, **kwargs):
    """Load one script in a fresh simulator, run state_entry, return the simulator."""
    sim = Simulator(**kwargs)
    sim.load(source)
    sim.start()
    return sim


def owner_heard(sim):
    return [c.text for c in sim.chat if c.kind == "ownersay"]


def run_expr(expr, prelude=""):
    """Evaluate an LSL expression inside state_entry and return the owner-say text."""
    sim = run_script("%s\ndefault { state_entry() { llOwnerSay((string)(%s)); } }" % (prelude, expr))
    if sim.errors:
        raise sim.errors[0][1]
    return owner_heard(sim)[-1]


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

    def test_missing_script_file_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            self.load("no_such_file.lsl")

    def test_deeply_nested_expression_is_a_syntax_error_not_a_crash(self):
        parse("default { state_entry() { integer x = %s1%s; } }" % ("(" * 118, ")" * 118))
        parse("default { state_entry() { %s %s } }" % ("{" * 119, "}" * 119))
        for depth in (119, 200, 20000):
            with self.assertRaises(LslSyntaxError):
                parse("default { state_entry() { integer x = %s1%s; } }" % ("(" * depth, ")" * depth))
        with self.assertRaises(LslSyntaxError):
            parse("default { state_entry() { %s %s } }" % ("{" * 120, "}" * 120))

    def test_nested_vector_literals_parse_in_linear_time(self):
        import time
        source = "default { state_entry() { rotation r = %s1%s; } }" % ("<0, 0, 0, " * 14, " >" * 14)
        started = time.perf_counter()
        parse(source)
        self.assertLess(time.perf_counter() - started, 2.0)

    def test_bundled_builtins_match_the_root_file(self):
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "builtins.txt"), "rb") as root, \
                open(os.path.join(here, "lsltest", "data", "builtins.txt"), "rb") as bundled:
            self.assertEqual(root.read(), bundled.read())

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
        self.assertIs(self.sim.constants, CONSTANTS)


class GridBehaviourTest(LslTestCase):
    """Behaviours checked against the wiki or against the grid's own rules (round 3 of the reviews)."""

    def test_rotation_composition_is_associative_and_euler_round_trips(self):
        sim = run_script("""
            default { state_entry() {
                rotation rx = llEuler2Rot(<90.0, 0.0, 0.0> * DEG_TO_RAD);
                rotation rz = llEuler2Rot(<0.0, 0.0, 90.0> * DEG_TO_RAD);
                llOwnerSay((string)(<1.0, 0.0, 0.0> * rx * rz));
                llOwnerSay((string)(<1.0, 0.0, 0.0> * (rx * rz)));
                llOwnerSay((string)(llRot2Euler(llEuler2Rot(<30.0, 0.0, 60.0> * DEG_TO_RAD)) * RAD_TO_DEG));
                llOwnerSay((string)(<0.0, 0.0, 1.0> * llRotBetween(<0.0, 0.0, 1.0>, <0.0, 0.0, -1.0>)));
            } }""")
        heard = owner_heard(sim)
        self.assertEqual(heard[0], heard[1])
        self.assertEqual(heard[2], "<30.00000, -0.00000, 60.00000>")
        self.assertEqual(heard[3], "<0.00000, 0.00000, -1.00000>")

    def test_mixed_integer_and_float_go_through_single_precision(self):
        self.assertEqual(run_expr("f == big", "integer big = 16777217; float f = big;"), "1")
        self.assertEqual(run_expr("1700000030 - start", "float start = 1700000000;"), "0.000000")

    def test_link_messages_are_delivered_by_prim(self):
        self.load("""default {
            state_entry() {
                llMessageLinked(LINK_ALL_OTHERS, 1, "others", "");
                llMessageLinked(LINK_THIS, 2, "this", "");
                llMessageLinked(llGetLinkNumber(), 3, "self", "");
            }
            link_message(integer s, integer n, string t, key k) { llOwnerSay("core " + (string)s + " " + t); } }""", name="core")
        self.load('default { link_message(integer s, integer n, string t, key k) { llOwnerSay("menu " + (string)s + " " + t); } }', name="menu")
        self.sim.start()
        self.assertEqual(sorted(owner_heard(self.sim)), ["core 0 self", "core 0 this", "menu 0 self", "menu 0 this"])
        message = self.assertLinkMessage(num=2)
        self.assertEqual((message.script.name, message.sender, message.str), ("core", 0, "this"))

    def test_http_response_is_cut_at_body_maxlength_and_reaches_every_script(self):
        self.load("""default {
            state_entry() { llHTTPRequest("http://example.invalid/", [HTTP_CUSTOM_HEADER, "X-A", "b", HTTP_METHOD, "POST"], ""); }
            http_response(key r, integer st, list m, string b) { llOwnerSay("core " + (string)llStringLength(b) + " " + llList2CSV(m)); } }""", name="core")
        self.load('default { http_response(key r, integer st, list m, string b) { llOwnerSay("api " + (string)st); } }', name="api")
        self.sim.start()
        self.assertEqual(self.assertHttpOut().method, "POST")
        self.sim.http_respond(200, "x" * 3000)
        self.assertOwnerSaid("core 2048 %d, 2048" % CONSTANTS["HTTP_BODY_TRUNCATED"], exact=True)
        self.assertOwnerSaid("api 200", exact=True)

    def test_content_type_through_a_custom_header_is_a_runtime_error(self):
        run = run_script('default { state_entry() { llHTTPRequest("http://example.invalid/", [HTTP_CUSTOM_HEADER, "Content-Type", "text/plain"], ""); } }')
        self.assertEqual([e.kind for _, e in run.errors], ["Script run-time error"])
        self.assertIn("HTTP_MIMETYPE", run.errors[0][1].detail)

    def test_memory_limit_kills_the_script(self):
        sim = run_script("list l; default { state_entry() { integer i; for (i = 0; i < 700; i++) l += [llGenerateKey()]; } }")
        self.assertEqual([e.kind for _, e in sim.errors], ["Stack-Heap Collision"])

    def test_sleep_inside_a_timer_neither_hangs_nor_turns_the_clock_back(self):
        sim = run_script("default { state_entry() { llSetTimerEvent(1.0); } timer() { llSleep(1.0); llOwnerSay((string)llGetTime()); } }")
        sim.tick(3.0)
        self.assertEqual(owner_heard(sim), ["2.000000", "3.000000", "4.000000"])
        self.assertEqual(sim.time, 4.0)

    def test_error_in_state_exit_kills_the_script_and_names_the_line(self):
        script = self.load("integer z;\ndefault { touch_start(integer n) { state two; }\n state_exit() { integer x = 1 / z; } }\nstate two { state_entry() { } }")
        self.sim.start()
        self.sim.touch()
        err = self.assertError("Math Error", script)
        self.assertEqual(err.line, 3)
        self.assertTrue(script.dead)

    def test_touch_end_runs_after_the_state_change_of_touch_start(self):
        self.load('default { touch_start(integer n) { state armed; } } state armed { touch_end(integer n) { llSay(0, "BOOM"); state default; } }')
        self.sim.start()
        self.sim.touch()
        self.assertSaid("BOOM")

    def test_permissions_arrive_with_the_event_not_inside_the_call(self):
        sim = run_script("""default {
            state_entry() { llRequestPermissions(llGetOwner(), PERMISSION_DEBIT); llOwnerSay("now " + (string)llGetPermissions()); }
            run_time_permissions(integer p) { llOwnerSay("later " + (string)p); } }""")
        self.assertEqual(owner_heard(sim), ["now 0", "later %d" % CONSTANTS["PERMISSION_DEBIT"]])

    def test_json_output_uses_six_decimals(self):
        self.assertEqual(run_expr('llList2Json(JSON_ARRAY, [1.5, 2, "a", "7"])'), '[1.500000,2,"a","7"]')
        self.assertEqual(run_expr('llJsonSetValue("[]", [JSON_APPEND], "0.25")'), "[0.25]")
        self.assertEqual(run_expr('llJsonSetValue("[9]", [0], "10")'), "[10]")

    def test_urls_die_on_rez_and_on_region_restart(self):
        script = self.load('default { state_entry() { llRequestURL(); } http_request(key id, string method, string body) { if (method == URL_REQUEST_GRANTED) llOwnerSay(body); } }')
        self.sim.start()
        url = owner_heard(self.sim)[0]
        self.assertEqual(self.sim.http_in_request(url, "GET")[0], 500)        # reachable: the script just does not answer GET
        self.sim.on_rez(0)
        self.assertEqual(self.sim.http_in_request(url, "GET")[0], 404)
        self.assertEqual(script.urls, set())

    def test_notecard_sync_read_needs_the_cache(self):
        self.sim.notecard("cfg", "line0")
        self.load("""default {
            state_entry() { if (llGetNotecardLineSync("cfg", 0) == NAK) llOwnerSay("nak"); llGetNotecardLine("cfg", 0); }
            dataserver(key q, string d) { llOwnerSay(d + " " + llGetNotecardLineSync("cfg", 0)); } }""")
        self.sim.start()
        self.assertEqual(owner_heard(self.sim), ["nak", "line0 line0"])
        cached = Simulator()
        cached.notecard("cfg2", "x", cached=True)
        cached.load('default { state_entry() { llOwnerSay(llGetNotecardLineSync("cfg2", 0)); } }')
        cached.start()
        self.assertEqual(owner_heard(cached), ["x"])

    def test_sensor_results_are_nearest_first(self):
        self.sim.avatar("Far Away").pos = Vector(138.0, 128.0, 25.0)
        self.sim.avatar("Near By").pos = Vector(130.0, 128.0, 25.0)
        self.sim.owner.pos = Vector(178.0, 128.0, 25.0)
        self.load('default { state_entry() { llSensor("", NULL_KEY, AGENT, 96.0, PI); } sensor(integer n) { llOwnerSay(llDetectedName(0) + "," + llDetectedName(2)); } }')
        self.sim.start()
        self.assertOwnerSaid("Near By,Test Owner", exact=True)

    def test_vector_literal_components_accept_any_expression_before_the_last(self):
        self.assertEqual(run_expr("<flags & 1, 1 < 2, 3>", "integer flags = 3;"), "<1.00000, 1.00000, 3.00000>")

    def test_same_listen_again_returns_the_handle_even_at_the_limit(self):
        sim = run_script("""default { state_entry() {
            integer i; for (i = 1; i <= 65; i++) llListen(i, "", NULL_KEY, "");
            llOwnerSay((string)llListen(5, "", NULL_KEY, ""));
        } }""")
        self.assertEqual(owner_heard(sim), ["5"])
        self.assertEqual(sim.errors, [])

    def test_return_with_a_value_in_an_event_handler_is_an_error(self):
        sim = run_script("default { state_entry() { return 1; } }")
        self.assertIn("event handler", sim.errors[0][1].detail)

    def test_dialog_errors_are_debug_shouts_and_the_script_goes_on(self):
        sim = run_script("""default { state_entry() {
            llDialog(llGetOwner(), "", ["OK"], 5);
            llDialog(llGetOwner(), "x", ["a","b","c","d","e","f","g","h","i","j","k","l","m"], 5);
            llDialog(llGetOwner(), "x", ["a very long button label indeed"], 5);
            llOwnerSay("alive");
        } }""")
        debug = [c.text for c in sim.chat if c.kind == "debug"]
        self.assertEqual(len(debug), 3)
        self.assertTrue(all(line.startswith("llDialog:") for line in debug))
        self.assertEqual(sim.dialogs, [])
        self.assertEqual(owner_heard(sim), ["alive"])

    def test_scripts_posting_to_each_other_forever_are_caught(self):
        with self.assertRaises(RuntimeError):
            run_script('default { state_entry() { llMessageLinked(LINK_THIS, 0, "", NULL_KEY); } link_message(integer s, integer n, string t, key k) { llMessageLinked(LINK_THIS, 0, "", NULL_KEY); } }')
        with self.assertRaises(RuntimeError):
            run_script("default { state_entry() { llResetScript(); } }")

    def test_strict_mode(self):
        sim = run_script('default { state_entry() { llTakeControls(CONTROL_FWD, TRUE, TRUE); llOwnerSay("ok"); } }', strict=True)
        self.assertEqual(owner_heard(sim), ["ok"])
        with self.assertRaises(UnsupportedError):
            run_script("default { state_entry() { llSetColor(<1.0, 1.0, 1.0>, ALL_SIDES); } }", strict=True)

    def test_http_handler_answers_during_the_run(self):
        self.sim.http_handler = lambda request: (200, "pong " + request.url)
        self.load('default { state_entry() { llHTTPRequest("http://example.invalid/x", [], ""); } http_response(key r, integer s, list m, string b) { llOwnerSay(b); } }')
        self.sim.start()
        self.assertOwnerSaid("pong http://example.invalid/x", exact=True)

    def test_owner_and_targeted_chat_assertions(self):
        other = self.sim.avatar("Other Resident")
        self.load('default { state_entry() { llInstantMessage("%s", "psst"); llSay(7, "seven"); } }' % other.key)
        self.sim.start()
        self.assertSaidTo(other, "psst")
        self.assertNotOwnerSaid("psst")
        self.assertSaid("seven", channel=None)
        self.assertNotSaid("seven")                  # channel 0 by default
        with self.assertRaises(AssertionError):
            self.assertSaid("nothing", channel=None)

    def test_assert_error_takes_the_script_and_assert_global_reports_a_missing_name(self):
        script = self.load("float rate = 0.1; integer z; default { state_entry() { integer x = 1 / z; } }")
        self.sim.start()
        self.assertError("Math Error", script)
        self.assertGlobal(script, "rate", 0.1)       # compared at single precision
        with self.assertRaises(AssertionError):
            self.assertGlobal(script, "rtae", 0.1)

    def test_chat_is_cut_at_1024_bytes(self):
        sim = run_script('default { state_entry() { string s = "\u00e9"; integer i; for (i = 0; i < 11; i++) s += s; llSay(0, s); } }')
        self.assertEqual(len(sim.chat[0].text.encode("utf-8")), 1024)

    def test_linkset_find_keys_refuses_catastrophic_and_polynomial_patterns(self):
        sim = run_script("""default { state_entry() {
            llLinksetDataWrite("abc", "1"); llLinksetDataWrite("abd", "2");
            llOwnerSay(llList2CSV(llLinksetDataFindKeys("^ab", 0, 0)));
            llOwnerSay((string)llLinksetDataCountFound("^(a+)+$") + (string)llLinksetDataCountFound(".*.*x"));
        } }""")
        self.assertEqual(owner_heard(sim), ["abc, abd", "00"])


class GuardTest(LslTestCase):
    """lsltest's own limits, each one reached on purpose."""

    def kind_and_detail(self, sim):
        self.assertEqual(len(sim.errors), 1, sim.errors)
        err = sim.errors[0][1]
        return err.kind, err.detail

    def test_builtin_results_go_through_the_size_cap(self):
        sim = run_script("list l = [1]; default { state_entry() { integer i; for (i = 0; i < 17; i++) l = llListInsertList(l, l, 0); } }")
        self.assertEqual(self.kind_and_detail(sim)[0], "Stack-Heap Collision")

    def test_joins_are_sized_before_they_are_built(self):
        sim = run_script("""list l = [1]; default { state_entry() {
            integer i; for (i = 0; i < 16; i++) l += l;
            llOwnerSay((string)llGetListLength(l));
            string s = llDumpList2String(l, ", ");
        } }""")
        self.assertEqual(owner_heard(sim), ["65536"])
        self.assertEqual(self.kind_and_detail(sim)[0], "Stack-Heap Collision")

    def test_record_lists_are_capped(self):
        sim = run_script('default { state_entry() { while (TRUE) llSay(0, "x"); } }')
        self.assertIn("records", self.kind_and_detail(sim)[1])
        self.assertEqual(len(sim.chat), 100000)

    def test_urls_are_capped_at_38(self):
        sim = run_script("""integer denied; default {
            state_entry() { integer i; for (i = 0; i < 39; i++) llRequestURL(); }
            http_request(key id, string method, string body) { if (method == URL_REQUEST_DENIED) denied++; } }""")
        self.assertEqual(sim.objects[0].scripts[0].globals["denied"], 1)
        self.assertEqual(len(sim.http_in), 38)

    def test_statement_budget_kills_a_looping_handler(self):
        self.sim.max_statements = 50000
        self.load("default { state_entry() { integer i; while (TRUE) i++; } }")
        self.sim.start()
        self.assertIn("statements", self.kind_and_detail(self.sim)[1])

    def test_handler_deadline_kills_a_slow_handler(self):
        self.sim.max_handler_seconds = 0.05
        self.load("default { state_entry() { integer i; while (TRUE) i++; } }")
        self.sim.start()
        self.assertIn("seconds", self.kind_and_detail(self.sim)[1])

    def test_locals_count_in_the_memory_check(self):
        # 5000 iterations: the periodic check (every 4096 statements) sees about 4000 local keys, 400 KB
        sim = run_script("default { state_entry() { list l; integer i; for (i = 0; i < 5000; i++) l += [llGenerateKey()]; } }")
        self.assertEqual(self.kind_and_detail(sim)[0], "Stack-Heap Collision")

    def test_timer_without_a_handler_in_the_current_state_costs_nothing(self):
        sim = run_script("default { state_entry() { llSetTimerEvent(0.1); state two; } } state two { state_entry() { } }")
        sim.tick(86400.0)
        self.assertEqual(sim.errors, [])

    def test_linkset_rewrite_of_an_existing_key_counts_the_old_value_once(self):
        # values are capped at 65536 characters, so the 128 KiB store is approached with two keys;
        # the rewrite fits by 20 bytes only when the old value AND its name are released first
        sim = run_script("""default { state_entry() {
            string v = "x"; integer i; for (i = 0; i < 16; i++) v += v;         // 65536 characters
            string name = "a_twenty_char_key___";
            llOwnerSay((string)llLinksetDataWrite(name, llGetSubString(v, 0, 59999)));
            llOwnerSay((string)llLinksetDataWrite("b", v));
            llOwnerSay((string)llLinksetDataWrite(name, llGetSubString(v, 0, 65499)));
        } }""")
        self.assertEqual(sim.errors, [])
        self.assertEqual(owner_heard(sim), ["%d" % CONSTANTS["LINKSETDATA_OK"]] * 3)

class WikiFactsTest(LslTestCase):
    """Grid facts read on the wiki, each with the page that states it in lsl-for-ai.md."""

    def test_facts_checked_on_the_wiki(self):
        self.assertEqual(run_expr('llHMAC("k", "m", "sha256")'), "tgCQ4wUil661oICInOL8S8qVfnVvrrTffTGADKHncew=")
        self.assertEqual(run_expr('llList2Vector(["<1,2,3>"], 0)'), "<0.00000, 0.00000, 0.00000>")
        self.assertEqual(run_expr("(integer)1e10"), "-2147483648")

    def test_more_facts_checked_on_the_wiki(self):
        self.assertEqual(run_expr('llListFindStrided(["a", 1, "b", 2], [2], 1, -1, 2)'), "3")
        self.assertEqual(run_expr('llListFindStrided(["a", 1, "b", 2, "c"], ["c"], 1, -1, 2)'), "-1")
        self.assertEqual(run_expr('llEscapeURL("a-b_c.d~e f")'), "a%2Db%5Fc%2Ed%7Ee%20f")
        self.load("""default {
            state_entry() { llRequestURL(); }
            http_request(key id, string method, string body) {
                if (method == URL_REQUEST_GRANTED) return;
                llHTTPResponse(id, 200, llGetHTTPHeader(id, "user-agent") + "|" + llGetHTTPHeader(id, "User-Agent"));
            } }""")
        self.sim.start()
        url = next(iter(self.sim.http_in))
        self.assertEqual(self.sim.http_in_request(url, "GET")[1], "lsltest|")

    def test_list2json_turns_plain_words_into_literals_and_keeps_json_text(self):
        self.assertEqual(run_expr('llList2Json(JSON_ARRAY, ["true", "null", "[1,2]", "x"])'), '[true,null,[1,2],"x"]')

    def test_wallclock_follows_us_daylight_saving(self):
        self.assertEqual(run_expr("llGetWallclock()"), "51200.000000")        # 2023-11-14, PST
        sim = run_script("default { state_entry() { llSleep(1.0); } }")
        sim.epoch = 1690000000                                                   # 2023-07-22 04:26:40 UTC, PDT
        sim.time = 0.0
        self.assertEqual(sim.ll_GetWallclock(sim.objects[0].scripts[0]), 77200.0)


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
            looping = os.path.join(folder, "looping.lsl")
            with open(looping, "w") as handle:
                handle.write("default { state_entry() { llResetScript(); } }")
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(main([os.path.join(folder, "missing.lsl")]), 2)
                self.assertEqual(main([bad]), 2)
                self.assertEqual(main([folder]), 1)            # no test_*.py there
                self.assertEqual(main([good]), 0)
                self.assertEqual(main([looping]), 1)
            self.assertNotIn("\x1b", out.getvalue())           # control characters are escaped


if __name__ == "__main__":
    unittest.main()
