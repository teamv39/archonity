"""Проекция исполнения на рёбра эталона (M5): видимость конструкторов (правило R7, ADR-006).

Трассировщик организаторов перехватывает методы, но не конструкторы. Конструктор виден в эталоне только как
кадр, из которого вызван перехваченный метод проекта (`Order#<init>() -> Date2String`). Отсюда:
- конструктор идёт в `executes`, только если из него исполнился вызов проекта, то есть он источник ребра шага;
- рёбер `calls` в конструктор нет никогда.

Способ создания объекта (`new` из кода проекта, Hibernate) не важен. Исполнитель M4 пишет
исполнение как есть, отбор делает эта функция на каждом шаге.
"""
from __future__ import annotations

from typing import Any

RULE = "R7:ctor_visibility"


def is_ctor(method_id: str) -> bool:
    return "#<init>(" in method_id


def project_constructors(
    methods: set[str],
    calls: set[tuple[str, str]],
    remote: set[tuple[str, str]],
    data: set[tuple[str, str]],
    mode: str,
    ledger: Any = None,
) -> None:
    """Отбор конструкторов шага по режиму `RuntimeRules.constructors`, множества правятся на месте.

    all — без изменений (как до ADR-006); caller_only — без рёбер `calls` в конструктор и без конструкторов,
    которые не стоят источником ни одного ребра шага; off — без конструкторов и рёбер с ними (отладка).
    Каждое удаление пишется в журнал решений на текущем шаге, рядом с включением.
    """
    if mode == "all":
        return
    for rel, edges in (("calls", calls), ("remote", remote), ("data", data)):
        for s, t in sorted(edges):
            if mode == "off" and (is_ctor(s) or is_ctor(t)):
                why = f"{RULE}:off"
            elif rel == "calls" and is_ctor(t):
                why = f"{RULE}:no_calls_into_ctor"
            else:
                continue
            edges.discard((s, t))
            if ledger is not None:
                ledger.discard(rel, s, t, "FRAMEWORK_RULE", why)
    sources = {s for s, _ in calls | remote | data}
    for m in sorted(methods):
        if is_ctor(m) and m not in sources:
            methods.discard(m)
            if ledger is not None:
                why = f"{RULE}:off" if mode == "off" else f"{RULE}:no_project_call"
                ledger.discard("executes", f"scenario:{ledger.scenario_id}", m, "FRAMEWORK_RULE", why)
