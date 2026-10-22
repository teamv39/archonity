"""Ссылка на список без слова позиции в тексте шага — созданная запись (RuntimeRules.ref_unpositioned, annotation_rules.md, R22).

X10.8 «Pay for the order from the internal account balance» после «Refresh the list of orders»: M1 дал
`order: first_of_step_7` (список), а оплачивать нужно заказ, который сценарий забронировал на шаге 6. Первый в списке —
старый заказ пассажира из дампа, оплата отказывает («Order status Not allowed to Pay»), и дальше выдача билета и вход
идут по неоплаченному заказу. Перефразированный S6.13 — тот же случай.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from engine.executor.step import _POSITION

ROOT = Path(__file__).resolve().parent.parent
X10 = ROOT / "eval" / "own" / "scenarios" / "X10.json"
EXEC = ROOT / "rust" / "target" / "release" / "archonity-exec"
SET_STATUS = "InsidePaymentServiceImpl#setOrderStatus("


def _run(out: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "run_eval.py"), "--scenarios", str(X10), "--require-cache", "--no-eval",
         "-o", str(out), *flags],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=300)


def _executes(out: Path, mode: str) -> set[str]:
    res = _run(out, "--ref-unpositioned", mode)
    if res.returncode == 2 and "--require-cache" in res.stdout + res.stderr:
        pytest.skip("нет кеша LLM для X10")
    assert res.returncode == 0, res.stderr[-2000:]
    edges = json.loads(out.read_text(encoding="utf-8"))["scenarios"]["X10"]["edges"]
    return {e["target"] for e in edges if e["relation"] == "executes"}


@pytest.mark.skipif(not X10.is_file(), reason="нет сценария X10")
def test_created_order_is_paid(tmp_path: Path) -> None:
    on = _executes(tmp_path / "on" / "submission.json", "on")
    off = _executes(tmp_path / "off" / "submission.json", "off")
    assert any(SET_STATUS in m for m in on)
    assert not any(SET_STATUS in m for m in off)
    # без правила отмена «использованного» заказа проходит как для неоплаченного и возвращает деньги (`drawBack`)
    assert any("drawBack(" in m for m in off - on)


@pytest.mark.parametrize("text", [
    "Open the first new order",
    "Pay for the second order from the internal account balance",
    "Book another first-class seat on the same trip",
    "Cancel the 2nd order",
    "Pay for the last order",
])
def test_position_words_keep_the_reference(text: str) -> None:
    assert _POSITION.search(text)


@pytest.mark.parametrize("text", [
    "Pay for the order from the internal account balance",
    "Try to rebook the used order onto a first-class seat on a regular train",
    "Cancel the new order",
])
def test_no_position_word_prefers_the_created_record(text: str) -> None:
    assert not _POSITION.search(text)


@pytest.mark.skipif(not X10.is_file(), reason="нет сценария X10")
@pytest.mark.skipif(not EXEC.is_file(), reason="нет archonity-exec: cd rust && cargo build --release --locked")
def test_rust_engine_matches_python(tmp_path: Path) -> None:
    """R22 в Rust (`StepCore::prefer_created`): с правилом выдача X10 та же, что у Python-движка, байт в байт."""
    py, rs = tmp_path / "py" / "submission.json", tmp_path / "rs" / "submission.json"
    res = _run(py, "--ref-unpositioned", "on", "--engine", "python")
    if res.returncode == 2 and "--require-cache" in res.stdout + res.stderr:
        pytest.skip("нет кеша LLM для X10")
    assert res.returncode == 0, res.stderr[-2000:]
    res = _run(rs, "--ref-unpositioned", "on", "--engine", "rust")
    assert res.returncode == 0, res.stderr[-2000:]
    assert not (rs.parent / "ATTENTION.txt").exists(), "Rust не отработал, выдача — отката на Python"
    assert rs.read_bytes() == py.read_bytes()
