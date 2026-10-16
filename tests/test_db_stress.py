"""Adversarial stress tests and edge-case challenge suite for Milestone M0.

Covers:
- Malformed SQL statements and tokenizer edge cases.
- Deep fork chains and concurrent multi-threaded mutation isolation.
- Query engine edge cases (non-existent columns, non-existent tables, partial matches).
- SkeletonIndex resolution across all 33 skeleton table nodes and malformed node IDs.
- Performance and throughput benchmarks under stress.
"""
from __future__ import annotations

import concurrent.futures
import gzip
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from engine.adapters.db import (
    DatabaseState,
    TableCollection,
    TableNodeResolution,
    _parse_sql_values,
    load_db_dump,
)
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


@pytest.fixture(scope="module")
def skeleton_index(skeleton_dict: dict[str, Any]) -> SkeletonIndex:
    return SkeletonIndex(skeleton_dict)


# ==============================================================================
# 1. Adversarial SQL Scanner Stress
# ==============================================================================

class TestAdversarialSQLScanner:
    """Stress-test _parse_sql_values against malformed, adversarial, and edge SQL."""

    def test_empty_and_whitespace(self) -> None:
        assert _parse_sql_values("") == []
        assert _parse_sql_values("   \t\r\n   ") == []
        assert _parse_sql_values("()") == [[]]
        assert _parse_sql_values("( )") == [[]]
        assert _parse_sql_values("(), ()") == [[], []]

    def test_unclosed_quote_resilience(self) -> None:
        """Unclosed quotes must terminate safely without hanging or raising IndexError.
        
        Because the closing quote is missing, the scanner consumes the remaining characters
        including the closing parenthesis, never encountering a valid tuple delimiter ')',
        and safely returns [] without crashing.
        """
        res = _parse_sql_values("(1, 'unclosed quote)")
        assert res == []

        # Lone quote without closing quote
        res_lone = _parse_sql_values("(')")
        assert res_lone == []

    def test_dangling_escape_at_eof(self) -> None:
        """Backslash escape at the very end of string / stream terminates safely without IndexError."""
        res = _parse_sql_values("(1, 'test\\")
        assert res == []

    def test_unclosed_parenthesis(self) -> None:
        """Row without closing parenthesis is discarded safely."""
        res = _parse_sql_values("(1, 'foo', 42")
        assert len(res) == 0

        # Valid tuple followed by unclosed tuple
        res2 = _parse_sql_values("(1, 'foo'), (2, 'bar'")
        assert len(res2) == 1
        assert res2[0] == [1, "foo"]

    def test_sql_escapes_and_control_chars(self) -> None:
        """Verifies MySQL escape sequences: \\0, \\b, \\n, \\r, \\t, \\Z, \\', \\\\, and ''."""
        sql = r"('hello\0world', 'tab\there', 'new\nline', 'cr\rhere', 'back\bspace', 'ctrl\Zchar', 'it\'s', 'back\\slash', 'double''quote')"
        rows = _parse_sql_values(sql)
        assert len(rows) == 1
        row = rows[0]
        assert row[0] == "hello\0world"
        assert row[1] == "tab\there"
        assert row[2] == "new\nline"
        assert row[3] == "cr\rhere"
        assert row[4] == "back\bspace"
        assert row[5] == "ctrl\x1achar"
        assert row[6] == "it's"
        assert row[7] == "back\\slash"
        assert row[8] == "double'quote"

    def test_unicode_and_emoji_literals(self) -> None:
        """Verifies multi-byte UTF-8 characters and emoji inside SQL strings."""
        sql = "('北京南站', 'Шанхай', '🚀🚅✨', 'mixed-English-中文-123')"
        rows = _parse_sql_values(sql)
        assert len(rows) == 1
        assert rows[0] == ["北京南站", "Шанхай", "🚀🚅✨", "mixed-English-中文-123"]

    def test_binary_literals_escape_behavior(self) -> None:
        """Documents empirical finding: _binary literals strip backslash without escape expansion.
        
        In engine/adapters/db.py line 88-91:
            if c == '\\':
                i += 1
                if i < n:
                    chars.append(val_str[i])
        This causes \\n to become 'n' and \\0 to become '0' instead of control characters.
        """
        sql = "(_binary 'abc\\ndef', _binary '', 123)"
        rows = _parse_sql_values(sql)
        assert len(rows) == 1
        # Empirically observed behavior in M0: 'abcndef'
        assert rows[0][0] == "abcndef"
        assert rows[0][1] == ""
        assert rows[0][2] == 123

    def test_number_parsing_boundaries(self) -> None:
        """Verifies integers, floats, negative values, and zero."""
        sql = "(0, -0, -1, 42, -99.99, 0.0, 1000000000)"
        rows = _parse_sql_values(sql)
        assert len(rows) == 1
        assert rows[0] == [0, 0, -1, 42, -99.99, 0.0, 1000000000]

    def test_null_parsing_case_sensitivity(self) -> None:
        """Verifies that NULL -> None, but lowercase 'null' becomes string 'null'."""
        sql = "(NULL, 1, null, 'NULL')"
        rows = _parse_sql_values(sql)
        assert len(rows) == 1
        assert rows[0][0] is None
        assert rows[0][1] == 1
        # Lowercase null is parsed as string token
        assert rows[0][2] == "null"
        assert rows[0][3] == "NULL"

    def test_nested_commas_and_parentheses_in_strings(self) -> None:
        """Strings containing commas, parentheses, and SQL keywords."""
        sql = "('(1, 2, 3)', 'a, b, c', 'INSERT INTO foo VALUES (1);')"
        rows = _parse_sql_values(sql)
        assert len(rows) == 1
        assert rows[0] == ["(1, 2, 3)", "a, b, c", "INSERT INTO foo VALUES (1);"]

    def test_large_adversarial_stream_termination(self) -> None:
        """Ensure 50,000 unbalanced characters do not cause catastrophic backtracking or hang."""
        adversarial_blob = "((('\"\\\"\'\n\r" * 5000
        t0 = time.perf_counter()
        res = _parse_sql_values(adversarial_blob)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.1, f"Parsing took {elapsed:.3f}s"
        assert isinstance(res, list)


