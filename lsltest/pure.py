"""Pure builtins: functions that compute a result without touching the simulator.

Names match builtins.txt exactly (llAbs, llList2String...); the simulator looks a
function up here when it has no ll_Xxx handler of its own.

Each entry maps the LSL name to a Python callable taking the LSL argument
values (already coerced to the declared parameter types) and returning an
LSL value. Functions that act on the world live in sim.py.
"""

import base64
import hashlib
import hmac
import json
import math
import re
import urllib.parse

from .errors import ScriptError
from .signatures import CONSTANTS
from .values import (Key, Vector, Rotation, f32, to_int32, to_string, type_of, cast, default_value, format_float,
                     join_checked, rot_mul, vec_rotate, MAX_VALUE_LEN, ZERO_VECTOR, ZERO_ROTATION)

# LSL constants come from builtins.txt, never from a literal here.
JSON_INVALID, JSON_OBJECT, JSON_ARRAY, JSON_NUMBER, JSON_STRING, JSON_NULL, JSON_TRUE, JSON_FALSE, JSON_DELETE = (
    CONSTANTS[n] for n in ("JSON_INVALID", "JSON_OBJECT", "JSON_ARRAY", "JSON_NUMBER", "JSON_STRING", "JSON_NULL",
                           "JSON_TRUE", "JSON_FALSE", "JSON_DELETE"))
TYPE_INVALID, TYPE_INTEGER, TYPE_FLOAT, TYPE_STRING, TYPE_KEY, TYPE_VECTOR, TYPE_ROTATION = (
    CONSTANTS[n] for n in ("TYPE_INVALID", "TYPE_INTEGER", "TYPE_FLOAT", "TYPE_STRING", "TYPE_KEY", "TYPE_VECTOR",
                           "TYPE_ROTATION"))
STRING_TRIM_HEAD, STRING_TRIM_TAIL = CONSTANTS["STRING_TRIM_HEAD"], CONSTANTS["STRING_TRIM_TAIL"]
JSON_APPEND = CONSTANTS["JSON_APPEND"]
_TYPE_CODES = {"integer": TYPE_INTEGER, "float": TYPE_FLOAT, "string": TYPE_STRING, "key": TYPE_KEY,
               "vector": TYPE_VECTOR, "rotation": TYPE_ROTATION}
_LIST_STATS = {CONSTANTS[name]: name for name in (
    "LIST_STAT_RANGE", "LIST_STAT_MIN", "LIST_STAT_MAX", "LIST_STAT_MEAN", "LIST_STAT_MEDIAN", "LIST_STAT_STD_DEV",
    "LIST_STAT_SUM", "LIST_STAT_SUM_SQUARES", "LIST_STAT_NUM_COUNT", "LIST_STAT_GEOMETRIC_MEAN")}

_HASHES = {"md5": hashlib.md5, "sha1": hashlib.sha1, "sha224": hashlib.sha224, "sha256": hashlib.sha256,
           "sha384": hashlib.sha384, "sha512": hashlib.sha512}


def _b64decode(text):
    return base64.b64decode(text + "=" * (-len(text) % 4))


def _clamp1(x):
    return max(-1.0, min(1.0, x))


_JSON_NUMBER = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$")


class _RawNumber(str):
    """A number given as LSL text: written to JSON as it was typed, not reformatted."""
    __slots__ = ()


def _dumps(value):
    """JSON text as the grid writes it: compact, LSL floats with six decimals."""
    if isinstance(value, _RawNumber):
        return str(value)
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format_float(value, 6)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(_dumps(v) for v in value) + "]"
    return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + _dumps(v) for k, v in value.items()) + "}"


# --- lists ---------------------------------------------------------------------

def _norm_range(length, start, end):
    """LSL inclusive range with negative indexes; returns a list of indexes or None for empty."""
    if length == 0:
        return []
    if start < 0:
        start += length
    if end < 0:
        end += length
    if start <= end:
        start = max(start, 0)
        end = min(end, length - 1)
        return list(range(start, end + 1)) if start <= end else []
    # start > end: exclusion, [0..end] + [start..length-1]
    head = list(range(0, min(end, length - 1) + 1)) if end >= 0 else []
    tail = list(range(max(start, 0), length)) if start < length else []
    return head + tail


