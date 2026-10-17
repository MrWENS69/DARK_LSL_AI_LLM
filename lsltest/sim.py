"""The fake simulator: objects, avatars, clock, event queues, and every builtin that acts.

What it captures for assertions: chat (per channel, with the speaker), dialogs
and textboxes, listens, timers, link messages, HTTP requests out and responses
in, HTTP-in requests and the responses the script gave, permissions, linkset
data, hover text, inventory, and every call to a builtin it does not model
(recorded with its arguments, so nothing is silently lost).
"""

import datetime
import os
import random
import re
import time as _time
import uuid
from types import SimpleNamespace

from . import pure
from ._version import __version__
from .errors import LslSyntaxError, ResetSignal, ScriptError, UnsupportedError
from .interp import MAX_HANDLER_SECONDS, MAX_STATEMENTS, Script
from .signatures import CONSTANTS, SIGNATURES
from .values import (Key, Vector, f32, check_size, coerce, default_value, to_string, to_int32, type_of,
                     ZERO_VECTOR, ZERO_ROTATION, NULL_KEY, is_valid_key)


def _consts(*names):
    return tuple(CONSTANTS[n] for n in names)


# LSL constants come from builtins.txt through signatures.py: the handlers below name the ones they need.
EOF, NAK, DEBUG_CHANNEL, PUBLIC_CHANNEL = _consts("EOF", "NAK", "DEBUG_CHANNEL", "PUBLIC_CHANNEL")
INVENTORY_NOTECARD, INVENTORY_SCRIPT, INVENTORY_OBJECT, INVENTORY_NONE, INVENTORY_ALL = _consts(
    "INVENTORY_NOTECARD", "INVENTORY_SCRIPT", "INVENTORY_OBJECT", "INVENTORY_NONE", "INVENTORY_ALL")
URL_REQUEST_GRANTED, URL_REQUEST_DENIED = _consts("URL_REQUEST_GRANTED", "URL_REQUEST_DENIED")
HTTP_METHOD, HTTP_CUSTOM_HEADER, HTTP_BODY_MAXLENGTH, HTTP_BODY_TRUNCATED = _consts(
    "HTTP_METHOD", "HTTP_CUSTOM_HEADER", "HTTP_BODY_MAXLENGTH", "HTTP_BODY_TRUNCATED")
AGENT, ACTIVE, PASSIVE, SCRIPTED = _consts("AGENT", "ACTIVE", "PASSIVE", "SCRIPTED")
LINK_SET, LINK_ALL_OTHERS, LINK_ALL_CHILDREN, LINK_THIS = _consts(
    "LINK_SET", "LINK_ALL_OTHERS", "LINK_ALL_CHILDREN", "LINK_THIS")
CHANGED_REGION, CHANGED_REGION_START = _consts("CHANGED_REGION", "CHANGED_REGION_START")
(OBJECT_NAME, OBJECT_DESC, OBJECT_POS, OBJECT_ROT, OBJECT_VELOCITY, OBJECT_OWNER, OBJECT_GROUP, OBJECT_CREATOR,
 OBJECT_ROOT, OBJECT_PRIM_COUNT, OBJECT_TOTAL_SCRIPT_COUNT, OBJECT_RUNNING_SCRIPT_COUNT,
 OBJECT_ATTACHED_POINT) = _consts(
    "OBJECT_NAME", "OBJECT_DESC", "OBJECT_POS", "OBJECT_ROT", "OBJECT_VELOCITY", "OBJECT_OWNER", "OBJECT_GROUP",
    "OBJECT_CREATOR", "OBJECT_ROOT", "OBJECT_PRIM_COUNT", "OBJECT_TOTAL_SCRIPT_COUNT",
    "OBJECT_RUNNING_SCRIPT_COUNT", "OBJECT_ATTACHED_POINT")
