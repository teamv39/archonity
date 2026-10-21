"""Rust-движок (ADR-008): выдача `--engine rust` совпадает с Python байт в байт. Пропускается без собранного бинарника
(`cd rust && cargo build --release --locked`) или без кеша LLM."""
from __future__ import annotations

import filecmp
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "rust" / "target" / "release" / "archonity-exec"
pytestmark = pytest.mark.skipif(not BIN.is_file(), reason="нет бинарника archonity-exec")


def _run(engine: str, out: Path) -> None:
    res = subprocess.run(
        [sys.executable, str(ROOT / "run_eval.py"), "--engine", engine, "--require-cache", "--no-eval", "-o", str(out)],
        cwd=ROOT, capture_output=True, text=True, env={**__import__("os").environ, "PYTHONUTF8": "1"},
    )
    if res.returncode == 2:
        pytest.skip("нет кеша LLM")
    assert res.returncode == 0, res.stderr[-2000:]


def test_rust_matches_python(tmp_path):
    _run("python", tmp_path / "py" / "submission.json")
    _run("rust", tmp_path / "rs" / "submission.json")
    for name in ("submission.json", "decisions.json", "evidence.json", "m4_unknowns.json"):
        assert filecmp.cmp(tmp_path / "py" / name, tmp_path / "rs" / name, shallow=False), name
    assert filecmp.cmp(tmp_path / "py" / "step_requests.json", tmp_path / "rs" / "step_requests.json", shallow=False)
