"""Тесты динамической схемы сущностей EntitySchema (engine/executor/schema.py)."""
from __future__ import annotations

from pathlib import Path
import pytest

from engine.adapters.skeleton import SkeletonIndex
from engine.executor.schema import EntitySchema, simple_name

ROOT = Path(__file__).resolve().parent.parent
SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"


@pytest.fixture(scope="module")
def skeleton_index():
    return SkeletonIndex(SKELETON_PATH)


class TestEntitySchema:

    def test_simple_name(self):
        assert simple_name("order.entity.Order") == "order"
        assert simple_name("ts.common.User$Inner") == "inner"
        assert simple_name("") == ""
        assert simple_name(None) == ""

    def test_default_schema_fallback(self):
        schema = EntitySchema()
        assert "order" in schema.known_kinds
        assert "id" in schema.id_fields("order")
        assert "orderId" in schema.id_fields("order")
        assert schema.primary_id_field("order") == "orderId"
        assert schema.kind_rank("order.entity.Order", "order") == 3
        assert schema.is_kind("order.entity.Order", "order") is True

    def test_skeleton_discovery(self, skeleton_index):
        schema = EntitySchema(skeleton_index)
        assert len(schema.known_kinds) >= 12
        assert "user" in schema.known_kinds
        assert "order" in schema.known_kinds
        assert "trip" in schema.known_kinds

        # Проверка ключевых полей сущностей Train Ticket
        assert "userId" in schema.id_fields("user")
        assert "orderId" in schema.id_fields("order")
        assert "tripId" in schema.id_fields("trip")
        assert "contactsId" in schema.id_fields("contact")

        # Проверка приоритетов первичных ключей
        assert schema.primary_id_field("trip") == "tripId"
        assert schema.primary_id_field("order") == "orderId"
        assert schema.primary_id_field("contact") == "contactsId"

    def test_unknown_kind_conventions(self):
        schema = EntitySchema()
        # Для неизвестной сущности invoice
        assert schema.id_fields("invoice") == ("invoiceId", "invoicesId", "id")
        assert schema.primary_id_field("invoice") == "invoiceId"
        # Для сущности во множественном числе metrics
        assert schema.id_fields("metrics") == ("metricsId", "metricId", "id")

    def test_field_aliases(self):
        schema = EntitySchema()
        aliases = schema.field_aliases("from")
        assert "startStation" in aliases
        assert "from" in aliases
        assert schema.field_aliases("unknown") == ("unknown",)
