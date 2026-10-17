"""The fake simulator: objects, avatars, clock, event queues, and every builtin that acts.

What it captures for assertions: chat (per channel, with the speaker), dialogs
and textboxes, listens, timers, link messages, HTTP requests out and responses
in, HTTP-in requests and the responses the script gave, permissions, linkset
data, hover text, inventory, and every call to a builtin it does not model
(recorded with its arguments, so nothing is silently lost).

The builtins that act live in the mixins (one method ll_Xxx per builtin): sim_chat, sim_time,
sim_objects, sim_http, sim_events, sim_linkset_data. The records are in world.py, the constants
and limits in limits.py.
"""

import os
import random
import uuid

from . import pure
from ._version import __version__
from .errors import LslSyntaxError, ResetSignal, ScriptError, UnsupportedError
from .interp import Script
from .limits import (AGENT, CHANGED_REGION, CHANGED_REGION_START, INVENTORY_NOTECARD, INVENTORY_SCRIPT,
                     MAX_HANDLER_SECONDS, MAX_RECORDS, MAX_RUN_ROUNDS, MAX_SCRIPT_BYTES, MAX_STATEMENTS,
                     MAX_TICK_STEPS, PASSIVE, RECORD_ONLY)
from .signatures import CONSTANTS, SIGNATURES
from .values import Key, check_size, coerce, default_value, ZERO_VECTOR, ZERO_ROTATION, NULL_KEY
from .world import Avatar, SimObject, Chat, clip_text
from .sim_chat import ChatMixin
from .sim_events import EventsMixin
from .sim_http import HttpMixin
from .sim_linkset_data import LinksetDataMixin
from .sim_objects import ObjectsMixin
from .sim_time import TimeMixin