DATA_ONLINE, DATA_NAME, DATA_BORN, DATA_PAYINFO = _consts("DATA_ONLINE", "DATA_NAME", "DATA_BORN", "DATA_PAYINFO")
(PARCEL_DETAILS_NAME, PARCEL_DETAILS_DESC, PARCEL_DETAILS_OWNER, PARCEL_DETAILS_GROUP, PARCEL_DETAILS_AREA,
 PARCEL_DETAILS_ID) = _consts("PARCEL_DETAILS_NAME", "PARCEL_DETAILS_DESC", "PARCEL_DETAILS_OWNER",
                              "PARCEL_DETAILS_GROUP", "PARCEL_DETAILS_AREA", "PARCEL_DETAILS_ID")
(LINKSETDATA_OK, LINKSETDATA_EMEMORY, LINKSETDATA_ENOKEY, LINKSETDATA_EPROTECTED, LINKSETDATA_NOTFOUND,
 LINKSETDATA_NOUPDATE) = _consts("LINKSETDATA_OK", "LINKSETDATA_EMEMORY", "LINKSETDATA_ENOKEY",
                                 "LINKSETDATA_EPROTECTED", "LINKSETDATA_NOTFOUND", "LINKSETDATA_NOUPDATE")
LINKSETDATA_RESET, LINKSETDATA_UPDATE, LINKSETDATA_DELETE, LINKSETDATA_MULTIDELETE = _consts(
    "LINKSETDATA_RESET", "LINKSETDATA_UPDATE", "LINKSETDATA_DELETE", "LINKSETDATA_MULTIDELETE")
_CONTENT_TYPES = {CONSTANTS[name]: mime for name, mime in (
    ("CONTENT_TYPE_TEXT", "text/plain"), ("CONTENT_TYPE_HTML", "text/html"), ("CONTENT_TYPE_XML", "application/xml"),
    ("CONTENT_TYPE_XHTML", "application/xhtml+xml"), ("CONTENT_TYPE_ATOM", "application/atom+xml"),
    ("CONTENT_TYPE_JSON", "application/json"), ("CONTENT_TYPE_LLSD", "application/llsd+xml"),
    ("CONTENT_TYPE_FORM", "application/x-www-form-urlencoded"), ("CONTENT_TYPE_RSS", "application/rss+xml"))
    if name in CONSTANTS}

# Grid limits that are not LSL constants.
MAX_LISTENS = 65              # llListen handles per script before "Too Many Listens"
MAX_URLS = 38                 # HTTP-in URLs per script, what llGetFreeURLs counts down from
LINKSET_DATA_SIZE = 131072    # bytes of linkset data per object
HTTP_BODY_DEFAULT = 2048      # bytes of an HTTP response body kept without HTTP_BODY_MAXLENGTH
MIN_TIMER = 0.022             # one simulator frame: shorter timers and sensor rates are rounded up to it
MAX_SLEEP = 31536000.0        # one year: llSleep never moves the clock further in one call
SENSOR_MAX = 32               # results of one sensor scan, nearest first (16 before March 2024)
RECORD_ONLY = frozenset(("llGiveInventory", "llTakeControls", "llReleaseControls", "llStartAnimation",
                         "llStopAnimation"))   # modelled as "record the call", even under strict

# lsltest's own guards, not grid limits.
MAX_RUN_ROUNDS = 10000        # run() rounds before the scripts are declared to be ping-ponging
MAX_TICK_STEPS = 100000       # timer or sensor steps a single tick() may run
MAX_RECORDS = 100000          # chat lines, dialogs, requests... of one kind the simulator keeps
MAX_PATTERN_LEN = 256         # llLinksetDataFindKeys patterns longer than this match nothing...
MAX_MATCH_LEN = 256           # ...and only the first characters of a key are matched
MAX_SCRIPT_BYTES = 1048576    # a .lsl file over 1 MB is refused


