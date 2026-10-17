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
from typing import Any

from engine.adapters.skeleton import SkeletonIndex
from engine.decisions import DecisionLedger, rules_return_line
from engine.entities import hydration
from engine.rules import RuntimeRules, ScenarioProfile
from engine.state import ScenarioState


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
    ) -> tuple[set[str], set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
        """Обход графа от точек входа.

        Возвращает:
            methods: множество вызванных методов
            calls: внутрисервисные вызовы (method -> method)
            remote: межсервисные вызовы (method -> method другого сервиса)
            data: обращения к таблицам БД (method -> res:table:...)

        Если передан ledger, каждое решение по ребру (включение, отсев, удаление) пишется в журнал.
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
            if self.rules.is_dead_code_method(m, profile=profile, is_admin_scenario=is_admin_scenario):
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

        while stack:
            m, u = stack.pop()
            if (m, u) in seen_methods:
                continue
            seen_methods.add((m, u))

            # 0. Enum-вызовы по правилу R7 из AST IR пула методов
            if hasattr(self.index, "pool_ir") and self.index.pool_ir.has_method(m):
                for c_enum in self.index.pool_ir.enum_calls_by_method.get(m, []):
                    trace: list[str] = []
                    active = self.index.pool_ir.evaluate_guard(m, c_enum.guard, profile, scenario_state, trace=trace)
                    enum_target = self.index.pool_ir.get_enum_target(c_enum)
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
            remote_targets = (
                self.index.wiring["remote_call"].get(m, set())
                | self.index.wiring["message_delivery"].get(m, set())
            )
            for t in remote_targets:
                if self.rules.is_dead_code_method(t, profile=profile, is_admin_scenario=is_admin_scenario):
                    self._prune_by_rule(self.rules.is_dead_code_method, "remote", m, t, profile, is_admin_scenario)
                    continue
                if self.rules.is_dead_code_edge(m, "remote", t, profile=profile, is_admin_scenario=is_admin_scenario):
                    self._prune_by_rule(self.rules.is_dead_code_edge, "remote", m, t, profile, is_admin_scenario)
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

                edges_data.add((m, t))
                if ledger:
                    ledger.include("data", m, t, source_type, rule)

            # 4. Конструкторы сущностей при загрузке строк Hibernate (R7, факты archparse)
            for ctor, rule, via in self._hydrated_constructors(m, edges_data, profile, scenario_state):
                reached_via.setdefault(ctor, ("STATE", rule, via))
                stack.append((ctor, u))

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
        )

        return active_methods, edges_calls, edges_remote, edges_data

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
        mode = getattr(self.rules, "entity_constructors_on_load", "body")
        if entities is None or mode == "off":
            return []
        out: list[tuple[str, str, str]] = []
        for call in entities.calls_by_method.get(m, ()):
            table = next((t for t in sorted(call.tables) if (m, t) in edges_data), None)
            if table is None:
                continue
            c_ir = self.index.pool_ir.calls_by_mid_line_col.get((m, call.line, call.col))
            if c_ir is not None and c_ir.guard:
                active, _ = self._eval_guards(m, [c_ir.guard], profile, scenario_state)
                if not active:
                    continue
            is_new_user = bool(getattr(scenario_state, "is_new_user", False) or getattr(profile, "is_new_user", False))
            decision = hydration(call, scenario_state, self.index.table_resource_to_db, is_new_user,
                                 allowed=entities.allowed_ctors(mode))
            via = f"data|{m}|{call.main_table or table}"
            if decision.ctors:
                out.extend((ctor, decision.rule, via) for ctor in decision.ctors)
            elif self._ledger and call.entity and call.entity.no_arg_ctor and call.entity.ctor_statements > 0:
                self._ledger.prune("executes", f"scenario:{self._ledger.scenario_id}", call.entity.no_arg_ctor,
                                   "STATE", decision.rule, via=via, line=call.line, col=call.col)
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

    def _apply_framework_and_entity_lifecycle(
        self,
        active_methods: set[str],
        edges_calls: set[tuple[str, str]],
        edges_data: set[tuple[str, str]],
        scenario_meta: dict[str, Any] | None = None,
        profile: ScenarioProfile | None = None,
        scenario_state: ScenarioState | None = None,
    ) -> None:
        """Применение семантики Spring Security и гидрации JPA/MongoDB сущностей."""
        # 1. Spring Security Authentication Flow при логине через ts-auth-service
        auth_tokens = [m for m in active_methods if "TokenServiceImpl#getToken" in m]
        if auth_tokens:
            token_method = auth_tokens[0]
            user_details_method = (
                "method:ts-auth-service:auth.security.UserDetailsServiceImpl#loadUserByUsername(java.lang.String)"
            )
            self._activate(active_methods, user_details_method, "FRAMEWORK_RULE", "spring_security")
            self._add_edge(edges_data, "data", user_details_method, "res:table:ts-auth-service.auth_user",
                           "FRAMEWORK_RULE", "spring_security")

            # Прохождение через фильтр JWT
            jwt_filter = (
                "method:ts-common:edu.fudan.common.security.jwt.JWTFilter#doFilterInternal("
                "javax.servlet.http.HttpServletRequest,javax.servlet.http.HttpServletResponse,javax.servlet.FilterChain)"
            )
            if jwt_filter in self.index.N:
                self._activate(active_methods, jwt_filter, "FRAMEWORK_RULE", "spring_security")

            # Вызовы методов сущности User со стороны Spring Security и токена
            user_methods = [
                "method:ts-auth-service:auth.entity.User#getAuthorities()",
                "method:ts-auth-service:auth.entity.User#getPassword()",
                "method:ts-auth-service:auth.entity.User#getUsername()",
                "method:ts-auth-service:auth.entity.User#isAccountNonExpired()",
                "method:ts-auth-service:auth.entity.User#isAccountNonLocked()",
                "method:ts-auth-service:auth.entity.User#isCredentialsNonExpired()",
                "method:ts-auth-service:auth.entity.User#isEnabled()",
            ]
            for um in user_methods:
                if um in self.index.N:
                    self._activate(active_methods, um, "FRAMEWORK_RULE", "spring_security")

            user_pwd = "method:ts-auth-service:auth.entity.User#getPassword()"
            if user_pwd in self.index.N:
                self._add_edge(edges_calls, "calls", token_method, user_pwd, "FRAMEWORK_RULE", "spring_security")

            jwt_prov = "method:ts-auth-service:auth.security.jwt.JWTProvider#createToken(auth.entity.User)"
            user_name = "method:ts-auth-service:auth.entity.User#getUsername()"
            if jwt_prov in self.index.N and user_name in self.index.N:
                self._add_edge(edges_calls, "calls", jwt_prov, user_name, "FRAMEWORK_RULE", "spring_security")

        # 2. Конструкторы сущностей при загрузке строк (R7) решает обход по фактам archparse
        #    (_hydrated_constructors), вызовы внутри конструкторов дают IR и скелет.

        # Фильтрация неактивного условия по дате в queryOrders
        table_targets = {t for _, t in edges_data}
        if any("ts-order-other-service.orders_other" in t for t in table_targets):
            query_orders = (
                "method:ts-order-other-service:other.service.OrderOtherServiceImpl#queryOrders("
                "other.entity.QueryInfo,java.lang.String,org.springframework.http.HttpHeaders)"
            )
            string2date = "method:ts-common:edu.fudan.common.util.StringUtils#String2Date(java.lang.String)"
            # Если сценарий не фильтрует явно по датам поездки (как S0)
            if scenario_state is not None:
                if not scenario_state.has_date_filter_query():
                    self._discard_edge(edges_calls, "calls", query_orders, string2date, "STATE", "date_filter")
            elif scenario_meta and not any(
                "travel date" in s.lower() or "bought date" in s.lower()
                for s in scenario_meta.get("step_texts", [])
            ):
                self._discard_edge(edges_calls, "calls", query_orders, string2date, "DEFAULT_RULE", "date_filter")

    def _discard_edge(
        self, edges: set[tuple[str, str]], relation: str, s: str, t: str, source_type: str, rule: str
    ) -> None:
        """Удаление уже включённого ребра (решение после обхода)."""
        if (s, t) in edges and self._ledger:
            self._ledger.discard(relation, s, t, source_type, rule)
        edges.discard((s, t))
