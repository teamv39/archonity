"""`VERB_SYN_EXTRA`, `VERB_OBJECT_SYN` и `PHRASAL_VERBS` (engine/grounding/text.py) не меняют кандидатов M1 у шагов
S0–S7 и своих сценариев X1–X12.

Кандидаты входят в промпт выбора, а значит в ключ кеша LLM: если бы синонимы сдвинули их у шага с ответом в `cache/`,
рекорд перестал бы воспроизводиться без GPU. Расширение смотрит только на первое слово шага, поэтому сторожей два:
ни один шаг не начинается со слова словаря, и списки кандидатов с синонимами и без них совпадают.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.grounding.text import PHRASAL_VERBS, VERB_OBJECT_SYN, VERB_SYN_EXTRA, expand_query, query_toks

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
def test_no_step_starts_with_phrasal_verb() -> None:
    hits = [(sid, a) for sid, acts in _steps() for a in acts if tuple(query_toks(a)[:2]) in PHRASAL_VERBS]
    assert not hits, hits


def test_phrasal_verb_is_replaced_by_synonym() -> None:
    q = query_toks("Looking for ordinary trains from Shanghai to Nanjing")
    assert expand_query(q)[:2] == ["search", "ordinary"]
    assert expand_query(q)[-3:] == ["get", "find", "query"]  # дальше `search` расширяется как обычный глагол
    assert expand_query(q, extra=False) == q + ["get", "find", "query"]  # без синонимов фраза остаётся как есть
    for text in ("Look up the luggage record of the order", "Look at the food stores of the station"):
        q = query_toks(text)
        assert expand_query(q) == q + ["get", "find", "query"]  # «Look up» и «Look at» остаются прежними


PARAPHRASE_STEPS = {
    "X10.2": (ROOT / "eval" / "own" / "paraphrase" / "X10.json", 2),
    "S2.2": (ROOT / "eval" / "paraphrase" / "scenarios" / "S2.json", 2),
}


@pytest.mark.parametrize("name", PARAPHRASE_STEPS)
def test_look_for_finds_search_handler(shared_pipeline, name: str) -> None:
    """«Look for ordinary trains …» (перефразированные X10.2 и S2.2): поиск рейсов Other-стороны среди кандидатов
    (без правила — на 26-м и 28-м месте слитого списка)."""
    path, n = PARAPHRASE_STEPS[name]
    if not path.is_file():
        pytest.skip("нет перефразированного сценария")
    g = shared_pipeline.m1
    step = next(s["action"] for s in json.loads(path.read_text(encoding="utf-8"))["steps"] if s["n"] == n)
    assert step.startswith("Look for")
    cands = g.retriever.search([step])[0].candidates(g.top_k, g.retriever.twins)
    assert any("ts-travel2-service:travel2.controller.Travel2Controller#queryInfo" in h for h in cands)


@pytest.mark.skipif(not SCENARIOS, reason="нет сценариев")
def test_candidates_unchanged(shared_pipeline, monkeypatch) -> None:
    g = shared_pipeline.m1
    r = g.retriever

    def cands(on: bool) -> list[tuple[str, ...]]:
        monkeypatch.setattr(r, "verb_synonyms", on)
        return [tuple(x.candidates(g.top_k, r.twins)) for _, acts in _steps() for x in r.search(acts)]

    assert cands(True) == cands(False)
