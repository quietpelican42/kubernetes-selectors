# Copyright 2014 The Kubernetes Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Label selectors: lexer, parser, requirements and matching.

Derived from k8s.io/apimachinery pkg/labels/selector.go.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from ._gofmt import go_json_string, go_json_strings, go_quote, parse_int64
from ._gosort import go_sort
from .errors import SelectorError
from .validate import validate_label_key, validate_label_value

Labels = Mapping[str, str]
"""A set of labels: any mapping of str to str."""

BINARY_OPERATORS: Final = ("in", "notin", "=", "==", "!=", "gt", "lt")
_VALID_OPERATORS: Final = (*BINARY_OPERATORS, "exists", "!")


def _aggregate(errs: list[str]) -> SelectorError | None:
    seen: list[str] = []
    for e in errs:
        if e not in seen:
            seen.append(e)
    if not seen:
        return None
    return SelectorError(seen[0] if len(seen) == 1 else "[" + ", ".join(seen) + "]")


def _invalid(path: str, bad_value: str, detail: str) -> str:
    return f"{path}: Invalid value: {bad_value}: {detail}"


class Requirement:
    """One ``key operator values`` term of a selector. Build with :func:`new_requirement`."""

    __slots__ = ("key", "operator", "_values")

    def __init__(self, key: str, operator: str, values: Sequence[str]) -> None:
        self.key = key
        self.operator = operator
        self._values = tuple(values)

    def values(self) -> list[str]:
        """Sorted, de-duplicated values (``Requirement.Values().List()``)."""
        return sorted(set(self._values))

    def values_unsorted(self) -> list[str]:
        """Values in the order they were passed (``ValuesUnsorted``)."""
        return list(self._values)

    def matches(self, labels: Labels) -> bool:
        val = labels.get(self.key)
        op = self.operator
        if op in ("in", "=", "=="):
            return val is not None and val in self._values
        if op in ("notin", "!="):
            return val is None or val not in self._values
        if op == "exists":
            return val is not None
        if op == "!":
            return val is None
        if op in ("gt", "lt"):
            if val is None:
                return False
            left = parse_int64(val)
            if left is None or len(self._values) != 1:
                return False
            right = parse_int64(self._values[0])
            if right is None:
                return False
            return left > right if op == "gt" else left < right
        return False

    def __str__(self) -> str:
        op = self.operator
        s = "!" + self.key if op == "!" else self.key
        symbols = {"=": "=", "==": "==", "!=": "!=", "in": " in ", "notin": " notin ", "gt": ">", "lt": "<"}
        if op not in symbols:
            return s
        s += symbols[op]
        paren = op in ("in", "notin")
        if paren:
            s += "("
        s += self._values[0] if len(self._values) == 1 else ",".join(sorted(self._values))
        if paren:
            s += ")"
        return s

    def __repr__(self) -> str:
        return f"Requirement({self.key!r}, {self.operator!r}, {list(self._values)!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Requirement):
            return NotImplemented
        return (self.key, self.operator, self._values) == (other.key, other.operator, other._values)

    def __hash__(self) -> int:
        return hash((self.key, self.operator, self._values))


