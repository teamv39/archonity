"""Явный ID в параметрах шага сильнее позиции в ссылке (RuntimeRules.ref_explicit_id, annotation_rules.md, R21).

X6.3 «Change the departure time of the trip G9998»: M1 даёт `tripId: G9998` и ссылку `trip: first_of_step_2`. Без
правила маршрут и станции тела берутся у первого рейса списка, проверка станций отказывает и рейс не обновляется.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
X6 = ROOT / "eval" / "own" / "scenarios" / "X6.json"
UPDATE_TRIP = "travel.controller.TravelController#updateTrip("


def _executes(out: Path, mode: str) -> set[str]:
    res = subprocess.run(
        [sys.executable, str(ROOT / "run_eval.py"), "--scenarios", str(X6), "--ref-explicit-id", mode,
         "--require-cache", "--no-eval", "-o", str(out)],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=300)
    if res.returncode == 2:
        pytest.skip("нет кеша LLM для X6")
    assert res.returncode == 0, res.stderr[-2000:]
    edges = json.loads(out.read_text(encoding="utf-8"))["scenarios"]["X6"]["edges"]
    return {e["target"] for e in edges if e["relation"] == "executes"}


@pytest.mark.skipif(not X6.is_file(), reason="нет сценария X6")
def test_named_trip_is_updated(tmp_path: Path) -> None:
    on = _executes(tmp_path / "on" / "submission.json", "on")
    off = _executes(tmp_path / "off" / "submission.json", "off")
    assert any(UPDATE_TRIP in m for m in on)
    assert not any(UPDATE_TRIP in m for m in off)
    assert off < on
