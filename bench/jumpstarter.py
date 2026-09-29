"""Measure the hand-written selector parser in jumpstarter-dev/jumpstarter against the Go corpus.

The file is fetched at run time from a commit-pinned URL, checked against a sha256 and kept in
the gitignored .cache directory. It is not part of this repository.

    python bench/jumpstarter.py
"""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

SHA = "c6f3978165d5019fe46457fd74fb832e8057c01d"
PATH = "python/packages/jumpstarter/jumpstarter/client/selectors.py"
URL = f"https://raw.githubusercontent.com/jumpstarter-dev/jumpstarter/{SHA}/{PATH}"
SHA256 = "a01f70025a7546dd9f33e2fb8bf395f71ed51df9f6a1b602f47107ceaf14696e"
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "js_selectors.py"


def load() -> Any:
    if not CACHE.exists():
        CACHE.parent.mkdir(exist_ok=True)
        try:
            with urllib.request.urlopen(URL, timeout=30) as r:  # noqa: S310
                CACHE.write_bytes(r.read())
        except OSError as e:
            print(f"SKIPPED: could not fetch {URL}: {e}")
            return None
    if hashlib.sha256(CACHE.read_bytes()).hexdigest() != SHA256:
        print(f"SKIPPED: {CACHE} does not match the pinned sha256")
        return None
    spec = importlib.util.spec_from_file_location("js_selectors", CACHE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def as_requirements(labels: dict[str, str], exprs: list[tuple[str, str, list[str]]]) -> list[tuple[str, str, tuple[str, ...]]]:
    ops = {"in": "in", "notin": "notin", "!=": "!=", "exists": "exists", "!exists": "!"}
    out: list[tuple[str, str, tuple[str, ...]]] = [(k, "=", (v,)) for k, v in labels.items()]
    out += [(k, ops.get(op, op), tuple(sorted(set(vals)))) for k, op, vals in exprs]
    return sorted(out)


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.2f}%"


def main() -> int:
    mod = load()
    if mod is None:
        return 0
    lines = gzip.open(ROOT / "tests" / "fixtures" / "corpus.jsonl.gz", "rt", encoding="utf-8").read().split("\n")
    invalid = accepted = valid = same = 0
    cases = case_same = 0
    for line in filter(None, lines):
        r = json.loads(line)
        if r["t"] != "sel":
            continue
        try:
            labels, exprs = mod.parse_label_selector(r["s"])
            parsed = True
        except Exception:
            parsed = False
        if not r["ok"]:
            invalid += 1
            accepted += parsed
            continue
        valid += 1
        want = sorted(
            (q["k"], "=" if q["o"] == "==" else q["o"], tuple(q["v"])) for q in r.get("rq", [])
        )
        if parsed and as_requirements(labels, exprs) == want:
            same += 1
        if any(q["o"] in ("gt", "lt") for q in r.get("rq", [])):
            continue
        for sel_labels, bit in zip(r["ls"], r["m"], strict=True):
            cases += 1
            try:
                ok = all(
                    sel_labels.get(k) == v for k, v in labels.items()
                ) and all(mod._label_satisfies_expression(sel_labels, k, op, vals) for k, op, vals in exprs)
            except Exception:
                ok = None
            case_same += ok == (bit == "1")
    print(f"Go-invalid selectors: {invalid}, silently accepted by jumpstarter parse_label_selector: {accepted} ({pct(accepted, invalid)})")
    print(f"Go-valid selectors: {valid}, parsed to the same requirements: {same} ({pct(same, valid)})")
    print(f"match results (Go-valid, no gt/lt): {case_same}/{cases} equal ({pct(case_same, cases)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
