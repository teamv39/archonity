"""Итог M1 за прогон: откуда взяты ответы LLM и векторы, в каком режиме построена выдача.

Режимы:
- `full` — каждый шаг выбран моделью, все ответы LLM на месте (из кеша или от сервера);
- `partial` — часть ответов LLM нет (промах кеша без сервера, ошибка сервера): у шагов без выбора — первый
  кандидат поиска, у голосования — большинство из оставшихся голосов, без параметров — пустые поля;
- `emergency` — ни один шаг не выбран моделью: M1 — только поиск, параметров LLM нет.

Без ответов LLM выдача заметно хуже (замер 20.10 без кеша и сервера — итог 0.575 против 1.0,
docs/researches/gpu_dependence_and_cpu_fallback_study.md, раздел 7), поэтому режим печатается в конце прогона
и пишется в `m1_report.json`, а `run_eval.py --require-cache` завершается с ошибкой, если режим не `full` из кеша.
"""
from __future__ import annotations

from typing import Any

EMERGENCY_SCORE = 0.575  # итог без LLM, замер 20.10 (раздел 7 исследования)
STUDY = "docs/researches/gpu_dependence_and_cpu_fallback_study.md"


def m1_report(step_requests: dict[str, list[dict[str, Any]]], llm_stats: Any = None,
              embed_misses: int = 0, llm_keys: Any = (), embed_failure: str | None = None) -> dict[str, Any]:
    """Сводка M1: шаги по источнику выбора, ответы LLM (кеш, сервер, без ответа, ошибки), промахи векторов, режим;
    `llm_keys` — ключи всех запросов к LLM за прогон (по ним `scripts/verify_llm_cache.py` сверяет кеш);
    `embed_failure` — почему у промахов векторов нет модели (`STEmbedder.failure`).

    Режим считается только по LLM. Промах векторов режим не меняет, но у таких шагов поиск кандидатов идёт по одному
    BM25 (на X1–X8 верный обработчик среди кандидатов 70/83 вместо 81/83), поэтому он тоже идёт в рамку ATTENTION."""
    steps = [r for reqs in step_requests.values() for r in reqs]
    by_llm = sum((r.get("grounding") or {}).get("source") == "LLM" for r in steps)
    llm = {
        "from_cache": getattr(llm_stats, "hits", 0),
        "from_server": getattr(llm_stats, "calls", 0),
        "missing": getattr(llm_stats, "misses", 0),
        "errors": getattr(llm_stats, "errors", 0),
    }
    if llm_stats is None or by_llm == 0:
        mode = "emergency"
    elif by_llm == len(steps) and llm["missing"] == 0 and llm["errors"] == 0:
        mode = "full"
    else:
        mode = "partial"
    return {"mode": mode, "steps": len(steps), "steps_by_llm": by_llm, "steps_by_retrieval": len(steps) - by_llm,
            "llm": llm, "embedding_misses": embed_misses, "embedding_failure": embed_failure if embed_misses else None,
            "llm_enabled": llm_stats is not None,
            "llm_keys": sorted(set(llm_keys))}


def cache_only(report: dict[str, Any]) -> bool:
    """Выдача построена целиком из кеша: режим `full`, к серверу не обращались."""
    return report["mode"] == "full" and report["llm"]["from_server"] == 0


def format_m1_report(report: dict[str, Any]) -> str:
    llm = report["llm"]
    lines = [
        "=" * 65,
        f"M1: режим {report['mode']}. Шагов {report['steps']}: выбрано моделью {report['steps_by_llm']}, "
        f"первым кандидатом поиска {report['steps_by_retrieval']}",
        f"    ответы LLM: из кеша {llm['from_cache']}, от сервера {llm['from_server']}, без ответа {llm['missing']}, "
        f"ошибок {llm['errors']}; промахов кеша векторов {report['embedding_misses']}",
    ]
    if report["mode"] != "full":
        why = "LLM выключена (--no-llm)" if not report["llm_enabled"] else \
            "нет ответов в cache/llm и нет сервера LLM (или сервер вернул ошибку)"
        lines += [
            f"    ВНИМАНИЕ: выдача построена без части ответов модели — {why}.",
            f"    Без ответов LLM итог ниже: замер 20.10 — около {EMERGENCY_SCORE} против 1.0 ({STUDY}, раздел 7).",
            "    Воспроизвести рекорд: запуск из репозитория с cache/ (без GPU и сети) или сервер LLM — README,",
            "    раздел «Проверка без кеша».",
        ]
    if report.get("embedding_misses"):
        lines.append(f"    ВНИМАНИЕ: векторов без кеша и без модели {report['embedding_misses']} — поиск кандидатов у этих "
                     f"шагов только BM25 ({report.get('embedding_failure') or 'эмбеддер недоступен'}).")
    lines.append("=" * 65)
    return "\n".join(lines)


__all__ = ["m1_report", "cache_only", "format_m1_report"]