# ==============================================================================
# 2. Dump Ingestion & Mock SQL Edge Cases
# ==============================================================================

class TestDumpIngestionEdgeCases:
    """Tests load_db_dump with synthetically crafted SQL dumps."""

    def test_dump_multiple_insert_statements(self) -> None:
        """Multiple INSERT INTO statements for the same table."""
        content = """
        USE `ts_station`;
        CREATE TABLE `station` (
          `id` varchar(36) NOT NULL,
          `name` varchar(255)
        ) ENGINE=InnoDB;

        INSERT INTO `station` VALUES ('s-1', 'Station A'), ('s-2', 'Station B');
        INSERT INTO `station` VALUES ('s-3', 'Station C');
        """
        with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as tf:
            temp_path = Path(tf.name)
            with gzip.open(temp_path, "wt", encoding="latin1") as gz:
                gz.write(content)

        try:
            state = load_db_dump(temp_path)
            rows = state.get_table("station")
            assert len(rows) == 3
            assert [r["name"] for r in rows] == ["Station A", "Station B", "Station C"]
        finally:
            temp_path.unlink(missing_ok=True)

    def test_dump_semicolon_inside_string_limitation(self) -> None:
        """Empirical demonstration: semicolon inside string literal terminates regex prematurely.
        
        Because load_db_dump uses regex:
            INSERT INTO ... VALUES (.*?);
        any semicolon inside a string literal terminates the match clause, dropping the statement.
        """
        content = """
        USE `ts_test`;
        CREATE TABLE `test_msg` (
          `id` varchar(36) NOT NULL,
          `message` text,
          `status` int(11) DEFAULT NULL
        ) ENGINE=InnoDB;

        INSERT INTO `test_msg` VALUES ('msg-1', 'Notice: train is delayed; please wait', 1);
        """
        with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as tf:
            temp_path = Path(tf.name)
            with gzip.open(temp_path, "wt", encoding="latin1") as gz:
                gz.write(content)

        try:
            state = load_db_dump(temp_path)
            rows = state.get_table("test_msg")
            # Empirical finding: rows is empty due to regex splitting on the first ';'
            assert len(rows) == 0
        finally:
            temp_path.unlink(missing_ok=True)


