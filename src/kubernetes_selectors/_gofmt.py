"""Helpers that reproduce Go's string formatting and number parsing."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

_INT = re.compile(r"[+-]?[0-9]+")


def byte_length(s: str) -> int:
    """Length in UTF-8 bytes, which is what Go's ``len`` reports."""
    return len(s.encode("utf-8", "surrogatepass"))


def go_quote(s: str) -> str:
    """``strconv.Quote``."""
    out = ['"']
    for ch in s:
        c = ord(ch)
        if ch in '"\\':
            out.append("\\" + ch)
        elif 0x20 <= c < 0x7F:
            out.append(ch)
        elif c >= 0x80 and unicodedata.category(ch)[0] in "LMNPS" and not 0xD800 <= c < 0xE000:
            out.append(ch)
        elif c == 7:
            out.append("\\a")
        elif c == 8:
            out.append("\\b")
        elif c == 12:
            out.append("\\f")
        elif c == 10:
            out.append("\\n")
        elif c == 13:
            out.append("\\r")
        elif c == 9:
            out.append("\\t")
        elif c == 11:
            out.append("\\v")
        elif c < 0x20 or c == 0x7F:
            out.append(f"\\x{c:02x}")
        elif 0xD800 <= c < 0xE000:
            out.append("\\ufffd")
        elif c < 0x10000:
            out.append(f"\\u{c:04x}")
        else:
            out.append(f"\\U{c:08x}")
    out.append('"')
    return "".join(out)


def go_json_string(s: str) -> str:
    """``encoding/json`` string encoding, including its HTML escaping."""
    out = ['"']
    for ch in s:
        c = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif c == 8:
            out.append("\\b")
        elif c == 12:
            out.append("\\f")
        elif c == 10:
            out.append("\\n")
        elif c == 13:
            out.append("\\r")
        elif c == 9:
            out.append("\\t")
        elif c < 0x20 or ch in "<>&" or c in (0x2028, 0x2029):
            out.append(f"\\u{c:04x}")
        elif 0xD800 <= c < 0xE000:
            out.append("\\ufffd")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def go_json_strings(values: Sequence[str] | None) -> str:
    """``json.Marshal`` of a ``[]string``, where a nil slice is ``null``."""
    if values is None:
        return "null"
    return "[" + ",".join(go_json_string(v) for v in values) + "]"


def parse_int64(s: str) -> int | None:
    """``strconv.ParseInt(s, 10, 64)``; None where Go returns an error."""
    if _INT.fullmatch(s) is None:
        return None
    try:
        n = int(s)
    except ValueError:  # more digits than Python's int() conversion limit
        return None
    if n > 9223372036854775807 or n < -9223372036854775808:
        return None
    return n
