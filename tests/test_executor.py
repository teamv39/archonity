"""Исполнитель M4 по IR (engine/executor, ADR-005): модель значений, библиотека, мир БД, сквозной прогон."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from engine.adapters.db import DatabaseState
from engine.executor.envelope import NAMES
from engine.executor.interpreter import arm_fails, match_template
from engine.executor.library import _date_call, call_library, new_library
from engine.executor.values import (
    UNKNOWN, Concat, DateV, ListV, Obj, OptionalV, concat, join, same_value, t_and, t_or,
)
from engine.executor.world import derived_props, native_query_conds, parse_java_args

ROOT = Path(__file__).resolve().parent.parent
SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"
TARGETS_ROOT = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"
SCENARIOS = ROOT / "hackaton" / "tt-challenge" / "scenarios"
GOLD_S0_PATH = ROOT / "hackaton" / "tt-challenge" / "gold" / "S0.json"
EVAL_SCRIPT = ROOT / "hackaton" / "tt-challenge" / "platform" / "evaluate_golden.py"


class TestValues:
    def test_three_valued_logic(self) -> None:
        assert t_and(True, UNKNOWN) is UNKNOWN
        assert t_and(False, UNKNOWN) is False
        assert t_or(True, UNKNOWN) is True
        assert t_or(False, UNKNOWN) is UNKNOWN

    def test_join_keeps_equal_and_merges_objects_by_field(self) -> None:
        assert join(1, 1) == 1
        assert join(1, 2) is UNKNOWN
        a = Obj("x.Response", {"status": 1, "msg": "ok"}, open=False)
        b = Obj("x.Response", {"status": 0, "msg": "ok"}, open=False)
        m = join(a, b)
        assert m.fields["status"] is UNKNOWN and m.fields["msg"] == "ok"

    def test_concat_keeps_holes(self) -> None:
        url = concat("http://ts-order-service/api/v1/orderservice/order/", UNKNOWN)
        assert isinstance(url, Concat)
        assert url.render().startswith("http://ts-order-service/")

    def test_same_value_null_and_strings(self) -> None:
        assert same_value(None, None) is True
        assert same_value("G", "G") is True
        assert same_value(UNKNOWN, 1) is UNKNOWN


class TestStructure:
    def test_match_template_binds_path_variables(self) -> None:
        b = match_template(["api", "v1", "orderservice", "order", "abc"], ["api", "v1", "orderservice", "order", "{id}"])
        assert b == {"id": "abc"}
        assert match_template(["api", "v1", "x"], ["api", "v1", "y"]) is None

    def test_derived_query_and_native_sql(self) -> None:
        assert derived_props("findByAccountIdAndStatus") == ("find", ["accountId", "status"])
        assert derived_props("save") is None
        assert native_query_conds("SELECT * FROM t WHERE route_id IN ?1 AND train_type IN ?2") == [
            ("route_id", 0), ("train_type", 1)]

    def test_enum_args_parse(self) -> None:
        assert parse_java_args('"G", 1') == ["G", 1]

    def test_failure_arm_detection(self) -> None:
        fail_new = [{"op": "return", "expr": {"new": "Response<>", "args": [{"lit": 0, "type": "int"}]}}]
        ok_new = [{"op": "return", "expr": {"new": "Response<>", "args": [{"lit": 1, "type": "int"}]}}]
        # response.setStatus(0); return response;
        fail_var = [
            {"op": "expr", "expr": {"call": "c", "callee": "setStatus", "recv": {"name": "response", "ref": "local"},
                                    "args": [{"lit": 0, "type": "int"}]}},
            {"op": "return", "expr": {"name": "response", "ref": "local"}},
        ]
        assert arm_fails(fail_new, NAMES) and arm_fails(fail_var, NAMES) and arm_fails([{"op": "throw", "expr": {}}], NAMES)
        assert not arm_fails(ok_new, NAMES) and not arm_fails([], NAMES)


class _It:
    """Минимальный интерпретатор для моделей библиотеки, которым он не нужен."""

    rules = None
    journal: list = []

    def touch_list(self, lst: ListV) -> None:
        pass


class TestLibrary:
    def test_dates_and_formats(self) -> None:
        fmt = new_library(_It(), "SimpleDateFormat", ["yyyy-MM-dd"])
        d = call_library(_It(), None, "parse", fmt, ["2026-10-01"], {})
        assert isinstance(d, DateV) and d.value.month == 10
        cal = DateV(d.value, calendar=True)
        assert _date_call(cal, "get", [2]) == 9  # Calendar.MONTH с нуля
        old = new_library(_It(), "Date", [2026, 9, 1, 9, 51, 52])  # Date(year-1900, ...)
        assert old.value.year == 3926
        df = new_library(_It(), "DecimalFormat", ["0.00"])
        assert call_library(_It(), None, "format", df, [280.0], {}) == "280.00"

    def test_sets_and_lists(self) -> None:
        s = new_library(_It(), "HashSet", [])
        call_library(_It(), None, "add", s, ["a"], {"recv": {}})
        call_library(_It(), None, "add", s, ["a"], {"recv": {}})
        assert s.items == ["a"]
        lst = ListV(["shanghai", "suzhou"])
        assert call_library(_It(), None, "indexOf", lst, ["suzhou"], {"recv": {}}) == 1
        assert call_library(_It(), None, "isEmpty", ListV(["x"], exact=False), [], {"recv": {}}) is UNKNOWN

    def test_optional_maybe(self) -> None:
        o = OptionalV(Obj("e.Route"), maybe=True)
        assert call_library(_It(), None, "isPresent", o, [], {"recv": {}}) is UNKNOWN


class TestWorld:
    def test_mysql_string_compare_is_case_insensitive(self) -> None:
        from engine.executor.world import World

        db = DatabaseState(tables={"station": [{"id": "1", "name": "shanghai"}]})
        w = World(db, types=None, entities=None, enum_factory=None)
        assert w._match({"name": "shanghai"}, "name", None, "Shanghai", None) is True
        assert w._match({"name": "shanghai"}, "name", None, UNKNOWN, None) is UNKNOWN


@pytest.fixture(scope="module")
def m4_pipeline(shared_pipeline):
    return shared_pipeline


class TestExecutorE2E:
    def test_s0_perfect_score(self, m4_pipeline, tmp_path: Path) -> None:
        out = tmp_path / "submission.json"
        m4_pipeline.run_all([SCENARIOS / "S0.json"], output_path=out)
        res = subprocess.run([sys.executable, str(EVAL_SCRIPT), str(GOLD_S0_PATH), str(out), "--json"],
                             capture_output=True, text=True)
        assert json.loads(res.stdout)["score"] == pytest.approx(1.0, abs=1e-4)

    def test_ledger_matches_answer_and_determinism(self, m4_pipeline) -> None:
        from engine.adapters.skeleton import load_json

        for sp in sorted(SCENARIOS.glob("*.json")):
            s = load_json(sp)
            first = m4_pipeline.run_scenario(s)
            sid = s["id"]
            methods, calls, remote, data = first
            answer = {("executes", f"scenario:{sid}", m) for m in methods}
            answer |= {("calls", a, b) for a, b in calls} | {("remote", a, b) for a, b in remote}
            answer |= {("data", a, b) for a, b in data}
            assert m4_pipeline.ledger.final_edges(sid) == answer, f"{sid}: журнал не совпадает с ответом"
            assert m4_pipeline.run_scenario(s) == first, f"{sid}: повторный прогон дал другой ответ"


@pytest.fixture(scope="module")
def m4_answers(m4_pipeline):
    from engine.adapters.skeleton import load_json

    return {sid: m4_pipeline.run_scenario(load_json(SCENARIOS / f"{sid}.json")) for sid in ("S1", "S2", "S3")}


class TestFrameworkMechanisms:
    """Механизмы, перенесённые из ручных посылок 11–17 (docs/researches/code_record_drift.md)."""

    REBOOK_INFO = "method:ts-rebook-service:rebook.entity.RebookInfo#<init>()"
    DATE2STRING = "method:ts-common:edu.fudan.common.util.StringUtils#Date2String(java.util.Date)"
    IS_STATUS = "method:ts-common:edu.fudan.common.entity.TravelResult#isStatus()"
    STATION_STORES = ("method:ts-station-food-service:food.controller.StationFoodController#getFoodStoresOfStation("
                      "java.lang.String,org.springframework.http.HttpHeaders)")

    def test_jackson_runs_request_body_ctor(self, m4_answers) -> None:
        methods, calls, _, _ = m4_answers["S2"]
        assert self.REBOOK_INFO in methods
        assert (self.REBOOK_INFO, self.DATE2STRING) in calls
        assert not any(t == self.REBOOK_INFO for _, t in calls)  # ребра в конструктор нет (R7)

    def test_lombok_tostring_in_logging_runs_handwritten_getter(self, m4_answers) -> None:
        for sid in ("S1", "S2", "S3"):
            methods, calls, _, _ = m4_answers[sid]
            assert self.IS_STATUS in methods, sid
            assert not any(t == self.IS_STATUS for _, t in calls), sid  # вызывает Lombok, не проект (R5)

    def test_unbound_handler_rebound_to_station_names(self, m4_pipeline, m4_answers) -> None:
        by_names = ("method:ts-station-food-service:food.service.StationFoodServiceImpl#getFoodStoresByStationNames("
                    "java.util.List)")
        for sid in ("S2", "S3"):
            methods, _, _, data = m4_answers[sid]
            assert self.STATION_STORES not in methods, sid  # Spring не вызывает сломанный обработчик
            assert by_names in methods, sid
            assert {t.split(":")[-1] for s, t in data if s == by_names} == {
                "ts-station-food-service.station_food_store", "ts-station-food-service.station_food_list"}, sid
            step4 = next(r for r in m4_pipeline.step_requests[sid] if r["step"] == 4)
            assert step4["grounding"]["rebound"]["rule"] == "R20:unbound_path_variable"
