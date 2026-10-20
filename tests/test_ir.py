from __future__ import annotations

import re
from pathlib import Path
import pytest

from engine.ir import (
    CallIR,
    BranchIR,
    MethodIR,
    EnumConstantIR,
    MethodPoolIR,
    ensure_pool_ir,
    ORDER_STATUS_GET_CODE,
    ORDER_STATUS_GET_NAME_BY_CODE,
    SEAT_CLASS_GET_CODE,
    SEAT_CLASS_GET_NAME_BY_CODE,
)
from engine.rules import ScenarioProfile


def test_ensure_pool_ir_fallback():
    path = ensure_pool_ir(reparse=False)
    assert path.is_file()
    assert path.name == "pool_ir.json"


def test_method_pool_ir_load():
    pool = MethodPoolIR.load()
    assert len(pool.methods) > 0
    # Check that cancelOrder is present
    cancel_mid = "method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)"
    assert pool.has_method(cancel_mid)
    assert len(pool.calls_by_mid_line_col) > 0
    assert len(pool.enum_calls_by_method) > 0


def test_enum_calls_indexing_and_resolution():
    pool = MethodPoolIR.load()
    # Check enum calls in cancelOrder
    cancel_mid = "method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)"
    enum_calls = pool.enum_calls_by_method.get(cancel_mid, [])
    assert len(enum_calls) > 0

    order_status_calls = [c for c in enum_calls if c.enum_constant and "OrderStatus" in c.enum_constant.type_fqn]
    assert len(order_status_calls) > 0

    first_call = order_status_calls[0]
    target = pool.get_enum_target(first_call)
    assert target == ORDER_STATUS_GET_CODE


def test_seat_class_enum_resolution():
    pool = MethodPoolIR.load()
    call = CallIR(
        file="ts-preserve-service/src/main/java/preserve/service/PreserveServiceImpl.java",
        line=100,
        col=20,
        callee="getCode",
        receiver="",
        kind="ENUM",
        arg_count=0,
        guard=(),
        enum_constant=EnumConstantIR(
            type_fqn="edu.fudan.common.entity.SeatClass",
            constant="FIRSTCLASS",
        ),
    )
    assert pool.get_enum_target(call) == SEAT_CLASS_GET_CODE

    name_call = CallIR(
        file="dummy",
        line=1,
        col=1,
        callee="getNameByCode",
        receiver="",
        kind="ENUM",
        arg_count=1,
        guard=(),
        enum_constant=EnumConstantIR(
            type_fqn="edu.fudan.common.entity.SeatClass",
            constant="FIRSTCLASS",
        ),
    )
    assert pool.get_enum_target(name_call) == SEAT_CLASS_GET_NAME_BY_CODE

    custom_call = CallIR(
        file="dummy",
        line=1,
        col=1,
        callee="getCode",
        receiver="",
        kind="ENUM",
        arg_count=0,
        guard=(),
        enum_constant=EnumConstantIR(
            type_fqn="com.example.CustomStatus",
            constant="ACTIVE",
        ),
    )
    assert pool.get_enum_target(custom_call) == "method:ts-common:com.example.CustomStatus#getCode()"


def test_evaluate_guard_unconditional():
    pool = MethodPoolIR.load()
    mid = "method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)"
    # Empty guard always evaluates to True
    assert pool.evaluate_guard(mid, (), None) is True
    profile = ScenarioProfile(
        id="S0",
        is_admin=False,
        has_assurance=False,
        has_consign=False,
        has_food=False,
        train_mode="high_speed_only",
    )
    assert pool.evaluate_guard(mid, (), profile) is True


def test_evaluate_guard_train_mode():
    pool = MethodPoolIR.load()
    mid = "method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)"
    # Find branch with getStatus() == 1
    branch_dict = pool.branches_by_method.get(mid, {})
    target_bid = None
    for bid, b in branch_dict.items():
        if "getStatus() == 1" in b.condition_text:
            target_bid = bid
            break

    assert target_bid is not None

    high_speed_profile = ScenarioProfile(
        id="S0",
        is_admin=False,
        has_assurance=False,
        has_consign=False,
        has_food=False,
        train_mode="high_speed_only",
    )
    regular_profile = ScenarioProfile(
        id="S4",
        is_admin=False,
        has_assurance=False,
        has_consign=False,
        has_food=False,
        train_mode="regular_only",
    )

    # then arm: for high speed it's True, for regular it's False
    assert pool.evaluate_guard(mid, (f"{target_bid}:then",), high_speed_profile) is True
    assert pool.evaluate_guard(mid, (f"{target_bid}:then",), regular_profile) is False

    # else arm: for high speed it's False, for regular it's True
    assert pool.evaluate_guard(mid, (f"{target_bid}:else",), high_speed_profile) is False
    assert pool.evaluate_guard(mid, (f"{target_bid}:else",), regular_profile) is True


