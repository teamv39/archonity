from __future__ import annotations

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
    # 14 base methods + 7 methods added in PR #15
    assert len(pool.methods) == 21
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