def llGetListLength(src):
    return len(src)


def _list_get(src, index, type_name):
    if index < 0:
        index += len(src)
    if index < 0 or index >= len(src):
        return default_value(type_name)
    value = src[index]
    t = type_of(value)
    if t == type_name:
        return value
    try:
        if type_name == "integer":
            return cast(value, "integer") if t in ("float", "string", "key") else 0
        if type_name == "float":
            return cast(value, "float") if t in ("integer", "string", "key") else 0.0
        if type_name == "string":
            return to_string(value)
        if type_name == "key":
            return Key(value) if t == "string" else Key("")
        if type_name == "vector":
            return ZERO_VECTOR            # no conversion from a string here (wiki: llList2Vector)
        if type_name == "rotation":
            return ZERO_ROTATION
    except ScriptError:
        pass
    return default_value(type_name)


def llList2Integer(src, index):
    return _list_get(src, index, "integer")


def llList2Float(src, index):
    return _list_get(src, index, "float")


def llList2String(src, index):
    return _list_get(src, index, "string")


def llList2Key(src, index):
    return _list_get(src, index, "key")


def llList2Vector(src, index):
    return _list_get(src, index, "vector")


def llList2Rot(src, index):
    return _list_get(src, index, "rotation")


def llGetListEntryType(src, index):
    if index < 0:
        index += len(src)
    if index < 0 or index >= len(src):
        return TYPE_INVALID
    return _TYPE_CODES[type_of(src[index])]


def llList2List(src, start, end):
    return [src[i] for i in _norm_range(len(src), start, end)]


def llDeleteSubList(src, start, end):
    keep = set(_norm_range(len(src), start, end))
    return [v for i, v in enumerate(src) if i not in keep]


def llListInsertList(dest, src, start):
    if start < 0:
        start += len(dest)
    start = max(0, min(start, len(dest)))
    return dest[:start] + src + dest[start:]


def llListReplaceList(dest, src, start, end):
    if not dest:
        return list(src)
    if start < 0:
        start += len(dest)
    if end < 0:
        end += len(dest)
    if start <= end:
        return dest[:max(start, 0)] + src + dest[end + 1:]
    # exclusion range: keep the middle, replace both ends
    return src + dest[end + 1:start]


def _same(a, b):
    return type_of(a) == type_of(b) and (float(a) == float(b) if type_of(a) == "float" else a == b)


def llListFindList(src, test):
    if not test:
        return 0
    n = len(test)
    for i in range(len(src) - n + 1):
        if all(_same(src[i + j], test[j]) for j in range(n)):
            return i
    return -1


def llListFindStrided(src, test, start, end, stride):
    # stride positions are counted from the start of the list, as in llList2ListStrided
    if stride < 1:
        stride = 1
    n = len(test)
    for i in _norm_range(len(src), start, end):
        if i % stride == 0 and i + n <= len(src):
            if all(_same(src[i + j], test[j]) for j in range(n)):
                return i
    return -1


def _sort_key(value):
    t = type_of(value)
    if t in ("integer", "float"):
        return (0, float(value), "")
    if t in ("string", "key"):
        return (1, 0.0, str(value))
    if t in ("vector", "rotation"):
        return (2, math.sqrt(sum(c * c for c in value[:3])), "")
    return (3, 0.0, "")


def chunks(src, stride):
    """src cut into stride-long pieces, or None when its length is not a multiple of the stride."""
    if stride < 1:
        stride = 1
    if len(src) % stride != 0:
        return None
    return [src[i:i + stride] for i in range(0, len(src), stride)]


def llListSort(src, stride, ascending):
    pieces = chunks(src, stride)
    if pieces is None:
        return list(src)
    pieces.sort(key=lambda c: _sort_key(c[0]), reverse=not ascending)
    return [v for c in pieces for v in c]


def llList2ListStrided(src, start, end, stride):
    return llList2ListSlice(src, start, end, stride, 0)


def llList2ListSlice(src, start, end, stride, slice_index):
    if stride < 1:
        stride = 1
    if slice_index < 0:
        slice_index += stride
    return [src[i] for i in _norm_range(len(src), start, end) if i % stride == slice_index]


