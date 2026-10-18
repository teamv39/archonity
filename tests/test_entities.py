"""Тесты правила R7 по фактам archparse: конструкторы сущностей при загрузке строк Hibernate."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.adapters.db import load_db_dump
from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.entities import EntityFacts, RepositoryCall, hydration
from engine.graph.builder import GraphBuilder
from engine.pipeline import ArchonityPipeline
from engine.rules import RuntimeRules
from engine.state import ScenarioState, TrainType

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

    def test_constructor_ir_merged_into_pool(self, index: SkeletonIndex) -> None:
        assert index.pool_ir.has_method("method:ts-common:edu.fudan.common.entity.Order#<init>()")
        assert len(index.pool_ir.enum_calls_by_method[ORDER_OTHER_CTOR]) == 2


class TestHydrationDecision:
    def _state(self, index: SkeletonIndex) -> ScenarioState:
        return ScenarioState.create_initial(db_state=index.db_state.fork())

    def test_read_with_rows(self, index: SkeletonIndex) -> None:
        call = _calls(index, "RouteServiceImpl#getRouteById", "findById")[0]
        h = hydration(call, self._state(index), index.table_resource_to_db)
        assert h.ctors == (ROUTE_CTOR,)
        assert h.rule.startswith("R7:read(")

    def test_read_expecting_empty_result(self, index: SkeletonIndex) -> None:
        call = _calls(index, "AssuranceServiceImpl#create", "findByOrderId")[0]
        assert call.expects == "EMPTY"
        h = hydration(call, self._state(index), index.table_resource_to_db)
        assert h.ctors == ()
        assert h.rule.startswith("R7:read_expects_empty")

    def test_save_merge_and_persist(self, index: SkeletonIndex) -> None:
        merge = _calls(index, "AssuranceServiceImpl#create", "save")[0]
        assert hydration(merge, self._state(index), index.table_resource_to_db).ctors
        persist = [c for c in _calls(index, "InsidePaymentServiceImpl#pay", "save") if c.id_assigned is False]
        assert persist
        assert hydration(persist[0], self._state(index), index.table_resource_to_db).ctors == ()

    def test_user_rows_filtered_by_account(self, index: SkeletonIndex) -> None:
        call = _calls(index, "OrderOtherServiceImpl#queryOrders", "findByAccountId")[0]
        state = self._state(index)
        assert hydration(call, state, index.table_resource_to_db).ctors == (ORDER_OTHER_CTOR,)
        state.account_id = "new-user-without-orders"
        h = hydration(call, state, index.table_resource_to_db)
        assert h.ctors == ()
        assert "0 rows of user in state" in h.rule

    def test_new_user_without_dump_uses_state(self, index: SkeletonIndex) -> None:
        call = _calls(index, "OrderOtherServiceImpl#queryOrders", "findByAccountId")[0]
        state = ScenarioState.create_initial()
        assert hydration(call, state, index.table_resource_to_db).ctors == (ORDER_OTHER_CTOR,)
        state.orders.append({"train_type": TrainType.GaoTie, "status": 0, "price": 1.0})
        assert hydration(call, state, index.table_resource_to_db, is_new_user=True).ctors == ()

    def test_missing_artifact_disables_rule(self) -> None:
        facts = EntityFacts.load(ROOT / "data" / "no_such_entity_ir.json")
        assert facts.calls_by_method == {}


class TestTraversal:
    def test_hydrated_constructor_executes_without_calls_edge(self, index: SkeletonIndex) -> None:
        builder = GraphBuilder(index, RuntimeRules(entity_constructors_on_load="body"))
        entry = ["method:ts-route-service:route.controller.RouteController#queryById(java.lang.String,org.springframework.http.HttpHeaders)"]
        state = ScenarioState.create_initial(db_state=index.db_state.fork())
        methods, calls, _, data = builder.traverse(entry, scenario_state=state)
        assert ROUTE_CTOR in methods
        assert not any(t == ROUTE_CTOR for _, t in calls)

    def test_s0_order_constructors_from_general_rule(self) -> None:
        pipeline = ArchonityPipeline(skeleton_path=SKELETON_PATH, targets_root=TARGETS_ROOT)
        methods, calls, _, _ = pipeline.run_scenario(load_json(SCENARIOS / "S0.json"))
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
    """Режимы RuntimeRules.entity_constructors_on_load для абляции на платформе."""

    def test_project_calls_mode_keeps_only_order(self, index: SkeletonIndex) -> None:
        allowed = index.entities.allowed_ctors("project_calls")
        assert ORDER_OTHER_CTOR in allowed
        assert ROUTE_CTOR not in allowed  # только UUID.randomUUID(): библиотека, не проект
        route = _calls(index, "RouteServiceImpl#getRouteById", "findById")[0]
        state = ScenarioState.create_initial(db_state=index.db_state.fork())
        h = hydration(route, state, index.table_resource_to_db, allowed=allowed)
        assert h.ctors == ()
        assert h.rule == "R7:mode_excludes_ctor"

    @pytest.mark.parametrize("mode,route_expected", [("body", True), ("project_calls", False), ("off", False)])
    def test_traversal_respects_mode(self, index: SkeletonIndex, mode: str, route_expected: bool) -> None:
        builder = GraphBuilder(index, RuntimeRules(entity_constructors_on_load=mode))
        entry = ["method:ts-route-service:route.controller.RouteController#queryById(java.lang.String,org.springframework.http.HttpHeaders)"]
        state = ScenarioState.create_initial(db_state=index.db_state.fork())
        methods, _, _, _ = builder.traverse(entry, scenario_state=state)
        assert (ROUTE_CTOR in methods) == route_expected

    def test_unknown_mode_rejected(self) -> None:
        with pytest.raises(ValueError):
            RuntimeRules(entity_constructors_on_load="maybe")


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

    @pytest.mark.parametrize("mode,expected", [("loaded", False), ("all", True)])
    def test_traversal_respects_mode(self, index: SkeletonIndex, mode: str, expected: bool) -> None:
        builder = GraphBuilder(index, RuntimeRules(collection_tables_on_read=mode))
        entry = ["method:ts-route-service:route.controller.RouteController#queryById(java.lang.String,org.springframework.http.HttpHeaders)"]
        state = ScenarioState.create_initial(db_state=index.db_state.fork())
        _, _, _, data = builder.traverse(entry, scenario_state=state)
        assert (ROUTE_BY_ID, "res:table:ts-route-service.route") in data
        assert ((ROUTE_BY_ID, ROUTE_STATIONS) in data) == expected

    def test_s0_user_roles_kept_on_get_token(self) -> None:
        """getToken передаёт пользователя в createToken, тот кладёт роли в токен: коллекция грузится на стеке."""
        pipeline = ArchonityPipeline(skeleton_path=SKELETON_PATH, targets_root=TARGETS_ROOT)
        _, _, _, data = pipeline.run_scenario(load_json(SCENARIOS / "S0.json"))
        roles = {s for s, t in data if t == "res:table:ts-auth-service.user_roles"}
        assert len(roles) == 1 and "TokenServiceImpl#getToken" in next(iter(roles))

    def test_unknown_mode_rejected(self) -> None:
        with pytest.raises(ValueError):
            RuntimeRules(collection_tables_on_read="maybe")


ORDER_EQUALS = "method:ts-order-service:order.entity.Order#equals(java.lang.Object)"
ORDER_CREATE_ENTRY = "method:ts-order-service:order.controller.OrderController#createNewOrder(order.entity.Order,org.springframework.http.HttpHeaders)"


class TestElementCallbacks:
    """Блок 8: list.contains(x) на результате чтения вызывает рукописный x.equals(элемент)."""

    def test_fact_bound_to_create(self, index: SkeletonIndex) -> None:
        call = _calls(index, "OrderServiceImpl#create(", "findByAccountId")[0]
        assert call.element_callbacks == ((ORDER_EQUALS, "contains"),)

    @pytest.mark.parametrize("mode,has_rows,expected", [("on", True, True), ("on", False, False), ("off", True, False)])
    def test_equals_executes_only_when_rows(self, index: SkeletonIndex, mode: str, has_rows: bool, expected: bool) -> None:
        if ORDER_CREATE_ENTRY not in index.N:
            pytest.skip("нет обработчика создания заказа в скелете")
        builder = GraphBuilder(index, RuntimeRules(element_callbacks=mode))
        state = ScenarioState.create_initial(db_state=index.db_state.fork())
        if not has_rows:
            state.account_id = "new-user-without-orders"
        methods, calls, _, _ = builder.traverse([ORDER_CREATE_ENTRY], scenario_state=state)
        assert (ORDER_EQUALS in methods) == expected
        assert not any(t == ORDER_EQUALS for _, t in calls)

    def test_unknown_mode_rejected(self) -> None:
        with pytest.raises(ValueError):
            RuntimeRules(element_callbacks="maybe")

    def test_owner_columns_and_state_rows_generality(self) -> None:
        from engine.entities import OWNER_COLUMNS, _state_rows
        assert "account_id" in OWNER_COLUMNS
        assert "user_id" in OWNER_COLUMNS
        assert "owner_id" in OWNER_COLUMNS
        assert "customer_id" in OWNER_COLUMNS

        class DummyState:
            pass

        assert _state_rows("orders", DummyState(), account=None) == []
        assert _state_rows("other_table", DummyState(), account=None) == []
