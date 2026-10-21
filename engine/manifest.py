"""Манифест сущностей проекта из скелета (ADR-007, решения 2 и 3): без LLM и без archparse.

Вид сущности — имя типа, который хранит JPA: класс с `@Entity` или `@Embeddable`, простое имя с первой
строчной буквой (`TrainType` -> `trainType`). Классы с одним простым именем в разных модулях (`Order` в
`ts-order-service` и `ts-order-other-service`) — один вид; конкретный класс исполнитель выбирает по модулю шага.

ID-поля вида (решение 2): поля `@Id`/`@EmbeddedId` его классов, если это не `id`; затем `<вид>Id`; затем `id`.
Так ссылку на сущность можно найти и в самой сущности (`id`, `userId`), и в DTO других сервисов (`trainTypeId`).

Таблица вида — узел `res:table:<схема>.<имя>` скелета: имя из `@Table(name)` (или `@Entity(name)`), иначе имя
класса по правилу именования Spring Boot (`TrainType` -> `train_type`); схема — `@Table(schema)`, иначе модуль.
Таблицы коллекций (`@ElementCollection`) сюда не входят: это не виды.

Манифест читают M4 (`EntitySchema`: виды и ID-поля) и M1 (список видов для схемы ответа `select`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

ENTITY_ANNOTATIONS = ("Entity", "Embeddable")
ID_ANNOTATIONS = ("Id", "EmbeddedId")


@dataclass(frozen=True)
class EntityKind:
    kind: str                      # "trainType"
    types: tuple[str, ...]         # FQN классов с этим простым именем
    id_fields: tuple[str, ...]     # по решению 2: @Id (если не id), <вид>Id, id
    tables: tuple[str, ...]        # ID узлов таблиц из @Table или имени класса


def kind_name(simple: str) -> str:
    """Вид по простому имени класса: первая буква строчная (`TrainType` -> `trainType`)."""
    return simple[:1].lower() + simple[1:]


def entity_kinds(ix: Any) -> dict[str, EntityKind]:
    """Виды сущностей проекта по аннотациям узлов скелета (`ix.N` — узлы `SkeletonIndex`), по имени вида."""
    nodes: dict[str, dict[str, Any]] = getattr(ix, "N", None) or {}
    types: dict[str, dict[str, Any]] = {
        nid: n for nid, n in nodes.items()
        if n.get("kind") == "type" and _annotation(n, *ENTITY_ANNOTATIONS) is not None
    }
    ids: dict[str, list[str]] = {}
    for n in nodes.values():
        if n.get("kind") == "field" and n.get("owner") in types and _annotation(n, *ID_ANNOTATIONS) is not None:
            ids.setdefault(n["owner"], []).append(n.get("name", ""))

    by_kind: dict[str, list[str]] = {}
    for nid in sorted(types):
        by_kind.setdefault(kind_name(_simple(_fqn(nid, types[nid]))), []).append(nid)

    out: dict[str, EntityKind] = {}
    for kind in sorted(by_kind):
        tids = by_kind[kind]
        own = sorted({f for t in tids for f in ids.get(t, ()) if f and f != "id"})
        tables = [t for t in (_table(nid, types[nid]) for nid in tids) if t in nodes]
        out[kind] = EntityKind(
            kind=kind,
            types=tuple(sorted(_fqn(t, types[t]) for t in tids)),
            id_fields=tuple(dict.fromkeys([*own, f"{kind}Id", "id"])),
            tables=tuple(sorted(set(tables))),
        )
    return out


def _annotation(n: dict[str, Any], *names: str) -> dict[str, Any] | None:
    for a in n.get("annotations") or ():
        a = a if isinstance(a, dict) else {"name": a, "args": ""}
        if a.get("name") in names:
            return a
    return None


def _fqn(nid: str, n: dict[str, Any]) -> str:
    return n.get("fqn") or nid.split(":", 2)[-1]


def simple_name(fqn: str | None, lower: bool = False) -> str:
    """Простое имя класса без пакетов и вложенных классов."""
    s = (fqn or "").rsplit(".", 1)[-1].split("$")[-1]
    return s.lower() if lower else s


_simple = simple_name


def _ann_arg(a: dict[str, Any] | None, key: str) -> str | None:
    """Строковый аргумент аннотации верхнего уровня: `name` в `@Table(name = "x", indexes = {@Index(name = ..)})`."""
    if a is None:
        return None
    args = a.get("args") or ""
    prev = None
    while prev != args:  # вложенные аннотации и массивы аргументов не учитываем
        prev, args = args, re.sub(r"\{[^{}]*\}|@\w+\([^()]*\)", "", args)
    m = re.search(rf"\b{key}\s*=\s*\"([^\"]*)\"", args)
    return m.group(1) if m and m.group(1) else None


def camel_to_snake(name: str) -> str:
    """Имя таблицы по умолчанию в Spring Boot (CamelCaseToUnderscoresNamingStrategy): `TrainType` -> `train_type`."""
    s = name.replace(".", "_")
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", s).lower()


_physical_name = camel_to_snake


def _table(nid: str, n: dict[str, Any]) -> str:
    """Узел таблицы сущности: `res:table:<схема>.<имя>`."""
    table = _annotation(n, "Table")
    name = _ann_arg(table, "name") or _ann_arg(_annotation(n, "Entity"), "name") \
        or _physical_name(_simple(_fqn(nid, n)))
    schema = _ann_arg(table, "schema") or n.get("module", "")
    return f"res:table:{schema}.{name}"


__all__ = ["EntityKind", "entity_kinds", "kind_name", "simple_name", "camel_to_snake"]
