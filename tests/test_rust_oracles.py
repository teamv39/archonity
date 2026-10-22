"""Оракулы переноса на Rust (ADR-008): выдача оракула = рекорд, вход Rust — шаги до R20, трасса выключена по умолчанию."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "hackaton" / "tt-challenge" / "scenarios"

pytestmark = pytest.mark.skipif(not SCENARIOS.is_dir(), reason="нет пакета организаторов")


def _run(out: Path, *args: str, trace: Path | None = None) -> None:
    env = dict(os.environ, PYTHONUTF8="1")
    env.pop("ARCHONITY_TRACE", None)
    if trace is not None:
        env["ARCHONITY_TRACE"] = str(trace)
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "rust_oracles.py"), *args],
                         capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=env, timeout=600)
    assert res.returncode == 0, res.stderr[-2000:]


def test_steps_oracle_keeps_record_and_records_pre_r20_requests(tmp_path: Path) -> None:
    trace = tmp_path / "trace.tsv"
    _run(tmp_path, "steps", str(tmp_path), trace=trace)

    # S0-S7 целиком: выдача оракула = рекорд (eval/records/README.md)
    assert hashlib.sha256((tmp_path / "submission.json").read_bytes()).hexdigest() == \
        "94463c41a72c244fc548cbb52d009cff7c65f44ad5e682b7176a156cb66a5a08"

    raw = json.loads((tmp_path / "step_requests_raw.json").read_text(encoding="utf-8"))
    steps = json.loads((tmp_path / "raw_steps.json").read_text(encoding="utf-8"))
    assert sorted(raw) == sorted(steps)
    for sid, blocks in steps.items():
        assert [s["step"] for s in blocks["steps"]] == [r["step"] for r in raw[sid]]
    # R20 хотя бы раз заменил обработчик: у входа Rust он другой, чем у шага, который получил M4
    pairs = [(r["handler"], s["request"]["handler"]) for sid in raw for r, s in zip(raw[sid], steps[sid]["steps"])]
    assert any(a != b for a, b in pairs)

    lines = trace.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# scenario S0" and lines[1] == "# step 1"
    assert lines[2].split("\t")[0] == "0"


def test_trace_is_off_by_default(tmp_path: Path) -> None:
    _run(tmp_path, "steps", str(tmp_path), str(SCENARIOS / "S0.json"))
    assert not list(tmp_path.glob("*.tsv"))
