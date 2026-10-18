"""Факты для судьи M4: значения переменных условия, пройденный путь, сводка состояния (ADR-005, «Вердикт судьи»).

Текст детерминирован (порядок по появлению в условии, поля по алфавиту): от него зависит ключ кеша ответов LLM.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from engine.executor.program import expr_kind, walk
from engine.executor.values import (
    NONNULL, Coll, Iter, Lambda, Obj, Opt, Sym, TypeRef, Unknown, leaves, simple_name,
)

if TYPE_CHECKING:
    from engine.executor.interp import Frame, StepRun

MAX_FIELDS = 10
MAX_ORDERS = 8
ORDER_STATUS = {0: "NOTPAID", 1: "PAID", 2: "COLLECTED", 3: "CHANGE", 4: "CANCEL", 5: "REFUND", 6: "USED"}


def render(v: Any, depth: int = 0) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return repr(v if len(v) <= 60 else v[:57] + "...")
    if isinstance(v, Unknown):
        hint = " (not null)" if v.default is NONNULL else ""
        return f"unknown: {v.origin}{hint}"
    if isinstance(v, Sym):
        return f"unknown: computed from {', '.join(u.origin for u in leaves(v)) or 'unknown values'}"
    if isinstance(v, Obj):
        if v.src == "enum":
            return f"{v.simple}.{v.fields.get('__name__')}"
        if v.src == "bean":
            return f"{v.simple} (service bean)"
        if depth >= 1:
            return f"{v.simple}{{...}}"
        known = [(k, x) for k, x in sorted(v.fields.items()) if not k.startswith("__") and not isinstance(x, Unknown)]
        inner = ", ".join(f"{k}={render(x, depth + 1)}" for k, x in known[:MAX_FIELDS])
        more = ", ..." if len(known) > MAX_FIELDS else ""
        where = {"state": " (row from the database)", "request": " (step request)"}.get(v.src, "")
        return f"{v.simple}{{{inner}{more}}}{where}"
    if isinstance(v, Coll):
        if v.items is not None:
            head = ", ".join(render(x, depth + 1) for x in v.items[:3])
            return f"list of {len(v.items)}: [{head}{', ...' if len(v.items) > 3 else ''}]"
        ne = v.nonempty
        state = "not empty" if ne is True else "empty" if ne is False else "unknown size"
        return f"list ({state}): {v.origin}"
    if isinstance(v, Opt):
        p = v.present
        return f"Optional({'present' if p is True else 'empty' if p is False else 'unknown'}): {v.origin}"
    if isinstance(v, Iter):
        return f"iterator over {render(v.coll, depth + 1)}"
    if isinstance(v, TypeRef):
        return f"class {v.simple}"
    if isinstance(v, Lambda):
        return "lambda"
    return type(v).__name__


def condition_facts(run: StepRun, frame: Frame, cond: Any, v: Any) -> tuple[str, ...]:
    """Значения переменных условия и неизвестные, от которых оно зависит."""
    out: list[str] = []
    seen: set[str] = set()
    for n in walk(cond):
        if expr_kind(n) != "name" or n.get("ref") not in ("local", "param", "field"):
            continue
        name = n["name"]
        if name in seen:
            continue
        seen.add(name)
        if n["ref"] == "field":
            val = frame.this.fields.get(name) if isinstance(frame.this, Obj) else None
            label = f"this.{name}"
        else:
            val = frame.env.get(name)
            label = name
        out.append(f"{label} = {render(val)}")
    for u in leaves(v):
        line = f"unknown value: {u.origin}"
        if line not in out:
            out.append(line)
    return tuple(out)


def path_lines(frame: Frame) -> tuple[str, ...]:
    """Стек вызовов от обработчика шага и решения в каждом кадре."""
    chain: list[Frame] = []
    f: Frame | None = frame
    while f is not None:
        chain.append(f)
        f = f.caller
    out: list[str] = []
    for i, fr in enumerate(reversed(chain)):
        name = _short(fr.method_id)
        if i == 0:
            out.append(f"{name} (handler of the step request)")
        else:
            out.append(f"-> {name} (called at line {fr.call_line})")
        for d in fr.history[-6:]:
            verdict = {"then": "TRUE", "else": "FALSE", "body": "runs", "skip": "skipped"}.get(d.arm, d.arm)
            out.append(f"   line {d.line}: {d.text or d.bid} -> {verdict}")
    return tuple(out)


def state_lines(run: StepRun) -> tuple[str, ...]:
    s = run.state
    out: list[str] = []
    if s is None:
        return ()
    who = getattr(s, "user_name", "?")
    out.append(f"logged-in user: {who} (account {getattr(s, 'account_id', '?')})"
               + ("; registered in this scenario, no earlier orders or contacts" if getattr(s, "is_new_user", False)
                  else ""))
    if hasattr(s, "balance"):
        out.append(f"internal account balance (scenario model): {s.balance}")
    created = {c.get("order_id") for c in run.ex.refs.created.values() if c.get("order_id")}
    orders = s.get_orders(account_id=s.account_id) if hasattr(s, "get_orders") else []
    orders = sorted(orders, key=lambda o: (o.get("id") not in created, str(o.get("id"))))
    for o in orders[:MAX_ORDERS]:
        st = o.get("status")
        try:
            code: Any = int(st)
        except (TypeError, ValueError):
            code = st
        mark = " (created in this scenario)" if o.get("id") in created else ""
        out.append(f"order {o.get('id')}: train {o.get('train_number')}, status {ORDER_STATUS.get(code, code)}, "
                   f"price {o.get('price')}{mark}")
    if len(orders) > MAX_ORDERS:
        out.append(f"... {len(orders) - MAX_ORDERS} more orders of the user")
    contacts = s.get_contacts() if hasattr(s, "get_contacts") else []
    out.append(f"contacts of the user: {len(contacts)}")
    cons = s.get_consignments() if hasattr(s, "get_consignments") else []
    if cons:
        out.append(f"luggage consignments of the user: {len(cons)}")
    return tuple(out)


def _short(method_id: str) -> str:
    tail = method_id.split(":", 2)[-1]
    cls, _, rest = tail.partition("#")
    module = method_id.split(":", 2)[1] if method_id.count(":") >= 2 else ""
    return f"{module} {simple_name(cls)}#{rest.split('(', 1)[0]}"