def _slt_offset(unix):
    """Seconds to add to UTC for Second Life Time: Pacific time with the US daylight saving rule."""
    utc = datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=unix)
    march = datetime.date(utc.year, 3, 8)
    start = datetime.datetime.combine(march + datetime.timedelta((6 - march.weekday()) % 7), datetime.time(10))
    november = datetime.date(utc.year, 11, 1)
    end = datetime.datetime.combine(november + datetime.timedelta((6 - november.weekday()) % 7), datetime.time(9))
    return -7 * 3600 if start <= utc < end else -8 * 3600   # 2:00 PST and 2:00 PDT, in UTC


def _clip(text, nbytes):
    """text cut to nbytes of UTF-8, as the grid cuts chat, hover text and HTTP bodies."""
    raw = text.encode("utf-8")
    return text if len(raw) <= nbytes else raw[:nbytes].decode("utf-8", "ignore")


def _http_options(params):
    """The HTTP_* flags of llHTTPRequest as {flag: value}, plus the (name, value) custom headers."""
    options, headers, i = {}, [], 0
    while i < len(params):
        if params[i] == HTTP_CUSTOM_HEADER:
            headers.append(tuple(to_string(v) for v in params[i + 1:i + 3]))
            i += 3
        else:
            if i + 1 < len(params):
                options[params[i]] = params[i + 1]
            i += 2
    return options, headers


