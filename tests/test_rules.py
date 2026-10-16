"""Модульные тесты правил отсева мертвого кода и классификации сценариев."""
from __future__ import annotations

import pytest

from engine.rules import RuntimeRules, ScenarioProfile


class TestScenarioProfile:
    """Тестирование классификатора сценариев ScenarioProfile."""

    def test_s0_profile_extraction(self) -> None:
        scenario_s0 = {
            "id": "S0",
            "title": "My account: contacts, orders of both train types, paid orders, luggage consignments",
            "description": "A registered passenger logs in... query orders of both train types...",
            "steps": [
                {"action": "Log in with username and password"},
                {"action": "Search high-speed (gaotie/dongche) trains from Shang Hai to Su Zhou on 2026-10-01"},
                {"action": "Check consignment records registered on the account"},
            ],
        }
        prof = ScenarioProfile.from_scenario(scenario_s0)
        assert prof.id == "S0"
        assert not prof.is_admin
        assert not prof.has_assurance
        assert prof.has_consign
        assert not prof.has_food
        assert prof.train_mode == "both"

    def test_s1_high_speed_with_all_options(self) -> None:
        scenario_s1 = {
            "id": "S1",
            "title": "Buying a high-speed train ticket with food on the train, insurance and luggage",
            "description": "book a high-speed ticket with food on the train, assurance (insurance) of the first type and luggage consignment of 2 kg",
            "steps": [
                {"action": "View the food menu offered on this trip"},
                {"action": "Book one first-class seat with food on the train, assurance (insurance) of the first type and luggage consignment of 2 kg"},
            ],
        }
        prof = ScenarioProfile.from_scenario(scenario_s1)
        assert not prof.is_admin
        assert prof.has_assurance
        assert prof.has_consign
        assert prof.has_food
        assert prof.train_mode == "high_speed_only"

    def test_s2_regular_train_with_negations(self) -> None:
        scenario_s2 = {
            "id": "S2",
            "title": "Buying a regular train ticket with station food and no insurance",
            "description": "Search regular trains (the 'Other' train type, not high-speed)... without assurance (insurance) and without luggage consignment",
            "steps": [
                {"action": "Browse the food stores at Suzhou station"},
                {"action": "Book one first-class seat on the regular train, with food from a station store, no assurance (insurance) and no luggage consignment"},
            ],
        }
        prof = ScenarioProfile.from_scenario(scenario_s2)
        assert not prof.is_admin
        assert not prof.has_assurance
        assert not prof.has_consign
        assert prof.has_food
        assert prof.train_mode == "regular_only"

    def test_s6_admin_scenario(self) -> None:
        scenario_s6 = {
            "id": "S6",
            "title": "An administrator opens a new high-speed trip and a passenger books",
            "description": "An administrator logs in... without food, assurance or consignment",
            "steps": [
                {"action": "Log in with admin account and password"},
            ],
        }
        prof = ScenarioProfile.from_scenario(scenario_s6)
        assert prof.is_admin
        assert not prof.has_assurance
        assert not prof.has_consign
        assert not prof.has_food
        assert prof.train_mode == "high_speed_only"

    def test_s7_high_speed_with_consign_refusal(self) -> None:
        scenario_s7 = {
            "id": "S7",
            "title": "After collecting the ticket: refused cancellation and rebook, luggage consignment of 3 kg",
            "description": "a high-speed train ticket with a luggage consignment of 3 kg, without food or assurance",
            "steps": [
                {"action": "Change the consignee's name and phone number in the consignment"},
            ],
        }
        prof = ScenarioProfile.from_scenario(scenario_s7)
        assert not prof.is_admin
        assert not prof.has_assurance
        assert prof.has_consign
        assert not prof.has_food
        assert prof.train_mode == "high_speed_only"
        assert prof.has_refused_cancel
        assert prof.has_refused_rebook


