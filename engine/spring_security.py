"""Spring Security при входе: методы и рёбра, которые исполняет фреймворк (правило фреймворка, ADR-005).

Вход — исполненный метод, в котором стоит вызов `AuthenticationManager.authenticate`. Его исполняет
DaoAuthenticationProvider: `loadUserByUsername` реализации `UserDetailsService` того же модуля (SQL — к таблицам
`data_access` этого метода, ленивые коллекции по R10 не загружены), затем методы `UserDetails` загруженного
пользователя. Ребро от входа к методу `UserDetails` — по R6: у входа есть call_site с тем же именем. Фильтры —
`doFilterInternal` подклассов `OncePerRequestFilter`. Имён проекта правило не знает: только типы и методы контракта.

Тел этих методов M4 не исполняет: их вызывает код фреймворка, которого нет в скелете. Применяется к рёбрам шага
после M4 (`ArchonityPipeline.run_scenario`).
"""
from __future__ import annotations

from typing import Any

from engine.decisions import DecisionLedger

_AUTH_MANAGER = "org.springframework.security.authentication.AuthenticationManager"
# Методы UserDetails, которые DaoAuthenticationProvider вызывает в authenticate: проверки до и после пароля,
# сам пароль, роли для итогового Authentication. getUsername провайдер не вызывает.
_PROVIDER_USER_METHODS = (
    "isAccountNonLocked", "isEnabled", "isAccountNonExpired", "getPassword", "isCredentialsNonExpired",
    "getAuthorities",
)
_RULE = "spring_security"


def apply_spring_security(
    index: Any,
    methods: set[str],
    calls: set[tuple[str, str]],
    data: set[tuple[str, str]],
    ledger: DecisionLedger | None = None,
) -> None:
    """Дополняет исполненные методы и рёбра шага методами, которые при входе вызывает Spring Security."""
    entries = [
        m for m in sorted(methods)
        if any(c.get("callee") == "authenticate" and c.get("receiver_type") == _AUTH_MANAGER
               for c in index.cs_nodes_by_method.get(m, ()))
    ]

    def execute(m: str) -> None:
        if ledger is not None and m not in methods:
            ledger.execute(m, "FRAMEWORK_RULE", _RULE)
        methods.add(m)

    def include(edges: set[tuple[str, str]], relation: str, s: str, t: str, rule: str) -> None:
        edges.add((s, t))
        if ledger is not None:
            ledger.include(relation, s, t, "FRAMEWORK_RULE", rule)

    for entry in entries:
        module = index.N.get(entry, {}).get("module")
        # UserDetailsService: загрузка пользователя
        for ud in _methods_of(index, _types_with_super(index, module, "UserDetailsService", "implements_raw"),
                              ("loadUserByUsername",)):
            execute(ud)
            for t in sorted(index.wiring["data_access"].get(ud, ())):
                dec = index.entities.collection_table_loaded(ud, t)
                if dec is None or dec[0]:
                    include(data, "data", ud, t, _RULE)
        # Фильтр запросов
        for f in _methods_of(index, _types_with_super(index, None, "OncePerRequestFilter", "extends_raw"),
                             ("doFilterInternal",)):
            execute(f)
        # UserDetails: методы, которые вызывает провайдер
        called_here = {c.get("callee") for c in index.cs_nodes_by_method.get(entry, ())}
        for um in _methods_of(index, _types_with_super(index, module, "UserDetails", "implements_raw"),
                              _PROVIDER_USER_METHODS):
            execute(um)
            if index.N[um].get("name") in called_here:
                include(calls, "calls", entry, um, f"{_RULE}:R6")


def _types_with_super(index: Any, module: str | None, simple: str, attr: str) -> set[str]:
    """Типы модуля (или всего проекта при module=None), у которых в extends/implements есть `simple`."""
    return {
        nid for nid, n in index.type_nodes.items()
        if (module is None or n.get("module") == module) and simple in (n.get(attr) or [])
    }


def _methods_of(index: Any, owners: set[str], names: tuple[str, ...]) -> list[str]:
    """Методы типов `owners` с именами из `names`, по ID."""
    return sorted(nid for o in owners for nid, n in index.methods_by_owner.get(o, ()) if n.get("name") in names)
