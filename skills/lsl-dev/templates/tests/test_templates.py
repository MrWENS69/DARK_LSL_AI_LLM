"""Example tests for the skill templates, written the way an assistant should write tests
for its own scripts: one behaviour per test, driven through the simulator, asserting on
what the script said or did. Run: python -m lsltest skills/lsl-dev/templates/tests
"""

import os

from lsltest import LslTestCase

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)


def template(name):
    return os.path.join(TEMPLATES, name)


GROUP = "11111111-1111-1111-1111-111111111111"


class DoorTest(LslTestCase):
    def setUp(self):
        LslTestCase.setUp(self)
        self.script = self.load(template("door.lsl"))
        self.sim.objects[0].group = GROUP      # a door set to a group; avatars without it are strangers
        self.sim.start()

    def test_announces_itself(self):
        self.assertOwnerSaid("Door 1.0 ready")
        self.assertNoErrors()

    def test_owner_opens_and_timer_closes(self):
        self.sim.touch()
        self.assertGlobal(self.script, "gOpen", 1)
        self.sim.tick(9.0)
        self.assertGlobal(self.script, "gOpen", 0)
        self.assertNoErrors()

    def test_stranger_is_refused(self):
        stranger = self.sim.avatar("Some Stranger")
        self.sim.touch(stranger)
        self.assertSaidTo(stranger, "for group members")
        self.assertGlobal(self.script, "gOpen", 0)

    def test_group_member_opens(self):
        member = self.sim.avatar("Group Member", group=GROUP)
        self.sim.touch(member)
        self.assertGlobal(self.script, "gOpen", 1)

    def test_debug_flag_comes_from_description(self):
        self.sim.objects[0].desc = "debug"
        self.sim.reset(self.script)
        self.sim.touch()
        self.assertOwnerSaid("[door] opened")


class MenuTest(LslTestCase):
    def setUp(self):
        LslTestCase.setUp(self)
        self.script = self.load(template("menu.lsl"))
        self.sim.start()

    def test_touch_shows_first_page_with_paging_buttons(self):
        self.sim.touch()
        dialog = self.assertDialog(contains="Pick a colour")
        self.assertEqual(dialog["buttons"][:2], ["Back", "Next"])
        self.assertEqual(len(dialog["buttons"]), 12)
        self.assertListening(dialog["channel"])

    def test_choice_is_announced_and_listener_closed(self):
        self.sim.touch()
        self.sim.dialog_reply(self.sim.owner, "Green")
        self.assertSaidTo(self.sim.owner, "You picked Green")
        self.assertNoListens()

    def test_next_page_then_pick(self):
        self.sim.touch()
        self.sim.dialog_reply(self.sim.owner, "Next")
        dialog = self.assertDialog(contains="Pick a colour")
        self.assertIn("Cyan", dialog["buttons"])
        self.sim.dialog_reply(self.sim.owner, "Cyan")
        self.assertSaidTo(self.sim.owner, "You picked Cyan")

    def test_free_text_is_ignored(self):
        self.sim.touch()
        self.sim.dialog_reply(self.sim.owner, "not a button")
        self.assertNotSaid("You picked")
        self.assertNoListens()

    def test_timeout_closes_the_menu(self):
        self.sim.touch()
        self.sim.tick(61.0)
        self.assertSaidTo(self.sim.owner, "Menu closed")
        self.assertNoListens()

    def test_second_avatar_is_told_to_wait(self):
        self.sim.touch()
        other = self.sim.avatar("Other One")
        self.sim.touch(other)
        self.assertSaidTo(other, "Someone else is using the menu")


class NotecardConfigTest(LslTestCase):
    def test_settings_are_loaded(self):
        self.load(template("notecard_config.lsl"))
        self.sim.notecard("config", "# comment\ngreeting = Hello there\n\nprice=250\n")
        self.sim.start()
        self.assertOwnerSaid("2 settings loaded, greeting is: Hello there")
        self.assertNoErrors()

    def test_missing_notecard_is_reported(self):
        self.load(template("notecard_config.lsl"))
        self.sim.start()
        self.assertOwnerSaid("No notecard named config")

    def test_reload_on_inventory_change(self):
        self.load(template("notecard_config.lsl"))
        self.sim.notecard("config", "greeting = one")
        self.sim.start()
        self.sim.notecard("config", "greeting = two")
        self.sim.changed(self.sim.constants["CHANGED_INVENTORY"])
        self.assertOwnerSaid("greeting is: two")