def _stat_std_dev(nums):
    n = len(nums)
    if n < 2:
        return 0.0
    mean = sum(nums) / n
    return math.sqrt(sum((x - mean) ** 2 for x in nums) / (n - 1))


def _stat_median(nums):
    s = sorted(nums)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _stat_geometric_mean(nums):
    if any(x <= 0 for x in nums):
        return 0.0
    return math.exp(sum(math.log(x) for x in nums) / len(nums))


_STAT_FUNCTIONS = {
    "LIST_STAT_RANGE": lambda nums: max(nums) - min(nums),
    "LIST_STAT_MIN": min,
    "LIST_STAT_MAX": max,
    "LIST_STAT_MEAN": lambda nums: sum(nums) / len(nums),
    "LIST_STAT_MEDIAN": _stat_median,
    "LIST_STAT_STD_DEV": _stat_std_dev,
    "LIST_STAT_SUM": sum,
    "LIST_STAT_SUM_SQUARES": lambda nums: sum(x * x for x in nums),
    "LIST_STAT_NUM_COUNT": len,
    "LIST_STAT_GEOMETRIC_MEAN": _stat_geometric_mean,
}


def llListStatistics(operation, src):
    nums = [float(v) for v in src if type_of(v) in ("integer", "float")]
    name = _LIST_STATS.get(operation)
    if not nums or name is None:
        return 0.0
    return f32(_STAT_FUNCTIONS[name](nums))


def llDumpList2String(src, separator):
    return join_checked(separator, [to_string(v) for v in src])


def llList2CSV(src):
    return join_checked(", ", [to_string(v) for v in src])


def llCSV2List(src):
    out = []
    current = []
    depth = 0
    for ch in src:
        if ch == "<":
            depth += 1
        elif ch == ">" and depth > 0:
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(current))
            current = []
        else:
            current.append(ch)
    out.append("".join(current))
    return [item[1:] if item.startswith(" ") else item for item in out]


def _split_keep(src, separators, spacers, keep_nulls):
    separators = [s for s in separators[:8] if type_of(s) in ("string", "key") and s != ""]
    spacers = [s for s in spacers[:8] if type_of(s) in ("string", "key") and s != ""]
    out = []
    i = 0
    start = 0
    n = len(src)
    while i < n:
        matched = False
        for sep in separators:
            if src.startswith(sep, i):
                out.append(src[start:i])
                i += len(sep)
                start = i
                matched = True
                break
        if matched:
            continue
        for sp in spacers:
            if src.startswith(sp, i):
                out.append(src[start:i])
                out.append(sp)
                i += len(sp)
                start = i
                matched = True
                break
        if matched:
            continue
        i += 1
    out.append(src[start:])
    if not keep_nulls:
        out = [s for s in out if s != ""]
    return out


def llParseString2List(src, separators, spacers):
    return _split_keep(src, separators, spacers, False)


def llParseStringKeepNulls(src, separators, spacers):
    return _split_keep(src, separators, spacers, True)


# --- strings -------------------------------------------------------------------

def llStringLength(src):
    return len(src)


def llGetSubString(src, start, end):
    return "".join(src[i] for i in _norm_range(len(src), start, end))


def llDeleteSubString(src, start, end):
    drop = set(_norm_range(len(src), start, end))
    return "".join(ch for i, ch in enumerate(src) if i not in drop)


def llInsertString(dst, position, src):
    position = max(0, min(position, len(dst)))
    return dst[:position] + src + dst[position:]


def llSubStringIndex(src, pattern):
    if pattern == "":
        return 0
    return src.find(pattern)


def llStringTrim(src, trim_type):
    if trim_type & STRING_TRIM_HEAD:
        src = src.lstrip(" \t\n\r")
    if trim_type & STRING_TRIM_TAIL:
        src = src.rstrip(" \t\n\r")
    return src


def llToUpper(src):
    return src.upper()


def llToLower(src):
    return src.lower()


