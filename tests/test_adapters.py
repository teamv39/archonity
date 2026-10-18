"""Модульные тесты адаптеров SubmissionAdapter и SkeletonIndex."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.adapters.submission import SubmissionAdapter
from engine.evidence import EvidenceLogger

ROOT = Path(__file__).resolve().parent.parent
SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"
TARGETS_ROOT = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"


@pytest.fixture(scope="module")
def skeleton_index(shared_skeleton_index: SkeletonIndex) -> SkeletonIndex:
    return shared_skeleton_index


class TestSkeletonIndex:
    """Тестирование загрузки и структуры SkeletonIndex."""

    def test_skeleton_index_nodes(self, skeleton_index: SkeletonIndex) -> None:
        assert skeleton_index.project == "trainticket"
        assert len(skeleton_index.N) > 1000
        # Проверка наличия контроллеров и методов
        assert any("UserController#getToken" in k for k in skeleton_index.N)
        # Проверка таблиц БД
        assert any(k.startswith("res:table:") for k in skeleton_index.N)

    def test_wiring_keys(self, skeleton_index: SkeletonIndex) -> None:
        wiring = skeleton_index.wiring
        assert "remote_call" in wiring
        assert "data_access" in wiring
        assert "message_delivery" in wiring
        assert "runtime_dispatch" in wiring


class TestSubmissionAdapter:
    """Тестирование SubmissionAdapter и генерации контрактов."""

    def test_add_scenario_edges_formatting(self) -> None:
        adapter = SubmissionAdapter(project="trainticket")
        methods = {
            "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)",
            "method:ts-contacts-service:contacts.controller.ContactsController#findContactsByAccountId(java.lang.String,?HttpHeaders)",
        }
        calls = {
            (
                "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)",
                "method:ts-auth-service:auth.service.impl.TokenServiceImpl#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)",
            )
        }
        remote: set[tuple[str, str]] = set()
        data = {
            (
                "method:ts-contacts-service:contacts.service.ContactsServiceImpl#findContactsByAccountId(java.lang.String,org.springframework.http.HttpHeaders)",
                "res:table:ts-contacts-service.contacts",
            )
        }

        adapter.add_scenario_edges("S0", methods=methods, calls=calls, remote=remote, data=data)

        d = adapter.to_dict()
        assert d["project"] == "trainticket"
        assert "S0" in d["scenarios"]
        edges = d["scenarios"]["S0"]["edges"]

        # Проверяем правильность префикса scenario:S0 для executes
        exec_edges = [e for e in edges if e["relation"] == "executes"]
        assert len(exec_edges) == 2
        for e in exec_edges:
            assert e["source"] == "scenario:S0"
            assert e["target"].startswith("method:")

        # Проверяем relation calls
        call_edges = [e for e in edges if e["relation"] == "calls"]
        assert len(call_edges) == 1
        assert call_edges[0]["source"].startswith("method:")
        assert call_edges[0]["target"].startswith("method:")

        # Проверяем relation data
        data_edges = [e for e in edges if e["relation"] == "data"]
        assert len(data_edges) == 1
        assert data_edges[0]["source"].startswith("method:")
        assert data_edges[0]["target"].startswith("res:table:")

    def test_canonical_graph_structure(
        self,
        skeleton_index: SkeletonIndex,
        tmp_path: Path,
    ) -> None:
        ev_logger = EvidenceLogger(skeleton_index, targets_root=TARGETS_ROOT)
        adapter = SubmissionAdapter(project="trainticket", evidence_logger=ev_logger)

        methods = {
            "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)",
        }
        data = {
            (
                "method:ts-auth-service:auth.service.impl.TokenServiceImpl#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)",
                "res:table:ts-auth-service.auth_user",
            )
        }
        remote = {
            (
                "method:ts-preserve-service:preserve.service.PreserveServiceImpl#checkSecurity(java.lang.String,org.springframework.http.HttpHeaders)",
                "method:ts-security-service:security.controller.SecurityController#check(java.lang.String,org.springframework.http.HttpHeaders)",
            )
        }

        adapter.add_scenario_edges("S1", methods=methods, calls=set(), remote=remote, data=data)

        cg = adapter.to_canonical_graph()
        assert "metadata" in cg
        assert "version" in cg["metadata"]
        assert "generated_at" in cg["metadata"]

        nodes = {n["id"]: n for n in cg["nodes"]}
        # Проверяем узлы сервисов
        assert "ts-auth-service" in nodes
        assert nodes["ts-auth-service"]["type"] == "SERVICE"

        # Проверяем терминальный узел БД
        db_id = "db-ts-auth-service-auth_user"
        assert db_id in nodes
        assert nodes[db_id]["type"] == "DATABASE"
        assert nodes[db_id]["isTerminalSink"] is True

        # Проверяем ребра и наличие evidence_details
        edges = {e["id"]: e for e in cg["edges"]}
        assert len(edges) >= 2
        for eid, e in edges.items():
            assert e["relation_type"] in ("REST_HTTP", "DATABASE", "CALLS_HTTP")
            assert e["source_type"] in ("AST_EXACT", "CONFIG")
            assert e["confidence"] == 1.0
            assert e["is_reachable"] is True
            # Каждое ребро обязано иметь evidence_details
            assert "evidence_details" in e
            assert e["evidence_details"] is not None

        # Проверяем экспорт canonical_graph.json и evidence.json
        cg_path = tmp_path / "canonical_graph.json"
        adapter.save_canonical_graph(cg_path)
        assert cg_path.is_file()

        ev_path = tmp_path / "evidence.json"
        adapter.save_evidence_log(ev_path)
        assert ev_path.is_file()


class TestContextAndDbState:
    """Тестирование динамической загрузки контекста и состояния БД."""

    def test_parse_context_readme(self) -> None:
        from engine.adapters.db import parse_context_readme

        context_readme = ROOT / "hackaton" / "tt-challenge" / "context" / "README.md"
        assert context_readme.is_file()

        info = parse_context_readme(context_readme)
        assert info.get("travel_date") == "2026-10-01"
        assert info.get("system_date") == "2026-09-15"
        assert info.get("user_name") == "fdse_microservice"
        assert info.get("balance") == 10000.0

    def test_database_state_user_and_balance(self) -> None:
        from engine.adapters.db import load_db_dump

        dump_path = ROOT / "hackaton" / "tt-challenge" / "context" / "db-after-warmup.sql.gz"
        assert dump_path.is_file()

        db = load_db_dump(dump_path)
        user = db.get_user_by_name("fdse_microservice")
        assert user is not None
        assert user["user_id"] == "4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f"

        # Проверка динамического расчета баланса
        balance = db.get_user_balance(user["user_id"])
        assert balance is not None
        assert balance > 8000.0  # 10361.0 - 1670.0 = 8691.0

    def test_skeleton_index_context(self, skeleton_index: SkeletonIndex) -> None:
        assert hasattr(skeleton_index, "context")
        assert skeleton_index.context.get("travel_date") == "2026-10-01"
        assert skeleton_index.context.get("system_date") == "2026-09-15"
        assert skeleton_index.context.get("user_name") == "fdse_microservice"

