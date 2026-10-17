"""Tokenizer for LSL, following lslmini.l (the lslint lexer)."""

import re

from .errors import LslSyntaxError

KEYWORDS = {
    "integer", "float", "string", "key", "vector", "rotation", "quaternion", "list",
    "default", "state", "jump", "return", "if", "else", "for", "do", "while",
}

# Longest operators first.
OPERATORS = [
    "++", "--", "+=", "-=", "*=", "/=", "%=", "==", "!=", "<=", ">=", "<<", ">>", "&&", "||",
    "+", "-", "*", "/", "%", "=", "<", ">", "!", "~", "&", "|", "^",
    "(", ")", "{", "}", "[", "]", ",", ";", ".", "@",
]

_TOKEN_RE = re.compile(r"""
    (?P<ws>[ \t\r\f\v]+)
  | (?P<nl>\n)
  | (?P<comment>//[^\n]*)
  | (?P<ccomment>/\*.*?\*/)
  | (?P<hex>0[xX][0-9a-fA-F]+)
  | (?P<float>(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?[fF]?|[0-9]+[eE][+-]?[0-9]+[fF]?)
  | (?P<int>[0-9]+)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\+\+|--|\+=|-=|\*=|/=|%=|==|!=|<=|>=|<<|>>|&&|\|\||[-+*/%=<>!~&|^(){}\[\],;.@])
""", re.VERBOSE | re.DOTALL)


class Token(object):
    __slots__ = ("kind", "value", "line", "col")

    def __init__(self, kind, value, line, col):
        self.kind = kind      # "int", "float", "string", "ident", "keyword", "op", "eof"
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self):
        return "Token(%s, %r, %d:%d)" % (self.kind, self.value, self.line, self.col)


def unescape(text):
    """Compile-time escapes of LSL string literals: \\n, \\t (four spaces), \\", \\\\.

    Any other backslash sequence drops the backslash, as the LSL compiler does.
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("    ")
            elif nxt == '"':
                out.append('"')
            elif nxt == "\\":
                out.append("\\")
            else:
                out.append(nxt)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def tokenize(source):
    tokens = []
    line = 1
    line_start = 0
    pos = 0
    length = len(source)
    while pos < length:
        m = _TOKEN_RE.match(source, pos)
        if not m:
            raise LslSyntaxError("unexpected character %r" % source[pos], line, pos - line_start + 1)
        kind = m.lastgroup
        text = m.group(kind)
        col = pos - line_start + 1
        if kind == "ws" or kind == "comment":
            pass
        elif kind == "nl":
            line += 1
            line_start = m.end()
        elif kind == "ccomment":
            newlines = text.count("\n")
            if newlines:
                line += newlines
                line_start = m.start() + text.rfind("\n") + 1
        elif kind == "hex":
            tokens.append(Token("int", to_int32(int(text, 16)), line, col))
        elif kind == "int":
            tokens.append(Token("int", to_int32(int(text, 10)), line, col))
        elif kind == "float":
            tokens.append(Token("float", float(text.rstrip("fF")), line, col))
        elif kind == "string":
            tokens.append(Token("string", unescape(text[1:-1]), line, col))
            newlines = text.count("\n")
            if newlines:                      # LSL string literals may span lines
                line += newlines
                line_start = m.start() + text.rfind("\n") + 1
        elif kind == "ident":
            tokens.append(Token("keyword" if text in KEYWORDS else "ident", text, line, col))
        elif kind == "op":
            tokens.append(Token("op", text, line, col))
        pos = m.end()
    tokens.append(Token("eof", None, line, pos - line_start + 1))
    return tokens


def to_int32(value):
    """Wrap a Python integer to a signed 32-bit integer, as LSL integers do."""
    value &= 0xFFFFFFFF
    if value >= 0x80000000:
        value -= 0x100000000
    return value
