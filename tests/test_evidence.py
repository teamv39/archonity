"""Модульные тесты модуля EvidenceLogger (ADR-001 / ADR-002)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.evidence import EvidenceLogger

ROOT = Path(__file__).resolve().parent.parent
SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"
TARGETS_ROOT = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"


@pytest.fixture(scope="module")
def skeleton_index() -> SkeletonIndex:
    return SkeletonIndex(load_json(SKELETON_PATH))


@pytest.fixture
def evidence_logger(skeleton_index: SkeletonIndex) -> EvidenceLogger:
    return EvidenceLogger(skeleton_index, targets_root=TARGETS_ROOT)


class TestEvidenceLogger:
    """Тестирование сбора доказательств связей."""

    def test_record_remote_call(self, evidence_logger: EvidenceLogger) -> None:
        src = "method:ts-preserve-service:preserve.service.PreserveServiceImpl#checkSecurity(java.lang.String,org.springframework.http.HttpHeaders)"
        tgt = "method:ts-security-service:security.controller.SecurityController#check(java.lang.String,org.springframework.http.HttpHeaders)"

        edge_id = evidence_logger.record_remote_call(src, tgt, scenario_id="S1")
        assert edge_id == "ts-preserve-service->ts-security-service:REST_HTTP"

        entry = evidence_logger.evidence[edge_id]
        assert entry["source"] == "ts-preserve-service"
        assert entry["target"] == "ts-security-service"
        assert entry["relation_type"] == "REST_HTTP"
        assert entry["source_type"] == "AST_EXACT"
        assert entry["confidence"] == 1.0

        details = entry["evidence_details"]
        assert "PreserveServiceImpl.java" in details["file_path"]
        assert details["line_number"] > 0
        assert details["caller"] == src
        assert details["matched_endpoint"] == tgt
        assert details["is_reachable"] is True
        assert len(details["code_snippet"]) > 0

    def test_record_data_access(self, evidence_logger: EvidenceLogger) -> None:
        src = "method:ts-order-service:order.service.OrderServiceImpl#queryOrders(order.entity.OrderInfo,java.lang.String,org.springframework.http.HttpHeaders)"
        tbl = "res:table:ts-order-service.orders"

        edge_id = evidence_logger.record_data_access(src, tbl, scenario_id="S0")
        assert edge_id == "ts-order-service->db-ts-order-service-orders:DATABASE"

        entry = evidence_logger.evidence[edge_id]
        assert entry["relation_type"] == "DATABASE"
        assert entry["source_type"] == "AST_EXACT"
        assert entry["confidence"] == 1.0

        details = entry["evidence_details"]
        assert "OrderServiceImpl.java" in details["file_path"]
        assert details["line_number"] > 0
        assert details["matched_endpoint"] == tbl

    def test_record_gateway_route_filtering(self, evidence_logger: EvidenceLogger) -> None:
        # Корректный маршрут шлюза
        edge_id = evidence_logger.record_gateway_route("ts-order-service")
        assert edge_id == "ts-gateway-service->ts-order-service:REST_HTTP"
        entry = evidence_logger.evidence[edge_id]
        assert entry["source_type"] == "CONFIG"
        assert entry["confidence"] == 1.0
        assert "application.yml" in entry["evidence_details"]["file_path"]

        # Невалидные цели (библиотеки и сам шлюз) должны отклоняться
        assert evidence_logger.record_gateway_route("ts-common") == ""
        assert "ts-gateway-service->ts-common:REST_HTTP" not in evidence_logger.evidence

        assert evidence_logger.record_gateway_route("ts-gateway-service") == ""
        assert "ts-gateway-service->ts-gateway-service:REST_HTTP" not in evidence_logger.evidence

    def test_snippet_caching(self, evidence_logger: EvidenceLogger) -> None:
        file_rel = "ts-order-service/src/main/java/order/service/OrderServiceImpl.java"
        s1 = evidence_logger.extract_snippet(file_rel, 65)
        assert len(s1) > 0
        assert str(TARGETS_ROOT / file_rel) in evidence_logger._file_cache

        # Второй вызов должен использовать кэш
        s2 = evidence_logger.extract_snippet(file_rel, 65)
        assert s1 == s2

    def test_snippet_invalid_file_or_line(self, evidence_logger: EvidenceLogger) -> None:
        assert evidence_logger.extract_snippet("nonexistent.java", 10) == ""
        assert evidence_logger.extract_snippet("", 10) == ""
        assert evidence_logger.extract_snippet("any.java", -1) == ""

    def test_save_and_reload(self, evidence_logger: EvidenceLogger, tmp_path: Path) -> None:
        src = "method:ts-contacts-service:contacts.service.ContactsServiceImpl#findContactsByAccountId(java.lang.String,org.springframework.http.HttpHeaders)"
        tbl = "res:table:ts-contacts-service.contacts"
        evidence_logger.record_data_access(src, tbl)

        out_file = tmp_path / "evidence.json"
        evidence_logger.save(out_file)
        assert out_file.is_file()

        loaded = json.loads(out_file.read_text(encoding="utf-8"))
        assert len(loaded) >= 1
        for eid, entry in loaded.items():
            assert "edge_id" in entry
            assert "source" in entry
            assert "target" in entry
            assert "relation_type" in entry
            assert "source_type" in entry
            assert "confidence" in entry
            assert "evidence_details" in entry