def llReplaceSubString(src, pattern, replacement, count):
    if pattern == "":
        return src
    hits = src.count(pattern) if count == 0 else min(src.count(pattern), abs(count))
    if len(src) + hits * (len(replacement) - len(pattern)) > MAX_VALUE_LEN:
        raise ScriptError("Stack-Heap Collision", "value over %d items" % MAX_VALUE_LEN)
    if count == 0:
        return src.replace(pattern, replacement)
    if count > 0:
        return src.replace(pattern, replacement, count)
    # negative: replace from the end
    parts = src.rsplit(pattern, -count)
    return replacement.join(parts)


def llEscapeURL(url):
    return urllib.parse.quote(url.encode("utf-8"), safe="")


def llUnescapeURL(url):
    return urllib.parse.unquote(url, errors="replace").replace("\x00", "")


def llStringToBase64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def llBase64ToString(text):
    try:
        return _b64decode(text).decode("utf-8", "replace").replace("\x00", "")
    except (ValueError, UnicodeDecodeError):
        return ""


def llIntegerToBase64(number):
    return base64.b64encode((number & 0xFFFFFFFF).to_bytes(4, "big")).decode("ascii")


def llBase64ToInteger(text):
    try:
        raw = _b64decode(text)[:4].ljust(4, b"\0")
        return to_int32(int.from_bytes(raw, "big"))
    except ValueError:
        return 0


def llXorBase64(s1, s2):
    try:
        a = _b64decode(s1)
        b = _b64decode(s2)
    except ValueError:
        return ""
    if not b:
        return s1
    out = bytes(x ^ b[i % len(b)] for i, x in enumerate(a))
    return base64.b64encode(out).decode("ascii")


def llMD5String(src, nonce):
    return hashlib.md5(("%s:%d" % (src, nonce)).encode("utf-8")).hexdigest()


def llSHA1String(src):
    return hashlib.sha1(src.encode("utf-8")).hexdigest()


def llSHA256String(src):
    return hashlib.sha256(src.encode("utf-8")).hexdigest()


def llHMAC(authkey, message, hashalg):
    alg = _HASHES.get(hashalg.lower())
    if alg is None:
        return ""
    return base64.b64encode(hmac.new(authkey.encode("utf-8"), message.encode("utf-8"), alg).digest()).decode("ascii")


def llComputeHash(data, algorithm):
    alg = _HASHES.get(algorithm.lower())
    if alg is None:
        return ""
    return alg(data.encode("utf-8")).hexdigest()


def llChar(code):
    if code <= 0 or code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
        return ""
    return chr(code)


def llOrd(text, index):
    if index < 0:
        index += len(text)
    if index < 0 or index >= len(text):
        return 0
    return ord(text[index])


def llHash(text):
    h = 0
    for ch in text:
        h = (h * 65599 + ord(ch)) & 0xFFFFFFFF
    return to_int32(h)


# --- JSON ----------------------------------------------------------------------

def _json_value_from_lsl(value, numeric_strings=False):
    """An LSL value as a JSON node. numeric_strings: a string that reads as a number becomes a number
    (llJsonSetValue does that, llList2Json keeps it a string: wiki, BUG-6284)."""
    t = type_of(value)
    if t == "integer":
        return value
    if t == "float":
        return value
    if t in ("string", "key"):
        s = str(value)
        if s == JSON_TRUE:
            return True
        if s == JSON_FALSE:
            return False
        if s == JSON_NULL:
            return None
        stripped = s.strip()
        if numeric_strings and _JSON_NUMBER.match(stripped):
            return _RawNumber(stripped)       # "10" is stored as the number 10 (wiki llJsonSetValue example)
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except ValueError:
                return s
        return s
    if t in ("vector", "rotation"):
        return to_string(value)
    return [_json_value_from_lsl(v) for v in value]


def _lsl_from_json_value(value):
    if value is None:
        return JSON_NULL
    if value is True:
        return JSON_TRUE
    if value is False:
        return JSON_FALSE
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = format_float(value, 6)
        return text.rstrip("0").rstrip(".") if "." in text else text
    if isinstance(value, str):
        return value
    return _dumps(value)


_MISSING = object()


