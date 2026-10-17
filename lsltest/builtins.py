"""Pure builtins: functions that compute a result without touching the simulator.

Each entry maps the LSL name to a Python callable taking the LSL argument
values (already coerced to the declared parameter types) and returning an
LSL value. Functions that act on the world live in sim.py.
"""

import base64
import hashlib
import json
import math
import urllib.parse

from .errors import ScriptError
from .lexer import to_int32
from .values import (Key, Vector, Rotation, f32, to_string, type_of, cast, truthy, is_valid_key,
                     ZERO_VECTOR, ZERO_ROTATION, NULL_KEY, format_float)

JSON_INVALID = "﷐"
JSON_OBJECT = "﷑"
JSON_ARRAY = "﷒"
JSON_NUMBER = "﷓"
JSON_STRING = "﷔"
JSON_NULL = "﷕"
JSON_TRUE = "﷖"
JSON_FALSE = "﷗"
JSON_DELETE = "﷘"

TYPE_INVALID, TYPE_INTEGER, TYPE_FLOAT, TYPE_STRING, TYPE_KEY, TYPE_VECTOR, TYPE_ROTATION = range(7)
STRING_TRIM_HEAD, STRING_TRIM_TAIL, STRING_TRIM = 1, 2, 3


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
        return {"integer": 0, "float": 0.0, "string": "", "key": Key(""), "vector": ZERO_VECTOR, "rotation": ZERO_ROTATION}[type_name]
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
            return cast(value, "vector") if t == "string" else ZERO_VECTOR
        if type_name == "rotation":
            return cast(value, "rotation") if t == "string" else ZERO_ROTATION
    except ScriptError:
        pass
    return _list_get([], 0, type_name)


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
    return {"integer": TYPE_INTEGER, "float": TYPE_FLOAT, "string": TYPE_STRING, "key": TYPE_KEY,
            "vector": TYPE_VECTOR, "rotation": TYPE_ROTATION}[type_of(src[index])]


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
    if stride < 1:
        stride = 1
    indexes = _norm_range(len(src), start, end)
    n = len(test)
    for i in indexes:
        if (i - (indexes[0] if indexes else 0)) % stride == 0 and i + n <= len(src):
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


def llListSort(src, stride, ascending):
    if stride < 1:
        stride = 1
    if len(src) % stride != 0:
        return list(src)
    chunks = [src[i:i + stride] for i in range(0, len(src), stride)]
    chunks.sort(key=lambda c: _sort_key(c[0]), reverse=not ascending)
    return [v for c in chunks for v in c]


def llListRandomize(src, stride):
    # deterministic in tests: the simulator overrides this with its seeded RNG
    return list(src)


def llList2ListStrided(src, start, end, stride):
    if stride < 1:
        stride = 1
    return [src[i] for i in _norm_range(len(src), start, end) if i % stride == 0]


def llList2ListSlice(src, start, end, stride, slice_index):
    if stride < 1:
        stride = 1
    if slice_index < 0:
        slice_index += stride
    return [src[i] for i in _norm_range(len(src), start, end) if i % stride == slice_index]


def llListStatistics(operation, src):
    nums = [float(v) for v in src if type_of(v) in ("integer", "float")]
    if not nums:
        return 0.0
    n = len(nums)
    if operation == 0:      # LIST_STAT_RANGE
        return f32(max(nums) - min(nums))
    if operation == 1:      # LIST_STAT_MIN
        return f32(min(nums))
    if operation == 2:      # LIST_STAT_MAX
        return f32(max(nums))
    if operation == 3:      # LIST_STAT_MEAN
        return f32(sum(nums) / n)
    if operation == 4:      # LIST_STAT_MEDIAN
        s = sorted(nums)
        return f32(s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)
    if operation == 5:      # LIST_STAT_STD_DEV
        mean = sum(nums) / n
        return f32(math.sqrt(sum((x - mean) ** 2 for x in nums) / (n - 1))) if n > 1 else 0.0
    if operation == 6:      # LIST_STAT_SUM
        return f32(sum(nums))
    if operation == 7:      # LIST_STAT_SUM_SQUARES
        return f32(sum(x * x for x in nums))
    if operation == 8:      # LIST_STAT_NUM_COUNT
        return f32(n)
    if operation == 9:      # LIST_STAT_GEOMETRIC_MEAN
        if any(x <= 0 for x in nums):
            return 0.0
        return f32(math.exp(sum(math.log(x) for x in nums) / n))
    return 0.0


def llDumpList2String(src, separator):
    return separator.join(to_string(v) for v in src)


def llList2CSV(src):
    return ", ".join(to_string(v) for v in src)


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
        padded = text + "=" * (-len(text) % 4)
        return base64.b64decode(padded).decode("utf-8", "replace").replace("\x00", "")
    except (ValueError, UnicodeDecodeError):
        return ""


def llIntegerToBase64(number):
    return base64.b64encode((number & 0xFFFFFFFF).to_bytes(4, "big")).decode("ascii")


def llBase64ToInteger(text):
    try:
        raw = base64.b64decode(text + "=" * (-len(text) % 4))[:4].ljust(4, b"\0")
        return to_int32(int.from_bytes(raw, "big"))
    except ValueError:
        return 0


