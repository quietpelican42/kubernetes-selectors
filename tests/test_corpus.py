from __future__ import annotations

from pathlib import Path

from .conformance import check_lines, read_gz_lines

FIXTURE = Path(__file__).parent / "fixtures" / "corpus.jsonl.gz"


def test_agrees_with_go_corpus() -> None:
    t = check_lines(read_gz_lines(str(FIXTURE)))
    for line, rec, msg in t.failures[:5]:
        print(f"line {line}: {str(rec)[:300]}\n  {msg}")
    assert not t.failures, f"{len(t.failures)} of {t.records} records disagree with Go"
    assert t.counts["sel"] >= 20000
    assert t.match_cases >= 20000
    assert t.counts["lsel"] >= 5000
    assert t.counts["fld"] >= 5000
    print(f"checked {t.records} records {dict(t.counts)}, valid {dict(t.valid)}, {t.match_cases} match results")
