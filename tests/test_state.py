"""Comprehensive unit and integration test suite for Milestone M3 (Scenario State Model & Mutations).

Covers:
1. Initial Scenario State (7 tests)
2. Order Lifecycle & Mutations (8 tests)
3. Scenario Isolation & Fork Performance (4 tests)
4. S4 New User Registration (5 tests)
5. S6 Admin Entity Creation (6 tests)
6. S7 Refusal Conditions (4 tests)
7. Pipeline & GraphBuilder Integration (4 tests)
Total: 38 tests.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from engine.adapters.db import DatabaseState, load_db_dump
from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.graph.builder import GraphBuilder
from engine.pipeline import ArchonityPipeline
from engine.state import OrderStatus, ScenarioState, TrainType

ROOT = Path(__file__).resolve().parent.parent
DUMP_PATH = ROOT / "hackaton" / "tt-challenge" / "context" / "db-after-warmup.sql.gz"
SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"
TARGETS_ROOT = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"


@pytest.fixture(scope="module")
def db_state() -> DatabaseState:
    assert DUMP_PATH.is_file(), f"Warmup dump missing at {DUMP_PATH}"
    return load_db_dump(DUMP_PATH)


# =============================================================================
# 1. TestInitialScenarioState (7 tests)
# =============================================================================


class TestInitialScenarioState:
    """Verifies default values and initialization from DatabaseState."""

    def test_default_passenger_identity(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state)
        assert state.user_name == "fdse_microservice"
        assert state.account_id == "4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f"
        assert state.user_id == "4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f"

    def test_initial_balance(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state)
        assert state.get_balance() == 10000.0
        assert state.balance == 10000.0

    def test_initial_dates(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state)
        assert state.travel_date == "2026-10-01"
        assert state.system_date == "2026-09-15"
        assert state.travel_date_display == "01.10.2026"
        assert state.system_date_display == "15.09.2026"

    def test_initial_contacts_loaded_from_db(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state)
        user_contacts = state.get_contacts()
        assert len(user_contacts) >= 4
        all_contacts = state.get_contacts("all")
        assert len(all_contacts) >= 5

    def test_initial_orders_loaded_from_db(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state)
        orders = state.get_orders()
        assert len(orders) >= 16
        gt_orders = state.get_orders(train_type=TrainType.GaoTie)
        assert len(gt_orders) >= 9
        other_orders = state.get_orders(train_type=TrainType.Other)
        assert len(other_orders) >= 7

    def test_query_helpers_and_lookups(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state)
        paid = state.get_orders(status=OrderStatus.PAID)
        assert len(paid) >= 4
        for o in paid:
            assert o["status"] == OrderStatus.PAID
        assert state.has_active_orders() is True
        assert state.has_orders() is True
        first_order = state.orders[0]
        assert state.get_order_by_id(first_order["id"]) == first_order

    def test_create_initial_with_empty_or_none_db_state(self) -> None:
        state = ScenarioState.create_initial(None)
        assert state.user_name == "fdse_microservice"
        assert state.balance == 10000.0
        assert len(state.orders) == 0
        assert len(state.contacts) == 0
        assert state.travel_date == "2026-10-01"


# =============================================================================
# 2. TestOrderLifecycleAndMutations (8 tests)
# =============================================================================


class TestOrderLifecycleAndMutations:
    """Verifies transitions NOTPAID -> PAID -> COLLECTED -> USED/CANCEL."""

    def test_order_status_enum_specification(self) -> None:
        assert OrderStatus.NOTPAID == 0
        assert OrderStatus.PAID == 1
        assert OrderStatus.COLLECTED == 2
        assert OrderStatus.CHANGE == 3
        assert OrderStatus.CANCEL == 4
        assert OrderStatus.CANCELLED == 4
        assert OrderStatus.REFUND == 5
        assert OrderStatus.REFUNDS == 5
        assert OrderStatus.USED == 6
        assert OrderStatus.from_value("paid") == OrderStatus.PAID
        assert OrderStatus.from_value("CANCELLED") == OrderStatus.CANCEL
        assert OrderStatus.from_value(1) == OrderStatus.PAID

    def test_booking_order_mutation_notpaid(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        init_bal = state.balance
        res = state.apply_step({
            "step": 6,
            "action": "Book one first-class seat on high-speed train G1234",
            "params": {"price": "100.0"},
        })
        assert res.status == "SUCCESS"
        assert state.balance == init_bal
        new_order = state.get_order_by_id(res.affected_entities["order_id"])
        assert new_order is not None
        assert new_order["status"] == OrderStatus.NOTPAID
        assert new_order["train_type"] == TrainType.GaoTie

    def test_payment_mutation_with_balance_deduction(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        state.apply_step({
            "step": 6,
            "action": "Book one first-class seat on high-speed train G1234",
            "params": {"price": "100.0"},
        })
        bal_before = state.balance
        res = state.apply_step({
            "step": 10,
            "action": "Pay for the order from internal account balance",
        })
        assert res.status == "SUCCESS"
        assert state.balance == bal_before - 100.0
        paid_orders = state.get_orders(status=OrderStatus.PAID)
        assert any(o["id"] == res.affected_entities["order_id"] for o in paid_orders)

    def test_collection_mutation_status_collected(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        state.apply_step({"step": 6, "action": "Book one seat on train", "params": {"price": "100.0"}})
        state.apply_step({"step": 10, "action": "Pay for the order"})
        res = state.apply_step({"step": 11, "action": "Collect ticket for the order"})
        assert res.status == "SUCCESS"
        collected = state.get_orders(status=OrderStatus.COLLECTED)
        assert len(collected) >= 1

    def test_station_entry_mutation_status_used(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        state.apply_step({"step": 6, "action": "Book one seat on train", "params": {"price": "100.0"}})
        state.apply_step({"step": 10, "action": "Pay for the order"})
        state.apply_step({"step": 11, "action": "Collect ticket for the order"})
        res = state.apply_step({"step": 12, "action": "Enter station (board the train) with the order"})
        assert res.status == "SUCCESS"
        used = state.get_orders(status=OrderStatus.USED)
        assert len(used) >= 1

    def test_cancellation_mutation_with_balance_refund(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        state.apply_step({"step": 6, "action": "Book one seat on regular train K1235", "params": {"price": "120.0"}})
        state.apply_step({"step": 8, "action": "Pay for the order"})
        bal_after_pay = state.balance
        res = state.apply_step({"step": 10, "action": "Cancel the paid order"})
        assert res.status == "SUCCESS"
        assert state.balance > bal_after_pay

    def test_full_order_lifecycle_chain(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        r1 = state.apply_step({"step": 1, "action": "Book one seat", "params": {"price": "50.0"}})
        oid = r1.affected_entities["order_id"]
        order = state.get_order_by_id(oid)
        assert order is not None
        assert order["status"] == OrderStatus.NOTPAID
        state.apply_step({"step": 2, "action": "Pay for order"})
        assert order["status"] == OrderStatus.PAID
        state.apply_step({"step": 3, "action": "Collect ticket"})
        assert order["status"] == OrderStatus.COLLECTED
        state.apply_step({"step": 4, "action": "Enter the station and board train"})
        assert order["status"] == OrderStatus.USED

    def test_invalid_state_transitions(self) -> None:
        state = ScenarioState(orders=[])
        r_collect = state.apply_step({"step": 1, "action": "Collect ticket"})
        assert r_collect.status == "REFUSED"
        r_board = state.apply_step({"step": 2, "action": "Enter the station"})
        assert r_board.status == "REFUSED"


# =============================================================================
# 3. TestScenarioIsolation (4 tests)
# =============================================================================


class TestScenarioIsolation:
    """Verifies state fork latency and complete cross-scenario isolation."""

    def test_state_fork_latency_under_50us(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state)
        t0 = time.perf_counter()
        for _ in range(500):
            _ = state.fork()
        avg_us = (time.perf_counter() - t0) / 500 * 1_000_000
        assert avg_us < 50.0, f"Fork took {avg_us:.2f} µs (expected < 50 µs)"

    def test_scenario_isolation_s1_does_not_mutate_s0(self, db_state: DatabaseState) -> None:
        base = ScenarioState.create_initial(db_state)
        s1 = base.fork()
        s1.apply_step({"step": 6, "action": "Book seat", "params": {"price": "100.0"}})
        s1.apply_step({"step": 10, "action": "Pay for order"})
        s1.apply_step({"step": 11, "action": "Collect ticket"})
        s1.apply_step({"step": 12, "action": "Enter station"})
        assert len(s1.orders) == len(base.orders) + 1
        assert s1.balance < base.balance
        assert base.balance == 10000.0
        assert not any(o["status"] == OrderStatus.COLLECTED for o in base.orders)

    def test_scenario_isolation_s1_does_not_affect_s2(self, db_state: DatabaseState) -> None:
        base = ScenarioState.create_initial(db_state)
        s1 = base.fork()
        s1.apply_step({"step": 1, "action": "Book seat", "params": {"price": "100.0"}})
        s1.apply_step({"step": 2, "action": "Pay for order"})
        s2 = base.fork()
        assert s2.balance == 10000.0
        assert len(s2.orders) == len(base.orders)

    def test_underlying_db_state_isolation(self, db_state: DatabaseState) -> None:
        base = ScenarioState.create_initial(db_state)
        s1 = base.fork()
        s1.apply_step({"step": 1, "action": "Book high-speed train seat", "params": {"price": "99.0"}})
        assert len(s1.db_state.get_table("orders")) == len(base.db_state.get_table("orders")) + 1
        assert len(base.db_state.get_table("orders")) == len(db_state.get_table("orders"))


# =============================================================================
# 4. TestScenarioS4NewUserRegistration (5 tests)
# =============================================================================


class TestScenarioS4NewUserRegistration:
    """Verifies S4 registration, empty state, and external payment fallback."""

    def test_s4_registration_step_mutation(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        res = state.apply_step({"step": 1, "action": "Register a new passenger account (MRK-reg-430)"})
        assert res.status == "SUCCESS"
        assert state.user_name == "MRK-reg-430"
        assert state.is_new_user is True

    def test_s4_empty_initial_state_and_zero_balance(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        state.apply_step({"step": 1, "action": "Register a new passenger account"})
        assert state.balance == 0.0
        assert len(state.get_orders()) == 0
        assert len(state.get_contacts()) == 0

    def test_s4_add_contact_mutation(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        state.apply_step({"step": 1, "action": "Register a new passenger account"})
        state.apply_step({"step": 3, "action": "Add a contact (the passenger themselves) to the empty contact book"})
        assert len(state.get_contacts()) == 1

    def test_s4_external_payment_channel_without_negative_balance(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        state.apply_step({"step": 1, "action": "Register a new passenger account"})
        state.apply_step({"step": 7, "action": "Book first-class seat on trip G1234", "params": {"price": "100.0"}})
        state.apply_step({"step": 11, "action": "Pay for the order: internal balance is empty, so completed via external payment channel"})
        assert state.has_external_payment is True
        assert state.balance == 0.0
        orders = state.get_orders(status=OrderStatus.PAID)
        assert len(orders) == 1

    def test_s4_cancellation_refund_credited_to_internal_balance(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        state.apply_step({"step": 1, "action": "Register a new passenger account"})
        state.apply_step({"step": 7, "action": "Book first-class seat", "params": {"price": "100.0"}})
        state.apply_step({"step": 11, "action": "Pay for the order through external payment"})
        state.apply_step({"step": 13, "action": "Cancel the paid order (the refund goes back to the internal balance)"})
        assert state.balance > 0.0
        cancelled = state.get_orders(status=OrderStatus.CANCEL)
        assert len(cancelled) == 1


# =============================================================================
# 5. TestScenarioS6AdminEntityCreation (6 tests)
# =============================================================================


class TestScenarioS6AdminEntityCreation:
    """Verifies S6 administrator entity creation and booking."""

    def test_s6_add_station_mutation_ning_bo(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        res = state.apply_step({"step": 2, "action": "Add a new station Ning Bo with a stay time of 5 minutes"})
        assert res.status == "SUCCESS"
        assert state.has_custom_station("Ning Bo")

    def test_s6_add_train_type_gaotie_six(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        res = state.apply_step({"step": 3, "action": "Add a new train type GaoTieSix with 100 second-class and 30 first-class seats"})
        assert res.status == "SUCCESS"
        assert len(state.get_admin_entities("train_types")) == 1

    def test_s6_add_route_mutation(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        res = state.apply_step({"step": 4, "action": "Add a new route Shanghai — Suzhou — Ning Bo"})
        assert res.status == "SUCCESS"
        assert len(state.get_admin_entities("routes")) == 1

    def test_s6_add_price_config_mutation(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        res = state.apply_step({"step": 5, "action": "Add a price configuration for train type GaoTieSix"})
        assert res.status == "SUCCESS"
        assert len(state.get_admin_entities("price_configs")) == 1

    def test_s6_add_trip_mutation_g9101(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        res = state.apply_step({"step": 6, "action": "Add a new high-speed trip G9101 of type GaoTieSix"})
        assert res.status == "SUCCESS"
        assert len(state.get_admin_entities("trips")) == 1

    def test_s6_passenger_booking_on_new_admin_entities(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        state.apply_step({"step": 6, "action": "Add a new high-speed trip G9101"})
        state.apply_step({"step": 7, "action": "Log in as passenger"})
        res = state.apply_step({"step": 11, "action": "Book first-class seat on new trip G9101", "params": {"price": "150.0"}})
        assert res.status == "SUCCESS"
        state.apply_step({"step": 13, "action": "Pay for order from internal balance"})
        order = state.get_order_by_id(res.affected_entities["order_id"])
        assert order is not None
        assert order["train_number"] == "G9101"
        assert order["status"] == OrderStatus.PAID


# =============================================================================
# 6. TestScenarioS7RefusalConditions (4 tests)
# =============================================================================


class TestScenarioS7RefusalConditions:
    """Verifies S7 cancellation & rebooking refusals on collected tickets."""

    def test_s7_cancellation_refusal_on_collected_order(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        state.orders.clear()
        state.apply_step({"step": 4, "action": "Book first-class seat with 3 kg luggage", "params": {"price": "100.0"}})
        state.apply_step({"step": 6, "action": "Pay for order from internal balance"})
        state.apply_step({"step": 7, "action": "Collect ticket for the order"})
        order = state.orders[0]
        assert order["status"] == OrderStatus.COLLECTED
        res = state.apply_step({"step": 9, "action": "Try to cancel the collected order (the system refuses)"})
        assert res.status == "REFUSED"
        assert state.has_refused_cancel is True
        assert order["status"] == OrderStatus.COLLECTED

    def test_s7_rebooking_refusal_on_collected_order(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        state.orders.clear()
        state.apply_step({"step": 4, "action": "Book seat", "params": {"price": "100.0"}})
        state.apply_step({"step": 6, "action": "Pay for order"})
        state.apply_step({"step": 7, "action": "Collect ticket for order"})
        res = state.apply_step({"step": 10, "action": "Try to rebook the collected order (the system refuses)"})
        assert res.status == "REFUSED"
        assert state.has_refused_rebook is True
        assert state.orders[0]["status"] == OrderStatus.COLLECTED

    def test_s7_status_and_balance_unmodified_on_refusal(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        state.orders.clear()
        state.apply_step({"step": 4, "action": "Book seat", "params": {"price": "100.0"}})
        state.apply_step({"step": 6, "action": "Pay for order"})
        state.apply_step({"step": 7, "action": "Collect ticket for order"})
        bal_before = state.balance
        state.apply_step({"step": 9, "action": "Try to cancel the collected order"})
        state.apply_step({"step": 10, "action": "Try to rebook the collected order"})
        assert state.balance == bal_before
        assert state.orders[0]["status"] == OrderStatus.COLLECTED

    def test_s7_consignee_update_mutation(self, db_state: DatabaseState) -> None:
        state = ScenarioState.create_initial(db_state).fork()
        state.apply_step({"step": 4, "action": "Book seat with 3.0 kg luggage"})
        res = state.apply_step({
            "step": 12,
            "action": "Change the consignee's name and phone number in the consignment",
            "params": {"consignee": "Alice", "phone": "13912345678"},
        })
        assert res.status == "SUCCESS"
        consign = state.consignments[-1]
        assert consign["consignee"] == "Alice"
        assert consign["phone"] == "13912345678"
        assert consign["weight"] == 3.0


# =============================================================================
# 7. TestPipelineAndGraphBuilderIntegration (4 tests)
# =============================================================================


class TestPipelineAndGraphBuilderIntegration:
    """Verifies end-to-end integration with ArchonityPipeline and GraphBuilder."""

    def test_pipeline_run_scenario_with_state(self) -> None:
        pipeline = ArchonityPipeline(skeleton_path=SKELETON_PATH, targets_root=TARGETS_ROOT)
        s0_dict = load_json(ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S0.json")
        methods, calls, remote, data = pipeline.run_scenario(s0_dict)
        assert len(methods) == 34
        assert len(calls) == 24
        assert len(remote) == 0
        assert len(data) == 7

    def test_pipeline_run_all_scenario_isolation(self) -> None:
        pipeline = ArchonityPipeline(skeleton_path=SKELETON_PATH, targets_root=TARGETS_ROOT)
        s1_dict = load_json(ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S1.json")
        s0_dict = load_json(ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S0.json")
        _ = pipeline.run_scenario(s1_dict)
        m0, c0, r0, d0 = pipeline.run_scenario(s0_dict)
        assert len(m0) == 34
        assert len(c0) == 24
        assert len(r0) == 0
        assert len(d0) == 7

    def test_builder_traverse_with_and_without_state(self) -> None:
        index = SkeletonIndex(SKELETON_PATH)
        builder = GraphBuilder(index)
        entry = ["method:ts-user-service:user.controller.UserController#getToken(user.entity.UserDto)"]
        m1, c1, r1, d1 = builder.traverse(entry)
        state = ScenarioState.create_initial(index.db_state)
        m2, c2, r2, d2 = builder.traverse(entry, scenario_state=state)
        assert m1 == m2
        assert c1 == c2
        assert r1 == r2
        assert d1 == d2

    def test_empty_db_state_pipeline_regression(self) -> None:
        pipeline = ArchonityPipeline(skeleton_path=SKELETON_PATH, targets_root=TARGETS_ROOT)
        pipeline.index.db_state = DatabaseState()
        s0_dict = load_json(ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S0.json")
        methods, calls, remote, data = pipeline.run_scenario(s0_dict)
        assert len(methods) == 34
        assert len(calls) == 24
        assert len(remote) == 0
        assert len(data) == 7


# =============================================================================
# 8. TestStepArtifactsAndRefsResolution (10 tests)
# =============================================================================


class TestStepArtifactsAndRefsResolution:
    """Verifies ADR-005 refs resolution and step artifacts recording (Milestone M3)."""

    def test_record_and_get_step_artifacts(self) -> None:
        state = ScenarioState()
        ent = {"id": "ord-1", "price": 100.0}
        rec = state.record_step_entity(4, "order", ent)
        assert rec["created_at_step"] == 4
        artifacts_step4 = state.get_step_artifacts(4)
        assert "order" in artifacts_step4
        assert artifacts_step4["order"][0]["id"] == "ord-1"

    def test_resolve_ref_order_new_and_first(self) -> None:
        state = ScenarioState()
        # Step 4: First order created
        state.apply_step({
            "step": 4,
            "action": "Book one seat on GaoTie train G1234",
            "params": {"price": "100.0", "orderId": "ord-step-4"},
        })
        # Step 6: Second order created
        state.apply_step({
            "step": 6,
            "action": "Book another seat on regular train K1235",
            "params": {"price": "120.0", "orderId": "ord-step-6"},
        })

        # Resolve refs
        o4 = state.resolve_ref("order", "new_of_step_4")
        assert o4 is not None
        assert o4["id"] == "ord-step-4"

        o6 = state.resolve_ref("order", "new_of_step_6")
        assert o6 is not None
        assert o6["id"] == "ord-step-6"

        # first_of_step_4
        o4_first = state.resolve_ref("order", "first_of_step_4")
        assert o4_first is not None
        assert o4_first["id"] == "ord-step-4"

    def test_resolve_ref_contact_first_and_second(self) -> None:
        state = ScenarioState()
        state.apply_step({
            "step": 3,
            "action": "Add new contact for passenger",
            "params": {"name": "Passenger_A", "id": "c-1"},
        })
        state.apply_step({
            "step": 3,
            "action": "Add another companion contact",
            "params": {"name": "Passenger_B", "id": "c-2"},
        })

        c1 = state.resolve_ref("contact", "first_of_step_3")
        assert c1 is not None
        assert c1["name"] == "Passenger_A"

        c2 = state.resolve_ref("contact", "second_of_step_3")
        assert c2 is not None
        assert c2["name"] == "Passenger_B"

        c_new = state.resolve_ref("contact", "new_of_step_3")
        assert c_new is not None
        assert c_new["name"] == "Passenger_B"

    def test_resolve_ref_trip_and_store_search(self) -> None:
        state = ScenarioState()
        # Step 2: Search train
        state.apply_step({
            "step": 2,
            "action": "Search high-speed trains from Shanghai to Beijing on 2026-10-01 (train G1234)",
            "params": {"tripId": "G1234"},
        })
        # Step 5: Query food store
        state.apply_step({
            "step": 5,
            "action": "Look at the food store in Shanghai",
        })

        tr = state.resolve_ref("trip", "first_of_step_2")
        assert tr is not None
        assert tr["id"] == "G1234"

        st = state.resolve_ref("store", "first_of_step_5")
        assert st is not None
        assert "shanghai" in st["id"]

    def test_resolve_ref_user_registration(self) -> None:
        state = ScenarioState()
        state.apply_step({
            "step": 1,
            "action": "Register a new passenger account MRK-reg-430",
            "params": {"username": "MRK-reg-430", "user_id": "u-430"},
        })
        u = state.resolve_ref("user", "new_of_step_1")
        assert u is not None
        assert u["user_id"] == "u-430"
        assert u["user_name"] == "MRK-reg-430"

    def test_resolve_ref_admin_entities(self) -> None:
        state = ScenarioState()
        state.apply_step({
            "step": 2,
            "action": "Admin add station Ning Bo",
            "params": {"name": "Ning Bo"},
        })
        state.apply_step({
            "step": 3,
            "action": "Admin add train GaoTieSix",
            "params": {"name": "GaoTieSix"},
        })
        state.apply_step({
            "step": 4,
            "action": "Admin add route route-sh-sz-nb",
            "params": {"id": "route-sh-sz-nb"},
        })
        state.apply_step({
            "step": 5,
            "action": "Admin add price price-gt6",
            "params": {"id": "price-gt6"},
        })
        state.apply_step({
            "step": 6,
            "action": "Admin add travel trip G9101",
            "params": {"trip_id": "G9101"},
        })

        assert state.resolve_ref("station", "new_of_step_2")["name"] == "Ning Bo"
        assert state.resolve_ref("train", "new_of_step_3")["name"] == "GaoTieSix"
        assert state.resolve_ref("route", "new_of_step_4")["id"] == "route-sh-sz-nb"
        assert state.resolve_ref("price", "new_of_step_5")["id"] == "price-gt6"
        assert state.resolve_ref("trip", "new_of_step_6")["id"] == "G9101"

    def test_resolve_step_refs_batch(self) -> None:
        state = ScenarioState()
        state.apply_step({
            "step": 2,
            "action": "Search high-speed train G1234",
            "params": {"tripId": "G1234"},
        })
        state.apply_step({
            "step": 4,
            "action": "Add contact Companion_One",
            "params": {"name": "Companion_One", "id": "c-comp"},
        })

        batch = state.resolve_step_refs({
            "trip": "first_of_step_2",
            "contact": "first_of_step_4",
        })
        assert "trip" in batch
        assert batch["trip"]["id"] == "G1234"
        assert "contact" in batch
        assert batch["contact"]["id"] == "c-comp"

    def test_resolve_ref_id_helper(self) -> None:
        state = ScenarioState()
        state.apply_step({
            "step": 4,
            "action": "Book seat",
            "params": {"orderId": "order-custom-xyz"},
        })
        assert state.resolve_ref_id("order", "new_of_step_4") == "order-custom-xyz"
        assert state.resolve_ref_id("order", "invalid_ref") is None
        assert state.resolve_ref_id("order", "") is None

    def test_refs_in_apply_step_payment_and_cancellation(self) -> None:
        state = ScenarioState()
        # Step 4: Book order without explicit orderId in payment step
        state.apply_step({
            "step": 4,
            "action": "Book seat on train G1234",
            "params": {"price": "150.0", "orderId": "ord-target-step4"},
        })
        # Step 5: Book second order
        state.apply_step({
            "step": 5,
            "action": "Book seat on train G1234",
            "params": {"price": "200.0", "orderId": "ord-other-step5"},
        })

        # Step 6: Pay specifically for order from step 4 using refs
        pay_res = state.apply_step({
            "step": 6,
            "action": "Pay for the order",
            "params": {},
            "refs": {"order": "new_of_step_4"},
        })
        assert pay_res.status == "SUCCESS"
        assert pay_res.affected_entities["order_id"] == "ord-target-step4"
        assert state.get_order_by_id("ord-target-step4")["status"] == OrderStatus.PAID
        assert state.get_order_by_id("ord-other-step5")["status"] == OrderStatus.NOTPAID

        # Step 7: Cancel order from step 4 using refs
        cancel_res = state.apply_step({
            "step": 7,
            "action": "Cancel the paid order",
            "params": {},
            "refs": {"order": "new_of_step_4"},
        })
        assert cancel_res.status == "SUCCESS"
        assert state.get_order_by_id("ord-target-step4")["status"] == OrderStatus.CANCEL

    def test_fork_preserves_step_artifacts_and_isolation(self) -> None:
        state = ScenarioState()
        state.apply_step({
            "step": 4,
            "action": "Book seat",
            "params": {"orderId": "ord-parent-4"},
        })

        forked = state.fork()
        assert forked.resolve_ref_id("order", "new_of_step_4") == "ord-parent-4"

        # Mutate forked state step 6
        forked.apply_step({
            "step": 6,
            "action": "Book seat",
            "params": {"orderId": "ord-fork-6"},
        })

        # Parent should not have step 6 artifact
        assert state.resolve_ref("order", "new_of_step_6") is None
        assert forked.resolve_ref_id("order", "new_of_step_6") == "ord-fork-6"
