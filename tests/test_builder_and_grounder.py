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

    def test_r7_seat_class_enum_calls_in_travel_and_rebook(self, skeleton_index: SkeletonIndex, rules: RuntimeRules) -> None:
        builder = GraphBuilder(skeleton_index, rules)
        seat_code = "method:ts-common:edu.fudan.common.entity.SeatClass#getCode()"
        entry = [
            "method:ts-travel-service:travel.controller.TravelController#queryInfo(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)"
        ]
        methods, calls, remote, data = builder.traverse(entry)
        assert seat_code in methods
        assert any(tgt == seat_code and "TravelServiceImpl#setResponse" in src for src, tgt in calls)

        # Конструктор Order обязан вызывать вспомогательные методы getCode и Date2String
        order_callees = {t for s, t in calls if "Order#<init>()" in s}
        assert any("OrderStatus#getCode" in t for t in order_callees)
        assert any("SeatClass#getCode" in t for t in order_callees)
        assert any("StringUtils#Date2String" in t for t in order_callees)

    def test_r7_order_status_enum_calls_in_cancel_and_rebook(self, skeleton_index: SkeletonIndex, rules: RuntimeRules) -> None:
        builder = GraphBuilder(skeleton_index, rules)
        order_status_code = "method:ts-common:edu.fudan.common.entity.OrderStatus#getCode()"
        entry = [
            "method:ts-cancel-service:cancel.controller.CancelController#cancelTicket(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)"
        ]
        methods, calls, remote, data = builder.traverse(entry)
        assert order_status_code in methods
        assert any(tgt == order_status_code and "CancelServiceImpl#cancelFromOtherOrder" in src for src, tgt in calls)


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

    def test_ground_s6_admin_guarantees(self, grounder: ScenarioGrounder, skeleton_index: SkeletonIndex) -> None:
        s6_dict = load_json(ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S6.json")
        entries = grounder.ground(s6_dict)

        for e in entries:
            assert e in skeleton_index.N

        assert any("AdminBasicInfoController#addStation" in e for e in entries)
        assert any("AdminBasicInfoController#addTrain" in e for e in entries)
        assert any("AdminRouteController#addRoute" in e for e in entries)
        assert any("AdminBasicInfoController#addPrice" in e for e in entries)
        assert any("AdminTravelController#addTravel" in e for e in entries)
        assert any("AdminOrderController#getAllOrders" in e for e in entries)

    def test_ground_s5_search_and_regular_trip_details(self, grounder: ScenarioGrounder, skeleton_index: SkeletonIndex) -> None:
        s5_dict = load_json(ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S5.json")
        entries = grounder.ground(s5_dict)

        for e in entries:
            assert e in skeleton_index.N

        assert any("TravelPlanController#getByMinStation" in e for e in entries)
        assert any("TravelPlanController#getByCheapest" in e for e in entries)
        assert any("TravelPlanController#getByQuickest" in e for e in entries)
        assert any("TravelPlanController#getTransferResult" in e for e in entries)
        # В S5 детали рейса открываются для обычного поезда (Travel2Controller)
        assert any("Travel2Controller#getTripAllDetailInfo" in e for e in entries)

    def test_ground_s1_and_s4_food_menu(self, grounder: ScenarioGrounder, skeleton_index: SkeletonIndex) -> None:
        s1_dict = load_json(ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S1.json")
        entries_s1 = grounder.ground(s1_dict)
        assert any("FoodController#getAllFood" in e for e in entries_s1)

        s4_dict = load_json(ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S4.json")
        entries_s4 = grounder.ground(s4_dict)
        assert any("FoodController#getAllFood" in e for e in entries_s4)

    def test_ground_ui_order_inspection_no_consign_pollution(self, grounder: ScenarioGrounder) -> None:
        # В S3 нет запроса багажа по номеру заказа, поэтому ConsignController#findByOrderId не должен попадать в точки входа
        s3_dict = load_json(ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S3.json")
        entries_s3 = grounder.ground(s3_dict)
        assert not any("ConsignController#findByOrderId" in e for e in entries_s3)

        # В S4 багаж вообще отсутствует, findByOrderId не должен появляться
        s4_dict = load_json(ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S4.json")
        entries_s4 = grounder.ground(s4_dict)
        assert not any("ConsignController#findByOrderId" in e for e in entries_s4)

    def test_ground_s4_inside_payment_gateway_entry(self, grounder: ScenarioGrounder) -> None:
        # В S4 оплата в UI идет в InsidePaymentController#pay, а PaymentController вызывается как remote call
        s4_dict = load_json(ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S4.json")
        entries_s4 = grounder.ground(s4_dict)
        assert any("InsidePaymentController#pay" in e for e in entries_s4)
        assert not any("com.trainticket.controller.PaymentController#pay" in e for e in entries_s4)

    def test_r7_and_r17_check_security_order_status_and_string2date(self, skeleton_index: SkeletonIndex, rules: RuntimeRules) -> None:
        builder = GraphBuilder(skeleton_index, rules)
        # Для существующего пользователя (S1, S2, S3, S5, S7) checkSecurityAboutOrder вызывает OrderStatus#getCode()
        prof_existing = ScenarioProfile.from_scenario({"id": "S1", "title": "S1", "description": "existing user"})
        sec_m_order = "method:ts-order-service:order.service.OrderServiceImpl#checkSecurityAboutOrder(java.util.Date,java.lang.String,org.springframework.http.HttpHeaders)"
        m, c, r, d = builder.traverse({sec_m_order}, profile=prof_existing)
        order_get_code = "method:ts-common:edu.fudan.common.entity.OrderStatus#getCode()"
        string2date = "method:ts-common:edu.fudan.common.util.StringUtils#String2Date(java.lang.String)"
        assert (sec_m_order, order_get_code) in c
        assert (sec_m_order, string2date) in c

        # Для нового пользователя (S4) в базе нет заказов (R17): OrderStatus#getCode() и String2Date не вызываются
        prof_new = ScenarioProfile.from_scenario({"id": "S4", "title": "S4", "description": "A new passenger registers a new account"})
        m4, c4, r4, d4 = builder.traverse({sec_m_order}, profile=prof_new)
        assert (sec_m_order, order_get_code) not in c4
        assert (sec_m_order, string2date) not in c4


