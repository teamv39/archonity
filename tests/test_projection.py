"""Тесты проекции M5: видимость конструкторов в ответе (R7, ADR-006, engine/projection.py)."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.adapters.skeleton import load_json
from engine.decisions import DecisionLedger
from engine.pipeline import ArchonityPipeline
from engine.projection import project_constructors

SCENARIOS = Path(__file__).resolve().parent.parent / "hackaton" / "tt-challenge" / "scenarios"

PRESERVE = "method:ts-preserve-service:preserve.service.PreserveServiceImpl#preserve(x)"
SOLD = "method:ts-seat-service:seat.service.SeatServiceImpl#getSoldTickets(x)"
ORDER_CTOR = "method:ts-common:edu.fudan.common.entity.Order#<init>()"
TICKET_CTOR = "method:ts-common:edu.fudan.common.entity.Ticket#<init>(int,int)"
DATE2STRING = "method:ts-common:edu.fudan.common.util.StringUtils#Date2String(java.util.Date)"
TABLE = "res:table:ts-order-service.orders"


def _step() -> tuple[set, set, set, set]:
    """Шаг бронирования (пример ADR-006): Order() вызывает Date2String, Ticket(...) — только присваивания."""
    methods = {PRESERVE, SOLD, ORDER_CTOR, TICKET_CTOR, DATE2STRING}
    calls = {(PRESERVE, ORDER_CTOR), (SOLD, TICKET_CTOR), (ORDER_CTOR, DATE2STRING)}
    return methods, calls, set(), {(PRESERVE, TABLE)}


def test_caller_only_keeps_ctor_with_project_call() -> None:
    methods, calls, remote, data = _step()
    project_constructors(methods, calls, remote, data, "caller_only")
    assert methods == {PRESERVE, SOLD, ORDER_CTOR, DATE2STRING}
    assert calls == {(ORDER_CTOR, DATE2STRING)}
    assert data == {(PRESERVE, TABLE)}


def test_all_changes_nothing() -> None:
    methods, calls, remote, data = _step()
    project_constructors(methods, calls, remote, data, "all")
    assert (methods, calls, remote, data) == _step()


def test_off_drops_every_ctor_edge() -> None:
    methods, calls, remote, data = _step()
    project_constructors(methods, calls, remote, data, "off")
    assert methods == {PRESERVE, SOLD, DATE2STRING}
    assert calls == set()
    assert data == {(PRESERVE, TABLE)}


def test_ledger_matches_projection() -> None:
    ledger = DecisionLedger()
    ledger.begin_scenario("S9")
    ledger.begin_step(1)
    methods, calls, remote, data = _step()
    for m in methods:
        ledger.execute(m, "SKELETON", "reachability")
    for s, t in calls:
        ledger.include("calls", s, t, "SKELETON", "reachability")
    for s, t in data:
        ledger.include("data", s, t, "SKELETON", "reachability")
    project_constructors(methods, calls, remote, data, "caller_only", ledger)

    expected = {("executes", "scenario:S9", m) for m in methods}
    expected |= {("calls", s, t) for s, t in calls} | {("data", s, t) for s, t in data}
    assert ledger.final_edges("S9") == expected
    entry = ledger.scenario_dict("S9")[f"executes|scenario:S9|{TICKET_CTOR}"]
    assert (entry["source_type"], entry["rule"]) == ("FRAMEWORK_RULE", "R7:ctor_visibility:no_project_call")


def test_ctor_visible_in_scenario_if_visible_in_any_step() -> None:
    """Конструктор, видимый на шаге 1 и невидимый на шаге 2, остаётся в ответе сценария (объединение по шагам)."""
    ledger = DecisionLedger()
    ledger.begin_scenario("S9")
    for step, calls in ((1, {(ORDER_CTOR, DATE2STRING)}), (2, set())):
        ledger.begin_step(step)
        methods = {ORDER_CTOR}
        ledger.execute(ORDER_CTOR, "SKELETON", "reachability")
        for s, t in calls:
            ledger.include("calls", s, t, "SKELETON", "reachability")
        project_constructors(methods, set(calls), set(), set(), "caller_only", ledger)
    assert ("executes", "scenario:S9", ORDER_CTOR) in ledger.final_edges("S9")


@pytest.mark.parametrize("scenario", ["S0.json"])
def test_pipeline_has_no_calls_into_ctors(shared_pipeline: ArchonityPipeline, scenario: str) -> None:
    methods, calls, remote, data = shared_pipeline.run_scenario(load_json(SCENARIOS / scenario))
    assert not any("#<init>(" in t for _, t in calls)
    sources = {s for s, _ in calls | remote | data}
    assert all(m in sources for m in methods if "#<init>(" in m)
