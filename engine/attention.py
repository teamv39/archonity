"""Заметная ошибка прогона (roadmap, Р2): рамка последней строкой вывода и `ATTENTION.txt` рядом с выдачей.

Решение запускают организаторы. Выдача строится всегда, код выхода 0, чтобы их скрипт не выбросил готовый
`submission.json`. Поэтому сбой должен быть виден из текста: что сломалось, сколько шагов затронуто, кому писать.

Сбой — запись `{"scenario", "step", "stage", "error", "where"}`: исключение на шаге (`step` — номер шага), в сценарии
(`step` — None) или в прогоне (`scenario` — None).
"""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

FILE_NAME = "ATTENTION.txt"
CONTACTS = "Telegram @Setttery, @gg_budet_m, почта mpaasha4@gmail.com"
RULE = "=" * 65
SHOWN = 5  # сбоев в рамке; полный список — в ATTENTION.txt


def failure(scenario: str | None, step: Any, stage: str, exc: BaseException) -> dict[str, Any]:
    """`where` — место исключения, файл:строка функция."""
    tb = traceback.extract_tb(exc.__traceback__)
    where = f"{Path(tb[-1].filename).name}:{tb[-1].lineno} {tb[-1].name}" if tb else ""
    return {"scenario": scenario, "step": step, "stage": stage, "error": f"{type(exc).__name__}: {exc}",
            "where": where}


def _where(f: dict[str, Any]) -> str:
    if f["scenario"] is None:
        return "прогон"
    return f["scenario"] if f["step"] is None else f"{f['scenario']}.{f['step']}"


def _m1_lines(report: dict[str, Any] | None) -> list[str]:
    """Что не так с M1: режим без части ответов LLM и векторы шагов без эмбеддера (поиск тогда только BM25)."""
    if report is None:
        return ["M1: отчёт не построен"]
    out = []
    if report["mode"] != "full":
        if not report.get("llm_enabled", True):
            why = "LLM выключена (--no-llm)"
        else:
            why = "нет ответов в cache/llm и сервер LLM не ответил"
        out.append(f"M1: режим {report['mode']}, шагов без модели {report['steps_by_retrieval']} "
                   f"из {report['steps']} ({why})")
    if report.get("embedding_misses"):
        out.append(f"M1: векторов без эмбеддера {report['embedding_misses']}, поиск кандидатов у этих шагов только BM25 "
                   f"({report.get('embedding_failure') or 'эмбеддер недоступен'})")
    return out


def needed(failures: list[dict[str, Any]], report: dict[str, Any] | None) -> bool:
    return bool(failures) or bool(_m1_lines(report))


def lines(failures: list[dict[str, Any]], report: dict[str, Any] | None, out: Path, *,
          empty_fallback: bool = False, full: bool = False) -> list[str]:
    """Текст ошибки: в рамке — первые `SHOWN` сбоев, при `full` — все."""
    head = (f"аварийный submission.json с пустыми блоками: {out}" if empty_fallback
            else f"submission.json записан: {out}")
    body = ["ARCHONITY: ВЫДАЧА ПОСТРОЕНА С ОШИБКАМИ", head]
    body += _m1_lines(report)
    if failures:
        steps = sum(f["scenario"] is not None and f["step"] is not None for f in failures)
        scenarios = sum(f["scenario"] is not None and f["step"] is None for f in failures)
        body.append(f"Сбоев {len(failures)}: на шагах {steps} (шаг без рёбер), в сценариях {scenarios} "
                    f"(пустой блок), в прогоне {len(failures) - steps - scenarios}")
        shown = failures if full else failures[:SHOWN]
        body += [f"  {_where(f)} ({f['stage']}): {f['error']}" + (f" [{f['where']}]" if full and f.get("where") else "")
                 for f in shown]
        if len(shown) < len(failures):
            body.append(f"  ... ещё {len(failures) - len(shown)}, полный список — {out.parent / FILE_NAME}")
    details = [out.parent / FILE_NAME] + ([out.parent / "m1_report.json"] if report is not None else [])
    body += [f"Пожалуйста, свяжитесь с командой Archonity: {CONTACTS}",
             f"Подробности: {', '.join(map(str, details))}"]
    return [RULE] + [f"!! {ln}" for x in body for ln in x.splitlines()] + [RULE]


def write(failures: list[dict[str, Any]], report: dict[str, Any] | None, out: Path, *,
          empty_fallback: bool = False) -> Path:
    path = out.parent / FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines(failures, report, out, empty_fallback=empty_fallback, full=True)) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def clear(out: Path) -> None:
    """Старый ATTENTION.txt от прошлого прогона в той же папке не должен пережить чистый прогон."""
    (out.parent / FILE_NAME).unlink(missing_ok=True)