def _safe_pattern(pattern):
    """A compiled regex for llLinksetDataFindKeys, or None when the pattern is refused.

    Python's backtracking engine takes exponential time on nested quantifiers and polynomial time on
    several unbounded ones, so groups, backreferences and more than one unbounded quantifier are
    refused; keys are matched on their first MAX_MATCH_LEN characters."""
    if len(pattern) > MAX_PATTERN_LEN or "(" in pattern or re.search(r"\\\d", pattern):
        return None
    if len(re.findall(r"[*+]|\{\d+,\}", pattern)) > 1:
        return None
    try:
        return re.compile(pattern)
    except re.error:
        return None


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
    def __init__(self, key, name, desc, owner, group):
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
        self.cached = set()                   # notecards the grid has in its cache (llGetNotecardLineSync)
        self.text = ""
        self.attached = 0
        self.wearer = None
        self.start_param = 0
        self.alive = True

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
    __slots__ = ("key", "script", "url", "method", "body", "params", "response", "time", "maxlen")

    def __init__(self, key, script, url, method, body, params, when, maxlen):
        self.key = key
        self.script = script
        self.url = url
        self.method = method
        self.body = body
        self.params = params
        self.response = None
        self.time = when
        self.maxlen = maxlen                  # HTTP_BODY_MAXLENGTH: the response body is cut there

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

    # --- world setup -------------------------------------------------------

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

    # --- running -------------------------------------------------------------

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

    # --- event injection ---------------------------------------------------

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
        text = _clip(text, 1024)
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

    def _drop_urls(self, obj):
        """Rez and region restart invalidate every HTTP-in URL of the object, as on the grid."""
        for script in obj.scripts:
            for url in list(script.urls):
                self.ll_ReleaseURL(script, url)

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

    def _post_prim(self, script, event, args):
        """Post an event to every script of the prim: http_response and dataserver reach them all."""
        for other in script.obj.scripts:
            other.post(event, args)

    def _answer(self, request, status, body, metadata=None):
        """Deliver the response: the body is cut at the request's HTTP_BODY_MAXLENGTH and the
        metadata then starts with [HTTP_BODY_TRUNCATED, limit]."""
        metadata = list(metadata or [])
        if len(body.encode("utf-8")) > request.maxlen:
            body = _clip(body, request.maxlen)
            metadata = [HTTP_BODY_TRUNCATED, request.maxlen] + metadata
        request.response = (status, body)
        self._http_pending.remove(request)
        self._post_prim(request.script, "http_response", [request.key, status, metadata, body])

    def http_respond(self, status=200, body="", request=None, metadata=None):
        """Answer a pending llHTTPRequest (the oldest unanswered one by default), then run."""
        if request is None:
            if not self._http_pending:
                raise AssertionError("no pending HTTP request")
            request = self._http_pending[0]
        self._answer(request, status, body, metadata)
        self.run()

    def auto_respond(self):
        """Called by run(): hand every unanswered request to http_handler. Returns how many it answered."""
        count = 0
        for request in list(self._http_pending):
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
        script.post("http_request", [key, method, _clip(body, 2048)])
        self.run()
        answer = self.http_in_pending.pop(key)
        if answer["status"] is None:
            return (500, "the script did not answer", "text/plain")
        return (answer["status"], answer["body"], answer["content_type"])

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
                    found.append(self._detected_record(avatar=av))
        if kind & (ACTIVE | PASSIVE | SCRIPTED):
            for obj in self.objects:
                if obj is script.obj or not obj.alive or obj.attached:
                    continue
                if pure.llVecDist(here, obj.pos) <= range_:
                    if name and obj.name != name:
                        continue
                    found.append(self._detected_record(obj=obj))
        found.sort(key=lambda d: pure.llVecDist(here, d["pos"]))
        found = found[:SENSOR_MAX]
        if found:
            script.post("sensor", [len(found)], found)
        else:
            script.post("no_sensor", [])

    def deliver_chat(self, channel, speaker_key, speaker_name, text, source_obj, target):
        for script in self.all_scripts():
            if source_obj is not None and script.obj is source_obj:
                continue                      # an object never hears itself
            if target is not None and script.obj.key != target and (
                    script.obj.wearer is None or script.obj.wearer.key != target):
                continue                      # llRegionSayTo: the target object, or the target avatar's attachments
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

    def _debug(self, script, text):
        """What the grid shouts on DEBUG_CHANNEL; visible in sim.chat with kind "debug"."""
        self._keep(self.chat, Chat(DEBUG_CHANNEL, script.obj.key, script.obj.name, text, "debug", None, self.time))

    # --- chat ----------------------------------------------------------------

    def _speak(self, script, channel, text, kind, target=None):
        obj = script.obj
        text = _clip(text, 1024)
        self._keep(self.chat, Chat(channel, obj.key, obj.name, text, kind, target, self.time))
        if kind == "ownersay" or (kind == "regionsayto" and channel == PUBLIC_CHANNEL):
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
        self._speak(script, channel, text, "regionsayto", target=Key(target))

    def ll_OwnerSay(self, script, text):
        self._speak(script, PUBLIC_CHANNEL, text, "ownersay")

    def ll_InstantMessage(self, script, user, text):
        self._keep(self.chat, Chat(PUBLIC_CHANNEL, script.obj.key, script.obj.name, _clip(text, 1023), "im",
                                   Key(user), self.time))
        self.time += 2.0

    def ll_Email(self, script, address, subject, message):
        self._keep(self.emails, SimpleNamespace(to=address, subject=subject, body=message, object=script.obj.key))
        self.time += 20.0

    # --- listens ---------------------------------------------------------------

    def ll_Listen(self, script, channel, name, id_, msg):
        wanted = (channel, name, id_ if is_valid_key(id_) and id_ != NULL_KEY else "", msg)
        for handle, listen in script.listens.items():
            if (listen.channel, listen.name, listen.id, listen.msg) == wanted:
                return handle                 # the same filter again: the existing handle, no new listen
        if len(script.listens) >= MAX_LISTENS:
            raise ScriptError("Too Many Listens")
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
        # every llDialog error is shouted on DEBUG_CHANNEL and no dialog is shown; the script goes on (wiki)
        if message == "" or len(message.encode("utf-8")) >= 512:
            self._debug(script, "llDialog: must supply a message" if message == ""
                        else "llDialog: message too long, must be less than 512 characters")
            return
        if any(type_of(b) != "string" for b in buttons):
            self._debug(script, "llDialog: all buttons must be strings")
            return
        labels = list(buttons) or ["OK"]
        if len(labels) > 12:
            self._debug(script, "llDialog: too many buttons [%d]" % len(labels))
            return
        if any(label == "" or len(label.encode("utf-8")) > 24 for label in labels):
            self._debug(script, "llDialog: button labels must be between 1 and 24 bytes")
            return
        self._keep(self.dialogs, SimpleNamespace(avatar=avatar, text=message, buttons=labels, channel=channel,
                                                 object=script.obj.key, script=script, time=self.time))
        self.time += 1.0

    def ll_TextBox(self, script, avatar, message, channel):
        self._keep(self.textboxes, SimpleNamespace(avatar=avatar, text=message, channel=channel,
                                                   object=script.obj.key, script=script, time=self.time))
        self.time += 1.0

    # --- timers and time ---------------------------------------------------

    def ll_SetTimerEvent(self, script, seconds):
        if not seconds > 0.0:                 # also NaN
            script.timer_interval = 0.0
            script.timer_due = None
        else:
            script.timer_interval = max(seconds, MIN_TIMER)
            script.timer_due = self.time + script.timer_interval

    def ll_Sleep(self, script, seconds):
        if seconds > 0:
            self.time += min(seconds, MAX_SLEEP)   # due timers fire after the handler, as on the grid

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

    def _utc(self):
        try:
            return _time.gmtime(self.epoch + self.time)
        except (OSError, OverflowError, ValueError):   # the clock was pushed beyond what the platform converts
            return _time.gmtime(0)

    def ll_GetTimestamp(self, script):
        return _time.strftime("%Y-%m-%dT%H:%M:%S", self._utc()) + ".%06dZ" % int((self.time % 1) * 1e6)

    def ll_GetWallclock(self, script):
        return f32(int((self.epoch + self.time + _slt_offset(self.epoch + self.time)) % 86400))

    def ll_GetGMTclock(self, script):
        return f32((self.epoch + self.time) % 86400)

    def ll_GetDate(self, script):
        return _time.strftime("%Y-%m-%d", self._utc())

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
        self.record_call(script, "llDie")

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

    ll_SetLocalRot = ll_SetRot

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
        script.obj.text = _clip(text, 254)

    def ll_GetObjectDetails(self, script, key, params):
        obj = next((o for o in self.objects if o.key == key), None)
        av = self.avatars.get(key)
        if obj is not None:
            details = {OBJECT_NAME: obj.name, OBJECT_DESC: obj.desc, OBJECT_POS: obj.pos, OBJECT_ROT: obj.rot,
                       OBJECT_VELOCITY: ZERO_VECTOR, OBJECT_OWNER: Key(obj.owner), OBJECT_GROUP: Key(obj.group),
                       OBJECT_CREATOR: Key(obj.owner), OBJECT_ROOT: Key(obj.key), OBJECT_PRIM_COUNT: obj.prims,
                       OBJECT_TOTAL_SCRIPT_COUNT: len(obj.scripts),
                       OBJECT_RUNNING_SCRIPT_COUNT: sum(1 for s in obj.scripts if s.running and not s.dead),
                       OBJECT_ATTACHED_POINT: obj.attached}
        elif av is not None:
            details = {OBJECT_NAME: av.name, OBJECT_DESC: "", OBJECT_POS: av.pos, OBJECT_ROT: ZERO_ROTATION,
                       OBJECT_VELOCITY: ZERO_VECTOR, OBJECT_OWNER: Key(av.key), OBJECT_GROUP: Key(av.group),
                       OBJECT_CREATOR: Key(av.key), OBJECT_ROOT: Key(av.key), OBJECT_ATTACHED_POINT: 0}
        else:
            return []
        return [details.get(p, "") for p in params]

    def ll_Key2Name(self, script, key):
        av = self.avatars.get(key)
        if av is not None:
            return av.name
        obj = next((o for o in self.objects if o.key == key), None)
        return obj.name if obj is not None else ""

    def _avatar_attr(self, key, attr):
        av = self.avatars.get(key)
        return getattr(av, attr) if av is not None else ""

    def _dataserver(self, script, value):
        """The grid answers asynchronous lookups with a dataserver event in every script of the prim."""
        query = self.new_key()
        self._post_prim(script, "dataserver", [query, value])
        self.time += 0.1
        return query

    def ll_GetDisplayName(self, script, key):
        return self._avatar_attr(key, "display_name")

    def ll_GetUsername(self, script, key):
        return self._avatar_attr(key, "username")

    def ll_RequestDisplayName(self, script, key):
        return self._dataserver(script, self._avatar_attr(key, "display_name"))

    def ll_RequestUsername(self, script, key):
        return self._dataserver(script, self._avatar_attr(key, "username"))

    def ll_RequestAgentData(self, script, key, data):
        av = self.avatars.get(key)
        value = ""
        if av is not None:
            value = {DATA_ONLINE: "1" if av.online else "0", DATA_NAME: av.name, DATA_BORN: "2010-01-01",
                     DATA_PAYINFO: "0"}.get(data, "")
        return self._dataserver(script, value)

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
        details = {PARCEL_DETAILS_NAME: "Test Parcel", PARCEL_DETAILS_DESC: "", PARCEL_DETAILS_OWNER: Key(self.owner.key),
                   PARCEL_DETAILS_GROUP: NULL_KEY, PARCEL_DETAILS_AREA: 65536, PARCEL_DETAILS_ID: Key("")}
        return [details.get(p, "") for p in params]

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
        return sum(1 for t, _ in script.obj.inventory.values() if kind == INVENTORY_ALL or t == kind)

    def ll_GetInventoryName(self, script, kind, index):
        names = sorted(n for n, (t, _) in script.obj.inventory.items() if kind == INVENTORY_ALL or t == kind)
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
        lines = self._notecard_lines(script, name)
        if lines is None:
            self._debug(script, "Couldn't find notecard %s" % name)
            return NULL_KEY
        script.obj.cached.add(name)           # an asynchronous read puts the notecard in the grid's cache
        return self._dataserver(script, _clip(lines[line] if 0 <= line < len(lines) else EOF, 1024))

    def ll_GetNumberOfNotecardLines(self, script, name):
        lines = self._notecard_lines(script, name)
        if lines is None:
            return NULL_KEY
        script.obj.cached.add(name)
        return self._dataserver(script, str(len(lines)))

    def ll_GetNotecardLineSync(self, script, name, line):
        lines = self._notecard_lines(script, name)
        if lines is None or name not in script.obj.cached:
            return NAK                        # not cached yet: the script must fall back to llGetNotecardLine
        return lines[line] if 0 <= line < len(lines) else EOF

    def ll_RemoveInventory(self, script, name):
        script.obj.inventory.pop(name, None)

    # --- HTTP out -------------------------------------------------------------

    def ll_HTTPRequest(self, script, url, params, body):
        options, headers = _http_options(params)
        if any(h and h[0].lower() == "content-type" for h in headers):
            raise ScriptError("Script run-time error",
                              "llHTTPRequest: Content-Type is set with HTTP_MIMETYPE, not with HTTP_CUSTOM_HEADER")
        # the grid throttles an object to 25 requests per 20 seconds and returns NULL_KEY beyond that
        recent = 0
        for r in reversed(self.http_out):
            if self.time - r.time >= 20.0:
                break
            if r.script.obj is script.obj:
                recent += 1
        if recent >= 25:
            return NULL_KEY
        method = to_string(options.get(HTTP_METHOD, "GET"))
        maxlen = options.get(HTTP_BODY_MAXLENGTH, HTTP_BODY_DEFAULT)
        if type_of(maxlen) != "integer" or maxlen <= 0:
            maxlen = HTTP_BODY_DEFAULT
        key = self.new_key()
        request = HttpOutRequest(key, script, url, method, body, list(params), self.time, maxlen)
        self._keep(self.http_out, request)
        self._http_pending.append(request)
        return key

    # --- HTTP in --------------------------------------------------------------

    def ll_RequestURL(self, script):
        key = self.new_key()
        if len(script.urls) >= MAX_URLS:
            script.post("http_request", [key, URL_REQUEST_DENIED, ""])
            return key
        url = "http://sim.invalid/cap/%s" % self.new_key()
        self.http_in[url] = script
        script.urls.add(url)
        script.post("http_request", [key, URL_REQUEST_GRANTED, url])
        return key

    ll_RequestSecureURL = ll_RequestURL

    def ll_ReleaseURL(self, script, url):
        self.http_in.pop(url, None)
        script.urls.discard(url)

    def ll_GetFreeURLs(self, script):
        return MAX_URLS - len(script.urls)

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
        return pending["headers"].get(header, "")      # the name must be lower case or it matches nothing (wiki)

    # --- link messages ---------------------------------------------------------

    def ll_MessageLinked(self, script, link, num, text, id_):
        """Delivery is by prim: every script of a target prim gets the message, the sender included."""
        sender = self.ll_GetLinkNumber(script)
        self._keep(self.link_messages, SimpleNamespace(script=script, sender=sender, link=link, num=num, str=text,
                                                       id=id_, time=self.time))
        for other in script.obj.scripts:
            target = self.ll_GetLinkNumber(other)
            same_prim = target == sender
            deliver = (
                link == LINK_SET
                or (link == LINK_ALL_OTHERS and not same_prim)
                or (link == LINK_ALL_CHILDREN and target > 1)
                or (link == LINK_THIS and same_prim)
                or (link >= 0 and link == target)
                or (script.obj.prims == 1 and link in (0, 1))      # an unlinked prim answers to 0 and 1
            )
            if deliver:
                other.post("link_message", [sender, num, text, Key(id_)])

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
        # the answer comes with the run_time_permissions event, never inside the calling handler
        script.pending_permissions = (granted, Key(agent) if granted else NULL_KEY)
        script.post("run_time_permissions", [granted])

    def ll_GetPermissions(self, script):
        return script.permissions

    def ll_GetPermissionsKey(self, script):
        return Key(script.permissions_key)

    # --- sensors --------------------------------------------------------------

    def ll_Sensor(self, script, name, id_, kind, range_, arc):
        self.deliver_sensor(script, name, id_, kind, range_, arc)

    def ll_SensorRepeat(self, script, name, id_, kind, range_, arc, rate):
        if not rate > 0:                      # also NaN
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

    def _linkset_fits(self, obj, name, value, old):
        """Whether writing value under name (replacing old, "" when new) stays within LINKSET_DATA_SIZE."""
        used = self._linkset_used(obj)
        if old:
            used -= len(name.encode("utf-8")) + len(old.encode("utf-8"))
        return used + len(name.encode("utf-8")) + len(value.encode("utf-8")) <= LINKSET_DATA_SIZE

    def _linkset_keys(self, obj, pattern=None):
        """The keys, sorted, optionally those a (restricted) regex matches."""
        keys = list(obj.linkset_data) + list(obj.linkset_protected)
        if pattern is not None:
            rx = _safe_pattern(pattern)
            if rx is None:
                return []
            keys = [k for k in keys if rx.search(k[:MAX_MATCH_LEN])]
        return sorted(keys)

    @staticmethod
    def _page(keys, start, count):
        return keys[start:start + count] if count > 0 else keys[start:]

    def ll_LinksetDataWrite(self, script, name, value):
        obj = script.obj
        if name == "":
            return LINKSETDATA_ENOKEY
        if name in obj.linkset_protected:
            return LINKSETDATA_EPROTECTED
        old = obj.linkset_data.get(name)
        if value == "":
            if old is None:
                return LINKSETDATA_NOTFOUND
            del obj.linkset_data[name]
            self._linkset_event(obj, LINKSETDATA_DELETE, name, "")
            return LINKSETDATA_OK
        if old == value:
            return LINKSETDATA_NOUPDATE
        if not self._linkset_fits(obj, name, value, old or ""):
            return LINKSETDATA_EMEMORY
        obj.linkset_data[name] = value
        self._linkset_event(obj, LINKSETDATA_UPDATE, name, value)
        return LINKSETDATA_OK

    def ll_LinksetDataWriteProtected(self, script, name, value, password):
        obj = script.obj
        if name == "":
            return LINKSETDATA_ENOKEY
        if name in obj.linkset_data:
            return LINKSETDATA_EPROTECTED
        existing = obj.linkset_protected.get(name)
        if existing is not None and existing[1] != password:
            return LINKSETDATA_EPROTECTED
        if value == "":
            if existing is None:
                return LINKSETDATA_NOTFOUND
            del obj.linkset_protected[name]
            self._linkset_event(obj, LINKSETDATA_DELETE, name, "")
            return LINKSETDATA_OK
        if existing is not None and existing[0] == value:
            return LINKSETDATA_NOUPDATE
        if not self._linkset_fits(obj, name, value, existing[0] if existing else ""):
            return LINKSETDATA_EMEMORY
        obj.linkset_protected[name] = (value, password)
        self._linkset_event(obj, LINKSETDATA_UPDATE, name, "")
        return LINKSETDATA_OK

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
        self._linkset_event(script.obj, LINKSETDATA_RESET, "", "")

    def ll_LinksetDataAvailable(self, script):
        return LINKSET_DATA_SIZE - self._linkset_used(script.obj)

    def ll_LinksetDataCountKeys(self, script):
        return len(self._linkset_keys(script.obj))

    def ll_LinksetDataListKeys(self, script, start, count):
        return self._page(self._linkset_keys(script.obj), start, count)

    def ll_LinksetDataFindKeys(self, script, pattern, start, count):
        return self._page(self._linkset_keys(script.obj, pattern), start, count)

    def ll_LinksetDataCountFound(self, script, pattern):
        return len(self._linkset_keys(script.obj, pattern))

    def ll_LinksetDataDeleteFound(self, script, pattern, password):
        obj = script.obj
        deleted = refused = 0
        for name in self._linkset_keys(obj, pattern):
            if name in obj.linkset_data:
                del obj.linkset_data[name]
                deleted += 1
            elif obj.linkset_protected[name][1] == password:
                del obj.linkset_protected[name]
                deleted += 1
            else:
                refused += 1
        if deleted:
            self._linkset_event(obj, LINKSETDATA_MULTIDELETE, "", "")
        return [deleted, refused]

    # --- randomness ------------------------------------------------------------

    def ll_Frand(self, script, mag):
        return f32(self.rng.random() * mag)

    def ll_GenerateKey(self, script):
        return self.new_key()

    def ll_ListRandomize(self, script, src, stride):
        pieces = pure.chunks(src, stride)
        if pieces is None:
            return list(src)
        self.rng.shuffle(pieces)
        return [v for c in pieces for v in c]

    # --- rezzing ---------------------------------------------------------------

    def ll_RezObject(self, script, inventory, pos, vel, rot, param):
        self.record_call(script, "llRezObject", inventory, pos, vel, rot, param)
        if inventory in script.obj.inventory and script.obj.inventory[inventory][0] == INVENTORY_OBJECT:
            child = self.rez(inventory, owner=self.avatars.get(script.obj.owner))
            child.pos = pos
            child.rot = rot
            child.start_param = param
            script.post("object_rez", [Key(child.key)])
        self.time += 0.1

    ll_RezAtRoot = ll_RezObject
