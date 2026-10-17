"""LSL values and their semantics: types, casts, formatting, truthiness, operators."""

import math
import re
import struct

from .errors import ScriptError
from .lexer import to_int32

TYPES = ("integer", "float", "string", "key", "vector", "rotation", "list")


def f32(value):
    """Round to IEEE 754 single precision, the float type of LSL."""
    try:
        return struct.unpack("f", struct.pack("f", float(value)))[0]
    except OverflowError:
        return math.copysign(float("inf"), float(value))


class Key(str):
    """A key is a string with a type tag. Equality and hashing are those of str."""
    __slots__ = ()

    def __repr__(self):
        return "Key(%s)" % str.__repr__(self)


class Vector(tuple):
    __slots__ = ()

    def __new__(cls, x=0.0, y=0.0, z=0.0):
        return tuple.__new__(cls, (f32(x), f32(y), f32(z)))

    x = property(lambda self: self[0])
    y = property(lambda self: self[1])
    z = property(lambda self: self[2])

    def __repr__(self):
        return "Vector(%r, %r, %r)" % self


class Rotation(tuple):
    __slots__ = ()

    def __new__(cls, x=0.0, y=0.0, z=0.0, s=1.0):
        return tuple.__new__(cls, (f32(x), f32(y), f32(z), f32(s)))

    x = property(lambda self: self[0])
    y = property(lambda self: self[1])
    z = property(lambda self: self[2])
    s = property(lambda self: self[3])

    def __repr__(self):
        return "Rotation(%r, %r, %r, %r)" % self


ZERO_VECTOR = Vector(0.0, 0.0, 0.0)
ZERO_ROTATION = Rotation(0.0, 0.0, 0.0, 1.0)
NULL_KEY = Key("00000000-0000-0000-0000-000000000000")

_KEY_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_INT_PREFIX_RE = re.compile(r"^\s*(0[xX][0-9a-fA-F]+|[+-]?[0-9]+)")
_FLOAT_PREFIX_RE = re.compile(r"^\s*([+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)")
_FLOAT_HEX_RE = re.compile(r"^\s*([+-]?0[xX][0-9a-fA-F]*\.?[0-9a-fA-F]*(?:[pP][+-]?[0-9]+)?)")


def type_of(value):
    if isinstance(value, bool):
        return "integer"
    if isinstance(value, Key):
        return "key"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Vector):
        return "vector"
    if isinstance(value, Rotation):
        return "rotation"
    if isinstance(value, list):
        return "list"
    raise TypeError("not an LSL value: %r" % (value,))


def default_value(type_name):
    return {
        "integer": 0, "float": 0.0, "string": "", "key": Key(""),
        "vector": ZERO_VECTOR, "rotation": ZERO_ROTATION, "list": [],
    }[type_name]


def is_valid_key(value):
    return bool(_KEY_RE.match(value))


def truthy(value):
    t = type_of(value)
    if t == "integer":
        return value != 0
    if t == "float":
        return value != 0.0
    if t == "key":
        return is_valid_key(value) and value != NULL_KEY
    if t == "string":
        return value != ""
    if t == "vector":
        return value != ZERO_VECTOR
    if t == "rotation":
        return value != ZERO_ROTATION
    return len(value) != 0


# --- formatting ---------------------------------------------------------------

def format_float(value, decimals=6):
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return "%.*f" % (decimals, value)


def to_string(value):
    """(string)value, as the LSL typecast does."""
    t = type_of(value)
    if t == "integer":
        return str(value)
    if t == "float":
        return format_float(value, 6)
    if t == "string" or t == "key":
        return str(value)
    if t == "vector":
        return "<%s, %s, %s>" % tuple(format_float(c, 5) for c in value)
    if t == "rotation":
        return "<%s, %s, %s, %s>" % tuple(format_float(c, 5) for c in value)
    return "".join(to_string(item) for item in value)


# --- casts --------------------------------------------------------------------

def to_integer(value):
    t = type_of(value)
    if t == "integer":
        return value
    if t == "float":
        if math.isnan(value) or math.isinf(value):
            return -2147483648
        return to_int32(int(value))
    if t in ("string", "key"):
        m = _INT_PREFIX_RE.match(value)
        if not m:
            return 0
        text = m.group(1)
        try:
            return to_int32(int(text, 16) if text.lower().startswith("0x") else int(text, 10))
        except ValueError:
            return 0
    raise ScriptError("Type mismatch", "cannot cast %s to integer" % t)


