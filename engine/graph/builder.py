"""Построитель графа связей и обход достижимости (Reachability Traversal).

Реализует правила ADR-001, ADR-003, ADR-004:
- Изоляция терминальных узлов БД (ребра data не имеют исходящих связей).
- Разделение контекста deployment units.
- Фильтрация мертвого кода и нерелевантных административных вызовов.
- Учет Spring Security и жизненного цикла сущностей ORM.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from engine.adapters.skeleton import SkeletonIndex
from engine.rules import RuntimeRules, ScenarioProfile
from engine.state import ScenarioState


class GraphBuilder:
    """Движок обхода графа вызовов от точек входа сценария."""

    def __init__(self, index: SkeletonIndex, rules: RuntimeRules | None = None) -> None:
        self.index = index
        self.rules = rules or RuntimeRules()

    def traverse(
        self,
        entry_methods: Iterable[str],
        is_admin_scenario: bool = False,
        scenario_meta: dict[str, Any] | None = None,
        profile: ScenarioProfile | None = None,
        scenario_state: ScenarioState | None = None,
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
            if not self.rules.is_dead_code_method(m, profile=profile, is_admin_scenario=is_admin_scenario)
        ]

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
                    if self.index.pool_ir.evaluate_guard(m, c_enum.guard, profile, scenario_state):
                        enum_target = self.index.pool_ir.get_enum_target(c_enum)
                        if enum_target and enum_target in self.index.N:
                            edges_calls.add((m, enum_target))
                            seen_methods.add((enum_target, self.index.unit_of(enum_target)))

            # 0.1 Дополнительные R7 Enum-вызовы SeatClass в сервисах Travel, TravelPlan и Rebook
            if (
                "TravelServiceImpl#setResponse(" in m
                or "TravelPlanServiceImpl#getCheapest(" in m
                or "TravelPlanServiceImpl#getQuickest(" in m
                or "TravelPlanServiceImpl#getMinStation(" in m
                or ("RebookServiceImpl#updateOrder(" in m and "TripAllDetail" in m)
            ):
                seat_get_code = "method:ts-common:edu.fudan.common.entity.SeatClass#getCode()"
                if seat_get_code in self.index.N:
                    edges_calls.add((m, seat_get_code))
                    seen_methods.add((seat_get_code, self.index.unit_of(seat_get_code)))

            # 0.2 Дополнительные R7 Enum-вызовы OrderStatus в сервисах Rebook, Cancel и Order
            if (
                ("RebookServiceImpl#updateOrder(" in m and "TripAllDetail" in m)
                or "CancelServiceImpl#cancelFromOrder(" in m
                or "CancelServiceImpl#cancelFromOtherOrder(" in m
                or "OrderServiceImpl#cancelOrder(" in m
                or "OrderOtherServiceImpl#cancelOrder(" in m
                or "OrderServiceImpl#alterOrder(" in m
                or "OrderOtherServiceImpl#alterOrder(" in m
                or "OrderServiceImpl#payOrder(" in m
                or "OrderOtherServiceImpl#payOrder(" in m
                or (
                    "checkSecurityAboutOrder(" in m
                    and not (profile and getattr(profile, "is_new_user", False))
                )
            ):
                order_get_code = "method:ts-common:edu.fudan.common.entity.OrderStatus#getCode()"
                if order_get_code in self.index.N:
                    edges_calls.add((m, order_get_code))
                    seen_methods.add((order_get_code, self.index.unit_of(order_get_code)))

            # 1. Внутрисервисные вызовы (calls + overrides/CHA + runtime_dispatch)
            for t in self.index.calls.get(m, ()):
                dispatch_targets = (
                    {t}
                    | self.index.cha(t)
                    | self.index.wiring["runtime_dispatch"].get(m, set())
                )
                for x in dispatch_targets:
                    if self.index.N.get(x, {}).get("abstract"):
                        continue
                    target_mod = self.index.module.get(x, "")
                    if u not in self.index.units.get(target_mod, ()):
                        continue
                    if self.rules.is_dead_code_method(x, profile=profile, is_admin_scenario=is_admin_scenario):
                        continue
                    if self.rules.is_dead_code_edge(m, "calls", x, profile=profile, is_admin_scenario=is_admin_scenario):
                        continue

                    # Проверка активности вызова по AST Guard из IR (M2 -> M4)
                    if hasattr(self.index, "edge_guards"):
                        guards = self.index.edge_guards.get((m, "calls", x)) or self.index.edge_guards.get((m, "calls", t))
                        if guards:
                            if not any(self.index.pool_ir.evaluate_guard(m, g, profile, scenario_state) for g in guards):
                                continue

                    # Исключаем вызовы конструкторов ошибок в штатных успешных сценариях
                    if "Exception#<init>" in x:
                        continue

                    edges_calls.add((m, x))
                    stack.append((x, u))

            # 2. Межсервисные вызовы (remote_call + message_delivery)
            remote_targets = (
                self.index.wiring["remote_call"].get(m, set())
                | self.index.wiring["message_delivery"].get(m, set())
            )
            for t in remote_targets:
                if self.rules.is_dead_code_method(t, profile=profile, is_admin_scenario=is_admin_scenario):
                    continue
                if self.rules.is_dead_code_edge(m, "remote", t, profile=profile, is_admin_scenario=is_admin_scenario):
                    continue

                # Проверка активности вызова по AST Guard из IR (M2 -> M4)
                if hasattr(self.index, "edge_guards"):
                    guards = (
                        self.index.edge_guards.get((m, "remote_call", t))
                        or self.index.edge_guards.get((m, "message_delivery", t))
                    )
                    if guards:
                        if not any(self.index.pool_ir.evaluate_guard(m, g, profile, scenario_state) for g in guards):
                            continue

                edges_remote.add((m, t))
                stack.append((t, self.index.unit_of(t)))

            # 3. Обращения к таблицам баз данных (data_access)
            # ПРАВИЛО БД: узлы БД являются терминальными стоками.
            for t in self.index.wiring["data_access"].get(m, set()):
                if self.rules.is_dead_code_edge(m, "data", t, profile=profile, is_admin_scenario=is_admin_scenario):
                    continue

                # Проверка активности вызова по AST Guard из IR (M2 -> M4)
                if hasattr(self.index, "edge_guards"):
                    guards = self.index.edge_guards.get((m, "data_access", t))
                    if guards:
                        if not any(self.index.pool_ir.evaluate_guard(m, g, profile, scenario_state) for g in guards):
                            continue

                edges_data.add((m, t))

        active_methods = {m for m, _ in seen_methods}

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
            active_methods.add(user_details_method)
            edges_data.add((user_details_method, "res:table:ts-auth-service.auth_user"))

            # Прохождение через фильтр JWT
            jwt_filter = (
                "method:ts-common:edu.fudan.common.security.jwt.JWTFilter#doFilterInternal("
                "javax.servlet.http.HttpServletRequest,javax.servlet.http.HttpServletResponse,javax.servlet.FilterChain)"
            )
            if jwt_filter in self.index.N:
                active_methods.add(jwt_filter)

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
                    active_methods.add(um)

            user_pwd = "method:ts-auth-service:auth.entity.User#getPassword()"
            if user_pwd in self.index.N:
                edges_calls.add((token_method, user_pwd))

            jwt_prov = "method:ts-auth-service:auth.security.jwt.JWTProvider#createToken(auth.entity.User)"
            user_name = "method:ts-auth-service:auth.entity.User#getUsername()"
            if jwt_prov in self.index.N and user_name in self.index.N:
                edges_calls.add((jwt_prov, user_name))

        # 2. Гидрация Order при обращении к таблицам orders / orders_other
        table_targets = {t for _, t in edges_data}

        # ts-order-service.orders
        if any("ts-order-service.orders" in t for t in table_targets):
            order_init = "method:ts-order-service:order.entity.Order#<init>()"
            if order_init in self.index.N:
                active_methods.add(order_init)
                self._add_order_constructor_calls(order_init, active_methods, edges_calls)

        # ts-order-other-service.orders_other
        if any("ts-order-other-service.orders_other" in t for t in table_targets):
            order_other_init = "method:ts-order-other-service:other.entity.Order#<init>()"
            if order_other_init in self.index.N:
                active_methods.add(order_other_init)
                self._add_order_constructor_calls(order_other_init, active_methods, edges_calls)

            # Фильтрация неактивного условия по дате в queryOrders
            query_orders = (
                "method:ts-order-other-service:other.service.OrderOtherServiceImpl#queryOrders("
                "other.entity.QueryInfo,java.lang.String,org.springframework.http.HttpHeaders)"
            )
            string2date = "method:ts-common:edu.fudan.common.util.StringUtils#String2Date(java.lang.String)"
            # Если сценарий не фильтрует явно по датам поездки (как S0)
            if scenario_state is not None:
                if not scenario_state.has_date_filter_query():
                    edges_calls.discard((query_orders, string2date))
            elif scenario_meta and not any(
                "travel date" in s.lower() or "bought date" in s.lower()
                for s in scenario_meta.get("step_texts", [])
            ):
                edges_calls.discard((query_orders, string2date))

    def _add_order_constructor_calls(
        self,
        order_init_method: str,
        active_methods: set[str],
        edges_calls: set[tuple[str, str]],
    ) -> None:
        """Добавление вызовов enum и форматирования даты из конструктора Order."""
        order_status = "method:ts-common:edu.fudan.common.entity.OrderStatus#getCode()"
        seat_class = "method:ts-common:edu.fudan.common.entity.SeatClass#getCode()"
        date2string = "method:ts-common:edu.fudan.common.util.StringUtils#Date2String(java.util.Date)"

        for helper in (order_status, seat_class, date2string):
            if helper in self.index.N:
                active_methods.add(helper)
                edges_calls.add((order_init_method, helper))