# ==============================================================================
# 3. Repeated Fork Chaining and Deep Mutation Isolation
# ==============================================================================

class TestForkDeepMutationStress:
    """Stress-tests fork() isolation across deep chains and multi-threaded mutations."""

    def test_deep_fork_chain_100_levels(self, db_state: DatabaseState) -> None:
        """Verify that a 100-level fork chain preserves independence of every ancestor."""
        chain: list[DatabaseState] = [db_state]
        for _ in range(100):
            chain.append(chain[-1].fork())

        assert len(chain) == 101

        # Deepest child mutation
        deepest = chain[-1]
        orig_orders = db_state.get_table("orders")
        assert len(orig_orders) == 10

        # Insert new order into deepest child
        deepest.insert("orders", {"id": "deep-order-100", "status": 999})
        assert len(deepest.get_table("orders")) == 11

        # Verify all ancestors (0..99) still have exactly 10 orders
        for idx in range(100):
            ancestor_orders = chain[idx].get_table("orders")
            assert len(ancestor_orders) == 10, f"Ancestor {idx} was corrupted by child 100!"
            assert ancestor_orders[0]["id"] == orig_orders[0]["id"]

        # Mutate intermediate node (level 50)
        chain[50].update("orders", {"status": 777}, id=orig_orders[0]["id"])
        assert chain[50].find_one("orders", id=orig_orders[0]["id"])["status"] == 777

        # Verify root still has original status
        assert db_state.find_one("orders", id=orig_orders[0]["id"])["status"] == orig_orders[0]["status"]
        # Verify level 49 is unaffected
        assert chain[49].find_one("orders", id=orig_orders[0]["id"])["status"] == orig_orders[0]["status"]
        # Verify level 51 is unaffected
        assert chain[51].find_one("orders", id=orig_orders[0]["id"])["status"] == orig_orders[0]["status"]

    def test_row_dictionary_reference_independence(self, db_state: DatabaseState) -> None:
        """Verify every row dictionary in a fork has a distinct memory address from the parent."""
        fork = db_state.fork()
        for tbl in db_state.table_names():
            parent_rows = db_state.get_table(tbl)
            fork_rows = fork.get_table(tbl)
            assert len(parent_rows) == len(fork_rows)
            for p_row, f_row in zip(parent_rows, fork_rows):
                assert id(p_row) != id(f_row), f"Row in table {tbl} shares dictionary reference!"

    def test_multithreaded_concurrent_forks_and_mutations(self, db_state: DatabaseState) -> None:
        """Execute concurrent forks and mutations across 16 threads without state bleeding."""
        num_threads = 16
        mutations_per_thread = 50

        def worker_task(thread_id: int) -> tuple[int, bool]:
            thread_fork = db_state.fork()
            # Perform mutations
            for m in range(mutations_per_thread):
                thread_fork.insert(
                    "orders",
                    {
                        "id": f"thread-{thread_id}-order-{m}",
                        "account_id": f"user-{thread_id}",
                        "status": thread_id,
                    },
                )
            # Update an existing order
            target_id = "1afc5f4a-4108-4511-9260-922436aebd1a"
            thread_fork.update("orders", {"status": 1000 + thread_id}, id=target_id)

            # Query own rows
            own_rows = thread_fork.query("orders", account_id=f"user-{thread_id}")
            count_match = len(own_rows) == mutations_per_thread
            updated_row = thread_fork.find_one("orders", id=target_id)
            update_match = updated_row is not None and updated_row["status"] == (1000 + thread_id)
            return len(thread_fork.get_table("orders")), (count_match and update_match)

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker_task, tid) for tid in range(num_threads)]
            results = [f.result() for f in futures]

        for final_count, success in results:
            assert success is True
            assert final_count == 10 + mutations_per_thread

        # Crucial check: root db_state must remain completely unchanged
        assert len(db_state.get_table("orders")) == 10
        root_row = db_state.find_one("orders", id="1afc5f4a-4108-4511-9260-922436aebd1a")
        assert root_row["status"] == 1


