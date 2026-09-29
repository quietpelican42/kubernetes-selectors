from __future__ import annotations

import os
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from .conformance import check_lines

GEN = Path(__file__).resolve().parent.parent / "gen"


@pytest.mark.skipif(
    shutil.which("go") is None,
    reason="SKIPPED LOUDLY: `go` not found on PATH; install Go to run the live oracle test",
)
def test_live_fresh_corpus_from_go(tmp_path: Path) -> None:
    seed = random.randrange(10**9)
    out = tmp_path / "corpus.jsonl"
    scale = os.environ.get("K8SSEL_SCALE", "0.15")
    run = subprocess.run(
        ["go", "run", ".", "-seed", str(seed), "-scale", scale, "-out", str(out)],
        cwd=GEN,
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, "GOFLAGS": "-mod=mod"},
        check=False,
    )
    if run.returncode != 0:
        pytest.skip(f"SKIPPED LOUDLY: go run failed (offline or module cache empty?): {run.stderr[:300]}")
    tally = check_lines(out.read_text(encoding="utf-8").split("\n"))
    for line, rec, msg in tally.failures[:3]:
        print(f"seed {seed} line {line}: {str(rec)[:300]}\n  {msg}")
    assert not tally.failures, f"seed {seed}: {len(tally.failures)}/{tally.records} disagree"
    print(f"live seed {seed}: {tally.records} records agree")
