"""Тесты исполнителя M4 (engine/executor): модели значений и библиотеки, разбор исходников, исполнение по IR на S0–S7.

Модели проверяются на маленьких значениях без пайплайна. Исполнение — на настоящем IR (`data/ir/`) и скелете,
M1 только из кеша, судья выключен: по каждому месту проверяется решение, которое следует из кода и состояния.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from engine.adapters.skeleton import load_json
from engine.executor import library
from engine.executor.executor import M4Options
from engine.executor.program import _enum_constants, _java_literal, _split_args
from engine.executor.repo import InValues, cell_matches, native_query
from engine.executor.values import Coll, Obj, Opt, Unknown, and_, or_, truth
from engine.grounding.llm import LLMClient
from engine.pipeline import ArchonityPipeline

ROOT = Path(__file__).resolve().parent.parent
SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"
TARGETS_ROOT = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"
SCENARIOS = ROOT / "hackaton" / "tt-challenge" / "scenarios"
GOLD_S0 = ROOT / "hackaton" / "tt-challenge" / "gold" / "S0.json"

FRAME = SimpleNamespace(line=1, method_id="method:svc:a.B#m()")


def fake_run(project_types: frozenset[str] = frozenset()) -> Any:
    program = SimpleNamespace(
        resolve_simple=lambda name, module: name,
        is_project_type=lambda fqn: fqn in project_types,
        module_of=lambda mid: "svc",
    )
    return SimpleNamespace(state=SimpleNamespace(system_date="2026-09-15"), program=program, expected="success")


# --- значения -----------------------------------------------------------------------------------------------------

class TestValues:
    def test_kleene_logic(self) -> None:
        u = Unknown("u", "bool")
        assert and_(False, lambda: u) is False
        assert or_(True, lambda: u) is True
        assert truth(and_(True, lambda: u)) is None
        assert truth(or_(u, lambda: True)) is True

    def test_nonempty_follows_items(self) -> None:
        c = Coll([])
        assert c.nonempty is False
        c.items.append(1)  # add в методе после создания списка
        assert c.nonempty is True

    def test_nonempty_of_unknown_items_is_stored(self) -> None:
        flag = Unknown("rows", "bool")
        assert Coll(None, flag).nonempty is flag


# --- модели библиотеки --------------------------------------------------------------------------------------------

class TestCollectionsAndMaps:
    def test_is_empty_after_add(self) -> None:
        c = Coll([])
        library._collection(fake_run(), FRAME, c, "add", ["x"])
        assert library._collection(fake_run(), FRAME, c, "isEmpty", []) is False

    def test_index_of_unknown_is_unknown(self) -> None:
        c = Coll(["shanghai", "suzhou"])
        assert library._collection(fake_run(), FRAME, c, "indexOf", ["suzhou"]) == 1
        assert library._collection(fake_run(), FRAME, c, "indexOf", ["nanjing"]) == -1
        assert truth(library._collection(fake_run(), FRAME, c, "indexOf", [Unknown("s", "string")])) is None

    def test_add_all_keeps_default_of_added(self) -> None:
        c = Coll([])
        remote = Unknown("trips", "collection", library.NONNULL, src="remote", rule="D2")
        library._collection(fake_run(), FRAME, c, "addAll", [remote])
        assert isinstance(c.nonempty, Unknown) and c.nonempty.default is True

    def test_map_missing_key_is_null(self) -> None:
        m = Obj("java.util.HashMap", {"__map__": {"a": 1}})
        assert library._map(m, "get", ["a"]) == 1
        assert library._map(m, "get", ["b"]) is None
        assert library._map(m, "containsKey", ["b"]) is False

    def test_map_put_unknown_key_makes_map_incomplete(self) -> None:
        m = Obj("java.util.HashMap", {"__map__": {}})
        library._map(m, "put", [Unknown("k", "string"), 1])
        assert library._map(m, "isEmpty", []) is False
        assert truth(library._map(m, "get", ["b"])) is None
        entries = library._map(m, "entrySet", [])
        assert entries.items is None and entries.nonempty is True


class TestJackson:
    def test_round_trip_keeps_value(self) -> None:
        run = fake_run(frozenset({"a.Route"}))
        route = Obj("a.Route", {"id": "r1", "stations": Coll(["shanghai"])}, src="state")
        json_text = library._object(run, FRAME, Obj("ObjectMapper", src="library"), "writeValueAsString", [route])
        back = library.from_json(run, FRAME, json_text, Obj("java.lang.Class", {"name": "a.Route"}))
        assert isinstance(back, Obj) and back is not route
        assert back.type == "a.Route" and back.fields["id"] == "r1" and back.src == "state"

    def test_optional_is_unwrapped_between_services(self) -> None:
        route = Obj("a.Route", {"id": "r1"})
        resp = Obj("Response", {"status": 1, "data": Opt(True, route)})
        assert library.wire(resp).fields["data"] is route
        assert library.wire(Opt(False)) is None

    def test_dto_to_map(self) -> None:
        run = fake_run()
        v = library.from_json(run, FRAME, Obj("a.Dto", {"x": 1}), Obj("java.lang.Class", {"name": "Map"}))
        assert v.fields["__map__"] == {"x": 1}


class TestDates:
    def test_parse_and_format(self) -> None:
        fmt = Obj("java.text.SimpleDateFormat", {"pattern": "yyyy-MM-dd"})
        d = library._date_format(fmt, "parse", "2026-10-01 09:00:00", FRAME)  # хвост Java не проверяет
        assert d.fields["v"] == dt.datetime(2026, 10, 1)
        long_fmt = Obj("java.text.SimpleDateFormat", {"pattern": "yyyy-MM-dd HH:mm:ss"})
        assert library._date_format(long_fmt, "format", d, FRAME) == "2026-10-01 00:00:00"

    def test_parse_error_throws(self) -> None:
        from engine.executor.interp import ThrowSignal

        long_fmt = Obj("java.text.SimpleDateFormat", {"pattern": "yyyy-MM-dd HH:mm:ss"})
        with pytest.raises(ThrowSignal):
            library._date_format(long_fmt, "parse", "2026-10-01", FRAME)

    def test_calendar_against_system_clock(self) -> None:
        run = fake_run()
        today = Obj(library.CALENDAR_TYPE, {"v": library.now(run)})  # Calendar.getInstance()
        assert library._calendar(today, "get", ["YEAR"]) == 2026
        assert library._calendar(today, "get", ["MONTH"]) == 8  # сентябрь, счёт с нуля
        library._calendar(today, "add", ["HOUR_OF_DAY", -1])
        assert library._calendar(today, "get", ["HOUR_OF_DAY"]) == library.NOW_TIME.hour - 1

    def test_deprecated_date_constructor_with_unknown_time(self) -> None:
        run = fake_run()
        start = library.new_date(run, [2026, 9, 1, Unknown("h", "number"), 0, 0])  # год от 1900: 3926
        assert start.fields.get("day_only") is True
        now = library.new_date(run, [])
        assert library._date(now, "after", [start]) is False

    def test_same_day_with_unknown_time_stays_unknown(self) -> None:
        run = fake_run()
        a = library.date_obj(dt.datetime(2026, 9, 15, 10))
        b = library.new_date(run, [126, 8, 15, Unknown("h", "number")])
        assert truth(library._date(a, "before", [b])) is None

    def test_decimal_format(self) -> None:
        assert library._decimal_format(Obj("java.text.DecimalFormat", {"pattern": "0.00"}), 96.0) == "96.00"


# --- разбор исходников и запросов ---------------------------------------------------------------------------------

class TestSourceParsing:
    def test_enum_constants_with_args(self) -> None:
        body = 'TRAFFIC_ACCIDENT(1, "Traffic Accident Assurance", 3.0);\n private int index;'
        consts = _enum_constants(body)
        assert consts == [("TRAFFIC_ACCIDENT", '1, "Traffic Accident Assurance", 3.0')]
        assert [_java_literal(a)["lit"] for a in _split_args(consts[0][1])] == [1, "Traffic Accident Assurance", 3.0]

    def test_enum_constants_without_args(self) -> None:
        assert _enum_constants("G, D, Z;") == [("G", None), ("D", None), ("Z", None)]

    def test_non_literal_argument(self) -> None:
        assert _java_literal("Foo.bar()") is None

    def test_native_query(self) -> None:
        mid = "method:svc:a.Repo#findByNames(java.util.List)"
        run = SimpleNamespace(program=SimpleNamespace(N={mid: {"annotations": [
            {"name": "Query", "args": '(value="SELECT * from station where name in ?1", nativeQuery = true)'}]}}))
        assert native_query(run, mid) == [("name", "in", 1)]

    def test_cell_matching(self) -> None:
        enum_g = Obj("a.Type", {"__name__": "G", "__ordinal__": 0}, src="enum")
        assert cell_matches(0, enum_g) and cell_matches("G", enum_g) and not cell_matches(1, enum_g)
        assert cell_matches("shanghai", "Shanghai")  # MySQL: без учёта регистра
        assert cell_matches("suzhou", InValues(["Shanghai", "Suzhou"]))


# --- исполнение по IR на сценариях --------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def runs() -> dict[str, Any]:
    pipeline = ArchonityPipeline(
        skeleton_path=SKELETON_PATH,
        targets_root=TARGETS_ROOT,
        grounder="m1",
        m1_options={"embedder": "qwen3-4b", "llm": LLMClient(use_server=False)},
        executor="m4",
        m4_options=M4Options(judge="off"),
    )
    out: dict[str, Any] = {}
    for path in sorted(SCENARIOS.glob("S*.json")):
        sid = path.stem
        start = len(pipeline.m4.branch_log)
        methods, calls, remote, data = pipeline.run_scenario(load_json(path))
        out[sid] = SimpleNamespace(methods=methods, calls=calls, remote=remote, data=data,
                                   branches=pipeline.m4.branch_log[start:])
    return out


def decision(run: Any, step: int, method_part: str, branch: str) -> dict[str, Any]:
    hits = [b for b in run.branches if b["step"] == step and method_part in b["method"] and b["branch"] == branch]
    assert hits, f"нет решения {method_part} {branch} на шаге {step}"
    return hits[0]


def has_edge(edges: set[tuple[str, str]], src_part: str, dst_part: str) -> bool:
    return any(src_part in s and dst_part in d for s, d in edges)


def test_s0_matches_gold(runs: dict[str, Any]) -> None:
    gold = json.loads(GOLD_S0.read_text(encoding="utf-8"))["scenarios"]["S0"]
    r = runs["S0"]
    assert set(r.methods) == set(gold["methods"])
    assert r.calls == {tuple(e) for e in gold["calls"]}
    assert r.remote == {tuple(e) for e in gold["remote"]}
    assert r.data == {tuple(e) for e in gold["data"]}


def test_rebook_of_collected_order_exits_early(runs: dict[str, Any]) -> None:
    """S7.10: статус COLLECTED != PAID, rebook выходит на строке 55, до проверок со статусами enum."""
    r = runs["S7"]
    assert decision(r, 10, "RebookServiceImpl#rebook(", "b53")["arm"] == "then"
    assert not has_edge(r.calls, "RebookServiceImpl#rebook(", "OrderStatus#getCode")


def test_booking_dispatches_seat(runs: dict[str, Any]) -> None:
    """S7.4: бронирование распределяет место, даже если позже в сценарии пересадку отклонят."""
    assert has_edge(runs["S7"].remote, "PreserveServiceImpl#dipatchSeat", "SeatController#create")


def test_regular_train_goes_to_order_other(runs: dict[str, Any]) -> None:
    """S2.2: поиск обычных поездов, номер рейса известен из trip2 — проданные билеты в ts-order-other-service."""
    r = runs["S2"]
    d = decision(r, 2, "SeatServiceImpl#getLeftTicketOfInterval", "b138")
    assert d["arm"] == "else" and d["source_type"] in ("IR_BRANCH", "STATE")
    assert has_edge(r.remote, "SeatServiceImpl#getLeftTicketOfInterval", "OrderOtherController#getTicketListByDateAndTripId")


def test_trip_id_to_string_runs_by_runtime_type(runs: dict[str, Any]) -> None:
    assert has_edge(runs["S1"].calls, "TravelServiceImpl#getTicketsByBatch", "TripId#toString")


def test_travel_plan_walks_cheapest_plan(runs: dict[str, Any]) -> None:
    """S5.2: план route-plan непуст (список собран add'ами) — по каждому варианту остатки мест и тип поезда."""
    r = runs["S5"]
    assert decision(r, 2, "TravelPlanServiceImpl#getCheapest", "b96")["arm"] == "then"
    assert has_edge(r.calls, "TravelPlanServiceImpl#getCheapest", "TravelPlanServiceImpl#getRestTicketNumber")


def test_assurance_type_by_index(runs: dict[str, Any]) -> None:
    """S1.6: тип страховки 1 найден (аргументы константы из объявления enum), страховка создаётся."""
    r = runs["S1"]
    assert decision(r, 6, "AssuranceServiceImpl#create", "b59")["arm"] == "else"
    assert has_edge(r.calls, "AssuranceServiceImpl#create", "Assurance#<init>")


def test_consignee_change_keeps_weight(runs: dict[str, Any]) -> None:
    """S7.12: UI отправляет найденную запись багажа, вес тот же — цена не пересчитывается."""
    r = runs["S7"]
    assert decision(r, 12, "ConsignServiceImpl#updateConsignRecord", "b97")["arm"] == "else"
    assert not has_edge(r.remote, "ConsignServiceImpl#updateConsignRecord", "ConsignPriceController")


def test_admin_trip_is_found(runs: dict[str, Any]) -> None:
    """S6.9: рейс G9101, созданный на шаге 6, есть в состоянии (строка trip с type и number)."""
    assert decision(runs["S6"], 9, "TravelServiceImpl#getTripAllDetailInfo", "b300")["arm"] == "else"


def test_new_trip_has_no_sold_tickets(runs: dict[str, Any]) -> None:
    """S6.11: на новый рейс билетов ещё не продавали — распределение места без isContained."""
    assert decision(runs["S6"], 11, "OrderServiceImpl#getSoldTickets", "b57")["arm"] == "else"


def test_unknown_conditions_left_for_the_judge(runs: dict[str, Any]) -> None:
    """Без судьи неизвестными остаются только места, которые не решает код и состояние."""
    asked = {(b["method"].split("#")[0].rsplit(".", 1)[-1], b["line"])
             for r in runs.values() for b in r.branches if b["rule"] in ("OUTCOME", "LOOP")}
    assert len(asked) <= 10, sorted(asked)
    assert ("SeatServiceImpl", 122) in asked  # случайное место: Random.nextInt
    assert ("PreserveServiceImpl", 218) in asked  # имя получателя багажа: текст шага

