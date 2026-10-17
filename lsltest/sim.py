"""The fake simulator: objects, avatars, clock, event queues, and every builtin that acts.

What it captures for assertions: chat (per channel, with the speaker), dialogs
and textboxes, listens, timers, link messages, HTTP requests out and responses
in, HTTP-in requests and the responses the script gave, permissions, linkset
data, hover text, inventory, and every call to a builtin it does not model
(recorded with its arguments, so nothing is silently lost).
"""

import os
import random
import re
import time as _time
import uuid
from types import SimpleNamespace

from . import pure
from ._version import __version__
from .errors import ScriptError, UnsupportedError
from .interp import Script
from .signatures import CONSTANTS, SIGNATURES
from .values import (Key, Vector, Rotation, f32, coerce, default_value, to_string, to_int32,
                     ZERO_VECTOR, ZERO_ROTATION, NULL_KEY, is_valid_key)

# LSL constants come from builtins.txt through signatures.py: the handlers below name the ones they need.
EOF = CONSTANTS["EOF"]
NAK = CONSTANTS["NAK"]
INVENTORY_NOTECARD = CONSTANTS["INVENTORY_NOTECARD"]
INVENTORY_SCRIPT = CONSTANTS["INVENTORY_SCRIPT"]
INVENTORY_OBJECT = CONSTANTS["INVENTORY_OBJECT"]
INVENTORY_NONE = CONSTANTS["INVENTORY_NONE"]
URL_REQUEST_GRANTED = CONSTANTS["URL_REQUEST_GRANTED"]
HTTP_METHOD = CONSTANTS["HTTP_METHOD"]
AGENT, ACTIVE, PASSIVE, SCRIPTED = (CONSTANTS[n] for n in ("AGENT", "ACTIVE", "PASSIVE", "SCRIPTED"))
LINK_SET, LINK_ALL_OTHERS, LINK_ALL_CHILDREN, LINK_THIS = (
    CONSTANTS[n] for n in ("LINK_SET", "LINK_ALL_OTHERS", "LINK_ALL_CHILDREN", "LINK_THIS"))
_CONTENT_TYPES = {CONSTANTS[name]: mime for name, mime in (
    ("CONTENT_TYPE_TEXT", "text/plain"), ("CONTENT_TYPE_HTML", "text/html"), ("CONTENT_TYPE_XML", "application/xml"),
    ("CONTENT_TYPE_XHTML", "application/xhtml+xml"), ("CONTENT_TYPE_ATOM", "application/atom+xml"),
    ("CONTENT_TYPE_JSON", "application/json"), ("CONTENT_TYPE_LLSD", "application/llsd+xml"),
    ("CONTENT_TYPE_FORM", "application/x-www-form-urlencoded"), ("CONTENT_TYPE_RSS", "application/rss+xml"))
    if name in CONSTANTS}

# Grid limits that are not LSL constants.
MAX_LISTENS = 65              # llListen handles per script before "Too Many Listens"
LINKSET_DATA_SIZE = 131072    # bytes of linkset data per object
MIN_TIMER = 0.022             # one simulator frame: shorter timers and sensor rates are rounded up to it
MAX_TICK_STEPS = 100000       # timer firings a single tick() may run before it is declared a runaway
MAX_PATTERN_LEN = 256         # llLinksetDataFindKeys patterns longer than this match nothing


class ResetSignal(Exception):
    pass


class Avatar(object):
    def __init__(self, key, name, username=None, display_name=None, group=NULL_KEY):
        self.key = key
        self.name = name                      # legacy name "First Last"
        self.username = username or name.lower().replace(" ", ".")
        self.display_name = display_name or name
        self.group = group
        self.pos = Vector(128.0, 128.0, 25.0)
        self.online = True
        self.attachments = []                 # SimObject


class SimObject(object):
    def __init__(self, sim, key, name, desc, owner, group):
        self.sim = sim
        self.key = key
        self.name = name
        self.desc = desc
        self.owner = owner
        self.group = group
        self.pos = Vector(128.0, 128.0, 25.0)
        self.rot = ZERO_ROTATION
        self.prims = 1
        self.scripts = []
        self.inventory = {}                   # name -> (type, content)
        self.linkset_data = {}                # name -> value
        self.linkset_protected = {}           # name -> (value, password)
        self.text = ""
        self.attached = 0
        self.wearer = None
        self.start_param = 0
        self.alive = True
        self.properties = {}                  # recorded prim parameter calls

    def script_named(self, name):
        for script in self.scripts:
            if script.name == name:
                return script
        return None


class Chat(object):
    __slots__ = ("channel", "speaker", "speaker_name", "text", "kind", "target", "time")

    def __init__(self, channel, speaker, speaker_name, text, kind, target, when):
        self.channel = channel
        self.speaker = speaker
        self.speaker_name = speaker_name
        self.text = text
        # kind: what produced the line. Scripts: say, whisper, shout, regionsay, regionsayto, ownersay, im, debug
        # (the grid's DEBUG_CHANNEL). Test code: avatar (sim.say). assertSaid only looks at script chat kinds.
        self.kind = kind
        self.target = target
        self.time = when

    def __repr__(self):
        return "Chat(%d, %s, %r, %s)" % (self.channel, self.speaker_name, self.text, self.kind)


