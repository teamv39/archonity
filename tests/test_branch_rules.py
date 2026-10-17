"""Тесты для модуля декларативных правил веток engine/branch_rules.py."""
from __future__ import annotations

import pytest

from engine.branch_rules import (
    BranchRule,
    BranchRulesRegistry,
    BranchRuleValidationError,
    RuleMatcher,
    RuleResolver,
)
from engine.rules import ScenarioProfile


@pytest.fixture
def sample_profile() -> ScenarioProfile:
    return ScenarioProfile(
        id="S_TEST",
        is_admin=False,
        has_assurance=True,
        has_consign=False,
        has_food=True,
        train_mode="high_speed_only",
        has_refused_cancel=False,
        has_refused_rebook=True,
        has_external_payment=True,
        has_advanced_search=False,
        has_consign_weight_change=True,
        is_new_user=False,
        has_order_filter=True,
        has_status_filter=False,
    )


def test_load_default_branch_rules():
    """Проверка успешной загрузки реального data/branch_rules.json."""
    registry = BranchRulesRegistry.load()
    assert len(registry.rules) > 15
    rule_ids = {r.id for r in registry.rules}
    assert "BR_FOOD_OPTION" in rule_ids
    assert "BR_EXECUTE_REGULAR_TRAIN_MODE" in rule_ids
    assert "BR_EXECUTE_HIGHSPEED_TRAIN_MODE" in rule_ids
    assert "BR_ASSURANCE_OPTION" in rule_ids


def test_validation_missing_fields():
    """Проверка ошибки валидации при отсутствии обязательных полей."""
    with pytest.raises(BranchRuleValidationError):
        BranchRule.from_dict({"code": "R1"})

    with pytest.raises(BranchRuleValidationError):
        BranchRule.from_dict({"id": "RULE_1"})

    with pytest.raises(BranchRuleValidationError):
        BranchRule.from_dict({
            "id": "RULE_1",
            "matcher": {},
            "resolver": {"type": "unknown_type"},
        })


def test_matcher_criteria():
    """Проверка сопоставления различных критериев RuleMatcher."""
    matcher = RuleMatcher.from_dict({
        "method_contains": "CancelService",
        "condition_contains_all": ["OrderStatus.NOTPAID.getCode()", "OrderStatus.PAID.getCode()"],
    })

    assert matcher.matches(
        method_id="method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelOrder",
        bid="b1",
        arm="then",
        cond="if (status == OrderStatus.NOTPAID.getCode() || status == OrderStatus.PAID.getCode())",
    )
    assert not matcher.matches(
        method_id="method:ts-order-service:order.service.OrderServiceImpl#create",
        bid="b1",
        arm="then",
        cond="if (status == OrderStatus.NOTPAID.getCode())",
    )


def test_any_of_matcher():
    """Проверка any_of в RuleMatcher."""
    matcher = RuleMatcher.from_dict({
        "any_of": [
          {"condition_contains": "orderOtherResult"},
          {"method_contains": "ExecuteServiceImpl", "branch_id_in": ["b65", "b113"]},
        ]
    })

    # Срабатывание по первому условию
    assert matcher.matches("SomeMethod", "b1", "then", "orderOtherResult.getStatus() == 1")
    # Срабатывание по второму условию
    assert matcher.matches("ExecuteServiceImpl#execute", "b65", "then", "result.getStatus() == 1")
    # Не сработало
    assert not matcher.matches("OtherService", "b20", "then", "result.getStatus() == 1")


def test_resolver_profile_flag(sample_profile: ScenarioProfile):
    """Проверка резолвера по флагам ScenarioProfile."""
    # has_food is True
    res_food = RuleResolver.from_dict({"type": "profile_flag", "flag": "has_food"})
    assert res_food.resolve(sample_profile) is True

    # has_consign is False
    res_consign = RuleResolver.from_dict({"type": "profile_flag", "flag": "has_consign"})
    assert res_consign.resolve(sample_profile) is False

    # has_consign with invert is True
    res_consign_inv = RuleResolver.from_dict({"type": "profile_flag", "flag": "has_consign", "invert": True})
    assert res_consign_inv.resolve(sample_profile) is True


def test_resolver_train_mode(sample_profile: ScenarioProfile):
    """Проверка резолвера режима поезда train_mode."""
    resolver = RuleResolver.from_dict({
        "type": "train_mode",
        "regular_only": False,
        "high_speed_only": True,
        "default": True,
    })

    # sample_profile has train_mode == "high_speed_only"
    assert resolver.resolve(sample_profile) is True

    # regular_only profile
    sample_profile.train_mode = "regular_only"
    assert resolver.resolve(sample_profile) is False

    # both
    sample_profile.train_mode = "both"
    assert resolver.resolve(sample_profile) is True


def test_rule_ablation_disable_enable(sample_profile: ScenarioProfile):
    """Проверка отключения правил для абляционных исследований."""
    registry = BranchRulesRegistry.load()
    rule_id = "BR_FOOD_OPTION"

    # Изначально активно
    val, rule = registry.evaluate_branch(
        method_id="preserve.service.PreserveServiceImpl#createOrder",
        bid="b1",
        arm="then",
        cond="oti.getFoodType() != 0",
        profile=sample_profile,
    )
    assert rule is not None
    assert rule.id == rule_id
    assert val is True

    # Отключаем правило
    registry.disable_rule(rule_id)
    val2, rule2 = registry.evaluate_branch(
        method_id="preserve.service.PreserveServiceImpl#createOrder",
        bid="b1",
        arm="then",
        cond="oti.getFoodType() != 0",
        profile=sample_profile,
    )
    assert rule2 is None
    assert val2 is None

    # Включаем обратно
    registry.enable_rule(rule_id)
    val3, rule3 = registry.evaluate_branch(
        method_id="preserve.service.PreserveServiceImpl#createOrder",
        bid="b1",
        arm="then",
        cond="oti.getFoodType() != 0",
        profile=sample_profile,
    )
    assert rule3 is not None
    assert rule3.id == rule_id
    assert val3 is True