class HttpClientTest(LslTestCase):
    def setUp(self):
        LslTestCase.setUp(self)
        self.load(template("http_client.lsl"))
        self.sim.start()

    def test_touch_posts_json_and_reads_the_answer(self):
        self.sim.touch()
        request = self.assertHttpRequest(url_contains="example.invalid/api/ping", method="POST")
        self.assertIn('"version":"1.0"', request.body)
        self.sim.http_respond(200, '{"message": "pong"}')
        self.assertOwnerSaid("API says: pong")
        self.assertNoErrors()

    def test_error_status_is_reported(self):
        self.sim.touch()
        self.sim.http_respond(503, "down")
        self.assertOwnerSaid("API error 503")

    def test_bad_json_is_reported(self):
        self.sim.touch()
        self.sim.http_respond(200, "<html>")
        self.assertOwnerSaid("not the expected JSON")

    def test_one_request_in_flight(self):
        self.sim.touch()
        self.sim.touch()
        self.assertEqual(len(self.sim.http_requests), 1)


class HttpServerTest(LslTestCase):
    def setUp(self):
        LslTestCase.setUp(self)
        self.script = self.load(template("http_server.lsl"))
        self.sim.start()
        self.url = self.script.globals["gUrl"]

    def test_url_is_granted_and_announced(self):
        self.assertTrue(self.url.startswith("http://"))
        self.assertOwnerSaid("Serving at " + self.url)

    def test_get_returns_json_status(self):
        status, body, ctype = self.sim.http_in_request(self.url + "/status")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "application/json")
        self.assertIn('"version":"1.0"', body)
        self.assertIn('"hits":1', body)

    def test_post_say_speaks_in_local_chat(self):
        status, body, _ = self.sim.http_in_request(self.url, "POST", '{"say": "hello world"}')
        self.assertEqual((status, body), (200, "said"))
        self.assertSaid("hello world", channel=0)

    def test_bad_post_is_rejected(self):
        status, _, _ = self.sim.http_in_request(self.url, "POST", "not json")
        self.assertEqual(status, 400)

    def test_region_restart_requests_a_new_url(self):
        old = self.url
        self.sim.changed(self.sim.constants["CHANGED_REGION_START"])
        self.assertNotEqual(self.script.globals["gUrl"], old)
        self.assertNotIn(old, self.sim.http_in)


class LinkProtocolTest(LslTestCase):
    def setUp(self):
        LslTestCase.setUp(self)
        self.core = self.load(template("link_core.lsl"))
        self.menu = self.load(template("link_menu.lsl"))
        self.sim.start()

    def test_open_through_the_menu(self):
        self.sim.touch()
        self.assertDialog(buttons=["open", "close", "status"])
        self.sim.dialog_reply(self.sim.owner, "open")
        self.assertLinkMessage(num=100, str_contains="open")
        self.assertLinkMessage(num=200, str_contains="The door is open")
        self.assertSaidTo(self.sim.owner, "The door is open")
        self.assertGlobal(self.core, "gOpen", 1)

    def test_unknown_command_is_answered(self):
        self.sim.link_message(100, "dance", self.sim.owner.key)
        self.assertSaidTo(self.sim.owner, "Unknown command dance")


class HudTest(LslTestCase):
    def test_attach_requests_permissions_and_takes_controls(self):
        self.load(template("hud_attachment.lsl"))
        self.sim.start()
        self.sim.attach()
        self.assertCalled("llTakeControls")
        self.assertEqual(self.sim.objects[0].text, "HUD 1.0")
        self.assertNoErrors()

    def test_refused_animation_permission_is_announced(self):
        self.load(template("hud_attachment.lsl"))
        self.sim.start()
        self.sim.permission_policy = lambda avatar, mask: mask & self.sim.constants["PERMISSION_TAKE_CONTROLS"]
        self.sim.attach()
        self.assertOwnerSaid("Animation permission refused")

    def test_detach_clears_the_text(self):
        self.load(template("hud_attachment.lsl"))
        self.sim.start()
        self.sim.attach()
        self.sim.detach()
        self.assertEqual(self.sim.objects[0].text, "")
        self.assertCalled("llReleaseControls")


class LinksetStorageTest(LslTestCase):
    def test_counter_survives_reset(self):
        script = self.load(template("linkset_storage.lsl"))
        self.sim.start()
        self.sim.touch()
        self.sim.touch()
        self.assertSaidTo(self.sim.owner, "Touch number 2")
        self.sim.reset(script)
        self.assertOwnerSaid("touches so far 2")

    def test_label_update_is_announced(self):
        self.load(template("linkset_storage.lsl"))
        self.load('default { touch_start(integer n) { llLinksetDataWrite("label", "Shop"); } }', name="writer")
        self.sim.start()
        self.sim.touch()
        self.assertOwnerSaid("Label is now Shop")