def _json_lookup(text, specifiers):
    """The JSON node at the path, or _MISSING when the text or the path is invalid."""
    try:
        node = json.loads(text)
    except ValueError:
        return _MISSING
    for spec in specifiers:
        if isinstance(node, dict) and type_of(spec) in ("string", "key") and spec in node:
            node = node[spec]
        elif isinstance(node, list) and type_of(spec) == "integer" and 0 <= spec < len(node):
            node = node[spec]
        else:
            return _MISSING
    return node


def _json_parse(text):
    try:
        return False, json.loads(text)
    except ValueError:
        return True, None


def llJsonGetValue(text, specifiers):
    node = _json_lookup(text, specifiers)
    return JSON_INVALID if node is _MISSING else _lsl_from_json_value(node)


def llJsonValueType(text, specifiers):
    node = _json_lookup(text, specifiers)
    if node is _MISSING:
        return JSON_INVALID
    if node is None:
        return JSON_NULL
    if node is True:
        return JSON_TRUE
    if node is False:
        return JSON_FALSE
    if isinstance(node, (int, float)):
        return JSON_NUMBER
    if isinstance(node, str):
        return JSON_STRING
    if isinstance(node, list):
        return JSON_ARRAY
    return JSON_OBJECT


def llJsonSetValue(text, specifiers, value):
    bad, root = _json_parse(text) if text.strip() else (False, None)
    if bad or not specifiers:
        return JSON_INVALID
    new_value = _json_value_from_lsl(value, numeric_strings=True) if value != JSON_DELETE else JSON_DELETE

    def set_in(node, specs):
        spec = specs[0]
        last = len(specs) == 1
        if type_of(spec) == "integer":
            if node is None:
                node = []
            if not isinstance(node, list):
                node = []
            if spec == JSON_APPEND:
                if last:
                    node.append(new_value)
                else:
                    node.append(set_in(None, specs[1:]))
                return node
            if spec < 0 or spec > len(node):
                raise ValueError
            if spec == len(node):
                node.append(None)
            if last:
                if new_value == JSON_DELETE:
                    del node[spec]
                else:
                    node[spec] = new_value
            else:
                node[spec] = set_in(node[spec], specs[1:])
            return node
        if node is None or not isinstance(node, dict):
            node = {}
        key = str(spec)
        if last:
            if new_value == JSON_DELETE:
                node.pop(key, None)
            else:
                node[key] = new_value
        else:
            node[key] = set_in(node.get(key), specs[1:])
        return node

    try:
        root = set_in(root, list(specifiers))
    except ValueError:
        return JSON_INVALID
    return _dumps(root)


def llList2Json(json_type, values):
    if json_type == JSON_OBJECT:
        if len(values) % 2 != 0:
            return JSON_INVALID
        obj = {}
        for i in range(0, len(values), 2):
            obj[to_string(values[i])] = _json_value_from_lsl(values[i + 1])
        return _dumps(obj)
    if json_type == JSON_ARRAY:
        return _dumps([_json_value_from_lsl(v) for v in values])
    return JSON_INVALID


def llJson2List(text):
    bad, root = _json_parse(text)
    if bad:
        return [text] if text.strip() else []
    if isinstance(root, dict):
        out = []
        for k, v in root.items():
            out.append(k)
            out.append(_lsl_from_json_value(v))
        return out
    if isinstance(root, list):
        return [_lsl_from_json_value(v) for v in root]
    return [_lsl_from_json_value(root)]


# --- math ----------------------------------------------------------------------

def llAbs(value):
    return abs(value) if value != -2147483648 else value


def llFabs(value):
    return f32(abs(value))


def _finite_int(value, fn):
    if math.isnan(value) or math.isinf(value):
        return -2147483648
    return to_int32(int(fn(value)))


def llFloor(value):
    return _finite_int(value, math.floor)


def llCeil(value):
    return _finite_int(value, math.ceil)


def llRound(value):
    return _finite_int(value, lambda v: math.floor(v + 0.5))


def llSqrt(value):
    if math.isnan(value) or value < 0:
        raise ScriptError("Math Error", "llSqrt of a negative number")
    return f32(math.sqrt(value))


def llPow(base, exponent):
    try:
        result = math.pow(base, exponent)
    except (ValueError, OverflowError):
        raise ScriptError("Math Error", "llPow with an imaginary or infinite result")
    return f32(result)


