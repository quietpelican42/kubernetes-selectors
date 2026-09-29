"""Check one corpus record produced by gen/main.go against this package."""

from __future__ import annotations

import gzip
import json
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from kubernetes_selectors import (
    FieldSelector,
    SelectorError,
    escape_field_value,
    field_selector_from_set,
    format_label_selector,
    label_selector_as_map,
    label_selector_as_selector,
    new_requirement,
    parse_field_selector,
    parse_selector,
    parse_to_label_selector,
    selector_from_set,
    unescape_field_value,
    validate_label_key,
    validate_label_value,
    validated_selector_from_set,
)
from kubernetes_selectors import Selector

Rec = dict[str, Any]
T = TypeVar("T")


def attempt(fn: Callable[[], T]) -> tuple[T | None, str | None]:
    """Return (value, None) or (None, error message)."""
    try:
        return fn(), None
    except SelectorError as e:
        return None, str(e)


def bits(sel: Any, sets: list[dict[str, str]]) -> str:
    return "".join("1" if sel.matches(s) else "0" for s in sets)


def normalize_ls(o: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if o and o.get("matchLabels"):
        out["matchLabels"] = o["matchLabels"]
    if o and o.get("matchExpressions"):
        out["matchExpressions"] = [
            {"key": e["key"], "operator": e["operator"], **({"values": e["values"]} if e.get("values") else {})}
            for e in o["matchExpressions"]
        ]
    return out


def check_label_selector(sel: Selector, rec: Rec) -> None:
    assert str(sel) == rec.get("str", ""), "String()"
    assert sel.empty() == bool(rec.get("em")), "Empty()"
    got = [{"k": r.key, "o": r.operator, "v": r.values()} for r in sel.requirements()]
    assert got == rec.get("rq", []), "requirements"
    assert bits(sel, rec.get("ls", [])) == rec.get("m", ""), "match results"


def check_rx(sel: Any, rx: list[Rec] | None) -> None:
    for r in rx or []:
        got = sel.requires_exact_match(r["k"])
        assert (got is not None) == bool(r.get("f")), f"requires_exact_match({r['k']!r}) found"
        assert (got or "") == r.get("v", ""), f"requires_exact_match({r['k']!r}) value"


def check_record(rec: Rec) -> None:
    t = rec["t"]
    if t == "sel":
        sel, err = attempt(lambda: parse_selector(rec["s"]))
        if rec["ok"]:
            assert sel is not None, f"parse failed: {err}"
            check_label_selector(sel, rec)
            check_rx(sel, rec.get("rx"))
        else:
            assert sel is None, "parse should fail"
            assert err == rec["e"]
        p, perr = attempt(lambda: parse_to_label_selector(rec["s"]))
        if rec["pls"]["ok"]:
            assert p is not None, perr
            assert normalize_ls(p) == normalize_ls(rec["pls"]["o"])
        else:
            assert p is None
            assert perr == rec["pls"]["e"]
    elif t == "lsel":
        sel, err = attempt(lambda: label_selector_as_selector(rec["o"]))
        if rec["ok"]:
            assert sel is not None, f"conversion failed: {err}"
            check_label_selector(sel, rec)
            assert (not sel.selectable) == bool(rec.get("nothing")), "selectable"
        else:
            assert sel is None
            assert err == rec["e"]
        assert format_label_selector(rec["o"]) == rec["fmt"], "format_label_selector"
        m, merr = attempt(lambda: label_selector_as_map(rec["o"]))
        if rec["map"]["ok"]:
            if rec["map"].get("nil"):
                assert m is None and merr is None
            else:
                assert m == rec["map"].get("m", {})
        else:
            assert merr == rec["map"]["e"]
    elif t == "req":
        r, err = attempt(lambda: new_requirement(rec["key"], rec["op"], rec["vals"]))
        if rec["ok"]:
            assert r is not None, f"new_requirement failed: {err}"
            assert str(r) == rec["str"]
            assert r.values_unsorted() == rec.get("uns", [])
            assert r.values() == rec.get("srt", [])
            assert bits(r, rec["ls"]) == rec["m"]
        else:
            assert r is None
            assert err == rec["e"]
    elif t == "set":
        s = selector_from_set(rec["set"])
        assert str(s) == rec["str"]
        assert s.empty() == rec["em"]
        assert bits(s, rec["ls"]) == rec["m"]
        v, verr = attempt(lambda: validated_selector_from_set(rec["set"]))
        if rec["vok"]:
            assert v is not None, verr
            assert str(v) == rec.get("vstr", "")
        else:
            assert v is None
            assert verr == rec["ve"]
    elif t == "val":
        assert validate_label_key(rec["s"]) == rec["key"], f"validate_label_key({rec['s']!r})"
        assert validate_label_value(rec["s"]) == rec["val"], f"validate_label_value({rec['s']!r})"
    elif t == "fld":
        f, err = attempt(lambda: parse_field_selector(rec["s"]))
        if rec["ok"]:
            assert f is not None, f"parse failed: {err}"
            fsel: FieldSelector = f
            assert str(fsel) == rec.get("str", "")
            assert fsel.empty() == bool(rec.get("em"))
            got_f = [{"o": q.operator, "f": q.field, "v": q.value} for q in fsel.requirements()]
            assert got_f == rec.get("rq", [])
            assert bits(fsel, rec.get("fs", [])) == rec.get("m", "")
            check_rx(fsel, rec.get("rx"))
            eq = {q.field: q.value for q in fsel.requirements() if q.operator == "="}
            assert len(field_selector_from_set(eq).requirements()) == len(eq)
        else:
            assert f is None, "parse should fail"
            assert err == rec["e"]
    elif t == "esc":
        assert escape_field_value(rec["v"]) == rec["esc"]
        u, uerr = attempt(lambda: unescape_field_value(rec["v"]))
        if rec["ok"]:
            assert u == rec.get("out", ""), uerr
        else:
            assert u is None
            assert uerr == rec["e"]
    else:
        raise AssertionError(f"unknown record type {t}")


@dataclass
class Tally:
    records: int = 0
    failures: list[tuple[int, Rec, str]] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)
    valid: Counter[str] = field(default_factory=Counter)
    match_cases: int = 0


def check_lines(lines: Iterable[str]) -> Tally:
    tally = Tally()
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        rec: Rec = json.loads(line)
        tally.records += 1
        tally.counts[rec["t"]] += 1
        if rec.get("ok"):
            tally.valid[rec["t"]] += 1
        tally.match_cases += len(rec.get("m", ""))
        try:
            check_record(rec)
        except AssertionError as e:
            tally.failures.append((i, rec, str(e).splitlines()[0] if str(e) else "assertion failed"))
    return tally


def read_gz_lines(path: str) -> list[str]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return f.read().split("\n")
