"""Динамическая схема сущностей и полей для исполнителя M4 (ADR-005, universality audit).

Устраняет жестко зашитые словари _KIND_HINTS, _ID_FIELDS из step.py:
- Виды сущностей и их ID извлекаются из JPA-аннотаций (@Entity, @Id) узлов скелета;
- Первичные ключи строятся по JPA @Id и конвенции JavaBeans (<entity>Id / id);
- Алиасы семантически связывают параметры шагов поиска и бронирования.
"""
from __future__ import annotations

import re
from typing import Any

# Канонические дефолты на случай отсутствия скелета или изолированного запуска
_DEFAULT_KIND_HINTS: dict[str, tuple[str, ...]] = {
    "order": ("order",),
    "trip": ("trip",),
    "contact": ("contact",),
    "user": ("user", "token", "account"),
    "food": ("food",),
    "store": ("store",),
    "station": ("station",),
    "route": ("route",),
    "train": ("traintype", "train"),
    "price": ("price",),
    "consign": ("consign",),
    "assurance": ("assurance",),
}

_DEFAULT_ID_FIELDS: dict[str, tuple[str, ...]] = {
    "order": ("orderId", "id"),
    "trip": ("tripId",),
    "contact": ("contactsId", "contactId"),
    "user": ("accountId", "userId", "loginId"),
    "food": ("foodId",),
    "store": ("storeId",),
    "station": ("stationId",),
    "route": ("routeId",),
    "train": ("trainTypeId",),
    "price": ("priceId",),
    "consign": ("consignId",),
    "assurance": ("assuranceId",),
}

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "from": ("from", "startStation", "startPlace", "startStationName", "fromStation"),
    "to": ("to", "terminalStation", "endPlace", "terminalStationName", "toStation"),
    "date": ("date", "travelDate", "departureTime"),
    "tripId": ("tripId", "trainNumber"),
    "oldTripId": ("trainNumber",),
}

_USER_FIELDS: tuple[str, ...] = ("accountId", "userId", "loginId")


def simple_name(fqn: str | None) -> str:
    """Простое имя класса в нижнем регистре без пакетов и вложенных классов."""
    return (fqn or "").rsplit(".", 1)[-1].split("$")[-1].lower()


class EntitySchema:
    """Динамический реестр сущностей, первичных ключей и полей DTO."""

    def __init__(self, index: Any = None) -> None:
        self.index = index
        self._kind_hints: dict[str, tuple[str, ...]] = dict(_DEFAULT_KIND_HINTS)
        self._id_fields: dict[str, tuple[str, ...]] = dict(_DEFAULT_ID_FIELDS)
        self._primary_ids: dict[str, str] = {k: v[0] for k, v in _DEFAULT_ID_FIELDS.items() if v}
        self.user_fields: tuple[str, ...] = _USER_FIELDS
        self._field_aliases: dict[str, tuple[str, ...]] = dict(_FIELD_ALIASES)
        self._entity_types: set[str] = set()

        if index is not None:
            self._discover_from_index(index)

    def _discover_from_index(self, index: Any) -> None:
        """Извлечение JPA сущностей и их @Id полей из узлов скелета."""
        nodes: dict[str, dict[str, Any]] = getattr(index, "N", {}) or {}
        if not nodes:
            return

        # 1. Поиск типов с аннотацией @Entity
        entity_types: dict[str, dict[str, Any]] = {}
        for nid, n in nodes.items():
            if n.get("kind") != "type":
                continue
            anns = [a.get("name") if isinstance(a, dict) else a for a in n.get("annotations", [])]
            if "Entity" in anns:
                fqn = nid.split(":", 2)[-1] if ":" in nid else n.get("name", "")
                simple = simple_name(fqn)
                self._entity_types.add(fqn)
                entity_types[nid] = {"fqn": fqn, "simple": simple, "id_fields": set()}

        # 2. Поиск полей с аннотацией @Id или @EmbeddedId
        for nid, n in nodes.items():
            if n.get("kind") != "field":
                continue
            anns = [a.get("name") if isinstance(a, dict) else a for a in n.get("annotations", [])]
            if any(a in ("Id", "EmbeddedId") for a in anns):
                prefix = nid.rsplit(".", 1)[0]
                type_nid = "type:" + prefix.split(":", 1)[1] if ":" in prefix else prefix
                if type_nid in entity_types:
                    entity_types[type_nid]["id_fields"].add(n.get("name", ""))

        # 3. Обогащение словарей видов и ID полей
        for meta in entity_types.values():
            s = meta["simple"]
            base = re.sub(r"(entity|record|config|order|info)$", "", s) or s
            for k in (s, base):
                if k not in self._id_fields:
                    pk = next(iter(meta["id_fields"]), None)
                    candidates: list[str] = []
                    if pk and pk != "id":
                        candidates.append(pk)
                    candidates.extend([f"{k}Id", f"{k}sId", "id"])
                    self._id_fields[k] = tuple(candidates)
                    self._primary_ids[k] = candidates[0]
                if k not in self._kind_hints:
                    self._kind_hints[k] = (k, s) if k != s else (k,)

    @property
    def known_kinds(self) -> set[str]:
        return set(self._id_fields.keys())

    def id_fields(self, kind: str) -> tuple[str, ...]:
        """Все кандидатные имена полей первичного ключа для вида сущности."""
        if kind in self._id_fields:
            return self._id_fields[kind]
        # Общая конвенция JavaBeans для неизвестных видов: <kind>Id, <kind>sId, id
        k = kind.lower()
        if k.endswith("s"):
            return (f"{k}Id", f"{k[:-1]}Id", "id")
        return (f"{k}Id", f"{k}sId", "id")

    def primary_id_field(self, kind: str) -> str | None:
        """Главный ID атрибут вида (например tripId, orderId, contactsId, accountId)."""
        if kind in self._primary_ids:
            return self._primary_ids[kind]
        fields = self.id_fields(kind)
        return fields[0] if fields else None

    def kind_hints(self, kind: str) -> tuple[str, ...]:
        """Ключевые слова и подстроки для распознавания вида сущности в FQN."""
        return self._kind_hints.get(kind, (kind,))

    def kind_rank(self, fqn: str | None, kind: str) -> int:
        """Насколько тип похож на вид сущности: 3 — совпадает, 2 — префикс, 1 — содержит, 0 — нет."""
        s = simple_name(fqn)
        best = 0
        for h in self.kind_hints(kind):
            if s in (h, h + "s"):
                best = max(best, 3)
            elif s.startswith(h):
                best = max(best, 2)
            elif h in s:
                best = max(best, 1)
        return best

    def is_kind(self, fqn: str | None, kind: str) -> bool:
        return self.kind_rank(fqn, kind) > 0

    def field_aliases(self, name: str) -> tuple[str, ...]:
        """Алиасы поля DTO для поиска в сущностях предыдущих шагов."""
        return self._field_aliases.get(name, (name,))


__all__ = ["EntitySchema", "simple_name"]
