"""Тесты журнала решений по рёбрам (engine/decisions.py)."""
from __future__ import annotations

import pytest

from engine.decisions import DecisionLedger, edge_key


def test_include_and_prune_across_steps() -> None:
    ledger = DecisionLedger()
    ledger.begin_scenario("S9")
    ledger.begin_step(1)
    ledger.prune("calls", "a", "b", "IR_BRANCH", "R15")
    ledger.begin_step(2)
    ledger.include("calls", "a", "b", "SKELETON", "reachability")
    # Отсев того же ребра с другого пути (например, другой deployment unit) не снимает включение
    ledger.prune("calls", "a", "b", "SKELETON", "cross_unit")

    assert ledger.final_edges("S9") == {("calls", "a", "b")}
    entry = ledger.scenario_dict("S9")[edge_key("calls", "a", "b")]
    assert entry["included"] is True
    assert entry["steps"] == [2]
    assert entry["source_type"] == "SKELETON"
    assert len(entry["decisions"]) == 3


def test_discard_removes_edge_only_in_its_step() -> None:
    ledger = DecisionLedger()
    ledger.begin_scenario("S9")
    ledger.begin_step(1)
    ledger.include("calls", "a", "b", "SKELETON", "reachability")
    ledger.discard("calls", "a", "b", "STATE", "date_filter")
    assert ledger.final_edges("S9") == set()
    assert ledger.scenario_dict("S9")[edge_key("calls", "a", "b")]["rule"] == "date_filter"

    ledger.begin_step(2)
    ledger.include("calls", "a", "b", "SKELETON", "reachability")
    assert ledger.final_edges("S9") == {("calls", "a", "b")}


def test_execute_uses_scenario_source_and_rejects_unknown_type() -> None:
    ledger = DecisionLedger()
    ledger.begin_scenario("S9")
    ledger.execute("method:x", "SKELETON", "ENTRY")
    assert ledger.final_edges("S9") == {("executes", "scenario:S9", "method:x")}
    with pytest.raises(ValueError):
        ledger.include("calls", "a", "b", "GUESS", "r")