def test_evaluate_guard_preserve_options():
    pool = MethodPoolIR.load()
    mid = "method:ts-preserve-service:preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)"
    branch_dict = pool.branches_by_method.get(mid, {})

    assurance_bid = None
    food_bid = None
    consign_bid = None
    for bid, b in branch_dict.items():
        if "getAssurance() == 0" in b.condition_text:
            assurance_bid = bid
        elif "getFoodType() != 0" in b.condition_text:
            food_bid = bid
        elif "getConsigneeName()" in b.condition_text:
            consign_bid = bid

    assert assurance_bid is not None
    assert food_bid is not None
    assert consign_bid is not None

    p_with_all = ScenarioProfile(
        id="S1",
        is_admin=False,
        has_assurance=True,
        has_food=True,
        has_consign=True,
        train_mode="both",
    )
    p_none = ScenarioProfile(
        id="S2",
        is_admin=False,
        has_assurance=False,
        has_food=False,
        has_consign=False,
        train_mode="both",
    )

    # getAssurance() == 0 -> then: no assurance, else: has assurance
    assert pool.evaluate_guard(mid, (f"{assurance_bid}:else",), p_with_all) is True
    assert pool.evaluate_guard(mid, (f"{assurance_bid}:else",), p_none) is False

    # getFoodType() != 0 -> then: has food, else: no food
    assert pool.evaluate_guard(mid, (f"{food_bid}:then",), p_with_all) is True
    assert pool.evaluate_guard(mid, (f"{food_bid}:then",), p_none) is False

    # getConsigneeName() -> then: has consign, else: no consign
    assert pool.evaluate_guard(mid, (f"{consign_bid}:then",), p_with_all) is True
    assert pool.evaluate_guard(mid, (f"{consign_bid}:then",), p_none) is False


CANCEL_REFUND_MID = (
    "method:ts-cancel-service:cancel.service.CancelServiceImpl#calculateRefund("
    "java.lang.String,org.springframework.http.HttpHeaders)"
)


def _profile_for(scenario_file: str):
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "hackaton" / "tt-challenge" / "scenarios" / scenario_file
    return ScenarioProfile.from_scenario(json.loads(path.read_text(encoding="utf-8")))


def test_refund_for_paid_order_calls_private_calculate_refund():
    """Внутренняя проверка == NOTPAID не должна гасить вызов calculateRefund(Order) для оплаченного заказа."""
    pool = MethodPoolIR.load()
    mir = pool.methods[CANCEL_REFUND_MID]
    private_calls = [c for c in mir.calls if c.callee == "calculateRefund"]
    assert len(private_calls) == 2
    s2 = _profile_for("S2.json")  # обычный поезд: активна только ветка Other
    s4 = _profile_for("S4.json")  # скоростной поезд: активна только ветка G/D
    active_s2 = [c.line for c in private_calls if pool.evaluate_guard(CANCEL_REFUND_MID, c.guard, s2)]
    active_s4 = [c.line for c in private_calls if pool.evaluate_guard(CANCEL_REFUND_MID, c.guard, s4)]
    assert active_s2 == [187]
    assert active_s4 == [169]


def test_refused_cancel_blocks_refund_branch():
    pool = MethodPoolIR.load()
    mir = pool.methods[CANCEL_REFUND_MID]
    s7 = _profile_for("S7.json")
    assert not any(pool.evaluate_guard(CANCEL_REFUND_MID, c.guard, s7) for c in mir.calls if c.callee == "calculateRefund")


def test_catch_arm_and_lazy_lambda_are_inactive():
    pool = MethodPoolIR.load()
    s2 = _profile_for("S2.json")
    any_mid = next(iter(pool.methods))
    assert pool.evaluate_guard(any_mid, ("t10:catch",), s2) is False
    assert pool.evaluate_guard(any_mid, ("l91:orElseThrow",), s2) is False
    assert pool.evaluate_guard(any_mid, ("l91:map",), s2) is True


def test_get_token_exception_constructor_is_inactive_via_lambda_guard():
    pool = MethodPoolIR.load()
    mid = next(m for m in pool.methods if "TokenServiceImpl#getToken" in m)
    s0 = _profile_for("S0.json")
    lambda_calls = [c for c in pool.methods[mid].calls if any(g.startswith("l") and ":orElseThrow" in g for g in c.guard)]
    assert lambda_calls, "тело лямбды orElseThrow должно быть помечено guard-ом"
    assert not any(pool.evaluate_guard(mid, c.guard, s0) for c in lambda_calls)


def test_rebook_same_family_branch_is_active_for_regular_scenario():
    pool = MethodPoolIR.load()
    mid = next(m for m in pool.methods if "RebookServiceImpl#updateOrder(" in m and "TripAllDetail" in m)
    s2 = _profile_for("S2.json")
    updates = [c for c in pool.methods[mid].calls if c.callee == "updateOrder"]
    assert updates and all(pool.evaluate_guard(mid, c.guard, s2) for c in updates)