# ==============================================================================
# 4. Query Engine Edge Cases
# ==============================================================================

class TestQueryEngineEdgeCases:
    """Stress-tests query(), find_one(), and TableCollection indexing."""

    def test_query_non_existent_table(self, db_state: DatabaseState) -> None:
        """Querying a non-existent table returns [] without error."""
        assert db_state.query("non_existent_table") == []
        assert db_state.query("non_existent_table", id="123") == []
        assert db_state.find_one("non_existent_table", id="123") is None
        assert db_state.get_table("non_existent_table") == []

    def test_query_non_existent_column(self, db_state: DatabaseState) -> None:
        """Filtering by a non-existent column returns [] when searching for non-null value."""
        assert db_state.query("orders", non_existent_column="some_val") == []
        assert db_state.find_one("orders", non_existent_column="some_val") is None

    def test_query_none_matching_missing_columns_and_string_none(self) -> None:
        """Empirical quirk: row.get('col') returns None, so querying col=None matches missing cols.
        Also, str(val) != str(expected) matches string 'None' with None.
        """
        state = DatabaseState(
            tables={"test": [{"id": "1", "name": "None"}, {"id": "2", "name": None}]}
        )
        # Both rows match because 'None' == str(None)
        assert len(state.query("test", name=None)) == 2
        assert len(state.query("test", name="None")) == 2

    def test_query_multi_criteria_partial_match(self, db_state: DatabaseState) -> None:
        """Filtering with multiple criteria where some match and one fails."""
        res = db_state.query(
            "orders",
            account_id="4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f",
            status=999999,  # Does not exist
        )
        assert res == []

    def test_query_type_coercion_string_int(self, db_state: DatabaseState) -> None:
        """Verifies str vs int loose equality in query filters."""
        res_int = db_state.query("orders", status=1)
        res_str = db_state.query("orders", status="1")
        assert len(res_int) > 0
        assert len(res_int) == len(res_str)
        assert res_int == res_str

    def test_query_callable_predicates_and_falsy_returns(self, db_state: DatabaseState) -> None:
        """Callable predicate returning boolean, empty, or custom logic."""
        res_false = db_state.query("orders", status=lambda s: False)
        assert res_false == []

        res_true = db_state.query("orders", status=lambda s: True)
        assert len(res_true) == 10

        res_complex = db_state.query(
            "orders",
            train_number=lambda t: t and t.startswith("G"),
            status=lambda s: s == 0,
        )
        assert len(res_complex) > 0
        assert all(r["train_number"].startswith("G") and r["status"] == 0 for r in res_complex)

    def test_table_collection_aliasing_and_contains(self, db_state: DatabaseState) -> None:
        """TableCollection lookup across different naming variants."""
        tc = db_state.tables
        assert isinstance(tc, TableCollection)
        assert "orders" in tc
        assert "ts_order.orders" in tc
        assert "res:table:ts-order-service.orders" in tc
        assert "non_existent_table" not in tc

        assert 12345 not in tc
        assert None not in tc

        with pytest.raises(KeyError):
            _ = tc["non_existent_table_key"]

        assert tc.get("non_existent_table_key", "default_val") == "default_val"


