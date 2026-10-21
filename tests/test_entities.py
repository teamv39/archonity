"""Тесты правила R7 по фактам archparse: конструкторы сущностей при загрузке строк Hibernate."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.adapters.db import load_db_dump
from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.entities import EntityFacts, RepositoryCall
from engine.pipeline import ArchonityPipeline
from engine.rules import RuntimeRules

ROOT = Path(__file__).resolve().parent.parent
SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"
TARGETS_ROOT = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"
DB_DUMP = ROOT / "hackaton" / "tt-challenge" / "context" / "db-after-warmup.sql.gz"
SCENARIOS = ROOT / "hackaton" / "tt-challenge" / "scenarios"

ROUTE_CTOR = "method:ts-route-service:route.entity.Route#<init>()"
CONTACTS_CTOR = "method:ts-contacts-service:contacts.entity.Contacts#<init>()"
ORDER_OTHER_CTOR = "method:ts-order-other-service:other.entity.Order#<init>()"


@pytest.fixture(scope="module")
def index() -> SkeletonIndex:
    return SkeletonIndex(load_json(SKELETON_PATH), db_dump_path=DB_DUMP)


def _calls(index: SkeletonIndex, method_part: str, callee: str) -> list[RepositoryCall]:
    return [
        c for m, cs in index.entities.calls_by_method.items() if method_part in m
        for c in cs if c.callee == callee
    ]


class TestEntityFactsBinding:
    def test_every_repository_call_bound_to_skeleton(self, index: SkeletonIndex) -> None:
        bound = sum(len(cs) for cs in index.entities.calls_by_method.values())
        assert bound == len(index.entities.raw_calls) > 0
        for cs in index.entities.calls_by_method.values():
            for c in cs:
                assert c.tables, f"{c.method}@{c.line}: нет таблиц data_access"
        # Обратная сторона: каждый call_site с data_access покрыт вызовом репозитория
        covered = {(c.method, c.line, c.col) for cs in index.entities.calls_by_method.values() for c in cs}
        data_sites = {
            (index.N[e["source"]]["method"], index.N[e["source"]]["line"], index.N[e["source"]]["col"])
            for e in index.sk["edges"] if e["type"] == "data_access"
        }
        assert data_sites <= covered

    def test_constructors_only_with_statements(self, index: SkeletonIndex) -> None:
        route = _calls(index, "RouteServiceImpl#getRouteById", "findById")[0]
        assert route.ctors == (ROUTE_CTOR,)
        assert route.main_table == "res:table:ts-route-service.route"
        # Пустой конструктор Contacts не исполняется (эталон S0)
        contacts = _calls(index, "ContactsServiceImpl#findContactsByAccountId", "findByAccountId")[0]
        assert contacts.ctors == ()

    def test_read_expecting_empty_result(self, index: SkeletonIndex) -> None:
        assert _calls(index, "AssuranceServiceImpl#create", "findByOrderId")[0].expects == "EMPTY"

    def test_missing_artifact_disables_rule(self) -> None:
        facts = EntityFacts.load(ROOT / "data" / "no_such_entity_ir.json")
        assert facts.calls_by_method == {}


class TestS0:
    def test_s0_order_constructors_from_general_rule(self, shared_pipeline: ArchonityPipeline) -> None:
        methods, calls, _, _ = shared_pipeline.run_scenario(load_json(SCENARIOS / "S0.json"))
        assert ORDER_OTHER_CTOR in methods
        assert CONTACTS_CTOR not in methods
        order_callees = {t for s, t in calls if s == ORDER_OTHER_CTOR}
        assert order_callees == {
            "method:ts-common:edu.fudan.common.entity.OrderStatus#getCode()",
            "method:ts-common:edu.fudan.common.entity.SeatClass#getCode()",
            "method:ts-common:edu.fudan.common.util.StringUtils#Date2String(java.util.Date)",
        }


def test_db_dump_has_reference_rows() -> None:
    db = load_db_dump(DB_DUMP)
    assert db.get_table("route") and db.get_columns("inside_money")


class TestAblationModes:
    """Режимы RuntimeRules.constructors при загрузке Hibernate (ADR-006); отбор в ответ — tests/test_projection.py."""

    def test_all_mode_keeps_only_order(self, index: SkeletonIndex) -> None:
        allowed = index.entities.allowed_ctors("all")
        assert ORDER_OTHER_CTOR in allowed
        assert ROUTE_CTOR not in allowed  # только UUID.randomUUID(): библиотека, не проект

    @pytest.mark.parametrize("mode", ["maybe", "body", "project_calls"])
    def test_unknown_mode_rejected(self, mode: str) -> None:
        with pytest.raises(ValueError):
            RuntimeRules(constructors=mode)


ROUTE_STATIONS = "res:table:ts-route-service.route_stations"
ROUTE_DISTANCES = "res:table:ts-route-service.route_distances"
ROUTE_BY_ID = "method:ts-route-service:route.service.RouteServiceImpl#getRouteById(java.lang.String,org.springframework.http.HttpHeaders)"
ROUTE_BY_START_END = (
    "method:ts-route-service:route.service.RouteServiceImpl#getRouteByStartAndEnd("
    "java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)"
)


class TestLazyCollections:
    """R10: таблица ленивой коллекции при чтении — только если метод загрузил коллекцию сам."""

    def test_returned_entity_does_not_load_collections(self, index: SkeletonIndex) -> None:
        loaded, rule = index.entities.collection_table_loaded(ROUTE_BY_ID, ROUTE_STATIONS)
        assert not loaded
        assert rule.startswith("R10:lazy_not_loaded")

    def test_accessed_collection_loaded(self, index: SkeletonIndex) -> None:
        assert index.entities.collection_table_loaded(ROUTE_BY_START_END, ROUTE_STATIONS)[0]
        assert not index.entities.collection_table_loaded(ROUTE_BY_START_END, ROUTE_DISTANCES)[0]

    def test_main_table_and_eager_collection_not_decided(self, index: SkeletonIndex) -> None:
        assert index.entities.collection_table_loaded(ROUTE_BY_ID, "res:table:ts-route-service.route") is None
        store = next(m for m in index.entities.calls_by_method if "StationFoodServiceImpl#getFoodStoresByStationNames" in m)
        assert index.entities.collection_table_loaded(store, "res:table:ts-station-food-service.station_food_list") is None

    def test_save_writes_collection(self, index: SkeletonIndex) -> None:
        create = next(m for m in index.entities.calls_by_method if "RouteServiceImpl#createAndModify" in m)
        loaded, rule = index.entities.collection_table_loaded(create, ROUTE_STATIONS)
        assert loaded and "save_writes_collection" in rule

    def test_s0_user_roles_kept_on_get_token(self, shared_pipeline: ArchonityPipeline) -> None:
        """getToken передаёт пользователя в createToken, тот кладёт роли в токен: коллекция грузится на стеке."""
        _, _, _, data = shared_pipeline.run_scenario(load_json(SCENARIOS / "S0.json"))
        roles = {s for s, t in data if t == "res:table:ts-auth-service.user_roles"}
        assert len(roles) == 1 and "TokenServiceImpl#getToken" in next(iter(roles))

    def test_unknown_mode_rejected(self) -> None:
        with pytest.raises(ValueError):
            RuntimeRules(collection_tables_on_read="maybe")


ORDER_EQUALS = "method:ts-order-service:order.entity.Order#equals(java.lang.Object)"


class TestElementCallbacks:
    """Блок 8: list.contains(x) на результате чтения вызывает рукописный x.equals(элемент)."""

    def test_fact_bound_to_create(self, index: SkeletonIndex) -> None:
        call = _calls(index, "OrderServiceImpl#create(", "findByAccountId")[0]
        assert call.element_callbacks == ((ORDER_EQUALS, "contains"),)

    def test_unknown_mode_rejected(self) -> None:
        with pytest.raises(ValueError):
            RuntimeRules(element_callbacks="maybe")