def test_new_user_flag_only_for_registering_scenario():
    assert _profile_for("S4.json").is_new_user is True
    assert _profile_for("S1.json").is_new_user is False


def test_foreach_over_orders_is_empty_for_new_user_only():
    pool = MethodPoolIR.load()
    mid = next(m for m in pool.methods if "OrderServiceImpl#checkSecurityAboutOrder" in m and "other" not in m)
    loop_calls = [c for c in pool.methods[mid].calls if any(g.endswith(":orders") for g in c.guard)]
    assert loop_calls
    s4 = _profile_for("S4.json")
    s1 = _profile_for("S1.json")
    assert not any(pool.evaluate_guard(mid, c.guard, s4) for c in loop_calls)
    assert all(pool.evaluate_guard(mid, c.guard, s1) for c in loop_calls)


def test_evaluate_guard_high_speed_vs_regular_order_branches():
    pool = MethodPoolIR.load()

    p_hs = ScenarioProfile(
        id="S0",
        is_admin=False,
        has_assurance=False,
        has_food=False,
        has_consign=False,
        train_mode="high_speed_only",
    )
    p_reg = ScenarioProfile(
        id="S2",
        is_admin=False,
        has_assurance=False,
        has_food=False,
        has_consign=False,
        train_mode="regular_only",
    )

    cancel_mid = "method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)"
    # b49: G/D orderResult
    assert pool.evaluate_guard(cancel_mid, ("b49:then",), p_hs) is True
    assert pool.evaluate_guard(cancel_mid, ("b49:then",), p_reg) is False
    assert pool.evaluate_guard(cancel_mid, ("b49:else",), p_reg) is True

    # b105: Regular orderOtherResult
    assert pool.evaluate_guard(cancel_mid, ("b105:then",), p_reg) is True
    assert pool.evaluate_guard(cancel_mid, ("b105:then",), p_hs) is False

    # b65 in CancelServiceImpl is drawbackMoney status check, NOT execute b65!
    assert pool.evaluate_guard(cancel_mid, ("b65:then",), p_hs) is True

    execute_mid = "method:ts-execute-service:execute.serivce.ExecuteServiceImpl#ticketCollect(java.lang.String,org.springframework.http.HttpHeaders)"
    # b95: G/D order check
    assert pool.evaluate_guard(execute_mid, ("b95:then",), p_hs) is True
    assert pool.evaluate_guard(execute_mid, ("b95:then",), p_reg) is False

    # b113: Regular order check
    assert pool.evaluate_guard(execute_mid, ("b95:else", "b113:then"), p_reg) is True
    assert pool.evaluate_guard(execute_mid, ("b95:else", "b113:then"), p_hs) is False


def test_evaluate_guard_consign_is_present():
    pool = MethodPoolIR.load()
    consign_mid = "method:ts-consign-service:consign.service.ConsignServiceImpl#updateConsignRecord(consign.entity.Consign,org.springframework.http.HttpHeaders)"
    profile = ScenarioProfile(id="S7", is_admin=False, has_assurance=False, has_food=False, has_consign=True, train_mode="high_speed_only")
    # b85: !repository.findById(consignRequest.getId()).isPresent() -> then (fallback insert) should be False
    assert pool.evaluate_guard(consign_mid, ("b85:then",), profile) is False
    assert pool.evaluate_guard(consign_mid, ("b85:else",), profile) is True


def test_get_enum_target_dynamic():
    from engine.ir import CallIR, EnumConstantIR

    pool = MethodPoolIR.load()
    call = CallIR(
        file="SomeFile.java",
        line=10,
        col=20,
        callee="getCode",
        receiver="MyStatus.PAID",
        kind="ENUM",
        arg_count=0,
        guard=(),
        enum_constant=EnumConstantIR(
            type_fqn="com.example.custom.MyStatus",
            constant="PAID",
        ),
    )

    fake_skeleton = {
        "method:my-service:com.example.custom.MyStatus#getCode()": {
            "kind": "method",
            "name": "getCode",
        }
    }

    # Динамический поиск по скелету
    target = pool.get_enum_target(call, skeleton_nodes=fake_skeleton)
    assert target == "method:my-service:com.example.custom.MyStatus#getCode()"

    # Fallback для стандартных перечислений Train Ticket
    call_order = CallIR(
        file="SomeFile.java",
        line=10,
        col=20,
        callee="getCode",
        receiver="OrderStatus.PAID",
        kind="ENUM",
        arg_count=0,
        guard=(),
        enum_constant=EnumConstantIR(
            type_fqn="edu.fudan.common.entity.OrderStatus",
            constant="PAID",
        ),
    )
    assert pool.get_enum_target(call_order) == "method:ts-common:edu.fudan.common.entity.OrderStatus#getCode()"