# ==============================================================================
# 5. SkeletonIndex Resolution Across All 33 Table Nodes
# ==============================================================================

class TestSkeletonResolutionAdversarial:
    """Tests resolution of all 33 skeleton nodes, unknown nodes, and malformed inputs."""

    def test_all_33_nodes_detailed_attributes(
        self,
        skeleton_index: SkeletonIndex,
        skeleton_dict: dict[str, Any],
    ) -> None:
        """Exhaustively verify every one of the 33 table nodes has correct metadata."""
        table_nodes = [nid for nid in skeleton_dict["nodes"] if nid.startswith("res:table:")]
        assert len(table_nodes) == 33

        for nid in table_nodes:
            res = skeleton_index.resolve_table_node(nid)
            assert isinstance(res, TableNodeResolution)
            assert res.node_id == nid
            assert res.service != ""
            assert res.table != ""
            assert res.db != ""
            assert res.qualified == f"{res.db}.{res.table}"
            # Check dict interface
            assert res["node_id"] == nid
            assert res["service"] == res.service
            assert res["db"] == res.db
            assert res["table"] == res.table
            assert res["qualified"] == res.qualified
            # Check list interface
            assert isinstance(res, list)

    def test_resolve_unknown_table_node(self, skeleton_index: SkeletonIndex) -> None:
        """A valid res:table: format but for an unknown service/table returns empty list without error."""
        unknown_nid = "res:table:ts-unknown-future-service.future_table"
        res = skeleton_index.resolve_table_node(unknown_nid)
        assert isinstance(res, TableNodeResolution)
        assert res.node_id == unknown_nid
        assert res.service == "ts-unknown-future-service"
        assert res.db == "ts_unknown_future"
        assert res.table == "future_table"
        assert res.qualified == "ts_unknown_future.future_table"
        assert len(res) == 0

    def test_resolve_invalid_non_table_node(self, skeleton_index: SkeletonIndex) -> None:
        """Calling resolve_table_node on a method or module node raises ValueError."""
        with pytest.raises(ValueError, match="Not a table resource node"):
            skeleton_index.resolve_table_node("ts-order-service:com.example.OrderService:createOrder()")

        with pytest.raises(ValueError, match="Not a table resource node"):
            skeleton_index.resolve_table_node("module:ts-order-service")

    def test_table_resource_to_qualified_db_errors(self, skeleton_index: SkeletonIndex) -> None:
        """Non-resource strings raise ValueError."""
        with pytest.raises(ValueError):
            skeleton_index.table_resource_to_qualified_db("not_a_resource")


# ==============================================================================
# 6. Performance & Throughput Benchmarks Under Stress
# ==============================================================================

class TestPerformanceUnderStress:
    """Benchmark throughput for repeated queries and forks under stress."""

    def test_query_throughput_10000_operations(self, db_state: DatabaseState) -> None:
        """10,000 queries should execute in well under 1 second."""
        t0 = time.perf_counter()
        for i in range(10_000):
            status = i % 2
            _ = db_state.query("orders", status=status)
        elapsed = time.perf_counter() - t0
        rate = 10_000 / elapsed
        assert elapsed < 1.0, f"10k queries took {elapsed:.3f}s (rate: {rate:.0f} ops/s)"

    def test_fork_throughput_1000_operations(self, db_state: DatabaseState) -> None:
        """1,000 forks should execute in under 100 ms."""
        t0 = time.perf_counter()
        for _ in range(1_000):
            _ = db_state.fork()
        elapsed = time.perf_counter() - t0
        rate = 1_000 / elapsed
        avg_us = (elapsed / 1_000) * 1_000_000
        assert elapsed < 0.1, f"1,000 forks took {elapsed:.3f}s (avg: {avg_us:.2f} us, rate: {rate:.0f} ops/s)"