def llXorBase64(s1, s2):
    try:
        a = base64.b64decode(s1 + "=" * (-len(s1) % 4))
        b = base64.b64decode(s2 + "=" * (-len(s2) % 4))
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
    import hmac
    alg = {"sha1": hashlib.sha1, "sha224": hashlib.sha224, "sha256": hashlib.sha256,
           "sha384": hashlib.sha384, "sha512": hashlib.sha512, "md5": hashlib.md5}.get(hashalg.lower())
    if alg is None:
        return ""
    return hmac.new(authkey.encode("utf-8"), message.encode("utf-8"), alg).hexdigest()


def llComputeHash(data, algorithm):
    alg = {"md5": hashlib.md5, "sha1": hashlib.sha1, "sha224": hashlib.sha224, "sha256": hashlib.sha256,
           "sha384": hashlib.sha384, "sha512": hashlib.sha512}.get(algorithm.lower())
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

def _json_value_from_lsl(value):
    t = type_of(value)
    if t == "integer":
        return value
    if t == "float":
        return float(format_float(value, 6))
    if t in ("string", "key"):
        s = str(value)
        if s == JSON_TRUE:
            return True
        if s == JSON_FALSE:
            return False
        if s == JSON_NULL:
            return None
        stripped = s.strip()
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
    if isinstance(value, (int, float)):
        return str(value) if isinstance(value, int) else format_float(value, 6).rstrip("0").rstrip(".") if "." in format_float(value, 6) else format_float(value, 6)
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _json_walk(root, specifiers):
    node = root
    for spec in specifiers:
        if isinstance(node, dict):
            if type_of(spec) not in ("string", "key"):
                return JSON_INVALID, None
            if spec not in node:
                return JSON_INVALID, None
            node = node[spec]
        elif isinstance(node, list):
            if type_of(spec) != "integer":
                return JSON_INVALID, None
            if spec < 0 or spec >= len(node):
                return JSON_INVALID, None
            node = node[spec]
        else:
            return JSON_INVALID, None
    return None, node


def _json_parse(text):
    try:
        return False, json.loads(text)
    except ValueError:
        return True, None


def llJsonGetValue(text, specifiers):
    bad, root = _json_parse(text)
    if bad:
        return JSON_INVALID
    invalid, node = _json_walk(root, specifiers)
    if invalid:
        return JSON_INVALID
    return _lsl_from_json_value(node)


def llJsonValueType(text, specifiers):
    bad, root = _json_parse(text)
    if bad:
        return JSON_INVALID
    invalid, node = _json_walk(root, specifiers)
    if invalid:
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
    new_value = _json_value_from_lsl(value) if value != JSON_DELETE else JSON_DELETE

    def set_in(node, specs):
        spec = specs[0]
        last = len(specs) == 1
        if type_of(spec) == "integer":
            if node is None:
                node = []
            if not isinstance(node, list):
                node = []
            if spec == -1:                      # JSON_APPEND
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
    return json.dumps(root, separators=(",", ":"), ensure_ascii=False)


def llList2Json(json_type, values):
    if json_type == JSON_OBJECT:
        if len(values) % 2 != 0:
            return JSON_INVALID
        obj = {}
        for i in range(0, len(values), 2):
            obj[to_string(values[i])] = _json_value_from_lsl(values[i + 1])
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    if json_type == JSON_ARRAY:
        return json.dumps([_json_value_from_lsl(v) for v in values], separators=(",", ":"), ensure_ascii=False)
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


def llFloor(value):
    return to_int32(int(math.floor(value)))


def llCeil(value):
    return to_int32(int(math.ceil(value)))


def llRound(value):
    return to_int32(int(math.floor(value + 0.5)))


def llSqrt(value):
    if value < 0:
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
    return f32(math.asin(max(-1.0, min(1.0, value))))


def llAcos(value):
    return f32(math.acos(max(-1.0, min(1.0, value))))


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
    from .values import rot_mul
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
    return f32(2.0 * math.acos(max(-1.0, min(1.0, r[3]))))


def llRot2Fwd(r):
    from .values import vec_rotate
    return vec_rotate(Vector(1.0, 0.0, 0.0), r)


def llRot2Left(r):
    from .values import vec_rotate
    return vec_rotate(Vector(0.0, 1.0, 0.0), r)


def llRot2Up(r):
    from .values import vec_rotate
    return vec_rotate(Vector(0.0, 0.0, 1.0), r)


def llAngleBetween(a, b):
    dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]
    return f32(2.0 * math.acos(max(-1.0, min(1.0, abs(dot)))))


def llRotBetween(a, b):
    na, nb = llVecNorm(a), llVecNorm(b)
    dot = na[0] * nb[0] + na[1] * nb[1] + na[2] * nb[2]
    if dot >= 1.0 - 1e-7:
        return ZERO_ROTATION
    if dot <= -1.0 + 1e-7:
        return Rotation(0.0, 0.0, 1.0, 0.0)
    cross = Vector(na[1] * nb[2] - na[2] * nb[1], na[2] * nb[0] - na[0] * nb[2], na[0] * nb[1] - na[1] * nb[0])
    s = math.sqrt((1.0 + dot) * 2.0)
    return Rotation(cross[0] / s, cross[1] / s, cross[2] / s, s / 2.0)


PURE = {name: obj for name, obj in list(globals().items()) if name.startswith("ll") and callable(obj)}
