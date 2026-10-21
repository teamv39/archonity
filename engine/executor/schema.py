"""Виды сущностей и ID-поля для исполнителя M4 (ADR-007, решения 2 и 3).

Виды ссылок шагов (`StepRequest.refs`) и их ID-поля берутся из манифеста `engine/manifest.py`: классы с
`@Entity`/`@Embeddable` скелета, поля `@Id`. Тип объекта относится к виду по простому имени класса: совпадает
(`Contacts`), начинается с имени вида (`TripResponse`) или содержит его.

Виды M1 до ADR-007 (режим `--ref-kinds v7`) сюда не попадают: их переводит в виды манифеста `StepExecutor`.
"""
from __future__ import annotations

from typing import Any

from engine.manifest import EntityKind, camel_to_snake, entity_kinds, simple_name as _canonical_simple_name

# Режим отката --m4-conventions names, как до feature/102 и feature/108: маршрут и дата бронирования — из полей
# найденной записи по именам Train Ticket, ID рейса — из trainNumber. По умолчанию (code) таблицы нет: маршрут и дату
# M1 берёт из текста шага и сценария, ID рейса — каталог UI (StepRequest.body_src),
# docs/researches/m4_code_derived_conventions.md.
_NAMES_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "from": ("from", "startStation", "startPlace", "startStationName", "fromStation"),
    "to": ("to", "terminalStation", "endPlace", "terminalStationName", "toStation"),
    "date": ("date", "travelDate", "departureTime"),
    "tripId": ("tripId", "trainNumber"),
    "oldTripId": ("trainNumber",),
}

# Поля тела и пути, куда UI кладёт ID вошедшего пользователя (client_login.js: sessionStorage client_id =
# data.userId; затем accountId, loginId, {client_id} в пути). Общее правило — поток данных UI, но каталог UI
# (engine/grounding/ui_catalog.py) нелитеральные значения полей не хранит; пока список (annotation_rules.md).
_USER_FIELDS: tuple[str, ...] = ("accountId", "userId", "loginId")


def simple_name(fqn: str | None, lower: bool = True) -> str:
    """Простое имя класса (по умолчанию в нижнем регистре) без пакетов и вложенных классов."""
    return _canonical_simple_name(fqn, lower=lower)


class EntitySchema:
    """Виды сущностей манифеста, их ID-поля и простые имена типов для разрешения ссылок шагов."""

    def __init__(self, index: Any = None) -> None:
        self.index = index
        self.manifest: dict[str, EntityKind] = entity_kinds(index) if index is not None else {}
        self._kind_hints: dict[str, tuple[str, ...]] = {
            k: tuple(dict.fromkeys(simple_name(t) for t in ek.types)) for k, ek in self.manifest.items()}
        self._id_fields: dict[str, tuple[str, ...]] = {k: ek.id_fields for k, ek in self.manifest.items()}
        self.user_fields: tuple[str, ...] = _USER_FIELDS
        self._names_aliases: dict[str, tuple[str, ...]] = dict(_NAMES_FIELD_ALIASES)

    @property
    def known_kinds(self) -> set[str]:
        return set(self._id_fields.keys())

    def id_fields(self, kind: str) -> tuple[str, ...]:
        """ID-поля вида: из манифеста; для вида вне манифеста — `<вид>Id`, `<вид>sId` (или без s), `id`."""
        if kind in self._id_fields:
            return self._id_fields[kind]
        k = kind[:1].lower() + kind[1:]
        if k.endswith("s"):
            return (f"{k}Id", f"{k[:-1]}Id", "id")
        return (f"{k}Id", f"{k}sId", "id")

    def primary_id_field(self, kind: str) -> str | None:
        """Главное ID-поле вида (`tripId`, `userId`, `contactsId`): первое из ID-полей."""
        fields = self.id_fields(kind)
        return fields[0] if fields else None

    def kind_hints(self, kind: str) -> tuple[str, ...]:
        """Простые имена типов вида в нижнем регистре: по ним тип объекта относится к виду."""
        return self._kind_hints.get(kind, (kind.lower(),))

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

    def field_aliases(self, name: str, names: bool = False) -> tuple[str, ...]:
        """Алиасы поля DTO для поиска в сущностях предыдущих шагов: по умолчанию — само имя поля, `names` — таблица
        режима отката (--m4-conventions names)."""
        return self._names_aliases.get(name, (name,)) if names else (name,)


__all__ = ["EntitySchema", "simple_name"]
