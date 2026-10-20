"""Тесты схемы сущностей EntitySchema (engine/executor/schema.py): виды и ID-поля из манифеста (ADR-007)."""
from __future__ import annotations

from engine.executor.schema import EntitySchema, simple_name
from engine.manifest import entity_kinds


class TestEntitySchema:

    def test_simple_name(self):
        assert simple_name("order.entity.Order") == "order"
        assert simple_name("ts.common.User$Inner") == "inner"
        assert simple_name("") == ""
        assert simple_name(None) == ""

    def test_without_index_only_conventions(self):
        schema = EntitySchema()
        assert schema.known_kinds == set()
        assert schema.id_fields("order") == ("orderId", "ordersId", "id")
        assert schema.primary_id_field("order") == "orderId"
        assert schema.kind_rank("order.entity.Order", "order") == 3
        assert schema.is_kind("order.entity.Order", "order") is True

    def test_kinds_from_manifest(self, shared_skeleton_index):
        schema = EntitySchema(shared_skeleton_index)
        assert schema.known_kinds == set(entity_kinds(shared_skeleton_index))
        assert schema.id_fields("trainType") == ("trainTypeId", "id")
        assert schema.id_fields("user") == ("userId", "id")
        assert schema.primary_id_field("contacts") == "contactsId"
        assert schema.primary_id_field("trip") == "tripId"
        # тип относится к виду по простому имени класса: совпадает, начинается с вида, содержит
        assert schema.kind_rank("train.entity.TrainType", "trainType") == 3
        assert schema.kind_rank("contacts.entity.Contacts", "contacts") == 3
        assert schema.kind_rank("edu.fudan.common.entity.TripResponse", "trip") == 2
        assert schema.kind_rank("price.entity.PriceConfig", "priceConfig") == 3
        # ответ входа не вид user: текущего пользователя даёт шаг входа (StepExecutor._logged_in_user)
        assert schema.kind_rank("auth.dto.TokenDto", "user") == 0

    def test_unknown_kind_conventions(self):
        schema = EntitySchema()
        assert schema.id_fields("invoice") == ("invoiceId", "invoicesId", "id")
        assert schema.primary_id_field("invoice") == "invoiceId"
        assert schema.id_fields("metrics") == ("metricsId", "metricId", "id")
        assert schema.id_fields("TrainType") == ("trainTypeId", "trainTypesId", "id")

    def test_field_aliases(self):
        schema = EntitySchema()
        aliases = schema.field_aliases("from")
        assert "startStation" in aliases
        assert "from" in aliases
        assert schema.field_aliases("unknown") == ("unknown",)
