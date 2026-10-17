"""Тесты журнала решений по рёбрам (engine/decisions.py)."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.decisions import DecisionLedger, edge_key, rules_return_line
from engine.rules import RuntimeRules

RULES_PY = Path(__file__).resolve().parent.parent / "engine" / "rules.py"


def test_include_and_prune_across_steps() -> None:
    ledger = DecisionLedger()
    ledger.begin_scenario("S9")
    ledger.begin_step(1)
    ledger.prune("calls", "a", "b", "DEFAULT_RULE", "rules.py:1")
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


def test_rules_return_line_points_to_firing_rule() -> None:
    rules = RuntimeRules()
    method = "method:ts-contacts-service:contacts.controller.ContactsController#home(org.springframework.http.HttpHeaders)"
    assert rules.is_dead_code_method(method)

    where = rules_return_line(rules.is_dead_code_method, method)
    assert where.startswith("rules.py:")
    line = int(where.split(":")[1])
    source = RULES_PY.read_text(encoding="utf-8").splitlines()
    assert source[line - 1].strip() == "return True"
    assert "Controller#home(" in source[line - 2]
