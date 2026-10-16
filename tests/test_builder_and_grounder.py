"""Модульные тесты GraphBuilder (reachability, Spring Security, JPA) и ScenarioGrounder."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.graph.builder import GraphBuilder
from engine.resolver import ScenarioGrounder
from engine.rules import RuntimeRules, ScenarioProfile

ROOT = Path(__file__).resolve().parent.parent
SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"
TARGETS_ROOT = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"


@pytest.fixture(scope="module")
def skeleton_index() -> SkeletonIndex:
    return SkeletonIndex(load_json(SKELETON_PATH))


@pytest.fixture(scope="module")
def rules() -> RuntimeRules:
    return RuntimeRules()


class TestGraphBuilder:
    """Тестирование обхода достижимости графа вызовов."""

    def test_database_terminal_sink(self, skeleton_index: SkeletonIndex, rules: RuntimeRules) -> None:
        builder = GraphBuilder(skeleton_index, rules)
        entry = [
            "method:ts-contacts-service:contacts.controller.ContactsController#findContactsByAccountId(java.lang.String,?HttpHeaders)"
        ]
        methods, calls, remote, data = builder.traverse(entry)

        # Ребра data должны вести к узлам res:table:...
        for s, t in data:
            assert t.startswith("res:table:")
            # Терминальные узлы БД не должны иметь исходящих вызовов
            assert not any(s_call == t for s_call, _ in calls)
            assert not any(s_rem == t for s_rem, _ in remote)

    def test_exception_constructors_filtered(self, skeleton_index: SkeletonIndex, rules: RuntimeRules) -> None:
        builder = GraphBuilder(skeleton_index, rules)
        entry = [
            "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)"
        ]
        methods, calls, remote, data = builder.traverse(entry)

        # Вызовы конструкторов ошибок Exception#<init> должны быть отфильтрованы
        assert not any("Exception#<init>" in tgt for _, tgt in calls)

    def test_spring_security_and_jwt_filter_injection(self, skeleton_index: SkeletonIndex, rules: RuntimeRules) -> None:
        builder = GraphBuilder(skeleton_index, rules)
        entry = [
            "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)"
        ]
        methods, calls, remote, data = builder.traverse(entry)

        # Должен активироваться UserDetailsServiceImpl#loadUserByUsername и JWTFilter
        assert any("UserDetailsServiceImpl#loadUserByUsername" in m for m in methods)
        assert any("JWTFilter#doFilterInternal" in m for m in methods)

        # Должно быть обращение к таблицам auth_user и user_roles
        data_tables = {t for _, t in data}
        assert "res:table:ts-auth-service.auth_user" in data_tables

    def test_order_hydration_rules(self, skeleton_index: SkeletonIndex, rules: RuntimeRules) -> None:
        builder = GraphBuilder(skeleton_index, rules)
        # Вход, обращающийся к таблице заказов ts-order-service.orders
        entry = [
            "method:ts-order-service:order.controller.OrderController#queryOrdersForRefresh(order.entity.OrderInfo,org.springframework.http.HttpHeaders)"
        ]
        methods, calls, remote, data = builder.traverse(entry)

        # Должен вызваться конструктор Order#<init>()
        assert any("order.entity.Order#<init>()" in m for m in methods)

        # Конструктор Order обязан вызывать вспомогательные методы getCode и Date2String
        order_callees = {t for s, t in calls if "Order#<init>()" in s}
        assert any("OrderStatus#getCode" in t for t in order_callees)
        assert any("SeatClass#getCode" in t for t in order_callees)
        assert any("StringUtils#Date2String" in t for t in order_callees)


class TestScenarioGrounder:
    """Тестирование резолвинга шагов сценария в точки входа."""

    @pytest.fixture(scope="module")
    def grounder(self, skeleton_index: SkeletonIndex) -> ScenarioGrounder:
        return ScenarioGrounder(skeleton_index, TARGETS_ROOT)

    def test_ground_s0_entries(self, grounder: ScenarioGrounder, skeleton_index: SkeletonIndex) -> None:
        s0_dict = load_json(ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S0.json")
        entries = grounder.ground(s0_dict)

        assert len(entries) > 0
        # Все точки входа обязаны существовать в скелете
        for e in entries:
            assert e in skeleton_index.N

        # Проверяем наличие ключевых контроллеров сценария S0
        assert any("UserController#getToken" in e for e in entries)
        assert any("ContactsController#findContactsByAccountId" in e for e in entries)
        assert any("OrderController#queryOrdersForRefresh" in e for e in entries)
        assert any("ConsignController#findByAccountId" in e for e in entries)