class TestRuntimeRules:
    """Тестирование RuntimeRules и отсева мертвого кода."""

    @pytest.fixture
    def rules(self) -> RuntimeRules:
        return RuntimeRules()

    def test_extract_service_method(self) -> None:
        m1 = "method:ts-order-service:order.entity.Order#<init>()"
        assert RuntimeRules.extract_service(m1) == "ts-order-service"

        m2 = "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)"
        assert RuntimeRules.extract_service(m2) == "ts-auth-service"

    def test_extract_service_table(self) -> None:
        t1 = "res:table:ts-consign-mysql.consign_record"
        assert RuntimeRules.extract_service(t1) == "ts-consign-mysql"

        t2 = "res:table:ts-order-service.orders"
        assert RuntimeRules.extract_service(t2) == "ts-order-service"

        t3 = "res:table:ts-assurance-service.assurance"
        assert RuntimeRules.extract_service(t3) == "ts-assurance-service"

    def test_extract_service_invalid_or_none(self) -> None:
        assert RuntimeRules.extract_service("") is None
        assert RuntimeRules.extract_service("invalid") is None

    def test_dead_code_canary_and_unreferenced(self, rules: RuntimeRules) -> None:
        # ts-travel2-service больше не является безусловно мертвым кодом
        assert not rules.is_dead_code_method("method:ts-travel2-service:travel2.service.Travel2ServiceImpl#getRoutes()")
        # В high_speed_only ts-travel2-service отсекается профилем
        prof_hs = ScenarioProfile("test", False, False, False, False, train_mode="high_speed_only")
        assert rules.is_dead_code_method("method:ts-travel2-service:travel2.service.Travel2ServiceImpl#getRoutes()", profile=prof_hs)
        # Капча и аватарки — всегда мертвый код
        assert rules.is_dead_code_method("method:ts-verification-code-service:verify.VerifyController#verify()")
        assert rules.is_dead_code_method("method:ts-avatar-service:avatar.controller.AvatarController#get()")

    def test_dead_code_admin_services_filtered_in_user_scenario(self, rules: RuntimeRules) -> None:
        admin_method = "method:ts-admin-order-service:adminorder.controller.AdminOrderController#getAllOrders()"
        # В пользовательском сценарии — мертвый код
        assert rules.is_dead_code_method(admin_method, is_admin_scenario=False)

        # В административном сценарии — активный код
        assert not rules.is_dead_code_method(admin_method, is_admin_scenario=True)

    def test_profile_specific_dead_code_filtering(self, rules: RuntimeRules) -> None:
        # Профиль без страховки и без еды (внутренний платеж)
        profile_no_ass = ScenarioProfile(
            id="test",
            is_admin=False,
            has_assurance=False,
            has_consign=False,
            has_food=False,
            train_mode="high_speed_only",
            has_external_payment=False,
        )
        assert rules.is_dead_code_method("method:ts-assurance-service:assurance.service.AssuranceServiceImpl#find()", profile=profile_no_ass)
        assert rules.is_dead_code_method("method:ts-consign-service:consign.service.ConsignServiceImpl#query()", profile=profile_no_ass)
        assert rules.is_dead_code_method("method:ts-food-service:food.service.FoodServiceImpl#getFood()", profile=profile_no_ass)
        assert rules.is_dead_code_method("method:ts-station-food-service:food.service.StationFoodServiceImpl#getFood()", profile=profile_no_ass)
        assert rules.is_dead_code_method("method:ts-preserve-other-service:preserveOther.service.PreserveOtherServiceImpl#preserve()", profile=profile_no_ass)
        assert rules.is_dead_code_method("method:ts-travel2-service:travel2.service.Travel2ServiceImpl#queryInfo()", profile=profile_no_ass)
        # ts-payment-service отсекается, так как has_external_payment=False
        assert rules.is_dead_code_method("method:ts-payment-service:com.trainticket.service.PaymentServiceImpl#pay()", profile=profile_no_ass)
        # ts-order-other-service не отсекается, так как опрашивается фронтендом при любом refresh orders
        assert not rules.is_dead_code_method("method:ts-order-other-service:other.service.OrderOtherServiceImpl#query()", profile=profile_no_ass)

        # Профиль с активной страховкой и внешним платежом
        profile_with_ass = ScenarioProfile(
            id="test2",
            is_admin=False,
            has_assurance=True,
            has_consign=True,
            has_food=True,
            train_mode="regular_only",
            has_external_payment=True,
        )
        assert not rules.is_dead_code_method("method:ts-assurance-service:assurance.service.AssuranceServiceImpl#find()", profile=profile_with_ass)
        assert not rules.is_dead_code_method("method:ts-consign-service:consign.service.ConsignServiceImpl#query()", profile=profile_with_ass)
        assert not rules.is_dead_code_method("method:ts-payment-service:com.trainticket.service.PaymentServiceImpl#pay()", profile=profile_with_ass)
        # В regular_only ts-preserve-service и ts-travel-service должны быть отсечены
        assert rules.is_dead_code_method("method:ts-preserve-service:preserve.service.PreserveServiceImpl#preserve()", profile=profile_with_ass)
        assert rules.is_dead_code_method("method:ts-travel-service:travel.service.TravelServiceImpl#queryInfo()", profile=profile_with_ass)
        # А ts-travel2-service активен
        assert not rules.is_dead_code_method("method:ts-travel2-service:travel2.service.Travel2ServiceImpl#queryInfo()", profile=profile_with_ass)

    def test_refuse_cancellation_and_rebook_filtering(self, rules: RuntimeRules) -> None:
        prof_refused = ScenarioProfile(
            id="test_refused",
            is_admin=False,
            has_assurance=False,
            has_consign=False,
            has_food=False,
            train_mode="high_speed_only",
            has_refused_cancel=True,
            has_refused_rebook=True,
        )
        src_cancel = "method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)"
        assert rules.is_dead_code_edge(src_cancel, "calls", "method:ts-cancel-service:cancel.service.CancelServiceImpl#drawbackMoney()", profile=prof_refused)
        assert rules.is_dead_code_edge(src_cancel, "remote", "method:ts-inside-payment-service:inside_payment.controller.InsidePaymentController#drawBack()", profile=prof_refused)
        assert rules.is_dead_code_edge(src_cancel, "remote", "method:ts-order-other-service:other.controller.OrderOtherController#getOrder()", profile=prof_refused)

        # Проверка is_dead_code_method для методов CancelServiceImpl и InsidePaymentController
        assert rules.is_dead_code_method("method:ts-cancel-service:cancel.service.CancelServiceImpl#drawbackMoney()", profile=prof_refused)
        assert rules.is_dead_code_method("method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelFromOrder()", profile=prof_refused)
        assert rules.is_dead_code_method("method:ts-cancel-service:cancel.service.CancelServiceImpl#getAccount()", profile=prof_refused)
        assert rules.is_dead_code_method("method:ts-inside-payment-service:inside_payment.controller.InsidePaymentController#drawBack()", profile=prof_refused)

        src_rebook = "method:ts-rebook-service:rebook.service.RebookServiceImpl#rebook(rebook.entity.RebookInfo,org.springframework.http.HttpHeaders)"
        assert rules.is_dead_code_edge(src_rebook, "calls", "method:ts-rebook-service:rebook.service.RebookServiceImpl#payDifferentMoney()", profile=prof_refused)
        assert rules.is_dead_code_edge(src_rebook, "remote", "method:ts-inside-payment-service:inside_payment.controller.InsidePaymentController#payDifference()", profile=prof_refused)
        assert rules.is_dead_code_edge(src_rebook, "remote", "method:ts-seat-service:seat.controller.SeatController#create()", profile=prof_refused)
        assert rules.is_dead_code_edge(src_rebook, "remote", "method:ts-order-other-service:other.controller.OrderOtherController#getOrder()", profile=prof_refused)

        # Проверка is_dead_code_method для методов RebookServiceImpl и зависимых контроллеров
        assert rules.is_dead_code_method("method:ts-rebook-service:rebook.service.RebookServiceImpl#payDifferentMoney()", profile=prof_refused)
        assert rules.is_dead_code_method("method:ts-rebook-service:rebook.service.RebookServiceImpl#dipatchSeat()", profile=prof_refused)
        assert rules.is_dead_code_method("method:ts-inside-payment-service:inside_payment.controller.InsidePaymentController#payDifference()", profile=prof_refused)
        assert rules.is_dead_code_method("method:ts-seat-service:seat.controller.SeatController#create()", profile=prof_refused)

        # Проверка возврата явного False (не None) для разрешенных ребер
        is_dead = rules.is_dead_code_edge(src_cancel, "calls", "method:ts-cancel-service:cancel.service.CancelServiceImpl#getOrderByIdFromOrder()", profile=prof_refused)
        assert is_dead is False

    def test_dead_code_data_edge(self, rules: RuntimeRules) -> None:
        profile = ScenarioProfile(
            id="test",
            is_admin=False,
            has_assurance=False,
            has_consign=False,
            has_food=False,
            train_mode="high_speed_only",
            has_external_payment=False,
        )
        src = "method:ts-order-service:order.service.OrderServiceImpl#query()"

        # Таблица ts-travel2-service в режиме high_speed_only
        assert rules.is_dead_code_edge(src, "data", "res:table:ts-travel2-service.trip2", profile=profile)

        # Таблицы внешнего платежа при has_external_payment=False
        assert rules.is_dead_code_edge(src, "data", "res:table:ts-payment-service.payment", profile=profile)
        assert rules.is_dead_code_edge(src, "data", "res:table:ts-payment-service.money", profile=profile)

        # Таблица неактивной страховки
        assert rules.is_dead_code_edge(src, "data", "res:table:ts-assurance-service.assurance", profile=profile)

        # Таблица неактивного багажа
        assert rules.is_dead_code_edge(src, "data", "res:table:ts-consign-mysql.consign_record", profile=profile)

        # Таблица активных заказов скоростных поездов
        assert not rules.is_dead_code_edge(src, "data", "res:table:ts-order-service.orders", profile=profile)

    def test_home_endpoint_filtered(self, rules: RuntimeRules) -> None:
        home_m1 = "method:ts-contacts-service:contacts.controller.ContactsController#home()"
        home_m2 = "method:ts-train-food-service:trainFood.controller.TrainFoodController#home()"
        assert rules.is_dead_code_method(home_m1)
        assert rules.is_dead_code_method(home_m2)
        assert rules.is_dead_code_edge("method:ts-food-service:foodsearch.service.FoodServiceImpl#getAllFood()", "remote", home_m2)

    def test_cross_service_train_mode_remote_filtering(self, rules: RuntimeRules) -> None:
        prof_hs = ScenarioProfile("test_hs", False, True, True, True, train_mode="high_speed_only")
        prof_reg = ScenarioProfile("test_reg", False, True, True, True, train_mode="regular_only")

        # В high_speed_only inside-payment и seat не вызывают order-other
        assert rules.is_dead_code_edge(
            "method:ts-inside-payment-service:inside_payment.service.InsidePaymentServiceImpl#pay()",
            "remote",
            "method:ts-order-other-service:other.controller.OrderOtherController#getOrderById()",
            profile=prof_hs,
        )
        assert rules.is_dead_code_edge(
            "method:ts-seat-service:seat.service.SeatServiceImpl#distributeSeat()",
            "remote",
            "method:ts-order-other-service:other.controller.OrderOtherController#getTicketListByDateAndTripId()",
            profile=prof_hs,
        )
        # Но в high_speed_only они могут вызывать order-service
        assert not rules.is_dead_code_edge(
            "method:ts-inside-payment-service:inside_payment.service.InsidePaymentServiceImpl#pay()",
            "remote",
            "method:ts-order-service:order.controller.OrderController#getOrderById()",
            profile=prof_hs,
        )

        # В regular_only inside-payment и seat не вызывают order-service
        assert rules.is_dead_code_edge(
            "method:ts-inside-payment-service:inside_payment.service.InsidePaymentServiceImpl#pay()",
            "remote",
            "method:ts-order-service:order.controller.OrderController#getOrderById()",
            profile=prof_reg,
        )
        assert rules.is_dead_code_edge(
            "method:ts-seat-service:seat.service.SeatServiceImpl#distributeSeat()",
            "remote",
            "method:ts-order-service:order.controller.OrderController#getTicketListByDateAndTripId()",
            profile=prof_reg,
        )

    def test_phantom_edges_and_s7_refusal(self, rules: RuntimeRules) -> None:
        # Фантомное ребро getAssuranceById отсекается всегда
        assert rules.is_dead_code_edge(
            "method:ts-preserve-service:preserve.service.PreserveServiceImpl#addAssuranceForOrder()",
            "remote",
            "method:ts-assurance-service:assurance.controller.AssuranceController#getAssuranceById()",
        )
        # В S7 при смене получателя багажа пересчет цены отсекается
        prof_s7 = ScenarioProfile("S7", False, False, True, False, train_mode="high_speed_only")
        assert rules.is_dead_code_edge(
            "method:ts-consign-service:consign.service.ConsignServiceImpl#updateConsignRecord()",
            "remote",
            "method:ts-consign-price-service:consignprice.controller.ConsignPriceController#getPriceByWeightAndRegion()",
            profile=prof_s7,
        )

    def test_advanced_search_travel_service_preservation(self, rules: RuntimeRules) -> None:
        prof_s5 = ScenarioProfile(
            id="S5",
            is_admin=False,
            has_assurance=False,
            has_consign=False,
            has_food=False,
            train_mode="regular_only",
            has_advanced_search=True,
        )
        # При advanced search сервис ts-travel-service НЕ должен отсекаться, так как опрашивается для сравнения
        assert not rules.is_dead_code_method("method:ts-travel-service:travel.service.TravelServiceImpl#queryInfo()", profile=prof_s5)
        assert not rules.is_dead_code_edge(
            "method:ts-travel-service:travel.service.TravelServiceImpl#queryInfo()",
            "data",
            "res:table:ts-travel-service.trip",
            profile=prof_s5,
        )

    def test_cancel_service_probing_order_service(self, rules: RuntimeRules) -> None:
        prof_s2 = ScenarioProfile(
            id="S2",
            is_admin=False,
            has_assurance=False,
            has_consign=False,
            has_food=True,
            train_mode="regular_only",
        )
        # В regular_only зондирующий вызов чужого ts-order-service отсекается как мертвый код (симметрично high_speed_only)
        assert rules.is_dead_code_edge(
            "method:ts-cancel-service:cancel.service.CancelServiceImpl#getOrderByIdFromOrder(java.lang.String,org.springframework.http.HttpHeaders)",
            "remote",
            "method:ts-order-service:order.controller.OrderController#getOrderById(java.lang.String,org.springframework.http.HttpHeaders)",
            profile=prof_s2,
        )
        # А вот попытка мутации cancelFromOrder отсекается как мертвый код
        assert rules.is_dead_code_edge(
            "method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelFromOrder(edu.fudan.common.entity.Order,org.springframework.http.HttpHeaders)",
            "remote",
            "method:ts-order-service:order.controller.OrderController#modifyOrder(edu.fudan.common.entity.Order,org.springframework.http.HttpHeaders)",
            profile=prof_s2,
        )

    def test_rebook_and_cancel_dead_code_refinements(self, rules: RuntimeRules) -> None:
        prof_s2 = ScenarioProfile("S2", False, False, False, True, train_mode="regular_only")
        prof_s4 = ScenarioProfile("S4", False, False, False, True, train_mode="high_speed_only")

        # В RebookServiceImpl смена типа поезда и доплата являются мертвым кодом
        assert rules.is_dead_code_method(
            "method:ts-rebook-service:rebook.service.RebookServiceImpl#createOrder(edu.fudan.common.entity.Order,java.lang.String,org.springframework.http.HttpHeaders)",
            profile=prof_s2,
        )
        assert rules.is_dead_code_method(
            "method:ts-rebook-service:rebook.service.RebookServiceImpl#deleteOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
            profile=prof_s2,
        )
        assert rules.is_dead_code_method(
            "method:ts-rebook-service:rebook.service.RebookServiceImpl#payDifferentMoney(java.lang.String,java.lang.String,java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
            profile=prof_s2,
        )
        assert rules.is_dead_code_method(
            "method:ts-inside-payment-service:inside_payment.controller.InsidePaymentController#payDifference(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)",
            profile=prof_s2,
        )

        # В regular_only CancelServiceImpl не вызывает cancelFromOrder и getAccount
        assert rules.is_dead_code_method(
            "method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelFromOrder(edu.fudan.common.entity.Order,org.springframework.http.HttpHeaders)",
            profile=prof_s2,
        )
        assert rules.is_dead_code_method(
            "method:ts-cancel-service:cancel.service.CancelServiceImpl#getAccount(java.lang.String,org.springframework.http.HttpHeaders)",
            profile=prof_s2,
        )

        # В high_speed_only CancelServiceImpl не вызывает cancelFromOtherOrder и getOrderByIdFromOrderOther
        assert rules.is_dead_code_method(
            "method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelFromOtherOrder(edu.fudan.common.entity.Order,org.springframework.http.HttpHeaders)",
            profile=prof_s4,
        )
        assert rules.is_dead_code_method(
            "method:ts-cancel-service:cancel.service.CancelServiceImpl#getOrderByIdFromOrderOther(java.lang.String,org.springframework.http.HttpHeaders)",
            profile=prof_s4,
        )

    def test_execute_and_refusal_dead_code_refinements(self, rules: RuntimeRules) -> None:
        prof_hs = ScenarioProfile("S1", False, True, True, True, train_mode="high_speed_only")
        prof_reg = ScenarioProfile("S5", False, False, False, False, train_mode="regular_only")
        prof_s7 = ScenarioProfile(
            "S7", False, False, True, False,
            train_mode="high_speed_only",
            has_refused_cancel=True,
            has_refused_rebook=True,
        )

        # 1. ExecuteServiceImpl: отсечение чужого типа поезда
        assert rules.is_dead_code_method(
            "method:ts-execute-service:execute.serivce.ExecuteServiceImpl#executeOrderOther(java.lang.String,int,org.springframework.http.HttpHeaders)",
            profile=prof_hs,
        )
        assert rules.is_dead_code_method(
            "method:ts-execute-service:execute.serivce.ExecuteServiceImpl#getOrderByIdFromOrderOther(java.lang.String,org.springframework.http.HttpHeaders)",
            profile=prof_hs,
        )
        assert rules.is_dead_code_method(
            "method:ts-execute-service:execute.serivce.ExecuteServiceImpl#executeOrder(java.lang.String,int,org.springframework.http.HttpHeaders)",
            profile=prof_reg,
        )

        # 2. Refusal cancel dead code (S7)
        assert rules.is_dead_code_method(
            "method:ts-cancel-service:cancel.service.CancelServiceImpl#calculateRefund(edu.fudan.common.entity.Order)",
            profile=prof_s7,
        )
        src_cancel = "method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)"
        assert rules.is_dead_code_edge(
            src_cancel, "calls",
            "method:ts-common:edu.fudan.common.entity.NotifyInfo#<init>()",
            profile=prof_s7,
        )
        assert rules.is_dead_code_edge(
            src_cancel, "calls",
            "method:ts-common:edu.fudan.common.entity.SeatClass#getNameByCode(int)",
            profile=prof_s7,
        )

        # 3. Regular train cancel dead code (S2)
        prof_s2 = ScenarioProfile("S2", False, False, False, True, train_mode="regular_only")
        assert rules.is_dead_code_edge(
            src_cancel, "calls",
            "method:ts-common:edu.fudan.common.entity.NotifyInfo#<init>()",
            profile=prof_s2,
        )
        assert rules.is_dead_code_edge(
            src_cancel, "calls",
            "method:ts-common:edu.fudan.common.entity.SeatClass#getNameByCode(int)",
            profile=prof_s2,
        )

        # 4. Refusal rebook dead code (S7)
        assert rules.is_dead_code_method(
            "method:ts-rebook-service:rebook.service.RebookServiceImpl#checkTime(java.lang.String,java.lang.String)",
            profile=prof_s7,
        )
        src_rebook = "method:ts-rebook-service:rebook.service.RebookServiceImpl#rebook(rebook.entity.RebookInfo,org.springframework.http.HttpHeaders)"
        assert rules.is_dead_code_edge(
            src_rebook, "calls",
            "method:ts-common:edu.fudan.common.entity.TripAllDetailInfo#<init>()",
            profile=prof_s7,
        )
        assert rules.is_dead_code_edge(
            src_rebook, "calls",
            "method:ts-common:edu.fudan.common.entity.Order#<init>()",
            profile=prof_s7,
        )

