"""Unit and performance tests for Milestone M0 in-memory DB loader and DatabaseState."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from engine.adapters.db import DatabaseState, load_db_dump
from engine.adapters.skeleton import SkeletonIndex, load_json

ROOT = Path(__file__).resolve().parent.parent
DUMP_PATH = ROOT / "hackaton" / "tt-challenge" / "context" / "db-after-warmup.sql.gz"
SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"


@pytest.fixture(scope="module")
def db_state() -> DatabaseState:
    assert DUMP_PATH.is_file(), f"Warmup dump missing at {DUMP_PATH}"
    return load_db_dump(DUMP_PATH)


@pytest.fixture(scope="module")
def skeleton_dict() -> dict[str, Any]:
    assert SKELETON_PATH.is_file(), f"Skeleton missing at {SKELETON_PATH}"
    return load_json(SKELETON_PATH)


class TestDatabaseDumpLoader:
    """R1: Загрузка и производительность дампа БД."""

    def test_load_latency_under_50ms(self) -> None:
        """Проверка требования: загрузка < 1.0s (целевой бенчмарк < 50ms)."""
        latencies = []
        for _ in range(5):
            t0 = time.perf_counter()
            _ = load_db_dump(DUMP_PATH)
            latencies.append((time.perf_counter() - t0) * 1000)

        min_lat = min(latencies)
        avg_lat = sum(latencies) / len(latencies)
        assert min_lat < 50.0, f"Loading latency {min_lat:.2f} ms exceeds 50 ms target"
        assert avg_lat < 1000.0, f"Loading latency {avg_lat:.2f} ms exceeds 1.0s hard requirement"

    def test_table_and_row_counts(self, db_state: DatabaseState) -> None:
        """Проверка структуры дампа: 32 таблицы, 242 строки, 4 пустые таблицы."""
        all_tables = db_state.table_names()
        assert len(all_tables) == 32, f"Expected 32 created tables, got {len(all_tables)}"

        total_rows = sum(len(db_state.get_table(t)) for t in all_tables)
        assert total_rows == 242, f"Expected 242 total rows across all tables, got {total_rows}"

        # 4 таблицы без строк в warmup дампе
        empty_tables = [t for t in all_tables if len(db_state.get_table(t)) == 0]
        assert set(empty_tables) == {
            "food_delivery_order",
            "food_delivery_order_food_list",
            "notify_info",
            "money",
        }

    def test_latin1_and_binary_encoding_safety(self, db_state: DatabaseState) -> None:
        """Проверка устойчивости к байтам latin1 (0xd5) и бинарным литералам _binary."""
        delivery_rows = db_state.get_table("delivery")
        assert len(delivery_rows) == 4
        assert delivery_rows[0]["food_name"] == "HotPot"
        assert "order_id" in delivery_rows[0]

    def test_missing_table_resilience(self, db_state: DatabaseState) -> None:
        """Проверка отсутствующей таблицы wait_list_order."""
        assert db_state.get_table("wait_list_order") == []
        assert db_state.get_table("ts_wait_order.wait_list_order") == []
        assert db_state.get_table("res:table:ts-wait-order-service.wait_list_order") == []
        assert db_state.query("wait_list_order", status=1) == []
        assert db_state.find_one("wait_list_order", id="none") is None

    def test_column_names(self, db_state: DatabaseState) -> None:
        """Проверка имен столбцов и их соответствия полям записей."""
        cols = db_state.get_columns("orders")
        assert "id" in cols
        assert "account_id" in cols
        assert "status" in cols

        rows = db_state.get_table("orders")
        assert list(rows[0].keys()) == cols

    def test_file_not_found(self) -> None:
        """Проверка генерации исключения при отсутствии файла дампа."""
        with pytest.raises(FileNotFoundError):
            load_db_dump("non_existent_path.sql.gz")


class TestDatabaseQueries:
    """Проверка точности запросов к ключевым таблицам (auth_user, inside_money, orders, contacts)."""

    def test_query_auth_user(self, db_state: DatabaseState) -> None:
        """Проверка таблицы auth_user: пользователь fdse_microservice и admin."""
        users = db_state.get_table("auth_user")
        assert len(users) == 4

        fdse = db_state.find_one("auth_user", user_name="fdse_microservice")
        assert fdse is not None
        assert fdse["user_id"] == "4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f"

        admin = db_state.find_one("auth_user", user_name="admin")
        assert admin is not None
        assert admin["user_id"] == "06cfd7e8-6b58-4b8b-b548-80a60e891f3f"

    def test_query_inside_money_balance(self, db_state: DatabaseState) -> None:
        """Проверка баланса: у fdse_microservice начальный депозит 10 000."""
        money_rows = db_state.get_table("inside_money")
        assert len(money_rows) == 7

        fdse_deposit = db_state.find_one(
            "inside_money",
            user_id="4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f",
            type="A",
        )
        assert fdse_deposit is not None
        assert fdse_deposit["money"] == "10000"

    def test_query_orders_and_statuses(self, db_state: DatabaseState) -> None:
        """Проверка заказов и статусов (NOTPAID=0, PAID=1)."""
        orders = db_state.get_table("orders")
        assert len(orders) == 10

        user_orders = db_state.query(
            "orders",
            account_id="4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f",
        )
        assert len(user_orders) == 9

        paid_orders = db_state.query(
            "orders",
            account_id="4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f",
            status=1,
        )
        assert len(paid_orders) >= 1
        assert any(o["train_number"] == "G9998" for o in paid_orders)

        notpaid_orders = db_state.query(
            "orders",
            account_id="4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f",
            status=0,
        )
        assert len(notpaid_orders) >= 1
        assert any(o["train_number"] == "G1234" for o in notpaid_orders)

    def test_query_contacts(self, db_state: DatabaseState) -> None:
        """Проверка контактов пользователя fdse_microservice."""
        contacts = db_state.get_table("contacts")
        assert len(contacts) == 5

        c1 = db_state.find_one("contacts", name="Contacts_One")
        assert c1 is not None
        assert c1["account_id"] == "4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f"
        assert c1["document_number"] == "DocumentNumber_One"

        c2 = db_state.find_one("contacts", name="Contacts_Two")
        assert c2 is not None
        assert c2["phone_number"] == "ContactsPhoneNum_Two"

    def test_query_callable_predicates(self, db_state: DatabaseState) -> None:
        """Проверка запросов с использованием функций-предикатов."""
        filtered = db_state.query("orders", status=lambda s: s in (0, 1))
        assert len(filtered) == 6

        all_valid = db_state.query("orders", status=lambda s: s >= 0)
        assert len(all_valid) == 10

        active_money = db_state.query("inside_money", money=lambda m: float(m) >= 5000)
        assert len(active_money) >= 1

    def test_query_empty_filter_and_find_one_none(self, db_state: DatabaseState) -> None:
        """Проверка возврата всех строк при пустом фильтре и None при отсутствии совпадений."""
        all_routes = db_state.query("route")
        assert len(all_routes) == 10

        missing = db_state.find_one("route", id="non_existent_route_id")
        assert missing is None

    def test_table_collection_syntax(self, db_state: DatabaseState) -> None:
        """Проверка доступа через коллекцию db_state.tables."""
        assert len(db_state.tables["orders"]) == 10
        assert len(db_state.tables["ts_order.orders"]) == 10
        assert len(db_state.tables["res:table:ts-order-service.orders"]) == 10
        assert "orders" in db_state.tables
        assert "ts_order.orders" in db_state.tables
        assert db_state.tables.get("wait_list_order", []) == []


class TestDatabaseIsolationFork:
    """R2: Изоляция состояния через fork() для независимых прогонов сценариев."""

    def test_fork_latency_under_100us(self, db_state: DatabaseState) -> None:
        """fork() должен выполняться мгновенно (< 100 микросекунд)."""
        latencies_us = []
        for _ in range(500):
            t0 = time.perf_counter()
            _ = db_state.fork()
            latencies_us.append((time.perf_counter() - t0) * 1_000_000)

        avg_us = sum(latencies_us) / len(latencies_us)
        assert avg_us < 100.0, f"fork() avg latency {avg_us:.2f} us exceeds 100 us target"

    def test_fork_deep_copy_isolation(self, db_state: DatabaseState) -> None:
        """Мутации в форке не влияют на исходный экземпляр."""
        fork1 = db_state.fork()
        fork2 = db_state.fork()

        orig_len = len(db_state.get_table("orders"))
        assert orig_len == 10

        # Вставка новой записи в fork1
        new_order = {
            "id": "scenario-test-order-001",
            "account_id": "4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f",
            "status": 0,
            "train_number": "G9999",
        }
        fork1.insert("orders", new_order)
        assert len(fork1.get_table("orders")) == orig_len + 1
        assert len(db_state.get_table("orders")) == orig_len
        assert len(fork2.get_table("orders")) == orig_len

        # Модификация существующей строки в fork2
        target_id = "1afc5f4a-4108-4511-9260-922436aebd1a"
        row_f2 = fork2.find_one("orders", id=target_id)
        assert row_f2 is not None
        row_f2["status"] = 999  # Изменяем напрямую

        orig_row = db_state.find_one("orders", id=target_id)
        assert orig_row is not None
        assert orig_row["status"] == 1, "Исходная строка была мутирована через форк!"

        row_f1 = fork1.find_one("orders", id=target_id)
        assert row_f1 is not None
        assert row_f1["status"] == 1, "Форк 1 был мутирован через Форк 2!"

    def test_update_and_insert(self, db_state: DatabaseState) -> None:
        """Проверка методов update и insert."""
        forked = db_state.fork()
        updated_count = forked.update(
            "orders",
            {"status": 2},
            account_id="4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f",
            status=1,
        )
        assert updated_count >= 1

        # Проверяем, что обновилось в forked, но не в оригинале
        forked_paid = forked.query("orders", status=1)
        orig_paid = db_state.query("orders", status=1)
        assert len(forked_paid) < len(orig_paid)


class TestSkeletonIndexDbIntegration:
    """Интеграция SkeletonIndex с DatabaseState и разрешение узлов таблиц."""

    def test_all_33_skeleton_table_nodes_mapped(
        self,
        skeleton_dict: dict[str, Any],
        db_state: DatabaseState,
    ) -> None:
        """Проверка маппинга всех 33 узлов res:table:* скелета на базу данных."""
        table_nodes = [nid for nid in skeleton_dict["nodes"] if nid.startswith("res:table:")]
        assert len(table_nodes) == 33, f"Expected 33 table nodes, got {len(table_nodes)}"

        for nid in table_nodes:
            bare_table = nid.split(".")[-1]
            rows_by_node = db_state.get_table(nid)
            rows_by_bare = db_state.get_table(bare_table)
            assert rows_by_node == rows_by_bare, f"Mismatch for {nid} vs {bare_table}"

    def test_skeleton_resolution_logic(self, skeleton_dict: dict[str, Any]) -> None:
        """Имя таблицы дампа по узлу скелета — часть после точки, без соглашений об именах сервисов."""
        index = SkeletonIndex(skeleton_dict, db_dump_path=DUMP_PATH)

        assert index.table_resource_to_db("res:table:ts-order-service.orders") == "orders"
        assert index.table_resource_to_db("res:table:ts-consign-mysql.consign_record") == "consign_record"
    def test_skeleton_index_auto_discovery(self, skeleton_dict: dict[str, Any]) -> None:
        """Дамп ищется рядом со скелетом, переданным путём (`<пакет>/context`); словарь без дампа — пустой мир БД."""
        index = SkeletonIndex(SKELETON_PATH)
        assert len(index.db_state.table_names()) == 32
        assert len(index.get_table_records("res:table:ts-order-service.orders")) == 10
        assert SkeletonIndex(skeleton_dict).db_state.table_names() == []

    def test_skeleton_path_input(self) -> None:
        """Проверка передачи пути к файлу вместо словаря в SkeletonIndex."""
        index = SkeletonIndex(SKELETON_PATH)
        assert index.project == "trainticket"
        assert len(index.table_nodes) == 33
        assert len(index.get_table_records("orders")) == 10

    def test_skeleton_explicit_db_state(
        self,
        skeleton_dict: dict[str, Any],
        db_state: DatabaseState,
    ) -> None:
        """Проверка передачи явного db_state."""
        index = SkeletonIndex(skeleton_dict, db_state=db_state)
        assert index.db_state is db_state

    def test_skeleton_missing_table_resilience(self, skeleton_dict: dict[str, Any]) -> None:
        """Проверка устойчивости к отсутствующей таблице ts-wait-order-service.wait_list_order."""
        index = SkeletonIndex(skeleton_dict, db_dump_path=DUMP_PATH)
        missing_nid = "res:table:ts-wait-order-service.wait_list_order"
        rows = index.get_table_records(missing_nid)
        assert rows == []

    def test_skeleton_fallback_graceful(self, skeleton_dict: dict[str, Any]) -> None:
        """Проверка корректного fallback при некорректном пути к дампу."""
        index = SkeletonIndex(skeleton_dict, db_dump_path="invalid_path_to_dump.sql.gz")
        assert isinstance(index.db_state, DatabaseState)