def llLog(value):
    return f32(math.log(value)) if value > 0 else 0.0


def llLog10(value):
    return f32(math.log10(value)) if value > 0 else 0.0


def llSin(value):
    return f32(math.sin(value))


def llCos(value):
    return f32(math.cos(value))


def llTan(value):
    return f32(math.tan(value))


def llAtan2(y, x):
    return f32(math.atan2(y, x))


def llAsin(value):
    return f32(math.asin(_clamp1(value)))


def llAcos(value):
    return f32(math.acos(_clamp1(value)))


def llModPow(a, b, c):
    if c == 0:
        return 0
    return to_int32(pow(a & 0xFFFFFFFF, b & 0xFFFFFFFF, c & 0xFFFFFFFF))


def llVecMag(v):
    return f32(math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))


def llVecNorm(v):
    mag = llVecMag(v)
    if mag == 0.0:
        return ZERO_VECTOR
    return Vector(v[0] / mag, v[1] / mag, v[2] / mag)


def llVecDist(a, b):
    return llVecMag(Vector(a[0] - b[0], a[1] - b[1], a[2] - b[2]))


def llEuler2Rot(v):
    cx, sx = math.cos(v[0] / 2.0), math.sin(v[0] / 2.0)
    cy, sy = math.cos(v[1] / 2.0), math.sin(v[1] / 2.0)
    cz, sz = math.cos(v[2] / 2.0), math.sin(v[2] / 2.0)
    # LSL order: rotate about X, then Y, then Z (global axes)
    rx = Rotation(sx, 0.0, 0.0, cx)
    ry = Rotation(0.0, sy, 0.0, cy)
    rz = Rotation(0.0, 0.0, sz, cz)
    return rot_mul(rot_mul(rx, ry), rz)


def llRot2Euler(r):
    x, y, z, s = r
    sinr = 2.0 * (s * x + y * z)
    cosr = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr, cosr)
    sinp = 2.0 * (s * y - z * x)
    pitch = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1 else math.asin(sinp)
    siny = 2.0 * (s * z + x * y)
    cosy = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny, cosy)
    return Vector(roll, pitch, yaw)


def llAxisAngle2Rot(axis, angle):
    n = llVecNorm(axis)
    s = math.sin(angle / 2.0)
    return Rotation(n[0] * s, n[1] * s, n[2] * s, math.cos(angle / 2.0))


def llRot2Axis(r):
    return llVecNorm(Vector(r[0], r[1], r[2])) if (r[0] or r[1] or r[2]) else ZERO_VECTOR


def llRot2Angle(r):
    return f32(2.0 * math.acos(_clamp1(r[3])))


def llRot2Fwd(r):
    return vec_rotate(Vector(1.0, 0.0, 0.0), r)


def llRot2Left(r):
    return vec_rotate(Vector(0.0, 1.0, 0.0), r)


def llRot2Up(r):
    return vec_rotate(Vector(0.0, 0.0, 1.0), r)


def llAngleBetween(a, b):
    dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]
    return f32(2.0 * math.acos(_clamp1(abs(dot))))


def llRotBetween(a, b):
    na, nb = llVecNorm(a), llVecNorm(b)
    dot = na[0] * nb[0] + na[1] * nb[1] + na[2] * nb[2]
    if dot >= 1.0 - 1e-7:
        return ZERO_ROTATION
    if dot <= -1.0 + 1e-7:
        # opposite vectors: a half turn about any axis perpendicular to a
        axis = llVecNorm(Vector(na[1], -na[0], 0.0) if abs(na[2]) < 0.9 else Vector(0.0, na[2], -na[1]))
        return Rotation(axis[0], axis[1], axis[2], 0.0)
    cross = Vector(na[1] * nb[2] - na[2] * nb[1], na[2] * nb[0] - na[0] * nb[2], na[0] * nb[1] - na[1] * nb[0])
    s = math.sqrt((1.0 + dot) * 2.0)
    return Rotation(cross[0] / s, cross[1] / s, cross[2] / s, s / 2.0)


PURE = {name: obj for name, obj in list(globals().items()) if name.startswith("ll") and callable(obj)}
