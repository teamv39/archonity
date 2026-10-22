"""Отчёт прогона (scripts/report.py): строится по файлам прогона S0, IoU против эталона организаторов, паритет."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import report  # noqa: E402

S0 = ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S0.json"


def test_report_on_s0(tmp_path: Path) -> None:
    out = tmp_path / "run" / "submission.json"
    res = subprocess.run(
        [sys.executable, str(ROOT / "run_eval.py"), "--scenarios", str(S0), "--require-cache", "--no-eval",
         "-o", str(out)], capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=300)
    if res.returncode == 2:
        pytest.skip("нет кеша LLM")
    assert res.returncode == 0, res.stderr[-2000:]

    page = report.main([str(out.parent), "--compare", str(out.parent)]).read_text(encoding="utf-8")

    assert "эталон организаторов" in page
    assert page.count('<span class=ok>1.0000</span>') == 4  # IoU S0 по четырём видам рёбер
    assert "байт в байт</td>" in page
    assert "режим <span class=ok>full</span>" in page
    assert "Шаг 1. " in page and "UserController.java:" in page  # шаг и место обработчика в коде