def to_float(value):
    t = type_of(value)
    if t == "float":
        return value
    if t == "integer":
        return f32(value)
    if t in ("string", "key"):
        m = _FLOAT_HEX_RE.match(value)
        if m and m.group(1).lower().lstrip("+-") not in ("0x", "0x."):
            try:
                return f32(float.fromhex(m.group(1)))
            except ValueError:
                pass
        m = _FLOAT_PREFIX_RE.match(value)
        if not m:
            stripped = value.strip().lower()
            if stripped.startswith("nan"):
                return float("nan")
            if stripped.startswith("inf") or stripped.startswith("+inf"):
                return float("inf")
            if stripped.startswith("-inf"):
                return float("-inf")
            return 0.0
        try:
            return f32(float(m.group(1)))
        except ValueError:
            return 0.0
    raise ScriptError("Type mismatch", "cannot cast %s to float" % t)


def _parse_components(text, count):
    m = re.match(r"^\s*<\s*(.*?)\s*>", text)
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).split(",")]
    if len(parts) < count:
        return None
    values = []
    for part in parts[:count]:
        mm = _FLOAT_PREFIX_RE.match(part)
        if not mm:
            return None
        values.append(float(mm.group(1)))
    return values


def cast(value, type_name):
    """The LSL typecast (type)value. Raises ScriptError on casts LSL does not allow."""
    src = type_of(value)
    if src == type_name:
        return value
    if type_name == "string":
        return to_string(value)
    if type_name == "integer":
        return to_integer(value)
    if type_name == "float":
        return to_float(value)
    if type_name == "key":
        if src == "string":
            return Key(value)
        raise ScriptError("Type mismatch", "cannot cast %s to key" % src)
    if type_name == "list":
        return [value]
    if type_name == "vector":
        if src == "string":
            parts = _parse_components(value, 3)
            return Vector(*parts) if parts else ZERO_VECTOR
        raise ScriptError("Type mismatch", "cannot cast %s to vector" % src)
    if type_name == "rotation":
        if src == "string":
            parts = _parse_components(value, 4)
            return Rotation(*parts) if parts else ZERO_ROTATION
        raise ScriptError("Type mismatch", "cannot cast %s to rotation" % src)
    raise ScriptError("Type mismatch", "unknown type %s" % type_name)


def coerce(value, type_name):
    """Implicit conversion at assignment or call: integer -> float and string <-> key only."""
    src = type_of(value)
    if src == type_name:
        return value
    if type_name == "float" and src == "integer":
        return f32(value)
    if type_name == "key" and src == "string":
        return Key(value)
    if type_name == "string" and src == "key":
        return str(value)
    raise ScriptError("Type mismatch", "%s where %s expected" % (src, type_name))


# --- arithmetic with LSL semantics ------------------------------------------

def int_div(a, b):
    if b == 0:
        raise ScriptError("Math Error", "division by zero")
    if a == -2147483648 and b == -1:
        return -2147483648
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def int_mod(a, b):
    if b == 0:
        raise ScriptError("Math Error", "modulo by zero")
    if b == -1:
        return 0
    return a - int_div(a, b) * b


def float_div(a, b):
    if b == 0.0:
        raise ScriptError("Math Error", "division by zero")
    return f32(a / b)