class Simulator(ChatMixin, TimeMixin, ObjectsMixin, HttpMixin, EventsMixin, LinksetDataMixin):

    def __init__(self, seed=42, region_name="Test Region", strict=False):
        self.time = 0.0                       # simulated seconds since the simulator was created
        self.epoch = 1700000000               # llGetUnixTime at time 0
        self.rng = random.Random(seed)
        self.region_name = region_name
        self.sim_version = "lsltest " + __version__
        self.strict = strict                  # True: an unmodelled builtin raises instead of being recorded
        self.max_statements = MAX_STATEMENTS  # lsltest guards per event handler, lowered by tests of the guards
        self.max_handler_seconds = MAX_HANDLER_SECONDS
        self.avatars = {}                     # key -> Avatar
        self.objects = []                     # SimObject, objects[0] is the default one
        self.chat = []                        # Chat, everything said by scripts and avatars
        self.dialogs = []                     # SimpleNamespace(avatar, text, buttons, channel, object, script, time)
        self.textboxes = []                   # SimpleNamespace(avatar, text, channel, object, script, time)
        self.http_out = []                    # HttpOutRequest, every llHTTPRequest in order
        self._http_pending = []               # the ones not answered yet
        self.http_handler = None              # callable(HttpOutRequest) -> (status, body) or None, answers during run()
        self.http_in = {}                     # url -> script
        self.http_in_pending = {}             # request key -> dict(status, body, content_type, headers)
        self.link_messages = []               # SimpleNamespace(script, sender, link, num, str, id, time)
        self.calls = []                       # (script name, builtin, args): calls that are only recorded
        self.errors = []                      # (script name, ScriptError)
        self.emails = []                      # SimpleNamespace(to, subject, body, object)
        self.permission_policy = True         # True grants everything, False refuses, or callable(avatar, mask) -> mask
        self.constants = CONSTANTS            # LSL constants by name, from builtins.txt
        self.signatures = SIGNATURES          # builtin name -> (return type, [parameter types])
        self.owner = self.avatar("Test Owner")   # owner of every object rezzed without an explicit owner

    def new_key(self):
        return Key(str(uuid.UUID(int=self.rng.getrandbits(128), version=4)))

    def avatar(self, name, username=None, display_name=None, group=NULL_KEY, key=None):
        av = Avatar(key or self.new_key(), name, username, display_name, group)
        self.avatars[av.key] = av
        return av

    def rez(self, name="Object", desc="", owner=None, group=NULL_KEY):
        owner = owner or self.owner
        obj = SimObject(self.new_key(), name, desc, owner.key, group)
        self._keep(self.objects, obj)
        return obj

    def _keep(self, records, item):
        """Append to a record list; a script that fills it past MAX_RECORDS is looping and dies."""
        if len(records) >= MAX_RECORDS:
            raise ScriptError("Script run-time error",
                              "lsltest: over %d records of one kind, the script is looping" % MAX_RECORDS)
        records.append(item)

    def load(self, source, name=None, obj=None):
        """Attach a script to an object (the default one when None). source: path of a .lsl file, or LSL text."""
        if "{" not in source and source.lower().endswith(".lsl"):
            if not os.path.isfile(source):
                raise FileNotFoundError("no such script: %s" % source)
            if os.path.getsize(source) > MAX_SCRIPT_BYTES:
                raise LslSyntaxError("script file over %d bytes" % MAX_SCRIPT_BYTES)
            with open(source, "r", encoding="utf-8") as handle:
                text = handle.read()
            name = name or os.path.splitext(os.path.basename(source))[0]
        else:
            text = source
            name = name or "script"
        if obj is None:
            obj = self.objects[0] if self.objects else self.rez()
        script = Script(self, obj, text, name)
        obj.scripts.append(script)
        obj.inventory[name] = (INVENTORY_SCRIPT, text)
        return script

    def notecard(self, name, text, obj=None, cached=False):
        """Put a notecard in the object (the default one, rezzed if needed). cached=True: llGetNotecardLineSync
        answers at once instead of NAK."""
        obj = obj or (self.objects[0] if self.objects else self.rez())
        obj.inventory[name] = (INVENTORY_NOTECARD, text)
        if cached:
            obj.cached.add(name)
        else:
            obj.cached.discard(name)

    def all_scripts(self):
        return [s for o in self.objects if o.alive for s in o.scripts]

    def start(self):
        """Run state_entry of every script, like a fresh rez, then drain the queues."""
        for script in self.all_scripts():
            script.post("state_entry", [])
        self.run()

    def run(self):
        """Dispatch queued events, round after round, until every queue is empty. Returns the number run.

        A round dispatches what each script had queued when the round began, so scripts that keep
        posting to themselves or to each other are caught after MAX_RUN_ROUNDS rounds."""
        total = 0
        for _ in range(MAX_RUN_ROUNDS):
            progressed = 0
            for script in self.all_scripts():
                progressed += self.run_script(script)
            if self.http_handler:
                progressed += self.auto_respond()
            if not progressed:
                return total
            total += progressed
        raise RuntimeError("the scripts kept posting events for %d rounds: they are looping" % MAX_RUN_ROUNDS)

    def run_script(self, script):
        """Dispatch the events the script has queued now (not the ones its handlers add)."""
        count = 0
        for _ in range(len(script.queue)):
            if not script.queue or not script.running or script.dead:
                break
            name, args, detected = script.queue.pop(0)
            try:
                script.dispatch(name, args, detected)
            except ResetSignal:
                script.reset()
            count += 1
        return count

    def tick(self, seconds):
        """Advance the clock, firing timers and repeating sensors on the way, then drain the queues."""
        end = self.time + float(seconds)
        steps = 0
        while True:
            due = self._next_due()
            if due is None or due > end:
                break
            steps += 1
            if steps > MAX_TICK_STEPS:
                raise RuntimeError("tick(%s) ran %d timer or sensor steps before reaching the end: the timer is too short"
                                   % (seconds, MAX_TICK_STEPS))
            self.time = max(self.time, due)
            self.fire_due()
            self.run()
        self.time = max(self.time, end)       # never backwards: a handler may have slept past the end
        self.run()

    def _next_due(self):
        """The next timer or repeating sensor that would reach a handler in the script's current state."""
        due = None
        for script in self.all_scripts():
            if script.dead or not script.running:
                continue
            timer = script.timer_due if script.handles_event("timer") else None
            sensor = script.sensor_repeat.due if script.sensor_repeat and (
                script.handles_event("sensor") or script.handles_event("no_sensor")) else None
            for when in (timer, sensor):
                if when is not None and (due is None or when < due):
                    due = when
        return due

    def fire_due(self):
        for script in self.all_scripts():
            if script.timer_due is not None and script.timer_due <= self.time:
                script.post("timer", [])
                script.timer_due = self.time + script.timer_interval
            rep = script.sensor_repeat
            if rep is not None and rep.due <= self.time:
                self.deliver_sensor(script, rep.name, rep.id, rep.type, rep.range, rep.arc)
                rep.due = self.time + rep.rate

    def _detected_record(self, avatar=None, obj=None):
        """What llDetected* reads for one detected avatar or object (keys mirror the llDetected* names)."""
        if avatar is not None:
            return {"key": avatar.key, "name": avatar.name, "owner": avatar.key, "pos": avatar.pos,
                    "rot": ZERO_ROTATION, "group": avatar.group, "type": AGENT, "vel": ZERO_VECTOR}
        return {"key": obj.key, "name": obj.name, "owner": obj.owner, "pos": obj.pos, "rot": obj.rot,
                "group": obj.group, "type": PASSIVE, "vel": ZERO_VECTOR}

    def _inject(self, obj, events, args, detected=None):
        """Post the same event(s) to every script of obj (the default object when None), then run."""
        obj = obj or self.objects[0]
        for script in obj.scripts:
            for event in events:
                script.post(event, args, detected)
        self.run()

    def touch(self, avatar=None, obj=None):
        """Touch an object: touch_start, touch, touch_end with one detected avatar (the owner by default)."""
        det = [self._detected_record(avatar=avatar or self.owner)]
        for event in ("touch_start", "touch", "touch_end"):     # the release comes after the press has run
            self._inject(obj, (event,), [1], det)

    def collision(self, avatar=None, obj=None):
        det = [self._detected_record(avatar=avatar or self.owner)]
        for event in ("collision_start", "collision", "collision_end"):
            self._inject(obj, (event,), [1], det)

    def say(self, avatar, channel, text):
        """An avatar speaks on a channel; listening scripts receive listen()."""
        text = clip_text(text, 1024)
        self._keep(self.chat, Chat(channel, avatar.key, avatar.name, text, "avatar", None, self.time))
        self.deliver_chat(channel, avatar.key, avatar.name, text, source_obj=None, target=None)
        self.run()

    def dialog_reply(self, avatar, button):
        """Answer the latest dialog shown to this avatar by clicking a button (or typing free text)."""
        for dialog in reversed(self.dialogs):
            if dialog.avatar == avatar.key:
                self.say(avatar, dialog.channel, button)
                return dialog
        raise AssertionError("no dialog was shown to %s" % avatar.name)

    def textbox_reply(self, avatar, text):
        for box in reversed(self.textboxes):
            if box.avatar == avatar.key:
                self.say(avatar, box.channel, text)
                return box
        raise AssertionError("no textbox was shown to %s" % avatar.name)

    def changed(self, flags, obj=None):
        obj = obj or self.objects[0]
        if flags & (CHANGED_REGION | CHANGED_REGION_START):
            self._drop_urls(obj)
        self._inject(obj, ("changed",), [flags])

    def on_rez(self, start_param=0, obj=None):
        obj = obj or self.objects[0]
        obj.start_param = start_param
        for script in obj.scripts:
            script.start_param = start_param
        self._drop_urls(obj)
        self._inject(obj, ("on_rez",), [start_param])

    def attach(self, avatar=None, obj=None, point=31):
        avatar = avatar or self.owner
        obj = obj or self.objects[0]
        obj.attached = point
        obj.wearer = avatar
        obj.owner = avatar.key
        avatar.attachments.append(obj)
        self._inject(obj, ("attach",), [avatar.key])

    def detach(self, obj=None):
        obj = obj or self.objects[0]
        if obj.wearer and obj in obj.wearer.attachments:
            obj.wearer.attachments.remove(obj)
        obj.attached = 0
        obj.wearer = None
        self._inject(obj, ("attach",), [NULL_KEY])

    def link_message(self, num, text, id=NULL_KEY, obj=None, sender=0):
        """A link_message from another prim (sender is its link number; 0 is the only prim of a single-prim object)."""
        self._inject(obj, ("link_message",), [sender, num, text, Key(id)])

    def money(self, avatar, amount, obj=None):
        self._inject(obj, ("money",), [avatar.key, amount])

    def reset(self, script):
        script.reset()
        self.run()

    def call_builtin(self, script, name, args):
        sig = SIGNATURES.get(name)
        if sig is None:
            raise ScriptError("Script run-time error", "unknown function %s" % name)
        ret_type, param_types = sig
        if len(args) != len(param_types):
            raise ScriptError("Type mismatch", "%s expects %d arguments, got %d" % (name, len(param_types), len(args)))
        coerced = [coerce(a, t) for a, t in zip(args, param_types)]
        handler = getattr(self, "ll_" + name[2:], None)
        if handler is not None:
            result = handler(script, *coerced)
        elif name in pure.PURE:
            result = pure.PURE[name](*coerced)
        else:
            if self.strict and name not in RECORD_ONLY:
                raise UnsupportedError("%s is not modelled by lsltest (set strict=False to record it)" % name)
            self.record_call(script, name, *coerced)
            result = None
        if ret_type == "void":
            return None
        if result is None:
            return default_value(ret_type)
        return check_size(coerce(result, ret_type))

    def record_call(self, script, name, *args):
        self._keep(self.calls, (script.name, name, list(args)))