class HttpOutRequest(object):
    """One llHTTPRequest the script sent. `response` is (status, body) once answered."""
    __slots__ = ("key", "script", "url", "method", "body", "params", "response", "time")

    def __init__(self, key, script, url, method, body, params, when):
        self.key = key
        self.script = script
        self.url = url
        self.method = method
        self.body = body
        self.params = params
        self.response = None
        self.time = when

    def __repr__(self):
        return "HttpOutRequest(%s %s, %d bytes)" % (self.method, self.url, len(self.body))


class Simulator(object):
    def __init__(self, seed=42, region_name="Test Region", strict=False):
        self.time = 0.0                       # simulated seconds since the simulator was created
        self.epoch = 1700000000               # llGetUnixTime at time 0
        self.rng = random.Random(seed)
        self.region_name = region_name
        self.sim_version = "lsltest " + __version__
        self.strict = strict                  # True: an unmodelled builtin raises instead of being recorded
        self.avatars = {}                     # key -> Avatar
        self.objects = []                     # SimObject, objects[0] is the default one
        self.chat = []                        # Chat, everything said by scripts and avatars
        self.dialogs = []                     # SimpleNamespace(avatar, text, buttons, channel, object, script, time)
        self.textboxes = []                   # SimpleNamespace(avatar, text, channel, object, script, time)
        self.http_out = []                    # HttpOutRequest, every llHTTPRequest in order
        self.http_handler = None              # callable(HttpOutRequest) -> (status, body) or None, answers during run()
        self.http_in = {}                     # url -> script
        self.http_in_pending = {}             # request key -> dict(status, body, content_type, headers)
        self.link_messages = []               # SimpleNamespace(sender, link, num, str, id, time)
        self.calls = []                       # (script name, builtin, args) for unmodelled builtins
        self.errors = []                      # (script name, ScriptError)
        self.emails = []                      # SimpleNamespace(to, subject, body, sender)
        self.permission_policy = True         # True grants everything, False refuses, or callable(avatar, mask) -> mask
        self.constants = CONSTANTS            # LSL constants by name, from builtins.txt
        self.signatures = SIGNATURES          # builtin name -> (return type, [parameter types])
        self.owner = self.avatar("Test Owner")   # owner of every object rezzed without an explicit owner

    # --- world setup -------------------------------------------------------

    def new_key(self):
        return Key(str(uuid.UUID(int=self.rng.getrandbits(128), version=4)))

    def avatar(self, name, username=None, display_name=None, group=NULL_KEY, key=None):
        av = Avatar(key or self.new_key(), name, username, display_name, group)
        self.avatars[av.key] = av
        return av

    def rez(self, name="Object", desc="", owner=None, group=NULL_KEY):
        owner = owner or self.owner
        obj = SimObject(self, self.new_key(), name, desc, owner.key, group)
        self.objects.append(obj)
        return obj

    def load(self, source, name=None, obj=None):
        """Attach a script to an object (the default one when None). source: path of a .lsl file, or LSL text."""
        if "{" not in source and source.lower().endswith(".lsl"):
            if not os.path.isfile(source):
                raise FileNotFoundError("no such script: %s" % source)
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

    def notecard(self, name, text, obj=None):
        obj = obj or self.objects[0]
        obj.inventory[name] = (INVENTORY_NOTECARD, text)

    def all_scripts(self):
        return [s for o in self.objects if o.alive for s in o.scripts]

    # --- running -------------------------------------------------------------

    def start(self):
        """Run state_entry of every script, like a fresh rez, then drain the queues."""
        for script in self.all_scripts():
            script.post("state_entry", [])
        self.run()

    def run(self, limit=100000):
        """Dispatch queued events until every queue is empty. Returns the number of events run."""
        total = 0
        rounds = 0
        while rounds < limit:
            progressed = 0
            for script in self.all_scripts():
                if script.queue:
                    progressed += self.run_script(script)
            if self.http_handler:
                progressed += self.auto_respond()
            if not progressed:
                break
            total += progressed
            rounds += 1
        return total

    def run_script(self, script):
        count = 0
        while script.queue and script.running and not script.dead:
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
                raise RuntimeError("tick(%s) fired %d timers before reaching the end: the timer is too short for this tick"
                                   % (seconds, MAX_TICK_STEPS))
            self.time = max(self.time, due)
            self.fire_due()
            self.run()
        self.time = end
        self.run()

    def _next_due(self):
        due = None
        for script in self.all_scripts():
            for when in (script.timer_due, script.sensor_repeat and script.sensor_repeat.due):
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

    def record_error(self, script, err):
        self.errors.append((script.name, err))

    # --- event injection ---------------------------------------------------

    def detected_record(self, avatar=None, obj=None):
        if avatar is not None:
            return {"key": avatar.key, "name": avatar.name, "owner": avatar.key, "pos": avatar.pos,
                    "rot": ZERO_ROTATION, "group": avatar.group, "type": 1, "vel": ZERO_VECTOR}
        return {"key": obj.key, "name": obj.name, "owner": obj.owner, "pos": obj.pos, "rot": obj.rot,
                "group": obj.group, "type": 4, "vel": ZERO_VECTOR}

    def _inject(self, obj, events, args, detected=None):
        """Post the same event(s) to every script of obj (the default object when None), then run."""
        obj = obj or self.objects[0]
        for script in obj.scripts:
            for event in events:
                script.post(event, args, detected)
        self.run()

    def touch(self, avatar=None, obj=None):
        """Touch an object: touch_start, touch, touch_end with one detected avatar (the owner by default)."""
        det = [self.detected_record(avatar=avatar or self.owner)]
        self._inject(obj, ("touch_start", "touch", "touch_end"), [1], det)

    def collision(self, avatar=None, obj=None):
        det = [self.detected_record(avatar=avatar or self.owner)]
        self._inject(obj, ("collision_start", "collision", "collision_end"), [1], det)

    def say(self, avatar, channel, text):
        """An avatar speaks on a channel; listening scripts receive listen()."""
        self.chat.append(Chat(channel, avatar.key, avatar.name, text, "avatar", None, self.time))
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
        self._inject(obj, ("changed",), [flags])

    def on_rez(self, start_param=0, obj=None):
        obj = obj or self.objects[0]
        obj.start_param = start_param
        for script in obj.scripts:
            script.start_param = start_param
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

    def link_message(self, num, text, id_=NULL_KEY, obj=None, sender=1):
        self._inject(obj, ("link_message",), [sender, num, text, Key(id_)])

    def money(self, avatar, amount, obj=None):
        self._inject(obj, ("money",), [avatar.key, amount])

    def reset(self, script):
        script.reset()
        self.run()

    def _answer(self, request, status, body, headers=None):
        request.response = (status, body)
        metadata = [0, "text/plain;charset=utf-8"] + list(headers or [])
        request.script.post("http_response", [request.key, status, metadata, body])

    def http_respond(self, status=200, body="", request=None, headers=None):
        """Answer a pending llHTTPRequest (the oldest unanswered one by default), then run."""
        if request is None:
            pending = [r for r in self.http_out if r.response is None]
            if not pending:
                raise AssertionError("no pending HTTP request")
            request = pending[0]
        self._answer(request, status, body, headers)
        self.run()

    def auto_respond(self):
        """Called by run(): hand every unanswered request to http_handler. Returns how many it answered."""
        count = 0
        for request in [r for r in self.http_out if r.response is None]:
            answer = self.http_handler(request)
            if answer is None:
                continue
            status, body = answer
            self._answer(request, status, body)
            count += 1
        return count

    def http_in_request(self, url, method="GET", body="", headers=None):
        """Send a request to a script's HTTP-in URL; returns (status, body, content_type)."""
        base = url.split("?", 1)[0]
        script = None
        for known, owner in self.http_in.items():
            if base == known or base.startswith(known + "/"):
                script = owner
                break
        if script is None:
            return (404, "no such URL", "text/plain")
        key = self.new_key()
        path_info = base[len(known):]
        query = url.split("?", 1)[1] if "?" in url else ""
        request_headers = {k.lower(): v for k, v in (headers or {}).items()}
        request_headers.setdefault("x-script-url", known)
        request_headers.setdefault("x-path-info", path_info)
        request_headers.setdefault("x-query-string", query)
        request_headers.setdefault("x-remote-ip", "127.0.0.1")
        request_headers.setdefault("user-agent", "lsltest")
        self.http_in_pending[key] = {"status": None, "body": "", "content_type": "text/plain", "headers": request_headers}
        script.post("http_request", [key, method, body[:2048]])
        self.run()
        answer = self.http_in_pending.pop(key)
        if answer["status"] is None:
            return (500, "the script did not answer", "text/plain")
        return (answer["status"], answer["body"], answer["content_type"])

    def grant_url(self, script):
        url = "http://sim.invalid/cap/%s" % self.new_key()
        self.http_in[url] = script
        script.urls.add(url)
        return url

    def release_url(self, script, url):
        self.http_in.pop(url, None)
        script.urls.discard(url)

    def deliver_sensor(self, script, name, id_, kind, range_, arc):
        found = []
        here = script.obj.pos
        if kind & AGENT:
            for av in self.avatars.values():
                if script.obj.wearer is not None and av.key == script.obj.wearer.key:
                    continue          # an attachment never detects its wearer
                if pure.llVecDist(here, av.pos) <= range_:
                    if name and av.name != name:
                        continue
                    if is_valid_key(id_) and id_ != NULL_KEY and av.key != id_:
                        continue
                    found.append(self.detected_record(avatar=av))
        if kind & (ACTIVE | PASSIVE | SCRIPTED):
            for obj in self.objects:
                if obj is script.obj or not obj.alive or obj.attached:
                    continue
                if pure.llVecDist(here, obj.pos) <= range_:
                    if name and obj.name != name:
                        continue
                    found.append(self.detected_record(obj=obj))
        found = found[:32]
        if found:
            script.post("sensor", [len(found)], found)
        else:
            script.post("no_sensor", [])

    def deliver_chat(self, channel, speaker_key, speaker_name, text, source_obj, target):
        if len(text.encode("utf-8")) > 1024:
            text = text.encode("utf-8")[:1024].decode("utf-8", "ignore")
        for script in self.all_scripts():
            if source_obj is not None and script.obj is source_obj:
                continue                      # an object never hears itself
            if target is not None:
                if isinstance(target, SimObject):
                    if script.obj is not target:
                        continue
                else:
                    if script.obj.wearer is None or script.obj.wearer.key != target:
                        continue
            for listen in script.listens.values():
                if not listen.active or listen.channel != channel:
                    continue
                if listen.name and listen.name != speaker_name:
                    continue
                if listen.id and listen.id != speaker_key:
                    continue
                if listen.msg and listen.msg != text:
                    continue
                script.post("listen", [channel, speaker_name, Key(speaker_key), text])
                break

    # --- builtin dispatch --------------------------------------------------

    def call_builtin(self, script, name, args):
        sig = self.signatures.get(name)
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
            if self.strict:
                raise UnsupportedError("%s is not modelled by lsltest (set strict=False to record it)" % name)
            self.calls.append((script.name, name, coerced))
            result = None
        if ret_type == "void":
            return None
        if result is None:
            return default_value(ret_type)
        return coerce(result, ret_type)

    def record(self, script, name, *args):
        self.calls.append((script.name, name, list(args)))

    # --- chat ----------------------------------------------------------------

    def _speak(self, script, channel, text, kind, target=None):
        obj = script.obj
        self.chat.append(Chat(channel, obj.key, obj.name, text, kind, target, self.time))
        if kind == "ownersay" or kind == "im" or (kind == "regionsayto" and channel == 0):
            return
        self.deliver_chat(channel, obj.key, obj.name, text, source_obj=obj, target=target)

    def ll_Say(self, script, channel, text):
        self._speak(script, channel, text, "say")

    def ll_Whisper(self, script, channel, text):
        self._speak(script, channel, text, "whisper")

    def ll_Shout(self, script, channel, text):
        self._speak(script, channel, text, "shout")

    def ll_RegionSay(self, script, channel, text):
        if channel == 0:
            return
        self._speak(script, channel, text, "regionsay")

    def ll_RegionSayTo(self, script, target, channel, text):
        obj = next((o for o in self.objects if o.key == target), None)
        self._speak(script, channel, text, "regionsayto", target=obj if obj is not None else target)

    def ll_OwnerSay(self, script, text):
        self._speak(script, 0, text, "ownersay")

    def ll_InstantMessage(self, script, user, text):
        self.chat.append(Chat(0, script.obj.key, script.obj.name, text[:1023], "im", user, self.time))
        self.time += 2.0

    def ll_Email(self, script, address, subject, message):
        self.emails.append(SimpleNamespace(to=address, subject=subject, body=message, sender=script.obj.key))
        self.time += 20.0

    # --- listens ---------------------------------------------------------------

    def ll_Listen(self, script, channel, name, id_, msg):
        if len(script.listens) >= MAX_LISTENS:
            raise ScriptError("Too Many Listens")
        wanted = (channel, name, id_ if is_valid_key(id_) and id_ != NULL_KEY else "", msg)
        for handle, listen in script.listens.items():
            if (listen.channel, listen.name, listen.id, listen.msg) == wanted:
                return handle
        handle = script.next_listen
        script.next_listen += 1
        script.listens[handle] = SimpleNamespace(channel=wanted[0], name=wanted[1], id=wanted[2], msg=wanted[3], active=True)
        return handle

    def ll_ListenRemove(self, script, handle):
        script.listens.pop(handle, None)

    def ll_ListenControl(self, script, handle, active):
        if handle in script.listens:
            script.listens[handle].active = bool(active)

    # --- dialogs -------------------------------------------------------------

    def ll_Dialog(self, script, avatar, message, buttons, channel):
        if message == "" or len(message.encode("utf-8")) >= 512:
            self.chat.append(Chat(2147483647, script.obj.key, script.obj.name,
                                  "llDialog: must supply a message" if message == "" else "llDialog: message too long, must be less than 512 characters",
                                  "debug", None, self.time))
            return
        labels = [to_string(b) for b in buttons] or ["OK"]
        if len(labels) > 12:
            raise ScriptError("Script run-time error", "llDialog: too many buttons (%d)" % len(labels))
        for label in labels:
            if label == "" or len(label.encode("utf-8")) > 24:
                raise ScriptError("Script run-time error", "llDialog: button label must be 1 to 24 bytes: %r" % label)
        self.dialogs.append(SimpleNamespace(avatar=avatar, text=message, buttons=labels, channel=channel,
                                            object=script.obj.key, script=script.name, time=self.time))
        self.time += 1.0

    def ll_TextBox(self, script, avatar, message, channel):
        self.textboxes.append(SimpleNamespace(avatar=avatar, text=message, channel=channel, object=script.obj.key,
                                              script=script.name, time=self.time))
        self.time += 1.0

    # --- timers and time ---------------------------------------------------

    def ll_SetTimerEvent(self, script, seconds):
        if seconds <= 0.0:
            script.timer_interval = 0.0
            script.timer_due = None
        else:
            script.timer_interval = max(seconds, MIN_TIMER)
            script.timer_due = self.time + script.timer_interval

    def ll_Sleep(self, script, seconds):
        if seconds > 0:
            self.time += seconds
            self.fire_due()

    def ll_GetTime(self, script):
        return script.time_since_start()

    def ll_ResetTime(self, script):
        script.start_time = self.time

    def ll_GetAndResetTime(self, script):
        elapsed = script.time_since_start()
        script.start_time = self.time
        return elapsed

    def ll_GetUnixTime(self, script):
        return to_int32(int(self.epoch + self.time))

    def ll_GetTimestamp(self, script):
        return _time.strftime("%Y-%m-%dT%H:%M:%S", _time.gmtime(self.epoch + self.time)) + ".%06dZ" % int((self.time % 1) * 1e6)

    def ll_GetWallclock(self, script):
        return f32((self.epoch + self.time) % 86400)

    ll_GetGMTclock = ll_GetWallclock

    def ll_GetDate(self, script):
        return _time.strftime("%Y-%m-%d", _time.gmtime(self.epoch + self.time))

    # --- script control ----------------------------------------------------

    def ll_ResetScript(self, script):
        raise ResetSignal()

    def ll_ResetOtherScript(self, script, name):
        other = script.obj.script_named(name)
        if other is not None and other is not script:
            other.reset()

    def ll_GetScriptName(self, script):
        return script.name

    def ll_GetScriptState(self, script, name):
        other = script.obj.script_named(name)
        return int(other is not None and other.running and not other.dead)

    def ll_SetScriptState(self, script, name, running):
        other = script.obj.script_named(name)
        if other is not None:
            other.running = bool(running)

    def ll_GetStartParameter(self, script):
        return script.start_param

    def ll_GetFreeMemory(self, script):
        return max(0, script.memory_limit - script.memory_used())

    def ll_GetUsedMemory(self, script):
        return script.memory_used()

    def ll_GetMemoryLimit(self, script):
        return script.memory_limit

    def ll_SetMemoryLimit(self, script, limit):
        if limit < script.memory_used() or limit > 65536:
            return 0
        script.memory_limit = limit
        return 1

    def ll_ScriptProfiler(self, script, flags):
        pass

    def ll_GetSPMaxMemory(self, script):
        return script.memory_used()

    def ll_Die(self, script):
        script.obj.alive = False
        self.record(script, "llDie")

    # --- object and avatar getters -----------------------------------------

    def ll_GetOwner(self, script):
        return Key(script.obj.owner)

    def ll_GetKey(self, script):
        return Key(script.obj.key)

    def ll_GetObjectName(self, script):
        return script.obj.name

    def ll_SetObjectName(self, script, name):
        script.obj.name = name[:63]

    def ll_GetObjectDesc(self, script):
        return script.obj.desc

    def ll_SetObjectDesc(self, script, desc):
        script.obj.desc = desc[:127]

    def ll_GetPos(self, script):
        return script.obj.pos

    def ll_SetPos(self, script, pos):
        script.obj.pos = pos
        self.time += 0.2

    ll_GetLocalPos = ll_GetRootPosition = ll_GetPos

    def ll_GetRot(self, script):
        return script.obj.rot

    def ll_SetRot(self, script, rot):
        script.obj.rot = rot
        self.time += 0.2

    ll_GetLocalRot = ll_GetRootRotation = ll_GetRot

    def ll_SetLocalRot(self, script, rot):
        script.obj.rot = rot
        self.time += 0.2

    def ll_GetRegionName(self, script):
        return self.region_name

    def ll_GetRegionCorner(self, script):
        return Vector(256000.0, 256000.0, 0.0)

    def ll_GetEnv(self, script, name):
        return {"sim_version": self.sim_version, "sim_channel": "lsltest", "region_idle": "0",
                "simulator_hostname": "sim.invalid", "estate_name": "lsltest", "region_max_prims": "15000"}.get(name, "")

    def ll_GetLinkNumber(self, script):
        return script.link if script.obj.prims > 1 else 0

    def ll_GetNumberOfPrims(self, script):
        return script.obj.prims

    def ll_GetLinkName(self, script, link):
        return script.obj.name

    def ll_GetLinkKey(self, script, link):
        return Key(script.obj.key)

    def ll_GetAttached(self, script):
        return script.obj.attached

    def ll_SetText(self, script, text, color, alpha):
        script.obj.text = text.encode("utf-8")[:254].decode("utf-8", "ignore")

    def ll_GetObjectDetails(self, script, key, params):
        obj = next((o for o in self.objects if o.key == key), None)
        av = self.avatars.get(key)
        out = []
        for p in params:
            if obj is not None:
                out.append({1: obj.name, 2: obj.desc, 3: obj.pos, 4: obj.rot, 5: ZERO_VECTOR, 6: Key(obj.owner),
                            7: Key(obj.group), 8: Key(obj.owner), 12: 1, 13: obj.prims, 25: Key(obj.key)}.get(p, ""))
            elif av is not None:
                out.append({1: av.name, 2: "", 3: av.pos, 4: ZERO_ROTATION, 5: ZERO_VECTOR, 6: Key(av.key),
                            7: Key(av.group), 8: Key(av.key)}.get(p, ""))
        return out

    def ll_Key2Name(self, script, key):
        av = self.avatars.get(key)
        if av is not None:
            return av.name
        obj = next((o for o in self.objects if o.key == key), None)
        return obj.name if obj is not None else ""

    def ll_GetDisplayName(self, script, key):
        av = self.avatars.get(key)
        return av.display_name if av is not None else ""

    def ll_GetUsername(self, script, key):
        av = self.avatars.get(key)
        return av.username if av is not None else ""

    def ll_RequestDisplayName(self, script, key):
        query = self.new_key()
        av = self.avatars.get(key)
        script.post("dataserver", [query, av.display_name if av is not None else ""])
        return query

    def ll_RequestUsername(self, script, key):
        query = self.new_key()
        av = self.avatars.get(key)
        script.post("dataserver", [query, av.username if av is not None else ""])
        return query

    def ll_RequestAgentData(self, script, key, data):
        query = self.new_key()
        av = self.avatars.get(key)
        value = ""
        if av is not None:
            value = {1: "1" if av.online else "0", 2: av.name, 3: "2010-01-01", 8: "0"}.get(data, "")
        script.post("dataserver", [query, value])
        self.time += 0.1
        return query

    def ll_Name2Key(self, script, name):
        for av in self.avatars.values():
            if av.name == name or av.username == name:
                return Key(av.key)
        return NULL_KEY

    def ll_SameGroup(self, script, key):
        av = self.avatars.get(key)
        if av is None:
            return 0
        return int(av.group == script.obj.group)

    def ll_GetAgentSize(self, script, key):
        return Vector(0.45, 0.6, 1.9) if key in self.avatars else ZERO_VECTOR

    def ll_GetAgentInfo(self, script, key):
        return 0

    def ll_GetAgentList(self, script, scope, options):
        return [Key(k) for k in self.avatars]

    def ll_GetRegionAgentCount(self, script):
        return len(self.avatars)

    def ll_OverMyLand(self, script, key):
        return 1

    def ll_GetParcelDetails(self, script, pos, params):
        return [{0: "Test Parcel", 1: "", 2: Key(self.owner.key), 3: NULL_KEY, 4: 65536, 5: Key("")}.get(p, "") for p in params]

    # --- detected ------------------------------------------------------------

    def _detected(self, script, index, field, fallback):
        if index < 0 or index >= len(script.detected):
            return fallback
        return script.detected[index].get(field, fallback)

    def ll_DetectedKey(self, script, index):
        return Key(self._detected(script, index, "key", NULL_KEY))

    def ll_DetectedName(self, script, index):
        return self._detected(script, index, "name", "")

    def ll_DetectedOwner(self, script, index):
        return Key(self._detected(script, index, "owner", NULL_KEY))

    def ll_DetectedPos(self, script, index):
        return self._detected(script, index, "pos", ZERO_VECTOR)

    def ll_DetectedRot(self, script, index):
        return self._detected(script, index, "rot", ZERO_ROTATION)

    def ll_DetectedGroup(self, script, index):
        return int(self._detected(script, index, "group", NULL_KEY) == script.obj.group)

    def ll_DetectedType(self, script, index):
        return self._detected(script, index, "type", 0)

    def ll_DetectedVel(self, script, index):
        return self._detected(script, index, "vel", ZERO_VECTOR)

    def ll_DetectedLinkNumber(self, script, index):
        return 1 if script.detected else 0

    def ll_DetectedTouchFace(self, script, index):
        return 0 if script.detected else -1

    # --- inventory and notecards ---------------------------------------------

    def ll_GetInventoryType(self, script, name):
        item = script.obj.inventory.get(name)
        return item[0] if item else INVENTORY_NONE

    def ll_GetInventoryNumber(self, script, kind):
        return sum(1 for t, _ in script.obj.inventory.values() if kind == -1 or t == kind)

    def ll_GetInventoryName(self, script, kind, index):
        names = sorted(n for n, (t, _) in script.obj.inventory.items() if kind == -1 or t == kind)
        return names[index] if 0 <= index < len(names) else ""

    def ll_GetInventoryKey(self, script, name):
        return Key(str(uuid.UUID(int=pure.llHash(name) & 0xFFFFFFFF))) if name in script.obj.inventory else NULL_KEY

    def ll_GetInventoryCreator(self, script, name):
        return Key(self.owner.key) if name in script.obj.inventory else NULL_KEY

    def _notecard_lines(self, script, name):
        item = script.obj.inventory.get(name)
        if item is None or item[0] != INVENTORY_NOTECARD:
            return None
        return item[1].split("\n")

    def ll_GetNotecardLine(self, script, name, line):
        query = self.new_key()
        lines = self._notecard_lines(script, name)
        if lines is None:
            self.chat.append(Chat(2147483647, script.obj.key, script.obj.name, "Couldn't find notecard %s" % name, "debug", None, self.time))
            return NULL_KEY
        data = lines[line] if 0 <= line < len(lines) else EOF
        script.post("dataserver", [query, data.encode("utf-8")[:1024].decode("utf-8", "ignore")])
        self.time += 0.1
        return query

    def ll_GetNumberOfNotecardLines(self, script, name):
        query = self.new_key()
        lines = self._notecard_lines(script, name)
        if lines is None:
            return NULL_KEY
        script.post("dataserver", [query, str(len(lines))])
        self.time += 0.1
        return query

    def ll_GetNotecardLineSync(self, script, name, line):
        lines = self._notecard_lines(script, name)
        if lines is None:
            return NAK
        return lines[line] if 0 <= line < len(lines) else EOF

    def ll_GiveInventory(self, script, destination, name):
        self.record(script, "llGiveInventory", destination, name)

    def ll_RemoveInventory(self, script, name):
        script.obj.inventory.pop(name, None)

    # --- HTTP out -------------------------------------------------------------

    def ll_HTTPRequest(self, script, url, params, body):
        # the grid throttles an object to 25 requests per 20 seconds and returns NULL_KEY beyond that
        recent = [r for r in self.http_out if r.script.obj is script.obj and self.time - r.time < 20.0]
        if len(recent) >= 25:
            return NULL_KEY
        method = "GET"
        for i in range(0, len(params) - 1, 2):
            if params[i] == HTTP_METHOD:
                method = to_string(params[i + 1])
        key = self.new_key()
        self.http_out.append(HttpOutRequest(key, script, url, method, body, list(params), self.time))
        return key

    # --- HTTP in --------------------------------------------------------------

    def ll_RequestURL(self, script):
        key = self.new_key()
        url = self.grant_url(script)
        script.post("http_request", [key, URL_REQUEST_GRANTED, url])
        return key

    ll_RequestSecureURL = ll_RequestURL

    def ll_ReleaseURL(self, script, url):
        self.release_url(script, url)

    def ll_GetFreeURLs(self, script):
        return 38 - len(script.urls)

    def ll_HTTPResponse(self, script, request_id, status, body):
        pending = self.http_in_pending.get(request_id)
        if pending is not None:
            pending["status"] = status
            pending["body"] = body

    def ll_SetContentType(self, script, request_id, content_type):
        pending = self.http_in_pending.get(request_id)
        if pending is not None:
            pending["content_type"] = _CONTENT_TYPES.get(content_type, "text/plain")

    def ll_GetHTTPHeader(self, script, request_id, header):
        pending = self.http_in_pending.get(request_id)
        if pending is None:
            return ""
        return pending["headers"].get(header.lower(), "")

    # --- link messages ---------------------------------------------------------

    def ll_MessageLinked(self, script, link, num, text, id_):
        self.link_messages.append(SimpleNamespace(sender=script.name, link=link, num=num, str=text, id=id_, time=self.time))
        for other in script.obj.scripts:
            deliver = (
                link == LINK_SET
                or (link == LINK_ALL_OTHERS and other is not script)     # single prim: the other scripts
                or (link == LINK_ALL_CHILDREN and other.link > 1)
                or (link == LINK_THIS and other.obj is script.obj)
                or (link > 0 and link == other.link)
            )
            if deliver:
                other.post("link_message", [script.link, num, text, Key(id_)])

    # --- permissions and animations -----------------------------------------

    def ll_RequestPermissions(self, script, agent, perms):
        if perms == 0:
            return
        av = self.avatars.get(agent)
        if av is None:
            return
        policy = self.permission_policy
        if callable(policy):
            granted = int(policy(av, perms))
        else:
            granted = perms if policy else 0
        script.permissions = granted
        script.permissions_key = Key(agent) if granted else NULL_KEY
        script.post("run_time_permissions", [granted])

    def ll_GetPermissions(self, script):
        return script.permissions

    def ll_GetPermissionsKey(self, script):
        return Key(script.permissions_key)

    def ll_TakeControls(self, script, controls, accept, pass_on):
        self.record(script, "llTakeControls", controls, accept, pass_on)

    def ll_ReleaseControls(self, script):
        self.record(script, "llReleaseControls")

    def ll_StartAnimation(self, script, anim):
        self.record(script, "llStartAnimation", anim)

    def ll_StopAnimation(self, script, anim):
        self.record(script, "llStopAnimation", anim)

    # --- sensors --------------------------------------------------------------

    def ll_Sensor(self, script, name, id_, kind, range_, arc):
        self.deliver_sensor(script, name, id_, kind, range_, arc)

    def ll_SensorRepeat(self, script, name, id_, kind, range_, arc, rate):
        if rate <= 0:
            script.sensor_repeat = None
            return
        rate = max(rate, MIN_TIMER)
        script.sensor_repeat = SimpleNamespace(name=name, id=id_, type=kind, range=range_, arc=arc,
                                               rate=rate, due=self.time + rate)

    def ll_SensorRemove(self, script):
        script.sensor_repeat = None

    # --- linkset data ------------------------------------------------------------

    def _linkset_used(self, obj):
        used = sum(len(k.encode("utf-8")) + len(v.encode("utf-8")) for k, v in obj.linkset_data.items())
        used += sum(len(k.encode("utf-8")) + len(v[0].encode("utf-8")) + 32 for k, v in obj.linkset_protected.items())
        return used

    def _linkset_event(self, obj, action, name, value):
        for script in obj.scripts:
            script.post("linkset_data", [action, name, value])

    def ll_LinksetDataWrite(self, script, name, value):
        obj = script.obj
        if name == "":
            return 2
        if name in obj.linkset_protected:
            return 3
        if value == "":
            if name in obj.linkset_data:
                del obj.linkset_data[name]
                self._linkset_event(obj, 2, name, "")
                return 0
            return 4
        if obj.linkset_data.get(name) == value:
            return 5
        if self._linkset_used(obj) + len(name.encode("utf-8")) + len(value.encode("utf-8")) > LINKSET_DATA_SIZE:
            return 1
        obj.linkset_data[name] = value
        self._linkset_event(obj, 1, name, value)
        return 0

    def ll_LinksetDataWriteProtected(self, script, name, value, password):
        obj = script.obj
        if name == "":
            return 2
        if name in obj.linkset_data:
            return 3
        existing = obj.linkset_protected.get(name)
        if existing is not None and existing[1] != password:
            return 3
        if value == "":
            if existing is not None:
                del obj.linkset_protected[name]
                self._linkset_event(obj, 2, name, "")
                return 0
            return 4
        obj.linkset_protected[name] = (value, password)
        self._linkset_event(obj, 1, name, "")
        return 0

    def ll_LinksetDataRead(self, script, name):
        return script.obj.linkset_data.get(name, "")

    def ll_LinksetDataReadProtected(self, script, name, password):
        item = script.obj.linkset_protected.get(name)
        if item is None or item[1] != password:
            return ""
        return item[0]

    def ll_LinksetDataDelete(self, script, name):
        return self.ll_LinksetDataWrite(script, name, "")

    def ll_LinksetDataDeleteProtected(self, script, name, password):
        return self.ll_LinksetDataWriteProtected(script, name, "", password)

    def ll_LinksetDataReset(self, script):
        script.obj.linkset_data = {}
        script.obj.linkset_protected = {}
        self._linkset_event(script.obj, 0, "", "")

    def ll_LinksetDataAvailable(self, script):
        return LINKSET_DATA_SIZE - self._linkset_used(script.obj)

    def ll_LinksetDataCountKeys(self, script):
        return len(script.obj.linkset_data) + len(script.obj.linkset_protected)

    def ll_LinksetDataListKeys(self, script, start, count):
        keys = sorted(list(script.obj.linkset_data) + list(script.obj.linkset_protected))
        if count <= 0:
            return keys[start:]
        return keys[start:start + count]

    def ll_LinksetDataFindKeys(self, script, pattern, start, count):
        # A pattern that nests a quantifier inside a quantified group can take exponential time in Python's
        # backtracking engine (the grid uses a different one); such patterns match nothing here.
        if len(pattern) > MAX_PATTERN_LEN or re.search(r"\([^()]*[*+][^()]*\)[*+{]", pattern):
            return []
        try:
            rx = re.compile(pattern)
        except re.error:
            return []
        keys = sorted(k for k in list(script.obj.linkset_data) + list(script.obj.linkset_protected) if rx.search(k))
        return keys[start:start + count] if count > 0 else keys[start:]

    def ll_LinksetDataCountFound(self, script, pattern):
        return len(self.ll_LinksetDataFindKeys(script, pattern, 0, 0))

    def ll_LinksetDataDeleteFound(self, script, pattern, password):
        deleted = 0
        for name in self.ll_LinksetDataFindKeys(script, pattern, 0, 0):
            if name in script.obj.linkset_data:
                del script.obj.linkset_data[name]
                deleted += 1
            elif name in script.obj.linkset_protected and script.obj.linkset_protected[name][1] == password:
                del script.obj.linkset_protected[name]
                deleted += 1
        if deleted:
            self._linkset_event(script.obj, 3, "", "")
        return [deleted, 0]

    # --- randomness ------------------------------------------------------------

    def ll_Frand(self, script, mag):
        return f32(self.rng.random() * mag)

    def ll_GenerateKey(self, script):
        return self.new_key()

    def ll_ListRandomize(self, script, src, stride):
        if stride < 1:
            stride = 1
        if len(src) % stride != 0:
            return list(src)
        chunks = [src[i:i + stride] for i in range(0, len(src), stride)]
        self.rng.shuffle(chunks)
        return [v for c in chunks for v in c]

    # --- rezzing ---------------------------------------------------------------

    def ll_RezObject(self, script, inventory, pos, vel, rot, param):
        self.record(script, "llRezObject", inventory, pos, vel, rot, param)
        if inventory in script.obj.inventory and script.obj.inventory[inventory][0] == INVENTORY_OBJECT:
            child = self.rez(inventory, owner=self.avatars.get(script.obj.owner))
            child.pos = pos
            child.rot = rot
            child.start_param = param
            script.post("object_rez", [Key(child.key)])
        self.time += 0.1

    ll_RezAtRoot = ll_RezObject