def new_requirement(key: str, operator: str, values: Sequence[str] | None = None) -> Requirement:
    """Build a validated requirement, as ``labels.NewRequirement`` does.

    ``values=None`` stands for Go's nil slice. Raises :class:`SelectorError` with Go's message.
    Operators: ``in notin = == != exists ! gt lt``.
    """
    errs: list[str] = []
    key_errs = validate_label_key(key)
    if key_errs:
        errs.append(_invalid("key", go_quote(key), "; ".join(key_errs)))
    n = 0 if values is None else len(values)
    if operator in ("in", "notin"):
        if n == 0:
            errs.append(_invalid("values", go_json_strings(values), "for 'in', 'notin' operators, values set can't be empty"))
    elif operator in ("=", "==", "!="):
        if n != 1:
            errs.append(_invalid("values", go_json_strings(values), "exact-match compatibility requires one single value"))
    elif operator in ("exists", "!"):
        if n != 0:
            errs.append(_invalid("values", go_json_strings(values), "values set must be empty for exists and does not exist"))
    elif operator in ("gt", "lt"):
        if n != 1:
            errs.append(_invalid("values", go_json_strings(values), "for 'Gt', 'Lt' operators, exactly one value is required"))
        for i, v in enumerate(values or ()):
            if parse_int64(v) is None:
                errs.append(_invalid(f"values[{i}]", go_quote(v), "for 'Gt', 'Lt' operators, the value must be an integer"))
    else:
        errs.append(
            f"operator: Unsupported value: {go_json_string(operator)}: supported values: "
            + ", ".join(go_quote(o) for o in _VALID_OPERATORS)
        )
    for i, v in enumerate(values or ()):
        verrs = validate_label_value(v)
        if verrs:
            errs.append(_invalid(f"values[{i}][{key}]", go_quote(v), "; ".join(verrs)))
    err = _aggregate(errs)
    if err is not None:
        raise err
    return Requirement(key, operator, values or ())


def _sort_by_key(reqs: list[Requirement]) -> list[Requirement]:
    # Go sorts with sort.Sort, which is not stable; go_sort reproduces its order for equal keys.
    return go_sort(reqs, lambda a, b: a.key < b.key)


class Selector:
    """A parsed label selector: the AND of its requirements."""

    __slots__ = ("_reqs", "_nothing")

    def __init__(self, requirements: Iterable[Requirement] = (), *, nothing: bool = False) -> None:
        self._reqs = tuple(requirements)
        self._nothing = nothing

    def matches(self, labels: Labels) -> bool:
        if self._nothing:
            return False
        return all(r.matches(labels) for r in self._reqs)

    def empty(self) -> bool:
        """True when the selector does not restrict anything. The nothing-selector is not empty."""
        return not self._nothing and not self._reqs

    @property
    def selectable(self) -> bool:
        """False for the selector that matches nothing."""
        return not self._nothing

    def requirements(self) -> tuple[Requirement, ...]:
        """The requirements, sorted by key."""
        return () if self._nothing else self._reqs

    def add(self, *reqs: Requirement) -> Selector:
        """A new selector with extra requirements, re-sorted by key."""
        if self._nothing:
            return self
        return Selector(_sort_by_key([*self._reqs, *reqs]))

    def requires_exact_match(self, label: str) -> str | None:
        """The value the selector pins ``label`` to, or None."""
        if self._nothing:
            return None
        for r in self._reqs:
            if r.key == label:
                vals = r.values_unsorted()
                if r.operator in ("=", "==", "in") and len(vals) == 1:
                    return vals[0]
                return None
        return None

    def __str__(self) -> str:
        return "" if self._nothing else ",".join(str(r) for r in self._reqs)

    def __repr__(self) -> str:
        return f"Selector({str(self)!r})"


_EVERYTHING = Selector()
_NOTHING = Selector(nothing=True)


def everything() -> Selector:
    """The selector that matches every label set."""
    return _EVERYTHING


def nothing() -> Selector:
    """The selector that matches no label set."""
    return _NOTHING


# ---- lexer

_ERROR = 0
_EOS = 1
_CLOSED_PAR = 2
_COMMA = 3
_DOES_NOT_EXIST = 4
_DOUBLE_EQUALS = 5
_EQUALS = 6
_GREATER_THAN = 7
_IDENTIFIER = 8
_IN = 9
_LESS_THAN = 10
_NOT_EQUALS = 11
_NOT_IN = 12
_OPEN_PAR = 13

_STRING2TOKEN: Final = {
    ")": _CLOSED_PAR,
    ",": _COMMA,
    "!": _DOES_NOT_EXIST,
    "==": _DOUBLE_EQUALS,
    "=": _EQUALS,
    ">": _GREATER_THAN,
    "in": _IN,
    "<": _LESS_THAN,
    "!=": _NOT_EQUALS,
    "notin": _NOT_IN,
    "(": _OPEN_PAR,
}
_SPECIAL: Final = frozenset("=!(),><")
_WHITESPACE: Final = frozenset(" \t\r\n")

