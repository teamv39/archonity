"""Построитель графа связей и обход достижимости (Reachability Traversal).

Реализует правила ADR-001, ADR-003, ADR-004:
- Изоляция терминальных узлов БД (ребра data не имеют исходящих связей).
- Разделение контекста deployment units.
- Фильтрация мертвого кода и нерелевантных административных вызовов.
"""
from __future__ import annotations

from typing import Any, Iterable

from engine.adapters.skeleton import SkeletonIndex
from engine.rules import RuntimeRules


class GraphBuilder:
    """Движок обхода графа вызовов от точек входа сценария."""

    def __init__(self, index: SkeletonIndex, rules: RuntimeRules | None = None) -> None:
        self.index = index
        self.rules = rules or RuntimeRules()

    def traverse(
        self,
        entry_methods: Iterable[str],
        is_admin_scenario: bool = False,
    ) -> tuple[set[str], set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
        """Обход графа от точек входа.

        Возвращает:
            methods: множество вызванных методов
            calls: внутрисервисные вызовы (method -> method)
            remote: межсервисные вызовы (method -> method другого сервиса)
            data: обращения к таблицам БД (method -> res:table:...)
        """
        seen_methods: set[tuple[str, str]] = set()
        edges_calls: set[tuple[str, str]] = set()
        edges_remote: set[tuple[str, str]] = set()
        edges_data: set[tuple[str, str]] = set()

        # Фильтруем сами точки входа от заведомого мертвого кода
        valid_entries = [
            m for m in entry_methods
            if not self.rules.is_dead_code_method(m, is_admin_scenario)
        ]

        # Очередь обхода: (текущий_метод, deployment_unit)
        stack = [(m, self.index.unit_of(m)) for m in valid_entries]

        while stack:
            m, u = stack.pop()
            if (m, u) in seen_methods:
                continue
            seen_methods.add((m, u))

            # 1. Внутрисервисные вызовы (calls + overrides/CHA + runtime_dispatch)
            for t in self.index.calls.get(m, ()):
                dispatch_targets = (
                    {t}
                    | self.index.cha(t)
                    | self.index.wiring["runtime_dispatch"].get(m, set())
                )
                for x in dispatch_targets:
                    # Проверяем, не абстрактный ли и находится ли в том же unit
                    if self.index.N.get(x, {}).get("abstract"):
                        continue
                    target_mod = self.index.module.get(x, "")
                    if u not in self.index.units.get(target_mod, ()):
                        continue
                    if self.rules.is_dead_code_method(x, is_admin_scenario):
                        continue

                    edges_calls.add((m, x))
                    stack.append((x, u))

            # 2. Межсервисные вызовы (remote_call + message_delivery)
            remote_targets = (
                self.index.wiring["remote_call"].get(m, set())
                | self.index.wiring["message_delivery"].get(m, set())
            )
            for t in remote_targets:
                if self.rules.is_dead_code_method(t, is_admin_scenario):
                    continue

                edges_remote.add((m, t))
                stack.append((t, self.index.unit_of(t)))

            # 3. Обращения к таблицам баз данных (data_access)
            # ПРАВИЛО БД: узлы БД (res:table:...) являются терминальными стоками (terminal sinks).
            # В стек они не добавляются, из них обход не продолжается!
            for t in self.index.wiring["data_access"].get(m, set()):
                if self.rules.is_dead_code_edge(m, "data", t, is_admin_scenario):
                    continue
                edges_data.add((m, t))

        active_methods = {m for m, _ in seen_methods}
        return active_methods, edges_calls, edges_remote, edges_data
