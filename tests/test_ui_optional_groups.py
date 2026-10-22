"""Поля под условием UI (RuntimeRules.ui_optional_groups, annotation_rules.md, «Поля под условием UI»).

Каталог UI выделяет группы полей, которые форма шлёт только под общим условием (флажок, заполненный раздел), и
литералы этого условия. Шаг не дал ни поля группы, ни литерала со значением не по умолчанию — группы в запросе нет.

X8.4 «Book one first-class seat … without food, assurance or consignment»: M1 не даёт полей получателя багажа. Без
правила они неизвестны, условие в `PreserveServiceImpl#preserve` не решено, и M4 идёт и в ветку `createConsign`.
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

from engine.grounding.request import canon_value, group_sent
from engine.grounding.ui_catalog import UIRequest

ROOT = Path(__file__).resolve().parent.parent
X8 = ROOT / "eval" / "own" / "scenarios" / "X8.json"
CATALOG = ROOT / "data" / "ui_catalog.json"
CREATE_CONSIGN = "preserve.service.PreserveServiceImpl#createConsign("


def test_canon_value() -> None:
    """Те же случаи, что `canon_value_matches_python` в `rust/crates/archonity-model/src/request.rs`."""
    cases = [(None, None), (False, None), (0, None), (0.0, None), ("", None), ("0", None), (True, "true"), (2, "2"),
             (2.0, "2"), ("2", "2"), (0.5, "0.5"), ("0.5", "0.5"), ("false", None), ("Suzhou", "Suzhou"), ([1], None)]
    for v, want in cases:
        assert canon_value(v) == want, v


def test_group_sent_needs_non_default_value() -> None:
    g = {"fields": ["w", "name"], "on": [["kind", "2"]]}
    assert not group_sent(g, {})
    assert not group_sent(g, {"w": 0.0, "kind": 0})
    assert group_sent(g, {"w": 3.0})
    assert group_sent(g, {"kind": 2})
    assert not group_sent(g, {"kind": 1})


@pytest.mark.skipif(not CATALOG.is_file(), reason="нет каталога UI")
def test_catalog_groups_follow_ui_condition() -> None:
    """Группы — из кода формы, а не из имён: у каждой группы свои поля, литерал условия попадает в `on`, только
    если UI ставит его внутри условия группы (значение по умолчанию признаком не служит)."""
    names = {f.name for f in dataclasses.fields(UIRequest)}
    reqs = [UIRequest(**{k: v for k, v in r.items() if k in names})
            for r in json.loads(CATALOG.read_text(encoding="utf-8"))["requests"]]
    with_groups = [r for r in reqs if r.body_groups()]
    assert with_groups
    for r in with_groups:
        groups = r.body_groups()
        opt = {o["field"] for o in r.body_opt}
        assert {f for g in groups for f in g["fields"]} == opt
        for g in groups:
            assert all(v is not None and canon_value(v) == v for _, v in g["on"])


def _executes(out: Path, mode: str) -> set[str]:
    res = subprocess.run(
        [sys.executable, str(ROOT / "run_eval.py"), "--scenarios", str(X8), "--ui-optional-groups", mode,
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
