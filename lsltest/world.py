"""The things a script meets: avatars, objects, chat lines, outgoing HTTP requests, and the small helpers
that clip text, parse llHTTPRequest options, restrict linkset regexes and compute Second Life Time."""

import datetime
import re

from .limits import HTTP_CUSTOM_HEADER, MAX_PATTERN_LEN
from .values import Vector, to_string, ZERO_ROTATION, NULL_KEY


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