def rot_mul(a, b):
    """Quaternion product a * b, LSL order (apply a then b)."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return Rotation(
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def rot_conj(r):
    return Rotation(-r[0], -r[1], -r[2], r[3])


def vec_rotate(v, r):
    """v * r: rotate the vector by the quaternion."""
    vx, vy, vz = v
    rx, ry, rz, rs = r
    # q * (v, 0) * conj(q), expanded
    tx = 2.0 * (ry * vz - rz * vy)
    ty = 2.0 * (rz * vx - rx * vz)
    tz = 2.0 * (rx * vy - ry * vx)
    return Vector(
        vx + rs * tx + (ry * tz - rz * ty),
        vy + rs * ty + (rz * tx - rx * tz),
        vz + rs * tz + (rx * ty - ry * tx),
    )


def binary(op, a, b):
    """Apply a binary operator to two LSL values with LSL typing. Raises ScriptError when invalid."""
    ta, tb = type_of(a), type_of(b)
    num = ("integer", "float")

    if op == "+":
        if ta == "list" and tb == "list":
            return a + b
        if ta == "list":
            return a + [b]
        if tb == "list":
            return [a] + b
        if ta in ("string", "key") and tb in ("string", "key"):
            return str(a) + str(b)
        if ta in num and tb in num:
            return to_int32(a + b) if ta == tb == "integer" else f32(float(a) + float(b))
        if ta == "vector" and tb == "vector":
            return Vector(a[0] + b[0], a[1] + b[1], a[2] + b[2])
        if ta == "rotation" and tb == "rotation":
            return Rotation(a[0] + b[0], a[1] + b[1], a[2] + b[2], a[3] + b[3])
    elif op == "-":
        if ta in num and tb in num:
            return to_int32(a - b) if ta == tb == "integer" else f32(float(a) - float(b))
        if ta == "vector" and tb == "vector":
            return Vector(a[0] - b[0], a[1] - b[1], a[2] - b[2])
        if ta == "rotation" and tb == "rotation":
            return Rotation(a[0] - b[0], a[1] - b[1], a[2] - b[2], a[3] - b[3])
    elif op == "*":
        if ta in num and tb in num:
            return to_int32(a * b) if ta == tb == "integer" else f32(float(a) * float(b))
        if ta == "vector" and tb == "vector":
            return f32(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])
        if ta == "vector" and tb in num:
            return Vector(a[0] * b, a[1] * b, a[2] * b)
        if ta in num and tb == "vector":
            return Vector(b[0] * a, b[1] * a, b[2] * a)
        if ta == "vector" and tb == "rotation":
            return vec_rotate(a, b)
        if ta == "rotation" and tb == "rotation":
            return rot_mul(a, b)
    elif op == "/":
        if ta == "integer" and tb == "integer":
            return int_div(a, b)
        if ta in num and tb in num:
            return float_div(float(a), float(b))
        if ta == "vector" and tb in num:
            if b == 0:
                raise ScriptError("Math Error", "division by zero")
            return Vector(a[0] / b, a[1] / b, a[2] / b)
        if ta == "vector" and tb == "rotation":
            return vec_rotate(a, rot_conj(b))
        if ta == "rotation" and tb == "rotation":
            return rot_mul(a, rot_conj(b))
    elif op == "%":
        if ta == "integer" and tb == "integer":
            return int_mod(a, b)
        if ta == "vector" and tb == "vector":
            return Vector(a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    elif op in ("==", "!="):
        if ta == "list" and tb == "list":
            equal = len(a) == len(b)
            return int(equal) if op == "==" else (len(a) - len(b))
        if ta in ("string", "key") and tb in ("string", "key"):
            equal = str(a) == str(b)
        elif ta in num and tb in num:
            equal = float(a) == float(b)
        elif ta == tb and ta in ("vector", "rotation"):
            equal = a == b
        else:
            equal = None
        if equal is not None:
            return int(equal) if op == "==" else int(not equal)
    elif op in ("<", "<=", ">", ">="):
        if ta in num and tb in num:
            fa, fb = float(a), float(b)
            return int({"<": fa < fb, "<=": fa <= fb, ">": fa > fb, ">=": fa >= fb}[op])
    elif op in ("&", "|", "^", "<<", ">>"):
        if ta == "integer" and tb == "integer":
            if op == "&":
                return to_int32(a & b)
            if op == "|":
                return to_int32(a | b)
            if op == "^":
                return to_int32(a ^ b)
            shift = b & 31
            if op == "<<":
                return to_int32(a << shift)
            return to_int32(a >> shift)
    elif op in ("&&", "||"):
        # both operands are always evaluated by the interpreter; here only the result
        if ta in num and tb in num:
            if op == "&&":
                return int(truthy(a) and truthy(b))
            return int(truthy(a) or truthy(b))
    raise ScriptError("Type mismatch", "%s %s %s" % (ta, op, tb))


def unary(op, a):
    t = type_of(a)
    if op == "-":
        if t == "integer":
            return to_int32(-a)
        if t == "float":
            return f32(-a)
        if t == "vector":
            return Vector(-a[0], -a[1], -a[2])
        if t == "rotation":
            return Rotation(-a[0], -a[1], -a[2], -a[3])
    elif op == "!":
        if t == "integer":
            return int(a == 0)
    elif op == "~":
        if t == "integer":
            return to_int32(~a)
    raise ScriptError("Type mismatch", "%s%s" % (op, t))


def lsl_repr(value):
    """Debug representation used in test failure messages."""
    t = type_of(value)
    if t == "list":
        return "[" + ", ".join(lsl_repr(v) for v in value) + "]"
    if t == "string":
        return '"%s"' % value
    if t == "key":
        return "(key)\"%s\"" % value
    return to_string(value)
