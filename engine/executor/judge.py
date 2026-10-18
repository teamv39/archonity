"""Судья LLM для условий UNKNOWN исполнителя M4 (ADR-005, «Вердикт судьи»).

Вход: текст метода, строка условия, известные значения переменных в момент проверки, текст шага.
Выход по JSON-схеме: `cited_line`, `reasoning`, `verdict` (TRUE, FALSE, UNKNOWN). Ответы кешируются
в `cache/llm/` (ключ — модель, версия промпта, вход); без сервера и без кеша судья молчит, и условие решают
правила по умолчанию. Судью зовут только для условий, где иначе исполнились бы оба плеча.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

PROMPT_VERSION = "m4-judge/1"

SCHEMA = {
    "type": "object",
    "properties": {
        "cited_line": {"type": "string"},
        "reasoning": {"type": "string"},
        "verdict": {"type": "string", "enum": ["TRUE", "FALSE", "UNKNOWN"]},
    },
    "required": ["cited_line", "reasoning", "verdict"],
}

SYSTEM = (
    "You judge one branch condition in a Java method of the Train Ticket microservice project. "
    "The scenario step and the known values are given. Answer TRUE or FALSE only if the condition's value "
    "follows from them; otherwise UNKNOWN. Do not guess."
)


class Judge:
    """Судья с кешем. `decide` -> True, False или None (нет вердикта)."""

    def __init__(self, llm: Any, nodes: dict[str, dict[str, Any]], targets_root: Path | None) -> None:
        self.llm = llm
        self.nodes = nodes
        self.root = targets_root
        self.step_text = ""
        self.calls = 0
        self.verdicts = 0
        self._src: dict[str, list[str]] = {}

    def _lines(self, file: str) -> list[str]:
        if file not in self._src:
            try:
                self._src[file] = (self.root / file).read_text(encoding="utf-8", errors="replace").splitlines()
            except (OSError, TypeError):
                self._src[file] = []
        return self._src[file]

    def decide(self, method: str, stmt: dict[str, Any], step: int | None, facts: str = "") -> bool | None:
        node = self.nodes.get(method, {})
        lines = self._lines(node.get("file", ""))
        if not lines or self.llm is None:
            return None
        start, end = node.get("line", 1), node.get("end", node.get("line", 1))
        body = "\n".join(lines[max(0, start - 1):end])
        cond = lines[stmt.get("line", 1) - 1].strip() if 0 < stmt.get("line", 0) <= len(lines) else ""
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Step: {self.step_text}\n\nMethod {method}:\n{body}\n\n"
                                        f"Condition (line {stmt.get('line')}): {cond}\n\nKnown values:\n{facts}"},
        ]
        self.calls += 1
        resp, _ = self.llm.complete_json("m4_judge", PROMPT_VERSION, messages, SCHEMA)
        if not resp or resp.get("verdict") not in ("TRUE", "FALSE"):
            return None
        self.verdicts += 1
        return resp["verdict"] == "TRUE"
