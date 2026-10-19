"""Конструкторы сущностей при загрузке строк Hibernate (правило R7) по фактам archparse.

archparse (`--mode entities`) пишет `data/entity_ir.json`: сущности JPA, вызовы репозиториев с видом
операции и ожиданием успешного пути (ROWS / EMPTY / UNKNOWN), IR тел конструкторов без аргументов.
Здесь факты привязываются к скелету: вызов репозитория -> call_site -> таблицы `data_access`,
сущность -> её таблица и конструктор. Решение «исполнился ли конструктор» принимает `hydration`.

Когда Hibernate создаёт экземпляр сущности конструктором без аргументов:
- чтение (`find*`, своё `@Query`), если запрос вернул строки;
- удаление (`delete*`): Spring Data сначала загружает строку;
- `save` сущности с заданным id: Spring Data делает merge, Hibernate создаёт управляемую копию.

Конструктор с пустым телом не исполняется: `Contacts#<init>()` в эталоне S0 нет, хотя контакты грузятся.
Попадёт ли исполненный конструктор в ответ, решает проекция `engine/projection.py` (ADR-006).

Таблица ленивой коллекции при чтении (правило R10) идёт в ответ, только если метод загрузил коллекцию сам
(`collection_table_loaded`).

`list.contains(x)` на результате чтения вызывает рукописный `x.equals(элемент)` сущности (блок 8 плана archparse):
исполняется, если чтение вернуло строки (`element_callbacks`, решение в `GraphBuilder._element_callbacks`).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

DEFAULT_ENTITY_IR_PATH = Path(__file__).resolve().parent.parent / "data" / "entity_ir.json"

# Колонки владельца строки: по ним строки таблицы относятся к пользователю сценария
OWNER_COLUMNS = (
    "account_id",
    "user_id",
    "owner_id",
    "account",
    "user",
    "customer_id",
    "member_id",
    "client_id",
    "author_id",
)

# Таблицы, строки которых модель состояния ведёт сама (создаются шагами сценария)
STATE_TRACKED_TABLES = ("orders", "orders_other", "contacts")


@dataclass(frozen=True)
class Entity:
    type: str
    module: str
    table: str | None
    id_field: str | None
    no_arg_ctor: str | None
    ctor_statements: int
    embedded: tuple[str, ...]
    # Коллекции в отдельных таблицах: имя таблицы -> (поле, LAZY | EAGER)
    collections: dict[str, tuple[str, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class RepositoryCall:
    method: str
    line: int
    col: int
    callee: str
    operation: str
    expects: str | None
    expects_reason: str | None
    id_assigned: bool | None
    id_assigned_reason: str | None
    entity: Entity | None
    tables: frozenset[str]
    main_table: str | None
    ctors: tuple[str, ...] = field(default=())
    # Таблицы ленивых коллекций сущности среди tables: ID узла таблицы -> поле коллекции
    lazy_tables: dict[str, str] = field(default_factory=dict)
    # Для READ: поля ленивых коллекций, которые метод загрузил сам (None — archparse не определил)
    collections_loaded: tuple[str, ...] | None = None
    collections_loaded_reason: tuple[str, ...] = field(default=())
    # Для READ: (метод сущности, вызов библиотеки) — list.contains(x) вызывает x.equals(элемент)
    element_callbacks: tuple[tuple[str, str], ...] = field(default=())


@dataclass(frozen=True)
class Hydration:
    """Решение по вызову репозитория: какие конструкторы исполнились и почему."""

    ctors: tuple[str, ...]
    rule: str


class EntityFacts:
    """Факты archparse о сущностях, привязанные к скелету."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        data = data or {}
        self.raw_entities: list[dict[str, Any]] = data.get("entities") or []
        self.raw_calls: list[dict[str, Any]] = data.get("repository_calls") or []
        self.constructors: list[dict[str, Any]] = data.get("constructors") or []
        self.ctor_statements: dict[str, int] = data.get("no_arg_ctor_statements") or {}
        self.entities: dict[str, Entity] = {}
        self.calls_by_method: dict[str, list[RepositoryCall]] = {}
        # Конструкторы, в теле которых есть вызов проектного метода (ребро calls скелета или enum-вызов IR)
        self.ctors_with_project_calls: frozenset[str] = frozenset()

    @classmethod
    def load(cls, path: str | Path | None = None) -> EntityFacts:
        p = Path(path) if path else DEFAULT_ENTITY_IR_PATH
        try:
            with open(p, encoding="utf-8") as f:
                return cls(json.load(f))
        except (OSError, ValueError) as e:
            LOGGER.warning("Не удалось загрузить entity_ir.json, правило загрузки сущностей выключено: %s", e)
            return cls()

    def bind(self, nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        """Привязка к скелету: call_site по (file, line, col), таблицы data_access, ID конструкторов."""
        cs_by_pos: dict[tuple[str, int, int], str] = {}
        for nid, n in nodes.items():
            if n.get("kind") == "call_site":
                cs_by_pos[(n.get("file", ""), n.get("line", 0), n.get("col", 0))] = nid
        tables_by_cs: dict[str, set[str]] = {}
        calls_from_cs: set[str] = set()
        for e in edges:
            if e["type"] == "data_access":
                tables_by_cs.setdefault(e["source"], set()).add(e["target"])
            elif e["type"] == "calls":
                calls_from_cs.add(e["source"])

        with_calls = set()
        for ir in self.constructors:
            for c in ir.get("calls") or []:
                cs = cs_by_pos.get((c.get("file", ""), c.get("line", 0), c.get("col", 0)))
                if c.get("kind") == "ENUM" or (cs is not None and cs in calls_from_cs):
                    with_calls.add(ir.get("method_id", ""))
                    break
        self.ctors_with_project_calls = frozenset(with_calls)

        for d in self.raw_entities:
            self.entities[d["type"]] = Entity(
                type=d["type"],
                module=d.get("module", ""),
                table=d.get("table"),
                id_field=d.get("id_field"),
                no_arg_ctor=d.get("no_arg_ctor") if d.get("no_arg_ctor") in nodes else None,
                ctor_statements=int(d.get("ctor_statements") or 0),
                embedded=tuple(d.get("embedded") or ()),
                collections={c["table"]: (c["field"], c.get("fetch", "LAZY")) for c in d.get("collections") or ()},
            )

        unmatched = 0
        for d in self.raw_calls:
            cs = cs_by_pos.get((d["file"], d["line"], d["col"]))
            if cs is None:
                unmatched += 1
                continue
            method = nodes[cs]["method"]
            tables = frozenset(tables_by_cs.get(cs, ()))
            entity = self.entities.get(d.get("entity") or "")
            main_table = None
            lazy_tables: dict[str, str] = {}
            if entity and entity.table:
                main_table = next((t for t in tables if nodes.get(t, {}).get("name") == entity.table), None)
            if entity:
                for t in tables:
                    coll = entity.collections.get(nodes.get(t, {}).get("name", ""))
                    if coll and coll[1] == "LAZY":
                        lazy_tables[t] = coll[0]
            loaded = d.get("collections_loaded")
            call = RepositoryCall(
                method=method,
                line=d["line"],
                col=d["col"],
                callee=d.get("callee", ""),
                operation=d.get("operation", "READ"),
                expects=d.get("expects"),
                expects_reason=d.get("expects_reason"),
                id_assigned=d.get("id_assigned"),
                id_assigned_reason=d.get("id_assigned_reason"),
                entity=entity,
                tables=tables,
                main_table=main_table,
                ctors=self._ctors_of(entity, nodes),
                lazy_tables=lazy_tables,
                collections_loaded=None if loaded is None else tuple(loaded),
                collections_loaded_reason=tuple(d.get("collections_loaded_reason") or ()),
                element_callbacks=tuple(
                    (cb["method"], cb.get("via", "")) for cb in d.get("element_callbacks") or () if cb.get("method") in nodes
                ),
            )
            self.calls_by_method.setdefault(method, []).append(call)
        if unmatched:
            LOGGER.warning("entity_ir.json: %d вызовов репозиториев без call_site в скелете", unmatched)

    def collection_table_loaded(self, method: str, table: str) -> tuple[bool, str] | None:
        """Ушёл ли SQL к таблице ленивой коллекции, пока метод на стеке (R10).

        Ленивую коллекцию Hibernate читает при первом обращении к её элементам. Если метод только вернул
        сущность, коллекцию загрузит сериализация ответа после возврата, проектного кадра с этой таблицей
        в `data_access` на стеке уже нет. Запись (save, delete) трогает таблицу коллекции сама.
        None — таблица не ленивая коллекция ни у одного вызова метода, решение не наше.
        """
        calls = [c for c in self.calls_by_method.get(method, ()) if table in c.tables]
        if not calls or not any(table in c.lazy_tables for c in calls):
            return None
        for c in calls:
            coll = c.lazy_tables.get(table)
            if coll is None:
                return True, f"R10:not_lazy_at_line_{c.line}"
            if c.operation != "READ":
                return True, f"R10:{c.operation.lower()}_writes_collection(line {c.line})"
            if c.collections_loaded is None:
                return True, f"R10:loaded_unknown(line {c.line})"
            if coll in c.collections_loaded:
                why = next((r for r in c.collections_loaded_reason if f".get{coll[:1].upper()}{coll[1:]}()" in r), "")
                return True, f"R10:loaded({why})"
        lines = ",".join(str(c.line) for c in calls)
        return False, f"R10:lazy_not_loaded(lines {lines})"

    def allowed_ctors(self, mode: str) -> frozenset[str] | None:
        """Конструкторы, которые исполняются при загрузке в режиме `RuntimeRules.constructors`.

        None — все с непустым телом (caller_only: в ответ их отбирает проекция по исполненным вызовам);
        all — как до ADR-006, только с вызовом проектного метода в теле; off — ни одного.
        """
        if mode == "all":
            return self.ctors_with_project_calls
        if mode == "off":
            return frozenset()
        return None

    def _ctors_of(self, entity: Entity | None, nodes: dict[str, dict[str, Any]]) -> tuple[str, ...]:
        """Конструкторы с непустым телом, которые Hibernate вызывает при создании экземпляра сущности."""
        if entity is None:
            return ()
        out: list[str] = []
        if entity.no_arg_ctor and entity.ctor_statements > 0:
            out.append(entity.no_arg_ctor)
        for emb in entity.embedded:
            for mid, n in self.ctor_statements.items():
                if mid.endswith(f":{emb}#<init>()") and n > 0 and mid in nodes:
                    out.append(mid)
        return tuple(out)


def hydration(
    call: RepositoryCall,
    state: Any,
    table_db_name: Any,
    is_new_user: bool = False,
    allowed: frozenset[str] | None = None,
) -> Hydration:
    """Исполнились ли конструкторы сущности на этом вызове репозитория.

    `table_db_name` переводит ID узла таблицы в имя таблицы дампа.
    `allowed` — конструкторы, которые допускает режим правила (None — все с непустым телом).
    """
    if not call.ctors:
        return Hydration((), "R7:no_ctor_body")
    if allowed is not None and not any(c in allowed for c in call.ctors):
        return Hydration((), "R7:mode_excludes_ctor")
    if allowed is not None:
        call = replace(call, ctors=tuple(c for c in call.ctors if c in allowed))
    op = call.operation
    if op == "SAVE":
        # id_assigned: True — merge, Hibernate создаёт управляемую копию конструктором; False — persist;
        # None (сущность пришла параметром или id не выводится) трактуем как persist: на сценариях S1–S7
        # такие save идут после чтения той же сущности в том же методе (findById перед save),
        # либо конструктор пустой, так что конструктор уже в ответе по другому пути.
        if call.id_assigned:
            return Hydration(call.ctors, f"R7:save_merge({call.id_assigned_reason})")
        return Hydration((), f"R7:save_persist({call.id_assigned_reason or 'id unknown'})")
    if op == "READ":
        if call.expects == "EMPTY":
            return Hydration((), f"R7:read_expects_empty({call.expects_reason})")
        has_rows, why = rows_exist(call, state, table_db_name, is_new_user)
        if not has_rows:
            return Hydration((), f"R7:read_no_rows({why})")
        return Hydration(call.ctors, f"R7:read({why})")
    if op == "DELETE":
        has_rows, why = rows_exist(call, state, table_db_name, is_new_user)
        if not has_rows:
            return Hydration((), f"R7:delete_no_rows({why})")
        return Hydration(call.ctors, f"R7:delete_loads({why})")
    return Hydration((), f"R7:{op.lower()}_no_entity")


def rows_exist(call: RepositoryCall, state: Any, table_db_name: Any, is_new_user: bool = False) -> tuple[bool, str]:
    """Есть ли строки в таблице сущности по состоянию сценария перед шагом.

    Таблица с колонкой владельца (account_id, user_id), которая не является ключом сущности, хранит
    строки пользователя сценария: заказы и контакты берём из модели состояния, остальное из дампа.
    Справочники (маршруты, станции, поезда) и таблица самого пользователя — непустой дамп.
    Без дампа модели состояния верим только для нового пользователя: всё его создано в сценарии.
    """
    table = call.main_table
    if table is None:
        return True, "table unknown"
    name = table_db_name(table)
    if state is None:
        return True, f"{name}: no state"
    db = getattr(state, "db_state", None)
    if db is None or not hasattr(db, "table_names") or not db.table_names():
        if is_new_user and name in STATE_TRACKED_TABLES:
            mine = _state_rows(name, state, account=None)
            return bool(mine), f"{name}: no dump, {len(mine)} rows of new user in state"
        return True, f"{name}: no dump"
    rows = db.get_table(name) if hasattr(db, "get_table") else []
    columns = db.get_columns(name) if hasattr(db, "get_columns") else []
    id_column = _snake(call.entity.id_field) if call.entity and call.entity.id_field else None
    owner = next((c for c in OWNER_COLUMNS if c in columns and c != id_column), None)
    account = getattr(state, "account_id", None)

    if owner is None:
        return bool(rows), f"{name}: {len(rows)} rows in dump"
    if name in STATE_TRACKED_TABLES:
        mine = _state_rows(name, state, account)
        return bool(mine), f"{name}: {len(mine)} rows of user in state"
    mine = [r for r in rows if r.get(owner) == account]
    return bool(mine), f"{name}: {len(mine)} rows of user in dump"


def _state_rows(name: str, state: Any, account: str | None) -> list[dict[str, Any]]:
    """Строки таблицы, которые ведёт модель состояния (account=None — без фильтра по пользователю)."""
    if name in ("orders", "orders_other") and hasattr(state, "get_orders"):
        from engine.state import TrainType

        other = TrainType.from_table(name) == TrainType.Other
        return [o for o in state.get_orders(account_id=account) if (o.get("train_type") == TrainType.Other) == other]
    if hasattr(state, "get_contacts"):
        return state.get_contacts("all" if account is None else account)
    return []


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).lower()
