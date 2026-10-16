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
        # Канареечный дубль
        assert rules.is_dead_code_method("method:ts-travel2-service:travel2.service.Travel2ServiceImpl#getRoutes()")
        # Капча и аватарки
        assert rules.is_dead_code_method("method:ts-verification-code-service:verify.VerifyController#verify()")
        assert rules.is_dead_code_method("method:ts-avatar-service:avatar.controller.AvatarController#get()")

    def test_dead_code_admin_services_filtered_in_user_scenario(self, rules: RuntimeRules) -> None:
        admin_method = "method:ts-admin-order-service:adminorder.controller.AdminOrderController#getAllOrders()"
        # В пользовательском сценарии — мертвый код
        assert rules.is_dead_code_method(admin_method, is_admin_scenario=False)

        # В административном сценарии — активный код
        assert not rules.is_dead_code_method(admin_method, is_admin_scenario=True)

    def test_profile_specific_dead_code_filtering(self, rules: RuntimeRules) -> None:
        # Профиль без страховки и без еды
        profile_no_ass = ScenarioProfile(
            id="test",
            is_admin=False,
            has_assurance=False,
            has_consign=False,
            has_food=False,
            train_mode="high_speed_only",
        )
        assert rules.is_dead_code_method("method:ts-assurance-service:assurance.service.AssuranceServiceImpl#find()", profile=profile_no_ass)
        assert rules.is_dead_code_method("method:ts-consign-service:consign.service.ConsignServiceImpl#query()", profile=profile_no_ass)
        assert rules.is_dead_code_method("method:ts-food-service:food.service.FoodServiceImpl#getFood()", profile=profile_no_ass)
        assert rules.is_dead_code_method("method:ts-station-food-service:food.service.StationFoodServiceImpl#getFood()", profile=profile_no_ass)
        assert rules.is_dead_code_method("method:ts-preserve-other-service:preserveOther.service.PreserveOtherServiceImpl#preserve()", profile=profile_no_ass)
        # ts-order-other-service не отсекается, так как опрашивается фронтендом при любом refresh orders
        assert not rules.is_dead_code_method("method:ts-order-other-service:other.service.OrderOtherServiceImpl#query()", profile=profile_no_ass)

        # Профиль с активной страховкой
        profile_with_ass = ScenarioProfile(
            id="test2",
            is_admin=False,
            has_assurance=True,
            has_consign=True,
            has_food=True,
            train_mode="regular_only",
        )
        assert not rules.is_dead_code_method("method:ts-assurance-service:assurance.service.AssuranceServiceImpl#find()", profile=profile_with_ass)
        assert not rules.is_dead_code_method("method:ts-consign-service:consign.service.ConsignServiceImpl#query()", profile=profile_with_ass)
        # В regular_only ts-preserve-service (скоростной) должен быть отсечен
        assert rules.is_dead_code_method("method:ts-preserve-service:preserve.service.PreserveServiceImpl#preserve()", profile=profile_with_ass)

    def test_dead_code_data_edge(self, rules: RuntimeRules) -> None:
        profile = ScenarioProfile(
            id="test",
            is_admin=False,
            has_assurance=False,
            has_consign=False,
            has_food=False,
            train_mode="high_speed_only",
        )
        src = "method:ts-order-service:order.service.OrderServiceImpl#query()"

        # Таблица мертвого канареечного сервиса
        assert rules.is_dead_code_edge(src, "data", "res:table:ts-travel2-service.trip2", profile=profile)

        # Таблица неактивной страховки
        assert rules.is_dead_code_edge(src, "data", "res:table:ts-assurance-service.assurance", profile=profile)

        # Таблица неактивного багажа
        assert rules.is_dead_code_edge(src, "data", "res:table:ts-consign-mysql.consign_record", profile=profile)

        # Таблица активных заказов скоростных поездов
        assert not rules.is_dead_code_edge(src, "data", "res:table:ts-order-service.orders", profile=profile)
