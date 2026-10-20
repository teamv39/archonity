"""Итог M1 за прогон (engine/grounding/report.py): режим выдачи по источникам ответов LLM."""
from __future__ import annotations

from engine.grounding.llm import LLMStats
from engine.grounding.report import cache_only, format_m1_report, m1_report


def _steps(*sources: str) -> dict:
    return {"S1": [{"step": i + 1, "grounding": {"source": s}} for i, s in enumerate(sources)]}


class TestM1Report:
    def test_full_from_cache(self) -> None:
        r = m1_report(_steps("LLM", "LLM"), LLMStats(hits=12))
        assert r["mode"] == "full" and cache_only(r)
        assert "ВНИМАНИЕ" not in format_m1_report(r)

    def test_full_from_server_is_not_cache_only(self) -> None:
        r = m1_report(_steps("LLM"), LLMStats(hits=5, calls=1))
        assert r["mode"] == "full" and not cache_only(r)

    def test_lost_votes_are_partial(self) -> None:
        # Все шаги выбраны моделью, но часть выборок голосования без ответа: большинство считалось по остатку
        r = m1_report(_steps("LLM", "LLM"), LLMStats(hits=10, misses=2))
        assert r["mode"] == "partial" and not cache_only(r)

    def test_server_errors_are_partial(self) -> None:
        assert m1_report(_steps("LLM", "RETRIEVAL"), LLMStats(hits=6, errors=1))["mode"] == "partial"

    def test_no_answers_is_emergency(self) -> None:
        r = m1_report(_steps("RETRIEVAL", "RETRIEVAL"), LLMStats(misses=12), embed_misses=3)
        assert r["mode"] == "emergency" and r["embedding_misses"] == 3
        text = format_m1_report(r)
        assert "ВНИМАНИЕ" in text and "Проверка без кеша" in text

    def test_llm_disabled_is_emergency(self) -> None:
        r = m1_report(_steps("RETRIEVAL"), None)
        assert r["mode"] == "emergency" and not r["llm_enabled"] and "--no-llm" in format_m1_report(r)
