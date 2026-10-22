"""Получатель багажа без полей группы в параметрах шага — флажок «need consign» не отмечен (RuntimeRules.consign_absent_group,
annotation_rules.md, «Получатель багажа»).

X8.4 «Book one first-class seat … without food, assurance or consignment»: M1 не даёт ни имени, ни телефона, ни веса.
Без правила `consigneeName` неизвестен, условие в `PreserveServiceImpl#preserve` не решено и M4 идёт и в consign-ветку.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
X8 = ROOT / "eval" / "own" / "scenarios" / "X8.json"
CREATE_CONSIGN = "preserve.service.PreserveServiceImpl#createConsign("


def _executes(out: Path, mode: str) -> set[str]:
    res = subprocess.run(
        [sys.executable, str(ROOT / "run_eval.py"), "--scenarios", str(X8), "--consign-absent-group", mode,
         "--require-cache", "--no-eval", "-o", str(out)],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=300)
    if res.returncode == 2:
        pytest.skip("нет кеша LLM для X8")
    assert res.returncode == 0, res.stderr[-2000:]
    edges = json.loads(out.read_text(encoding="utf-8"))["scenarios"]["X8"]["edges"]
    return {e["target"] for e in edges if e["relation"] == "executes"}


@pytest.mark.skipif(not X8.is_file(), reason="нет сценария X8")
def test_booking_without_consignment_skips_consign_branch(tmp_path: Path) -> None:
    on = _executes(tmp_path / "on" / "submission.json", "on")
    off = _executes(tmp_path / "off" / "submission.json", "off")
    assert not any(CREATE_CONSIGN in m for m in on)
    assert any(CREATE_CONSIGN in m for m in off)
    assert on < off
