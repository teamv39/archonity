"""Манифест сущностей engine/manifest.py (ADR-007, решения 2 и 3)."""
from __future__ import annotations

from types import SimpleNamespace

from engine.manifest import EntityKind, entity_kinds, kind_name


def _ix(*nodes: tuple[str, dict]) -> SimpleNamespace:
    return SimpleNamespace(N=dict(nodes))


def _type(fqn: str, module: str, *anns: tuple[str, str]) -> tuple[str, dict]:
    return f"type:{module}:{fqn}", {"kind": "type", "fqn": fqn, "module": module,
                                    "annotations": [{"name": n, "args": a} for n, a in anns]}


def _field(owner: str, name: str, *anns: str) -> tuple[str, dict]:
    return f"field:{owner[5:]}.{name}", {"kind": "field", "owner": owner, "name": name,
                                          "annotations": [{"name": a, "args": ""} for a in anns]}


def _table(schema: str, name: str) -> tuple[str, dict]:
    return f"res:table:{schema}.{name}", {"kind": "data_resource", "resource_kind": "table"}


class TestManifestRules:
    def test_kind_name_lowercases_first_letter(self) -> None:
        assert kind_name("TrainType") == "trainType"
        assert kind_name("Order") == "order"

    def test_id_fields_order_and_table_naming(self) -> None:
        wait = _type("w.WaitListOrder", "ts-wait", ("Entity", ""))
        cfg = _type("c.Config", "ts-config", ("Entity", ""), ("Table", '(indexes = {@Index(name = "idx", columnList = "a")})'))
        rec = _type("r.ConsignRecord", "ts-consign", ("Entity", ""), ("Table", '(schema = "ts-consign-mysql")'))
        food = _type("f.Food", "ts-common", ("Embeddable", ""))
        dto = _type("d.WaitDto", "ts-wait", ("Data", ""))
        ks = entity_kinds(_ix(wait, cfg, rec, food, dto,
                              _field(wait[0], "id", "Id"), _field(cfg[0], "name", "Id"), _field(rec[0], "id", "Id"),
                              _table("ts-wait", "wait_list_order"), _table("ts-config", "config"),
                              _table("ts-consign-mysql", "consign_record")))
        assert set(ks) == {"waitListOrder", "config", "consignRecord", "food"}  # DTO без @Entity — не вид
        # @Id, если не id; затем <вид>Id; затем id
        assert ks["config"].id_fields == ("name", "configId", "id")
        assert ks["waitListOrder"].id_fields == ("waitListOrderId", "id")
        # имя таблицы: @Table(name) (имя @Index не берётся), иначе по правилу Spring Boot; схема — @Table(schema)
        assert ks["waitListOrder"].tables == ("res:table:ts-wait.wait_list_order",)
        assert ks["config"].tables == ("res:table:ts-config.config",)
        assert ks["consignRecord"].tables == ("res:table:ts-consign-mysql.consign_record",)
        assert ks["food"] == EntityKind("food", ("f.Food",), ("foodId", "id"), ())

    def test_same_simple_name_is_one_kind(self) -> None:
        a = _type("order.entity.Order", "ts-order", ("Entity", ""), ("Table", '(name = "orders")'))
        b = _type("other.entity.Order", "ts-order-other", ("Entity", ""), ("Table", '(name = "orders_other")'))
        ks = entity_kinds(_ix(a, b, _table("ts-order", "orders"), _table("ts-order-other", "orders_other")))
        assert list(ks) == ["order"]
        assert ks["order"].types == ("order.entity.Order", "other.entity.Order")
        assert ks["order"].tables == ("res:table:ts-order-other.orders_other", "res:table:ts-order.orders")

    def test_no_index(self) -> None:
        assert entity_kinds(None) == {}


class TestManifestTrainTicket:
    def test_23_kinds_from_skeleton(self, shared_skeleton_index) -> None:
        ks = entity_kinds(shared_skeleton_index)
        assert len(ks) == 23
        assert {"trainType", "contacts", "priceConfig", "consignRecord", "stationFoodStore", "food", "trip",
                "order", "user"} <= set(ks)
        assert not {"train", "contact", "price", "consign", "store"} & set(ks)  # не виды манифеста

    def test_id_fields_and_tables(self, shared_skeleton_index) -> None:
        ks = entity_kinds(shared_skeleton_index)
        assert ks["user"].id_fields == ("userId", "id")
        assert ks["trainType"].id_fields == ("trainTypeId", "id")
        assert ks["contacts"].id_fields == ("contactsId", "id")
        assert ks["user"].tables == ("res:table:ts-auth-service.auth_user", "res:table:ts-user-service.user")
        assert ks["consignRecord"].tables == ("res:table:ts-consign-mysql.consign_record",)
        # у каждой сущности @Entity нашлась своя таблица в узлах скелета
        assert sum(len(k.tables) for k in ks.values()) == 27
        assert all(t in shared_skeleton_index.N for k in ks.values() for t in k.tables)
