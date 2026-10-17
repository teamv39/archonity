"""Журнал решений по рёбрам сценария (evidence.json v2, ADR-005).

Единственный источник ответа на вопрос «почему это ребро есть или его нет»: записи делает сам
GraphBuilder в момент решения, поэтому журнал не может разойтись с submission.json.

Ключ ребра — "relation|source|target", relation из submission: executes, calls, remote, data.
Каждое решение — включение (include), отсев (prune) или удаление уже включённого ребра (discard).
Ребро попадает в ответ, если хотя бы на одном шаге после всех решений этого шага оно осталось включённым:
так же, как пайплайн объединяет множества рёбер по шагам.
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Источник решения (ADR-005, evidence.json v2) плюс IR_CALL: ребро построено из вызова в IR, которого нет в скелете (R7)
SOURCE_TYPES = frozenset({
    "SKELETON",        # связь из скелета без условий: включена достижимостью или отсеяна структурно
    "IR_BRANCH",       # решено условием ветки из IR (branch_rules.json или R15-R17)
    "IR_CALL",         # ребро добавлено по вызову из IR (enum-вызовы R7)
    "STATE",           # решено состоянием сценария (заказы, фильтры)
    "DEFAULT_RULE",    # эвристика rules.py или правило по умолчанию движка
    "FRAMEWORK_RULE",  # правило фреймворка (Spring Security, конструкторы сущностей)
    "LLM_JUDGE",
})

INCLUDE = "include"
PRUNE = "prune"
DISCARD = "discard"

_RULES_MODULE = "engine.rules"


def edge_key(relation: str, source: str, target: str) -> str:
    return f"{relation}|{source}|{target}"


def rules_return_line(fn: Callable[..., bool], *args: Any, **kwargs: Any) -> str:
    """Повторяет вызов правила rules.py и возвращает строку, где оно вернуло True ("rules.py:<line>").

    Правила rules.py возвращают только bool. Чтобы журнал называл конкретное правило, вызов
    повторяется под трассировкой: первая строка `return` со значением True внутри rules.py
    (самая вложенная) и есть сработавшее правило. Вызывается только для отсеянных рёбер.
    """
    hit: list[int] = []

    def local(frame: Any, event: str, arg: Any) -> Any:
        if event == "return" and arg is True and not hit:
            hit.append(frame.f_lineno)
        return local

    def tracer(frame: Any, event: str, arg: Any) -> Any:
        if event == "call" and frame.f_globals.get("__name__") == _RULES_MODULE:
            return local
        return None

    prev = sys.gettrace()
    sys.settrace(tracer)
    try:
        fn(*args, **kwargs)
    finally:
        sys.settrace(prev)
    return f"rules.py:{hit[0]}" if hit else "rules.py"


@dataclass
class Decision:
    step: int | None
    op: str
    source_type: str
    rule: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"step": self.step, "op": self.op, "source_type": self.source_type, "rule": self.rule}
        d.update(self.detail)
        return d


class DecisionLedger:
    """Журнал решений по всем сценариям прогона."""

    def __init__(self) -> None:
        self._scenarios: dict[str, dict[str, list[Decision]]] = {}
        self._sid: str | None = None
        self._step: int | None = None

    def begin_scenario(self, scenario_id: str) -> None:
        self._sid = scenario_id
        self._step = None
        self._scenarios[scenario_id] = {}

    def begin_step(self, step: int | None) -> None:
        self._step = step

    @property
    def scenario_id(self) -> str:
        if self._sid is None:
            raise RuntimeError("DecisionLedger: begin_scenario не вызван")
        return self._sid

    def _record(self, op: str, relation: str, source: str, target: str, source_type: str, rule: str,
                detail: dict[str, Any]) -> None:
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"Неизвестный source_type: {source_type}")
        key = edge_key(relation, source, target)
        self._scenarios[self.scenario_id].setdefault(key, []).append(
            Decision(self._step, op, source_type, rule, detail)
        )

    def include(self, relation: str, source: str, target: str, source_type: str, rule: str, **detail: Any) -> None:
        self._record(INCLUDE, relation, source, target, source_type, rule, detail)

    def prune(self, relation: str, source: str, target: str, source_type: str, rule: str, **detail: Any) -> None:
        self._record(PRUNE, relation, source, target, source_type, rule, detail)

    def discard(self, relation: str, source: str, target: str, source_type: str, rule: str, **detail: Any) -> None:
        self._record(DISCARD, relation, source, target, source_type, rule, detail)

    def execute(self, method: str, source_type: str, rule: str, **detail: Any) -> None:
        """Метод исполнен: ребро executes от сценария."""
        self.include("executes", f"scenario:{self.scenario_id}", method, source_type, rule, **detail)

    @staticmethod
    def _included_steps(decisions: list[Decision]) -> list[int | None]:
        """Шаги, после которых ребро осталось включённым (prune не снимает включение, discard снимает)."""
        state: dict[int | None, bool] = {}
        for d in decisions:
            if d.op == INCLUDE:
                state[d.step] = True
            elif d.op == DISCARD:
                state[d.step] = False
        return [s for s, on in state.items() if on]

    def final_edges(self, scenario_id: str) -> set[tuple[str, str, str]]:
        """Рёбра ответа сценария (relation, source, target) по журналу."""
        out = set()
        for key, decisions in self._scenarios.get(scenario_id, {}).items():
            if self._included_steps(decisions):
                relation, source, target = key.split("|", 2)
                out.add((relation, source, target))
        return out

    def scenario_dict(self, scenario_id: str) -> dict[str, Any]:
        """Записи сценария: итог по ребру и все решения по шагам."""
        result: dict[str, Any] = {}
        for key in sorted(self._scenarios.get(scenario_id, {})):
            decisions = self._scenarios[scenario_id][key]
            steps = self._included_steps(decisions)
            # Итоговое обоснование: первое включение для рёбер ответа, последний отсев для остальных
            if steps:
                main = next(d for d in decisions if d.op == INCLUDE and d.step in steps)
            else:
                main = next((d for d in reversed(decisions) if d.op != INCLUDE), decisions[-1])
            entry: dict[str, Any] = {
                "included": bool(steps),
                "steps": sorted(steps, key=lambda s: (s is None, s)),
                "source_type": main.source_type,
                "rule": main.rule,
            }
            entry.update(main.detail)
            entry["decisions"] = [d.to_dict() for d in decisions]
            result[key] = entry
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 2,
            "scenarios": {sid: self.scenario_dict(sid) for sid in sorted(self._scenarios)},
        }
