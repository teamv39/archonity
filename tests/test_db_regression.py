"""Adversarial regression and backward compatibility tests for Milestone M0."""
from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import patch

from engine.adapters.db import DatabaseState
from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.pipeline import ArchonityPipeline

ROOT = Path(__file__).resolve().parent.parent
SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"
TARGETS_ROOT = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"
DUMP_PATH = ROOT / "hackaton" / "tt-challenge" / "context" / "db-after-warmup.sql.gz"


class TestSkeletonBackwardCompatibility:
    """Проверка обратной совместимости SkeletonIndex при инициализации bare dict."""

    def test_full_skeleton_dict_in_memory(self) -> None:
        """Словарь полного скелета в памяти корректно индексируется и связывается с БД."""
        full_dict = load_json(SKELETON_PATH)
        idx = SkeletonIndex(full_dict)
        assert idx.project == "trainticket"
        assert len(idx.N) > 1000
        assert len(idx.table_nodes) == 33
        assert len(idx.get_table_records("orders")) == 10

    def test_minimal_empty_dictionary(self) -> None:
        """Минимальный пустой словарь не приводит к падениям."""
        min_dict = {"project": "toy", "nodes": {}, "edges": []}
        idx = SkeletonIndex(min_dict)
        assert idx.project == "toy"
        assert idx.N == {}
        assert idx.table_nodes == {}
        assert idx.handlers == []
        assert idx.table_resource_to_db("res:table:toy-service.items") == "items"
        assert idx.table_resource_to_qualified_db("res:table:toy-service.items") == "toy.items"

        res = idx.resolve_table_node("res:table:toy-service.items")
        assert len(res) == 0
        assert res.table == "items"
        assert res.service == "toy-service"
        assert res.db == "toy"
        assert res.qualified == "toy.items"

    def test_sparse_dictionary_defaults(self) -> None:
        """Словарь без полей project и edges корректно использует значения по умолчанию."""
        sparse_dict = {"nodes": {}}
        idx = SkeletonIndex(sparse_dict)
        assert idx.project == "trainticket"
        assert idx.N == {}
        assert idx.table_nodes == {}

    def test_custom_table_nodes_resolution(self) -> None:
        """Кастомный узел таблицы корректно индексируется в table_nodes."""
        custom_dict = {
            "nodes": {
                "res:table:custom-service.records": {
                    "kind": "resource",
                    "type": "database_table",
                }
            },
            "edges": [],
        }
        idx = SkeletonIndex(custom_dict)
        assert "res:table:custom-service.records" in idx.table_nodes
        assert idx.table_resource_to_db("res:table:custom-service.records") == "records"
        assert (
            idx.table_resource_to_qualified_db("res:table:custom-service.records")
            == "custom.records"
        )


class TestDumpFallbackAndCorruptedInput:
    """Проверка отказоустойчивости при отсутствии или повреждении дампа БД."""

    def test_nonexistent_dump_path_fallback(self) -> None:
        """Несуществующий путь к дампу приводит к созданию пустого DatabaseState."""
        full_dict = load_json(SKELETON_PATH)
        idx = SkeletonIndex(full_dict, db_dump_path="/path/that/does/not/exist.sql.gz")
        assert isinstance(idx.db_state, DatabaseState)
        assert len(idx.db_state.table_names()) == 0
        assert idx.get_table_records("orders") == []
        assert idx.table_resource_to_db("res:table:ts-order-service.orders") == "orders"

        res = idx.resolve_table_node("res:table:ts-order-service.orders")
        assert len(res) == 0
        assert res.table == "orders"
        assert res.db == "ts_order"

    def test_auto_discovery_fallback_when_dumps_missing(self) -> None:
        """Если стандартные дампы отсутствуют, fallback создает пустой DatabaseState."""
        full_dict = load_json(SKELETON_PATH)
        with patch.object(SkeletonIndex, "_find_default_db_dump", return_value=None):
            idx = SkeletonIndex(full_dict)
            assert isinstance(idx.db_state, DatabaseState)
            assert len(idx.db_state.table_names()) == 0
            assert idx.get_table_records("orders") == []

    def test_corrupted_gzip_dump_fallback(self, tmp_path: Path) -> None:
        """Поврежденный gzip-файл безопасно перехватывается с откатом на пустой DatabaseState."""
        corrupt_file = tmp_path / "corrupt_db.sql.gz"
        corrupt_file.write_bytes(b"NOT A VALID GZIP DATA")

        full_dict = load_json(SKELETON_PATH)
        idx = SkeletonIndex(full_dict, db_dump_path=corrupt_file)
        assert isinstance(idx.db_state, DatabaseState)
        assert len(idx.db_state.table_names()) == 0

    def test_explicit_empty_db_state(self) -> None:
        """Передача пустого экземпляра DatabaseState сохраняет ссылку и возвращает пустые списки."""
        full_dict = load_json(SKELETON_PATH)
        empty_db = DatabaseState()
        idx = SkeletonIndex(full_dict, db_state=empty_db)
        assert idx.db_state is empty_db
        assert idx.get_table_records("orders") == []


class TestPipelineContractAndExecution:
    """Проверка контракта инициализации ArchonityPipeline и устойчивости к пустой БД."""

    def test_pipeline_default_db_state_populated(self) -> None:
        """По умолчанию ArchonityPipeline инициализирует SkeletonIndex с заполненной БД."""
        pipe = ArchonityPipeline(
            skeleton_path=SKELETON_PATH,
            targets_root=TARGETS_ROOT,
        )
        assert hasattr(pipe.index, "db_state")
        assert isinstance(pipe.index.db_state, DatabaseState)
        assert len(pipe.index.db_state.table_names()) == 32

    def test_pipeline_init_parameter_conformance(self) -> None:
        """Проверка параметров ArchonityPipeline.__init__."""
        sig = inspect.signature(ArchonityPipeline.__init__)
        params = list(sig.parameters.keys())
        assert "skeleton_path" in params
        assert "targets_root" in params

    def test_pipeline_run_with_empty_db_state(self) -> None:
        """Пайплайн корректно исполняет S0 даже при отсутствии записей в DatabaseState."""
        pipe = ArchonityPipeline(
            skeleton_path=SKELETON_PATH,
            targets_root=TARGETS_ROOT,
        )
        pipe.index.db_state = DatabaseState()
        s0_dict = load_json(ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S0.json")

        methods, calls, remote, data = pipe.run_scenario(s0_dict)
        assert len(methods) == 34
        assert len(calls) == 24
        assert len(remote) == 0
        assert len(data) == 7
