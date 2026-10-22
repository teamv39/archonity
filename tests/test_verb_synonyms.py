"""`VERB_SYN_EXTRA` и `VERB_OBJECT_SYN` (engine/grounding/text.py) не меняют кандидатов M1 у шагов S0–S7 и своих
сценариев X1–X8.

Кандидаты входят в промпт выбора, а значит в ключ кеша LLM: если бы синонимы сдвинули их у шага с ответом в `cache/`,
рекорд перестал бы воспроизводиться без GPU. Расширение смотрит только на первое слово шага, поэтому сторожей два:
ни один шаг не начинается со слова словаря, и списки кандидатов с синонимами и без них совпадают.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.grounding.text import VERB_OBJECT_SYN, VERB_SYN_EXTRA, query_toks

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = sorted((ROOT / "hackaton" / "tt-challenge" / "scenarios").glob("S*.json")) \
    + sorted((ROOT / "eval" / "own" / "scenarios").glob("X*.json"))


def _steps() -> list[tuple[str, list[str]]]:
    out = []
    for f in SCENARIOS:
        sc = json.loads(f.read_text(encoding="utf-8"))
        out.append((sc["id"], [s["action"] for s in sc["steps"]]))
    return out


@pytest.mark.skipif(not SCENARIOS, reason="нет сценариев")
def test_no_step_starts_with_extra_verb() -> None:
    hits = [(sid, a) for sid, acts in _steps() for a in acts if (query_toks(a) or [""])[0] in VERB_SYN_EXTRA]
    assert not hits, hits


@pytest.mark.skipif(not SCENARIOS, reason="нет сценариев")
def test_no_step_matches_verb_object() -> None:
    hits = [(sid, a) for sid, acts in _steps() for a in acts for obj, (verbs, _) in VERB_OBJECT_SYN.items()
            if (q := query_toks(a)) and q[0] in verbs and obj in q[1:]]
    assert not hits, hits


PARAPHRASE_S4 = ROOT / "eval" / "paraphrase" / "scenarios" / "S4.json"


@pytest.mark.skipif(not PARAPHRASE_S4.is_file(), reason="нет перефразированного S4")
def test_create_account_finds_registration(shared_pipeline) -> None:
    """Перефразированный S4.1 «Create a new passenger account…»: регистрация среди кандидатов (без правила — 12-я)."""
    g = shared_pipeline.m1
    step = json.loads(PARAPHRASE_S4.read_text(encoding="utf-8"))["steps"][0]["action"]
    cands = g.retriever.search([step])[0].candidates(g.top_k, g.retriever.twins)
    assert any("ts-user-service:user.controller.UserController#registerUser" in h for h in cands)


@pytest.mark.skipif(not SCENARIOS, reason="нет сценариев")
def test_candidates_unchanged(shared_pipeline, monkeypatch) -> None:
    g = shared_pipeline.m1
    r = g.retriever

    def cands(on: bool) -> list[tuple[str, ...]]:
        monkeypatch.setattr(r, "verb_synonyms", on)
        return [tuple(x.candidates(g.top_k, r.twins)) for _, acts in _steps() for x in r.search(acts)]

    assert cands(True) == cands(False)
