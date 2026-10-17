"""Правила M4 для неизвестных условий: значения по умолчанию, инертные плечи, плечо по исходу шага (ADR-005, M4).

Порядок разрешения UNKNOWN: шаблоны по умолчанию (D1–D4, только если шаг ждёт успеха) -> судья -> плечо,
согласованное с ожидаемым исходом шага. Если оба плеча инертны, условие не влияет на рёбра и судья не нужен.

Шаблоны (значение `default` у листа `Unknown`, ставит интерпретатор при создании значения):
- D1: статус ответа другого сервиса или проектного метода (`Response.status`) равен 1;
- D2: результат вызова, удалённого вызова или репозитория не null (чтение с `expects = EMPTY` — null);
- D3: `Optional` из репозитория непуст при `expects = ROWS`, пуст при `EMPTY`;
- D4: коллекция из ответа другого сервиса непуста; из репозитория — по `expects`.
"""
from __future__ import annotations

from typing import Any, Callable

from engine.executor.program import expr_kind, walk
from engine.executor.values import MISSING, Unknown

LOG_METHODS = frozenset({"info", "warn", "error", "debug", "trace"})
FAIL_LOG_METHODS = frozenset({"warn", "error"})
RESPONSE_FQN = "edu.fudan.common.util.Response"


def default_leaf(u: Unknown) -> Any:
    """Значение листа на успешном пути (D1–D4) или MISSING."""
    return u.default


def is_logger_call(node: dict[str, Any]) -> bool:
    if expr_kind(node) != "call" or node.get("callee") not in LOG_METHODS:
        return False
    recv = node.get("recv") or {}
    name = recv.get("field") or recv.get("name") or ""
    return isinstance(name, str) and name.lower() in ("logger", "log")


def inert(stmts: list[dict[str, Any]], has_targets: Callable[[str | None], bool]) -> bool:
    """Плечо не влияет на рёбра и значения: только записи в лог без проектных вызовов в аргументах."""
    for st in stmts:
        if st.get("op") != "expr" or not is_logger_call(st.get("expr") or {}):
            return False
        for n in walk(st["expr"].get("args")):
            cs = n.get("call")
            if isinstance(cs, str) and (has_targets(cs) or n.get("target")):
                return False
    return True


def _fail_value(expr: dict[str, Any] | None) -> bool:
    """Возвращаемое значение означает отказ: Response со статусом не 1 (в том числе внутри ok(...)), false, null."""
    if expr is None:
        return False
    k = expr_kind(expr)
    if k == "lit":
        return expr.get("lit") is None or expr.get("lit") is False
    if k == "new":
        if (expr.get("fqn") or "") == RESPONSE_FQN or str(expr.get("new", "")).startswith("Response"):
            args = expr.get("args") or []
            first = args[0] if args else None
            return bool(first) and expr_kind(first) == "lit" and first.get("lit") != 1
        return False
    if k == "call" and expr.get("callee") in ("ok", "body") and expr.get("args"):
        return _fail_value(expr["args"][0])
    return False


def arm_fails(stmts: list[dict[str, Any]]) -> bool:
    """Плечо — отказ: на верхнем уровне throw, return отказа или запись warn/error в лог."""
    for st in stmts:
        op = st.get("op")
        if op == "throw":
            return True
        if op == "return" and _fail_value(st.get("expr")):
            return True
        if op == "expr":
            e = st.get("expr") or {}
            if is_logger_call(e) and e.get("callee") in FAIL_LOG_METHODS:
                return True
    return False


def arm_exits(stmts: list[dict[str, Any]]) -> bool:
    """Плечо заканчивается return или throw на верхнем уровне."""
    return any(st.get("op") in ("return", "throw") for st in stmts)


def arm_may_fail(stmts: list[dict[str, Any]]) -> bool:
    """В плече на любой глубине есть throw или return отказа (кроме тел лямбд: они исполняются по требованию)."""
    for n in walk(stmts):
        if "lambda" in n:
            continue
        if n.get("op") == "throw" or (n.get("op") == "return" and _fail_value(n.get("expr"))):
            return True
    return False


def outcome_arm(then: list[dict[str, Any]], els: list[dict[str, Any]], expected: str,
                no_signal_arm: str = "continue") -> tuple[str, str]:
    """Плечо, согласованное с ожидаемым исходом шага: (then|else, обоснование).

    Сильный сигнал — отказ на верхнем уровне плеча; слабый — плечо может закончиться отказом глубже.
    """
    want_fail = expected == "refused"
    outcome = "refused" if want_fail else "success"
    f_then, f_else = arm_fails(then), arm_fails(els)
    if f_then != f_else:
        arm = "then" if f_then == want_fail else "else"
        return arm, f"{outcome}:fail_arm" if want_fail else f"{outcome}:ok_arm"
    if not f_then:
        m_then, m_else = arm_may_fail(then), arm_may_fail(els)
        if m_then != m_else:
            arm = "then" if m_then == want_fail else "else"
            return arm, f"{outcome}:may_fail_arm" if want_fail else f"{outcome}:safe_arm"
    if no_signal_arm == "continue":
        e_then, e_else = arm_exits(then), arm_exits(els)
        if e_then != e_else:
            return ("else" if e_then else "then"), "no_signal:continue"
    return "then", "no_signal:then"


def leaf_rules(used: list[Unknown]) -> str:
    """Имена правил по умолчанию, давших значения листьям: `D1+D2`."""
    rules = sorted({u.rule for u in used if u.rule})
    return "+".join(rules) or "DEFAULT"


__all__ = ["default_leaf", "inert", "arm_fails", "arm_exits", "outcome_arm", "leaf_rules", "is_logger_call", "MISSING"]