_Item = tuple[int, str]


class _Lexer:
    """A NUL character ends a token exactly like the end of input, as in Go's lexer."""

    def __init__(self, s: str) -> None:
        self._s = s
        self._pos = 0

    def _read(self) -> str:
        if self._pos < len(self._s):
            c = self._s[self._pos]
            self._pos += 1
            return c
        return "\0"

    def _unread(self) -> None:
        self._pos -= 1

    def _scan_id_or_keyword(self) -> _Item:
        buf: list[str] = []
        while True:
            ch = self._read()
            if ch == "\0":
                break
            if ch in _SPECIAL or ch in _WHITESPACE:
                self._unread()
                break
            buf.append(ch)
        s = "".join(buf)
        return (_STRING2TOKEN.get(s, _IDENTIFIER), s)

    def _scan_special_symbol(self) -> _Item:
        last: _Item = (_ERROR, "")
        buf = ""
        while True:
            ch = self._read()
            if ch == "\0":
                break
            if ch in _SPECIAL:
                buf += ch
                tok = _STRING2TOKEN.get(buf)
                if tok is not None:
                    last = (tok, buf)
                elif last[0] != _ERROR:
                    self._unread()
                    break
            else:
                self._unread()
                break
        if last[0] == _ERROR:
            return (_ERROR, f"error expected: keyword found '{buf}'")
        return last

    def lex(self) -> _Item:
        ch = self._read()
        while ch in _WHITESPACE:
            ch = self._read()
        if ch == "\0":
            return (_EOS, "")
        self._unread()
        return self._scan_special_symbol() if ch in _SPECIAL else self._scan_id_or_keyword()


# ---- parser

_VALUES = 1
_KEY_AND_OPERATOR = 0


