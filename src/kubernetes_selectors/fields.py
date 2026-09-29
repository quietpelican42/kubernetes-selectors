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
"""Field selectors.

Derived from k8s.io/apimachinery pkg/fields.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .errors import SelectorError

Fields = Mapping[str, str]
"""A flat map of field path to value."""

_SPECIAL = re.compile(r"[\\,=]")


@dataclass(frozen=True, slots=True)
class FieldRequirement:
    """One term of a field selector. ``operator`` is ``=`` or ``!=``."""

    operator: str
    field: str
    value: str


def escape_field_value(s: str) -> str:
    """``fields.EscapeValue``: prefix ``\\``, ``,`` and ``=`` with a backslash."""
    return _SPECIAL.sub(lambda m: "\\" + m.group(0), s)


def unescape_field_value(s: str) -> str:
    """``fields.UnescapeValue``. Raises :class:`SelectorError` for stray ``,``/``=`` and unknown escapes."""
    if _SPECIAL.search(s) is None:
        return s
    out: list[str] = []
    in_slash = False
    for c in s:
        if in_slash:
            if c in "\\,=":
                out.append(c)
            else:
                raise SelectorError("invalid field selector: invalid escape sequence: \\" + c)
            in_slash = False
            continue
        if c == "\\":
            in_slash = True
        elif c in ",=":
            raise SelectorError(f"invalid field selector: unescaped character in value: {ord(c)}")
        else:
            out.append(c)
    if in_slash:
        raise SelectorError("invalid field selector: invalid escape sequence: \\")
    return "".join(out)


class FieldSelector:
    """A parsed field selector: the AND of ``field=value`` and ``field!=value`` terms."""

    __slots__ = ("_terms", "_nothing")

    def __init__(self, terms: tuple[FieldRequirement, ...] = (), *, nothing: bool = False) -> None:
        self._terms = terms
        self._nothing = nothing

    def matches(self, fields: Fields) -> bool:
        """A missing field reads as the empty string, so ``a=`` matches a mapping without ``a``."""
        if self._nothing:
            return False
        for t in self._terms:
            v = fields.get(t.field, "")
            if (v != t.value) if t.operator == "=" else (v == t.value):
                return False
        return True

    def empty(self) -> bool:
        return not self._nothing and not self._terms

    def requirements(self) -> tuple[FieldRequirement, ...]:
        return () if self._nothing else self._terms

    def requires_exact_match(self, field: str) -> str | None:
        """The value the selector pins ``field`` to with ``=``, or None."""
        if self._nothing:
            return None
        for t in self._terms:
            if t.operator == "=" and t.field == field:
                return t.value
        return None

    def __str__(self) -> str:
        if self._nothing:
            return ""
        return ",".join(f"{t.field}{t.operator}{escape_field_value(t.value)}" for t in self._terms)

    def __repr__(self) -> str:
        return f"FieldSelector({str(self)!r})"


def everything_fields() -> FieldSelector:
    """The field selector that matches everything."""
    return FieldSelector()


def nothing_fields() -> FieldSelector:
    """The field selector that matches nothing."""
    return FieldSelector(nothing=True)


def _split_terms(selector: str) -> list[str]:
    if not selector:
        return []
    terms: list[str] = []
    start = 0
    in_slash = False
    for i, c in enumerate(selector):
        if in_slash:
            in_slash = False
        elif c == "\\":
            in_slash = True
        elif c == ",":
            terms.append(selector[start:i])
            start = i + 1
    terms.append(selector[start:])
    return terms


_TERM_OPERATORS = ("!=", "==", "=")


def _split_term(term: str) -> tuple[str, str, str] | None:
    for i in range(len(term)):
        for op in _TERM_OPERATORS:
            if term.startswith(op, i):
                return term[:i], op, term[i + len(op) :]
    return None


def parse_field_selector(selector: str) -> FieldSelector:
    """``fields.ParseSelector``: ``=``, ``==`` and ``!=`` terms joined by commas, with ``\\,`` ``\\=`` ``\\\\`` escapes.

    Terms are sorted as strings and terms whose field and value are both empty are dropped.
    Raises :class:`SelectorError` with Go's message.
    """
    items: list[FieldRequirement] = []
    for part in sorted(_split_terms(selector)):
        if part == "":
            continue
        split = _split_term(part)
        if split is None:
            raise SelectorError(f"invalid selector: '{selector}'; can't understand '{part}'")
        lhs, op, rhs = split
        value = unescape_field_value(rhs)
        if lhs == "" and value == "":
            continue
        items.append(FieldRequirement("!=" if op == "!=" else "=", lhs, value))
    return FieldSelector(tuple(items))


def field_selector_from_set(fields: Fields | None) -> FieldSelector:
    """``fields.SelectorFromSet``. None means everything.

    Go iterates the map in random order; this sorts by field so the string form is stable.
    """
    if fields is None:
        return everything_fields()
    return FieldSelector(tuple(FieldRequirement("=", k, fields[k]) for k in sorted(fields)))
