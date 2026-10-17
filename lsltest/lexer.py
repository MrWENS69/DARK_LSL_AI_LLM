"""Tokenizer for LSL, following lslmini.l (the lslint lexer)."""

import re

from .errors import LslSyntaxError
from .values import to_int32, unescape

KEYWORDS = {
    "integer", "float", "string", "key", "vector", "rotation", "quaternion", "list",
    "default", "state", "jump", "return", "if", "else", "for", "do", "while",
}

_TOKEN_RE = re.compile(r"""
    (?P<ws>[ \t\r\f\v]+)
  | (?P<nl>\n)
  | (?P<comment>//[^\n]*)
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


def tokenize(source):
    tokens = []
    line = 1
    line_start = 0
    pos = 0
    length = len(source)
    while pos < length:
        if source.startswith("/*", pos):              # block comment, scanned once, never backtracked
            end = source.find("*/", pos + 2)
            if end < 0:
                raise LslSyntaxError("unterminated comment", line, pos - line_start + 1)
            text = source[pos:end + 2]
            newlines = text.count("\n")
            if newlines:
                line += newlines
                line_start = pos + text.rfind("\n") + 1
            pos = end + 2
            continue
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
        elif kind == "hex":
            tokens.append(Token("int", to_int32(int(text, 16)), line, col))
        elif kind == "int":
            if len(text) > 20:
                raise LslSyntaxError("integer literal too long", line, col)
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