class _Parser:
    def __init__(self, s: str) -> None:
        lexer = _Lexer(s)
        self._items: list[_Item] = []
        while True:
            item = lexer.lex()
            self._items.append(item)
            if item[0] == _EOS:
                break
        self._pos = 0

    def _lookahead(self, context: int) -> _Item:
        tok, lit = self._items[self._pos]
        if context == _VALUES and tok in (_IN, _NOT_IN):
            tok = _IDENTIFIER
        return tok, lit

    def _consume(self, context: int) -> _Item:
        tok, lit = self._items[self._pos]
        self._pos += 1
        if context == _VALUES and tok in (_IN, _NOT_IN):
            tok = _IDENTIFIER
        return tok, lit

    def parse(self) -> list[Requirement]:
        requirements: list[Requirement] = []
        while True:
            tok, lit = self._lookahead(_VALUES)
            if tok in (_IDENTIFIER, _DOES_NOT_EXIST):
                try:
                    r = self._parse_requirement()
                except SelectorError as e:
                    raise SelectorError(f"unable to parse requirement: {e}") from None
                requirements.append(r)
                t, ell = self._consume(_VALUES)
                if t == _EOS:
                    return requirements
                if t == _COMMA:
                    t2, l2 = self._lookahead(_VALUES)
                    if t2 not in (_IDENTIFIER, _DOES_NOT_EXIST):
                        raise SelectorError(f"found '{l2}', expected: identifier after ','")
                else:
                    raise SelectorError(f"found '{ell}', expected: ',' or 'end of string'")
            elif tok == _EOS:
                return requirements
            else:
                raise SelectorError(f"found '{lit}', expected: !, identifier, or 'end of string'")

    def _parse_requirement(self) -> Requirement:
        key, inferred = self._parse_key_and_infer_operator()
        if inferred in ("exists", "!"):
            return new_requirement(key, inferred, [])
        operator = self._parse_operator()
        values = self._parse_values() if operator in ("in", "notin") else self._parse_exact_value()
        return new_requirement(key, operator, values)

    def _parse_key_and_infer_operator(self) -> tuple[str, str]:
        operator = ""
        tok, literal = self._consume(_VALUES)
        if tok == _DOES_NOT_EXIST:
            operator = "!"
            tok, literal = self._consume(_VALUES)
        if tok != _IDENTIFIER:
            raise SelectorError(f"found '{literal}', expected: identifier")
        errs = validate_label_key(literal)
        if errs:
            raise SelectorError(_invalid("<nil>", go_quote(literal), "; ".join(errs)))
        t, _ = self._lookahead(_VALUES)
        if t in (_EOS, _COMMA) and operator != "!":
            operator = "exists"
        return literal, operator

    def _parse_operator(self) -> str:
        tok, lit = self._consume(_KEY_AND_OPERATOR)
        ops = {_IN: "in", _EQUALS: "=", _DOUBLE_EQUALS: "==", _GREATER_THAN: "gt", _LESS_THAN: "lt", _NOT_IN: "notin", _NOT_EQUALS: "!="}
        if tok not in ops:
            raise SelectorError(f"found '{lit}', expected: {', '.join(BINARY_OPERATORS)}")
        return ops[tok]

    def _parse_values(self) -> list[str]:
        tok, lit = self._consume(_VALUES)
        if tok != _OPEN_PAR:
            raise SelectorError(f"found '{lit}' expected: '('")
        tok, lit = self._lookahead(_VALUES)
        if tok in (_IDENTIFIER, _COMMA):
            s = self._parse_identifiers_list()
            tok, _ = self._consume(_VALUES)
            if tok != _CLOSED_PAR:
                raise SelectorError(f"found '{lit}', expected: ')'")
            return sorted(s)
        if tok == _CLOSED_PAR:
            self._consume(_VALUES)
            return [""]
        raise SelectorError(f"found '{lit}', expected: ',', ')' or identifier")

    def _parse_identifiers_list(self) -> set[str]:
        s: set[str] = set()
        while True:
            tok, lit = self._consume(_VALUES)
            if tok == _IDENTIFIER:
                s.add(lit)
                tok2, lit2 = self._lookahead(_VALUES)
                if tok2 == _COMMA:
                    continue
                if tok2 == _CLOSED_PAR:
                    return s
                raise SelectorError(f"found '{lit2}', expected: ',' or ')'")
            if tok == _COMMA:
                if not s:
                    s.add("")
                tok2, _ = self._lookahead(_VALUES)
                if tok2 == _CLOSED_PAR:
                    s.add("")
                    return s
                if tok2 == _COMMA:
                    s.add("")
            else:
                raise SelectorError(f"found '{lit}', expected: ',', or identifier")

    def _parse_exact_value(self) -> list[str]:
        tok, _ = self._lookahead(_VALUES)
        if tok in (_EOS, _COMMA):
            return [""]
        t, lit = self._consume(_VALUES)
        if t == _IDENTIFIER:
            return [lit]
        raise SelectorError(f"found '{lit}', expected: identifier")


def parse_requirements(selector: str) -> list[Requirement]:
    """``labels.ParseToRequirements``: the requirements sorted by key."""
    return _sort_by_key(_Parser(selector).parse())


def parse_selector(selector: str) -> Selector:
    """Parse a label selector with apimachinery's grammar (``labels.Parse``).

    Raises :class:`SelectorError` with Go's message. Requirements are sorted by key.
    """
    return Selector(parse_requirements(selector))


def matches(selector: str | Selector, labels: Labels) -> bool:
    """Whether ``labels`` satisfies ``selector``, which may be a string or a parsed Selector."""
    return (parse_selector(selector) if isinstance(selector, str) else selector).matches(labels)


def selector_from_set(labels: Labels | None) -> Selector:
    """``labels.SelectorFromSet``: ``k=v`` for every entry, no validation. None or empty means everything."""
    if not labels:
        return everything()
    return Selector(_sort_by_key([Requirement(k, "=", [v]) for k, v in labels.items()]))


def validated_selector_from_set(labels: Labels | None) -> Selector:
    """``labels.ValidatedSelectorFromSet``: raises :class:`SelectorError` for invalid keys or values."""
    if not labels:
        return everything()
    return Selector(_sort_by_key([new_requirement(k, "=", [v]) for k, v in labels.items()]))
