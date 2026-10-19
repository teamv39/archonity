"""Построитель графа связей и обход достижимости (Reachability Traversal).

Реализует правила ADR-001, ADR-003, ADR-004:
- Изоляция терминальных узлов БД (ребра data не имеют исходящих связей).
- Разделение контекста deployment units.
- Фильтрация мертвого кода и нерелевантных административных вызовов.
- Учет Spring Security и жизненного цикла сущностей ORM.

Каждое решение по ребру пишется в журнал решений (engine/decisions.py), если он передан в traverse.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from engine.adapters.skeleton import SkeletonIndex
from engine.decisions import DecisionLedger, rules_return_line
from engine.entities import RepositoryCall, hydration, rows_exist
from engine.rules import RuntimeRules, ScenarioProfile
from engine.state import ScenarioState


@dataclass
class TraversalContext:
    """Состояние одного обхода шага: общее для legacy-раскрытия и перехватчика M4."""

    seen_methods: set[tuple[str, str]]
    edges_calls: set[tuple[str, str]]
    edges_remote: set[tuple[str, str]]
    edges_data: set[tuple[str, str]]
    reached_via: dict[str, tuple[str, str, str | None]]
    stack: list[tuple[str, str]]
    ledger: DecisionLedger | None
    profile: ScenarioProfile | None
    scenario_state: ScenarioState | None
    is_admin_scenario: bool
    entries: frozenset[str]


class MethodInterceptor(Protocol):
    """Перехватчик методов обхода (M4): исполняет метод сам вместо раскрытия по скелету."""

    def wants(self, method_id: str) -> bool: ...

    def run(self, method_id: str, unit: str, ctx: TraversalContext, entry: bool) -> None: ...


class GraphBuilder:
    """Движок обхода графа вызовов от точек входа сценария."""

    def __init__(self, index: SkeletonIndex, rules: RuntimeRules | None = None) -> None:
        self.index = index
        self.rules = rules or RuntimeRules()
        self._ledger: DecisionLedger | None = None

    def traverse(
        self,
        entry_methods: Iterable[str],
        is_admin_scenario: bool = False,
        scenario_meta: dict[str, Any] | None = None,
        profile: ScenarioProfile | None = None,
        scenario_state: ScenarioState | None = None,
        ledger: DecisionLedger | None = None,
        interceptor: MethodInterceptor | None = None,
    ) -> tuple[set[str], set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
        """Обход графа от точек входа.

        Возвращает:
            methods: множество вызванных методов
            calls: внутрисервисные вызовы (method -> method)
            remote: межсервисные вызовы (method -> method другого сервиса)
            data: обращения к таблицам БД (method -> res:table:...)

        Если передан ledger, каждое решение по ребру (включение, отсев, удаление) пишется в журнал.
        Если передан interceptor, методы, которые он хочет, исполняет он (через TraversalContext),
        а legacy-раскрытие по скелету для них пропускается; остальные методы раскрываются как раньше.
        """
        self._ledger = ledger
        seen_methods: set[tuple[str, str]] = set()
        edges_calls: set[tuple[str, str]] = set()
        edges_remote: set[tuple[str, str]] = set()
        edges_data: set[tuple[str, str]] = set()
        # Чем обоснован вызов метода: (source_type, rule, ребро, по которому до него дошли)
        reached_via: dict[str, tuple[str, str, str | None]] = {}

        # Фильтруем сами точки входа от заведомого мертвого кода
        valid_entries = []
        for m in entry_methods:
            # Точку входа, которую исполняет перехватчик, на мёртвый код не проверяем: решает M4
            intercepted = interceptor is not None and interceptor.wants(m)
            if not intercepted and self.rules.is_dead_code_method(m, profile=profile, is_admin_scenario=is_admin_scenario):
                if ledger:
                    ledger.prune(
                        "executes", f"scenario:{ledger.scenario_id}", m, "DEFAULT_RULE",
                        rules_return_line(self.rules.is_dead_code_method, m, profile=profile,
                                          is_admin_scenario=is_admin_scenario),
                    )
                continue
            valid_entries.append(m)
            reached_via.setdefault(m, ("SKELETON", "ENTRY", None))

        # Очередь обхода: (текущий_метод, deployment_unit)
        stack = [(m, self.index.unit_of(m)) for m in valid_entries]

        # Контекст ссылается на те же объекты, что использует цикл: перехватчик пишет прямо в них
        ctx = TraversalContext(
            seen_methods=seen_methods,
            edges_calls=edges_calls,
            edges_remote=edges_remote,
            edges_data=edges_data,
            reached_via=reached_via,
            stack=stack,
            ledger=ledger,
            profile=profile,
            scenario_state=scenario_state,
            is_admin_scenario=is_admin_scenario,
            entries=frozenset(valid_entries),
        )

        while stack:
            m, u = stack.pop()
            if (m, u) in seen_methods:
                continue
            seen_methods.add((m, u))

            # M4: метод исполняет перехватчик, раскрытие по скелету (в том числе R7) пропускается
            if interceptor is not None and interceptor.wants(m):
                interceptor.run(m, u, ctx, entry=m in ctx.entries)
                continue

            # 0. Enum-вызовы по правилу R7 из AST IR пула методов
            if hasattr(self.index, "pool_ir") and self.index.pool_ir.has_method(m):
                for c_enum in self.index.pool_ir.enum_calls_by_method.get(m, []):
                    trace: list[str] = []
                    active = self.index.pool_ir.evaluate_guard(m, c_enum.guard, profile, scenario_state, trace=trace)
                    enum_target = self.index.pool_ir.get_enum_target(c_enum, skeleton_nodes=self.index.N)
                    if not active:
                        if ledger and enum_target:
                            ledger.prune("calls", m, enum_target, "IR_BRANCH", ";".join(trace),
                                         line=c_enum.line, col=c_enum.col)
                        continue
                    if enum_target and enum_target in self.index.N:
                        if self.rules.is_dead_code_edge(m, "calls", enum_target, profile=profile, is_admin_scenario=is_admin_scenario):
                            self._prune_by_rule(self.rules.is_dead_code_edge, "calls", m, enum_target, profile,
                                                is_admin_scenario, line=c_enum.line, col=c_enum.col)
                            continue
                        edges_calls.add((m, enum_target))
                        seen_methods.add((enum_target, self.index.unit_of(enum_target)))
                        rule = ";".join(["R7"] + trace)
                        reached_via.setdefault(enum_target, ("IR_CALL", rule, f"calls|{m}|{enum_target}"))
                        if ledger:
                            ledger.include("calls", m, enum_target, "IR_CALL", rule, line=c_enum.line, col=c_enum.col)
            # 1. Внутрисервисные вызовы (calls + overrides/CHA + runtime_dispatch)
            for t in self.index.calls.get(m, ()):
                # Правило R2: если у вызова есть точный runtime_dispatch в скелете,
                # в граф идет конкретная реализация. Иначе используем {t} и CHA.
                dispatches = getattr(self.index, "call_dispatch", {}).get(m, {}).get(t)
                if dispatches:
                    dispatch_targets = set(dispatches)
                elif self.index.N.get(t, {}).get("abstract"):
                    dispatch_targets = self.index.cha(t)
                else:
                    dispatch_targets = {t} | self.index.cha(t)
                for x in dispatch_targets:
                    if self.index.N.get(x, {}).get("abstract"):
                        if ledger:
                            ledger.prune("calls", m, x, "SKELETON", "abstract")
                        continue
                    target_mod = self.index.module.get(x, "")
                    if u not in self.index.units.get(target_mod, ()):
                        if ledger:
                            ledger.prune("calls", m, x, "SKELETON", "cross_unit", unit=u)
                        continue
                    if self.rules.is_dead_code_method(x, profile=profile, is_admin_scenario=is_admin_scenario):
                        self._prune_by_rule(self.rules.is_dead_code_method, "calls", m, x, profile, is_admin_scenario)
                        continue
                    if self.rules.is_dead_code_edge(m, "calls", x, profile=profile, is_admin_scenario=is_admin_scenario):
                        self._prune_by_rule(self.rules.is_dead_code_edge, "calls", m, x, profile, is_admin_scenario)
                        continue

                    # Вызовы методов перечисления AssuranceType (Гипотеза 3.1):
                    # off — абляция (исключить вызовы геттеров перечисления из getAllAssuranceTypes)
                    if (
                        getattr(self.rules, "enum_member_calls", "on") == "off"
                        and "getAllAssuranceTypes" in m
                        and "AssuranceType#" in x
                    ):
                        if ledger:
                            ledger.prune("calls", m, x, "DEFAULT_RULE", "enum_member_getter_ablation")
                        continue

                    # Проверка активности вызова по AST Guard из IR (M2 -> M4)
                    source_type, rule = "SKELETON", "reachability"
                    if hasattr(self.index, "edge_guards"):
                        guards = self.index.edge_guards.get((m, "calls", x)) or self.index.edge_guards.get((m, "calls", t))
                        if guards:
                            active, trace = self._eval_guards(m, guards, profile, scenario_state)
                            if not active:
                                if ledger:
                                    ledger.prune("calls", m, x, "IR_BRANCH", ";".join(trace),
                                                 guards=[list(g) for g in guards])
                                continue
                            if trace:
                                source_type, rule = "IR_BRANCH", ";".join(trace)

                    # Исключаем вызовы конструкторов ошибок в штатных успешных сценариях
                    if "Exception#<init>" in x:
                        if ledger:
                            ledger.prune("calls", m, x, "DEFAULT_RULE", "exception_ctor")
                        continue

                    edges_calls.add((m, x))
                    stack.append((x, u))
                    reached_via.setdefault(x, (source_type, rule, f"calls|{m}|{x}"))
                    if ledger:
                        ledger.include("calls", m, x, source_type, rule)

            # 2. Межсервисные вызовы (remote_call + message_delivery)
            remote_targets = set(self.index.wiring["remote_call"].get(m, set()))
            if getattr(self.rules, "rabbitmq_delivery", "on") != "off":
                remote_targets |= self.index.wiring["message_delivery"].get(m, set())
            elif ledger:
                for tgt in self.index.wiring["message_delivery"].get(m, set()):
                    ledger.prune("remote", m, tgt, "DEFAULT_RULE", "ablate_rabbitmq_delivery")
            for t in remote_targets:
                if self.rules.is_dead_code_method(t, profile=profile, is_admin_scenario=is_admin_scenario):
                    self._prune_by_rule(self.rules.is_dead_code_method, "remote", m, t, profile, is_admin_scenario)
                    continue
                if self.rules.is_dead_code_edge(m, "remote", t, profile=profile, is_admin_scenario=is_admin_scenario):
                    self._prune_by_rule(self.rules.is_dead_code_edge, "remote", m, t, profile, is_admin_scenario)
                    continue

                # Каскадный запрос станционной еды из getAllFood:
                # direct_train_food — запрос только поездного меню без станционных магазинов
                if (
                    getattr(self.rules, "trip_food_query", "cascade") == "direct_train_food"
                    and "FoodServiceImpl#getAllFood" in m
                    and "StationFoodController#getFoodStoresByStationNames" in t
                ):
                    if ledger:
                        ledger.prune("remote", m, t, "DEFAULT_RULE", "trip_food_no_station_cascade")
                    continue

                # Проверка активности вызова по AST Guard из IR (M2 -> M4)
                source_type, rule = "SKELETON", "reachability"
                if hasattr(self.index, "edge_guards"):
                    guards = (
                        self.index.edge_guards.get((m, "remote_call", t))
                        or self.index.edge_guards.get((m, "message_delivery", t))
                    )
                    if guards:
                        active, trace = self._eval_guards(m, guards, profile, scenario_state)
                        if not active:
                            if ledger:
                                ledger.prune("remote", m, t, "IR_BRANCH", ";".join(trace),
                                             guards=[list(g) for g in guards])
                            continue
                        if trace:
                            source_type, rule = "IR_BRANCH", ";".join(trace)

                edges_remote.add((m, t))
                stack.append((t, self.index.unit_of(t)))
                reached_via.setdefault(t, (source_type, rule, f"remote|{m}|{t}"))
                if ledger:
                    ledger.include("remote", m, t, source_type, rule)

            # 3. Обращения к таблицам баз данных (data_access)
            # ПРАВИЛО БД: узлы БД являются терминальными стоками.
            for t in self.index.wiring["data_access"].get(m, set()):
                if self.rules.is_dead_code_edge(m, "data", t, profile=profile, is_admin_scenario=is_admin_scenario):
                    self._prune_by_rule(self.rules.is_dead_code_edge, "data", m, t, profile, is_admin_scenario)
                    continue

                # Таблица коллекции блюд station_food_list: при просмотре каталога магазинов станции
                # (listFoodStoresByStationName) возвращаются метаданные магазинов без позиций блюд.
                sf_mode = getattr(self.rules, "station_food_collection", "store_browse_only")
                if "station_food_list" in t:
                    if sf_mode == "off" or (
                        sf_mode in ("store_browse_only", "store_only", "step4_store_only")
                        and "listFoodStoresByStationName" in m
                    ):
                        if ledger:
                            ledger.prune("data", m, t, "FRAMEWORK_RULE", "store_browse_no_food_items")
                        continue

                # Зондирующий SELECT к ts-order-service.orders при regular_only (поведение CancelServiceImpl):
                # в штатном режиме выполняется SELECT (0 строк); off — абляция
                if (
                    getattr(self.rules, "probe_orders_data", "on") == "off"
                    and getattr(profile, "train_mode", "") == "regular_only"
                    and "OrderServiceImpl#getOrderById" in m
                    and "ts-order-service.orders" in t
                ):
                    if ledger:
                        ledger.prune("data", m, t, "STATE", "regular_train_probe_empty_orders")
                    continue

                # Проверка активности вызова по AST Guard из IR (M2 -> M4)
                source_type, rule = "SKELETON", "reachability"
                if hasattr(self.index, "edge_guards"):
                    guards = self.index.edge_guards.get((m, "data_access", t))
                    if guards:
                        active, trace = self._eval_guards(m, guards, profile, scenario_state)
                        if not active:
                            if ledger:
                                ledger.prune("data", m, t, "IR_BRANCH", ";".join(trace),
                                             guards=[list(g) for g in guards])
                            continue
                        if trace:
                            source_type, rule = "IR_BRANCH", ";".join(trace)

                # Таблица ленивой коллекции: только если метод загрузил коллекцию сам (R10, факты archparse)
                rsu = getattr(self.rules, "route_stations_usage", "pruned")
                if rsu != "pruned" and "route_stations" in t and "getRouteById" in m:
                    if rsu == "all" or (rsu == "preserve" and any("preserve" in str(x).lower() for x in stack)):
                        loaded = (True, f"H3.13:route_stations_{rsu}")
                    else:
                        loaded = self._collection_table_loaded(m, t)
                elif (
                    getattr(self.rules, "route_distances_collection", "pruned") == "included"
                    and "getRouteByStartAndEnd" in m
                    and "route_distances" in t
                ):
                    loaded = (True, "ablation:route_distances_included")
                else:
                    loaded = self._collection_table_loaded(m, t)
                if loaded is not None:
                    if not loaded[0]:
                        if ledger:
                            ledger.prune("data", m, t, "STATE", loaded[1])
                        continue
                    source_type, rule = "STATE", loaded[1]

                edges_data.add((m, t))
                if ledger:
                    ledger.include("data", m, t, source_type, rule)

            # 4. Конструкторы сущностей при загрузке строк Hibernate (R7, факты archparse)
            for ctor, rule, via in self._hydrated_constructors(m, edges_data, profile, scenario_state):
                reached_via.setdefault(ctor, ("STATE", rule, via))
                stack.append((ctor, u))

            # 5. Методы сущности, которые библиотека коллекций вызывает на загруженных строках
            #    (list.contains(x) -> x.equals(элемент)); ребра calls нет: вызывает библиотека
            for cb, rule, via in self._element_callbacks(m, edges_data, profile, scenario_state):
                reached_via.setdefault(cb, ("STATE", rule, via))
                stack.append((cb, u))

        active_methods = {m for m, _ in seen_methods}
        if ledger:
            for m in sorted(active_methods):
                source_type, rule, via = reached_via.get(m, ("SKELETON", "reachability", None))
                ledger.execute(m, source_type, rule, via=via)

        # 4. Архитектурные правила Spring Security и ORM Entity Lifecycle
        self._apply_framework_and_entity_lifecycle(
            active_methods,
            edges_calls,
            edges_data,
            scenario_meta,
            profile=profile,
            scenario_state=scenario_state,
            interceptor=interceptor,
        )

        return active_methods, edges_calls, edges_remote, edges_data

    def _collection_table_loaded(self, m: str, t: str) -> tuple[bool, str] | None:
        """Решение R10 по таблице коллекции; None — правило не применяется (режим all или не коллекция)."""
        entities = getattr(self.index, "entities", None)
        if entities is None or getattr(self.rules, "collection_tables_on_read", "loaded") == "all":
            return None
        return entities.collection_table_loaded(m, t)

    def _hydrated_constructors(
        self,
        m: str,
        edges_data: set[tuple[str, str]],
        profile: ScenarioProfile | None,
        scenario_state: ScenarioState | None,
    ) -> list[tuple[str, str, str]]:
        """Конструкторы сущностей, которые Hibernate вызвал на вызовах репозитория в методе m.

        Вызов репозитория считается исполненным, если в ответ вошло ребро data к одной из его таблиц
        и его guard из IR (если метод в пуле) активен. Ребра calls к конструктору нет: его вызывает Hibernate.
        Возвращает [(конструктор, правило, ребро data, через которое он исполнился)].
        """
        entities = getattr(self.index, "entities", None)
        mode = getattr(self.rules, "constructors", "caller_only")
        if entities is None or mode == "off":
            return []
        out: list[tuple[str, str, str]] = []
        is_new_user = self._is_new_user(profile, scenario_state)
        for call, table in self._executed_repository_calls(m, edges_data, profile, scenario_state):
            decision = hydration(call, scenario_state, self.index.table_resource_to_db, is_new_user,
                                 allowed=entities.allowed_ctors(mode))
            via = f"data|{m}|{call.main_table or table}"
            if decision.ctors:
                out.extend((ctor, decision.rule, via) for ctor in decision.ctors)
            elif self._ledger and call.entity and call.entity.no_arg_ctor and call.entity.ctor_statements > 0:
                self._ledger.prune("executes", f"scenario:{self._ledger.scenario_id}", call.entity.no_arg_ctor,
                                   "STATE", decision.rule, via=via, line=call.line, col=call.col)
        return out

    def _executed_repository_calls(
        self,
        m: str,
        edges_data: set[tuple[str, str]],
        profile: ScenarioProfile | None,
        scenario_state: ScenarioState | None,
    ) -> list[tuple[RepositoryCall, str]]:
        """Вызовы репозитория в методе m, которые исполнились: в ответ вошло ребро data к одной из таблиц
        вызова, и guard вызова из IR (если метод в пуле) активен. Возвращает [(вызов, таблица)]."""
        entities = getattr(self.index, "entities", None)
        out: list[tuple[RepositoryCall, str]] = []
        for call in entities.calls_by_method.get(m, ()) if entities is not None else ():
            table = next((t for t in sorted(call.tables) if (m, t) in edges_data), None)
            if table is None:
                continue
            c_ir = self.index.pool_ir.calls_by_mid_line_col.get((m, call.line, call.col))
            if c_ir is not None and c_ir.guard:
                active, _ = self._eval_guards(m, [c_ir.guard], profile, scenario_state)
                if not active:
                    continue
            out.append((call, table))
        return out

    @staticmethod
    def _is_new_user(profile: ScenarioProfile | None, scenario_state: ScenarioState | None) -> bool:
        return bool(getattr(scenario_state, "is_new_user", False) or getattr(profile, "is_new_user", False))

    def _element_callbacks(
        self,
        m: str,
        edges_data: set[tuple[str, str]],
        profile: ScenarioProfile | None,
        scenario_state: ScenarioState | None,
    ) -> list[tuple[str, str, str]]:
        """equals сущности из list.contains(x) на результате чтения: исполняется, если чтение вернуло строки.

        Библиотека коллекций вызывает x.equals(элемент) обычным виртуальным вызовом, не через отражение,
        поэтому исключение REFERENCE («вызванные библиотекой лишь через отражение») сюда не относится.
        Возвращает [(метод, правило, ребро data вызова)].
        """
        if getattr(self.rules, "element_callbacks", "on") == "off":
            return []
        out: list[tuple[str, str, str]] = []
        is_new_user = self._is_new_user(profile, scenario_state)
        for call, table in self._executed_repository_calls(m, edges_data, profile, scenario_state):
            if not call.element_callbacks:
                continue
            via = f"data|{m}|{call.main_table or table}"
            has_rows, why = rows_exist(call, scenario_state, self.index.table_resource_to_db, is_new_user)
            for cb, lookup in call.element_callbacks:
                if has_rows:
                    out.append((cb, f"ELEMENT_CALLBACK:{lookup}({why})", via))
                elif self._ledger:
                    self._ledger.prune("executes", f"scenario:{self._ledger.scenario_id}", cb, "STATE",
                                       f"ELEMENT_CALLBACK:no_rows({why})", via=via)
        return out

    def _eval_guards(
        self,
        m: str,
        guards: list[tuple[str, ...]],
        profile: ScenarioProfile | None,
        scenario_state: ScenarioState | None,
    ) -> tuple[bool, list[str]]:
        """Вызов активен, если проходит хотя бы один из его guard. Возвращает (активен, правила решения)."""
        first_fail: list[str] = []
        for g in guards:
            trace: list[str] = []
            if self.index.pool_ir.evaluate_guard(m, g, profile, scenario_state, trace=trace):
                return True, trace
            if not first_fail:
                first_fail = trace
        return False, first_fail

    def _prune_by_rule(
        self,
        fn: Callable[..., bool],
        relation: str,
        source: str,
        target: str,
        profile: ScenarioProfile | None,
        is_admin_scenario: bool,
        **detail: Any,
    ) -> None:
        """Запись отсева эвристикой rules.py со ссылкой на сработавшую строку."""
        if not self._ledger:
            return
        if fn == self.rules.is_dead_code_method:
            where = rules_return_line(fn, target, profile=profile, is_admin_scenario=is_admin_scenario)
        else:
            where = rules_return_line(fn, source, relation, target, profile=profile, is_admin_scenario=is_admin_scenario)
        self._ledger.prune(relation, source, target, "DEFAULT_RULE", where, **detail)

    def _activate(self, active_methods: set[str], m: str, source_type: str, rule: str) -> None:
        """Добавление метода в executes правилом фреймворка или состояния."""
        if self._ledger and m not in active_methods:
            self._ledger.execute(m, source_type, rule)
        active_methods.add(m)

    def _add_edge(
        self, edges: set[tuple[str, str]], relation: str, s: str, t: str, source_type: str, rule: str
    ) -> None:
        edges.add((s, t))
        if self._ledger:
            self._ledger.include(relation, s, t, source_type, rule)

    def apply_spring_security(
        self,
        active_methods: set[str],
        edges_calls: set[tuple[str, str]],
        edges_data: set[tuple[str, str]],
    ) -> None:
        """Методы и рёбра, которые исполняет Spring Security при аутентификации (UserDetailsService, OncePerRequestFilter)."""
        if getattr(self.rules, "spring_security", "semantic") == "semantic":
            self._spring_security_semantic(active_methods, edges_calls, edges_data)
            return
        # Режим names (до 20.10): вход и таблица пользователя — по именам.
        # 1. Поиск модулей аутентификации по стандартному контракту Spring Security (loadUserByUsername)
        auth_modules = {
            n.get("module") for nid, n in self.index.N.items()
            if n.get("kind") == "method" and n.get("name") == "loadUserByUsername" and n.get("module")
        }
        if not auth_modules:
            return

        # Ищем сервисный метод аутентификации (не REST-контроллер, а сервис, вызывающий провайдер аутентификации)
        auth_service_methods = [
            m for m in sorted(active_methods)
            if self.index.N.get(m, {}).get("module") in auth_modules
            and "controller" not in self.index.N.get(m, {}).get("owner", "").lower()
            and self.index.N.get(m, {}).get("name") in ("getToken", "authenticate", "login")
        ]
        if auth_service_methods:
            token_method = auth_service_methods[0]
            auth_module = self.index.N.get(token_method, {}).get("module", "")

            # 1a. UserDetailsService (стандартный контракт Spring Security loadUserByUsername)
            user_details_methods = [
                nid for nid, n in self.index.N.items()
                if n.get("kind") == "method" and n.get("name") == "loadUserByUsername" and n.get("module") == auth_module
            ]
            for ud_method in user_details_methods:
                self._activate(active_methods, ud_method, "FRAMEWORK_RULE", "spring_security")
                target_table = next(
                    (t for t in self.index.table_nodes if auth_module in t and ("auth_user" in t or "user" in t)),
                    None,
                )
                if target_table:
                    self._add_edge(edges_data, "data", ud_method, target_table, "FRAMEWORK_RULE", "spring_security")

            # 1b. Веб-фильтр запросов (OncePerRequestFilter стандартный метод doFilterInternal)
            jwt_filters = [
                nid for nid, n in self.index.N.items()
                if n.get("kind") == "method" and n.get("name") == "doFilterInternal"
            ]
            for jf in jwt_filters:
                self._activate(active_methods, jf, "FRAMEWORK_RULE", "spring_security")

            # 1c. Сущность UserDetails (стандартный интерфейсный контракт методов состояния)
            user_details_classes = {
                n.get("owner") for nid, n in self.index.N.items()
                if n.get("kind") == "method" and n.get("module") == auth_module and n.get("name") in (
                    "isAccountNonExpired", "isCredentialsNonExpired", "isAccountNonLocked"
                )
            }
            standard_user_methods = {
                "getAuthorities", "getPassword", "getUsername",
                "isAccountNonExpired", "isAccountNonLocked",
                "isCredentialsNonExpired", "isEnabled",
            }
            user_methods: list[str] = []
            user_pwd: str | None = None
            user_name: str | None = None
            for nid, n in self.index.N.items():
                if n.get("owner") in user_details_classes and n.get("name") in standard_user_methods:
                    user_methods.append(nid)
                    if n.get("name") == "getPassword":
                        user_pwd = nid
                    elif n.get("name") == "getUsername":
                        user_name = nid

            for um in user_methods:
                self._activate(active_methods, um, "FRAMEWORK_RULE", "spring_security")

            if user_pwd:
                self._add_edge(edges_calls, "calls", token_method, user_pwd, "FRAMEWORK_RULE", "spring_security")

            # 1d. Вызов createToken в JWTProvider
            token_creators = [
                nid for nid, n in self.index.N.items()
                if n.get("kind") == "method" and n.get("module") == auth_module and n.get("name") == "createToken"
            ]
            for tc in token_creators:
                if user_name:
                    self._add_edge(edges_calls, "calls", tc, user_name, "FRAMEWORK_RULE", "spring_security")

    # Типы и методы контракта Spring Security
    _AUTH_MANAGER = "org.springframework.security.authentication.AuthenticationManager"
    # Методы UserDetails, которые DaoAuthenticationProvider вызывает в authenticate: проверки до и после пароля,
    # сам пароль, роли для итогового Authentication. getUsername провайдер не вызывает.
    _PROVIDER_USER_METHODS = (
        "isAccountNonLocked", "isEnabled", "isAccountNonExpired", "getPassword", "isCredentialsNonExpired",
        "getAuthorities",
    )

    def _types_with_super(self, module: str | None, simple: str, attr: str) -> set[str]:
        """Типы модуля (или всего проекта при module=None), у которых в extends/implements есть `simple`."""
        return {
            nid for nid, n in self.index.N.items()
            if n.get("kind") == "type" and (module is None or n.get("module") == module)
            and simple in (n.get(attr) or [])
        }

    def _spring_security_semantic(
        self,
        active_methods: set[str],
        edges_calls: set[tuple[str, str]],
        edges_data: set[tuple[str, str]],
    ) -> None:
        """Spring Security по контракту фреймворка, без имён проекта.

        Вход — исполненный метод, в котором стоит вызов `AuthenticationManager.authenticate`. Его исполняет
        DaoAuthenticationProvider: `loadUserByUsername` реализации `UserDetailsService` того же модуля (SQL — к
        таблицам `data_access` этого метода, ленивые коллекции по R10 не загружены), затем методы `UserDetails`
        загруженного пользователя. Ребро от входа к методу `UserDetails` — по R6: у входа есть call_site с тем же
        именем. Фильтры — `doFilterInternal` подклассов `OncePerRequestFilter`.
        """
        N = self.index.N
        cs_by_method: dict[str, list[dict[str, Any]]] = {}
        for n in N.values():
            if n.get("kind") == "call_site" and n.get("method") in active_methods:
                cs_by_method.setdefault(n["method"], []).append(n)
        entries = [
            m for m in sorted(active_methods)
            if any(c.get("callee") == "authenticate" and c.get("receiver_type") == self._AUTH_MANAGER
                   for c in cs_by_method.get(m, ()))
        ]
        for entry in entries:
            module = N.get(entry, {}).get("module")
            # UserDetailsService: загрузка пользователя
            services = self._types_with_super(module, "UserDetailsService", "implements_raw")
            for ud in sorted(nid for nid, n in N.items() if n.get("kind") == "method"
                             and n.get("owner") in services and n.get("name") == "loadUserByUsername"):
                self._activate(active_methods, ud, "FRAMEWORK_RULE", "spring_security")
                for t in sorted(self.index.wiring["data_access"].get(ud, ())):
                    dec = self.index.entities.collection_table_loaded(ud, t)
                    if dec is None or dec[0]:
                        self._add_edge(edges_data, "data", ud, t, "FRAMEWORK_RULE", "spring_security")
            # Фильтр запросов
            filters = self._types_with_super(None, "OncePerRequestFilter", "extends_raw")
            for nid, n in sorted(N.items()):
                if n.get("kind") == "method" and n.get("owner") in filters and n.get("name") == "doFilterInternal":
                    self._activate(active_methods, nid, "FRAMEWORK_RULE", "spring_security")
            # UserDetails: методы, которые вызывает провайдер
            users = self._types_with_super(module, "UserDetails", "implements_raw")
            called_here = {c.get("callee") for c in cs_by_method.get(entry, ())}
            for nid, n in sorted(N.items()):
                if n.get("kind") != "method" or n.get("owner") not in users \
                        or n.get("name") not in self._PROVIDER_USER_METHODS:
                    continue
                self._activate(active_methods, nid, "FRAMEWORK_RULE", "spring_security")
                if n.get("name") in called_here:
                    self._add_edge(edges_calls, "calls", entry, nid, "FRAMEWORK_RULE", "spring_security:R6")

    def _apply_framework_and_entity_lifecycle(
        self,
        active_methods: set[str],
        edges_calls: set[tuple[str, str]],
        edges_data: set[tuple[str, str]],
        scenario_meta: dict[str, Any] | None = None,
        profile: ScenarioProfile | None = None,
        scenario_state: ScenarioState | None = None,
        interceptor: MethodInterceptor | None = None,
    ) -> None:
        """Применение семантики Spring Security и гидрации JPA/MongoDB сущностей."""
        self.apply_spring_security(active_methods, edges_calls, edges_data)

        # 2. Конструкторы сущностей при загрузке строк (R7) решает обход по фактам archparse
        #    (_hydrated_constructors), вызовы внутри конструкторов дают IR и скелет.

        # Фильтрация неактивного условия по дате в queryOrders
        table_targets = {t for _, t in edges_data}
        query_orders = (
            "method:ts-order-other-service:other.service.OrderOtherServiceImpl#queryOrders("
            "other.entity.QueryInfo,java.lang.String,org.springframework.http.HttpHeaders)"
        )
        # Если queryOrders исполняет перехватчик, ветку по дате решает его IR, а не эта эвристика
        query_orders_intercepted = interceptor is not None and interceptor.wants(query_orders)
        if not query_orders_intercepted and any("ts-order-other-service.orders_other" in t for t in table_targets):
            string2date = "method:ts-common:edu.fudan.common.util.StringUtils#String2Date(java.lang.String)"
            # Если сценарий не фильтрует явно по датам поездки
            if scenario_state is not None:
                if not scenario_state.has_date_filter_query():
                    self._discard_edge(edges_calls, "calls", query_orders, string2date, "STATE", "date_filter")
            elif not getattr(profile, "has_order_filter", False):
                self._discard_edge(edges_calls, "calls", query_orders, string2date, "DEFAULT_RULE", "date_filter")

    def _discard_edge(
        self, edges: set[tuple[str, str]], relation: str, s: str, t: str, source_type: str, rule: str
    ) -> None:
        """Удаление уже включённого ребра (решение после обхода)."""
        if (s, t) in edges and self._ledger:
            self._ledger.discard(relation, s, t, source_type, rule)
        edges.discard((s, t))
