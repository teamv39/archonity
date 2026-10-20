"""Мир исполнителя M4: типы проекта из скелета и база данных сценария.

База — форк дампа `db-after-warmup` на сценарий. Вызовы репозиториев читают и пишут её строки, поэтому
статус заказа, баланс и созданные сущности следуют из самого исполнения шагов (M3 внутри M4).
Строка таблицы превращается в объект сущности по полям класса из скелета (`@Column`, встраиваемые типы,
enum по порядковому номеру, коллекции в отдельных таблицах).
"""
from __future__ import annotations

import itertools
import re
from pathlib import Path
from typing import Any

from engine.executor.values import UNKNOWN, EnumV, ListV, Obj, OptionalV, equals_value
from engine.manifest import camel_to_snake

_uuid = itertools.count(1)


def snake(name: str) -> str:
    return camel_to_snake(name)


def camel(col: str) -> str:
    head, *rest = col.split("_")
    return head + "".join(p[:1].upper() + p[1:] for p in rest)


def fresh_uuid() -> str:
    """UUID.randomUUID() исполнителя: детерминированный и валидный для UUID.fromString."""
    return f"00000000-0000-4000-8000-{next(_uuid):012d}"


_JAVA_LIT = re.compile(r'"((?:[^"\\]|\\.)*)"|(-?\d+\.\d*|-?\d*\.\d+)[dDfF]?|(-?\d+)[lL]?|(true|false|null)')


def parse_java_args(text: str) -> list[Any]:
    """Литералы аргументов константы enum: `("G", 1)` -> ["G", 1]."""
    out: list[Any] = []
    for m in _JAVA_LIT.finditer(text):
        if m.group(1) is not None:
            out.append(m.group(1))
        elif m.group(2) is not None:
            out.append(float(m.group(2)))
        elif m.group(3) is not None:
            out.append(int(m.group(3)))
        else:
            out.append({"true": True, "false": False, "null": None}[m.group(4)])
    return out


class TypeIndex:
    """Типы проекта из скелета: поля по порядку объявления, колонки, enum-константы, методы."""

    def __init__(self, nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]], targets_root: Path | None,
                 module_roles: str = "skeleton") -> None:
        self.nodes = nodes
        self.types: dict[str, dict[str, Any]] = {}  # type node id -> node
        self.by_fqn: dict[str, list[str]] = {}
        self.by_simple: dict[str, list[str]] = {}
        self.fields: dict[str, list[dict[str, Any]]] = {}  # type node id -> field nodes
        self.methods: dict[str, list[str]] = {}  # type node id -> method ids
        self.super_of: dict[str, str] = {}
        for nid, n in nodes.items():
            k = n.get("kind")
            if k == "type":
                self.types[nid] = n
                fqn = n.get("fqn", "")
                self.by_fqn.setdefault(fqn, []).append(nid)
                simple_name = fqn.rsplit(".", 1)[-1].split("$")[-1]
                self.by_simple.setdefault(simple_name, []).append(nid)
            elif k == "field":
                self.fields.setdefault(n.get("owner", ""), []).append(dict(n, id=nid))
            elif k == "method":
                self.methods.setdefault(n.get("owner", ""), []).append(nid)
        for fl in self.fields.values():
            fl.sort(key=lambda f: f.get("line", 0))
        # Зависимости модулей (depends_on скелета, из pom.xml): модуль -> модули, классы которых он видит
        self.deps: dict[str, list[str]] = {}
        for e in edges:
            if e["type"] == "extends" and e["target"] in nodes:
                self.super_of[e["source"]] = e["target"]
            elif e["type"] == "depends_on":
                self.deps.setdefault(e["source"].removeprefix("module:"), []).append(e["target"].removeprefix("module:"))
        # Общие библиотеки проекта — модули, от которых зависят другие
        self.shared = sorted({m for ms in self.deps.values() for m in ms})
        self.module_roles = module_roles
        self.targets_root = targets_root
        self._enum_consts: dict[str, list[tuple[str, list[Any]]]] = {}
        self._all_fields_cache: dict[str, list[dict[str, Any]]] = {}
        self._method_of_cache: dict[tuple[str, str, int | None], str | None] = {}

    def _prefs(self, module: str | None) -> list[str | None]:
        """Порядок модулей при неоднозначном имени типа: модуль вызывающего, затем его зависимости
        (без известного модуля или зависимостей — общие библиотеки проекта); names — `ts-common`, как до feature/84."""
        if self.module_roles == "names":
            return [module, "ts-common"]
        return [module, *(self.deps.get(module or "") or self.shared)]

    def resolve(self, fqn: str | None, module: str | None = None) -> str | None:
        """ID узла типа по полному имени: сначала модуль вызывающего, потом его зависимости, потом любой."""
        if not fqn:
            return None
        ids = self.by_fqn.get(fqn)
        if not ids:
            return None
        if len(ids) == 1:
            return ids[0]
        for pref in self._prefs(module):
            for i in ids:
                if pref and self.types[i].get("module") == pref:
                    return i
        return ids[0]

    def resolve_simple(self, simple: str, module: str | None) -> str | None:
        """Тип по простому имени в модуле (для instanceof и new без fqn)."""
        cands = self.by_simple.get(simple)
        if not cands:
            return None
        for pref in self._prefs(module):
            for i in cands:
                if self.types[i].get("module") == pref:
                    return i
        return cands[0]

    def all_fields(self, type_id: str | None) -> list[dict[str, Any]]:
        if not type_id:
            return []
        if type_id in self._all_fields_cache:
            return self._all_fields_cache[type_id]
        out: list[dict[str, Any]] = []
        seen = set()
        t = type_id
        while t and t not in seen:
            seen.add(t)
            out = [f for f in self.fields.get(t, []) if "static" not in (f.get("modifiers") or [])] + out
            t = self.super_of.get(t)
        self._all_fields_cache[type_id] = out
        return out

    def is_enum(self, type_id: str | None) -> bool:
        return bool(type_id) and self.types.get(type_id, {}).get("type_kind") == "enum"

    def fqn(self, type_id: str | None) -> str | None:
        return self.types.get(type_id or "", {}).get("fqn")

    def method_of(self, type_id: str | None, name: str, arity: int | None = None) -> str | None:
        """Метод типа (или суперкласса) по имени и числу параметров."""
        if not type_id:
            return None
        key = (type_id, name, arity)
        if key in self._method_of_cache:
            return self._method_of_cache[key]
        seen = set()
        t = type_id
        res: str | None = None
        while t and t not in seen:
            seen.add(t)
            for mid in self.methods.get(t, ()):
                n = self.nodes[mid]
                if n.get("name") != name:
                    continue
                if arity is None or len(n.get("params_as_written") or []) == arity:
                    res = mid
                    break
            if res is not None:
                break
            t = self.super_of.get(t)
        self._method_of_cache[key] = res
        return res

    def enum_constants(self, type_id: str) -> list[tuple[str, list[Any]]]:
        """Константы enum по порядку объявления с литералами аргументов (из исходника по строке поля)."""
        if type_id in self._enum_consts:
            return self._enum_consts[type_id]
        node = self.types.get(type_id, {})
        fqn = node.get("fqn", "")
        consts = [f for f in self.fields.get(type_id, [])
                  if f.get("type") == fqn and {"static", "final"} <= set(f.get("modifiers") or [])]
        lines: list[str] = []
        if self.targets_root is not None and node.get("file"):
            p = self.targets_root / node["file"]
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines = []
        out = []
        for f in consts:
            text = lines[f["line"] - 1] if 0 < f.get("line", 0) <= len(lines) else ""
            m = re.search(re.escape(f["name"]) + r"\s*\((.*)\)", text)
            out.append((f["name"], parse_java_args(m.group(1)) if m else []))
        self._enum_consts[type_id] = out
        return out


def column_of(field: dict[str, Any]) -> str:
    for a in field.get("annotations") or []:
        if a.get("name") in ("Column", "JoinColumn"):
            m = re.search(r'name\s*=\s*"([^"]+)"', a.get("args", ""))
            if m:
                return m.group(1)
    return snake(field["name"])


class World:
    """База сценария и преобразование строк в объекты сущностей."""

    def __init__(self, db: Any, types: TypeIndex, entities: Any, enum_factory: Any) -> None:
        self.db = db
        self.types = types
        self.entities = entities  # EntityFacts
        self.enum_factory = enum_factory  # (type_id, ordinal|name) -> EnumV
        self.table_of: dict[str, str] = {}  # entity fqn -> table
        self.collections_of: dict[str, dict[str, str]] = {}  # entity fqn -> {field: table}
        self.id_field: dict[str, str] = {}
        for e in getattr(entities, "raw_entities", []) or []:
            if e.get("table"):
                self.table_of[e["type"]] = e["table"]
            if e.get("id_field"):
                self.id_field[e["type"]] = e["id_field"]
            self.collections_of[e["type"]] = {c["field"]: c["table"] for c in e.get("collections") or ()}
        # Созданные шагом сущности: [(fqn, obj)] — для ссылок new_of_step_<n>
        self.saved: list[tuple[str, Obj]] = []

    # --- строки и объекты ----------------------------------------------------

    def rows(self, table: str) -> list[dict[str, Any]]:
        return self.db.get_table(table) if self.db is not None else []

    def columns(self, table: str) -> list[str]:
        cols = self.db.get_columns(table) if self.db is not None else []
        if not cols:
            rows = self.rows(table)
            cols = list(rows[0]) if rows else []
        return cols

    def _convert(self, ftype: str | None, raw: Any, module: str | None) -> Any:
        if raw is None:
            return None
        if ftype in ("int", "long", "short", "java.lang.Integer", "java.lang.Long"):
            try:
                return int(float(raw))
            except (TypeError, ValueError):
                return UNKNOWN
        if ftype in ("double", "float", "java.lang.Double", "java.lang.Float", "java.math.BigDecimal"):
            try:
                return float(raw)
            except (TypeError, ValueError):
                return UNKNOWN
        if ftype in ("boolean", "java.lang.Boolean"):
            return bool(int(raw)) if str(raw).isdigit() else str(raw).lower() == "true"
        if ftype == "java.lang.String":
            return str(raw)
        tid = self.types.resolve(ftype, module)
        if tid and self.types.is_enum(tid):
            return self.enum_factory(tid, raw)
        if ftype and ftype.startswith("java.util.Date"):
            return UNKNOWN
        return raw

    def row_to_obj(self, fqn: str, row: dict[str, Any], module: str | None) -> Obj:
        tid = self.types.resolve(fqn, module)
        obj = Obj(fqn, {}, open=True)
        colls = self.collections_of.get(fqn, {})
        for f in self.types.all_fields(tid):
            name, ftype = f["name"], f.get("type")
            col = column_of(f)
            if name in colls:
                obj.fields[name] = self._load_collection(colls[name], row, fqn, module)
            elif col in row:
                obj.fields[name] = self._convert(ftype, row[col], module)
            else:
                sub = self.types.resolve(ftype, module)
                if sub and not self.types.is_enum(sub) and self.types.all_fields(sub):
                    obj.fields[name] = self.row_to_obj(ftype, row, module)
        return obj

    def _load_collection(self, table: str, owner_row: dict[str, Any], fqn: str, module: str | None) -> ListV:
        cols = self.columns(table)
        fk = next((c for c in cols if c.endswith("_id")), None)
        owner_id = owner_row.get(snake(self.id_field.get(fqn, "id"))) or owner_row.get("id")
        if fk is None or owner_id is None:
            return ListV([], exact=False)
        rows = [r for r in self.rows(table) if str(r.get(fk)) == str(owner_id)]
        order = next((c for c in cols if c.endswith("_order")), None)
        if order:
            rows.sort(key=lambda r: r.get(order) or 0)
        val_cols = [c for c in cols if c not in (fk, order)]
        if len(val_cols) == 1:
            return ListV([r.get(val_cols[0]) for r in rows])
        return ListV([Obj(None, {camel(c): r.get(c) for c in val_cols}) for r in rows])

    def obj_to_row(self, fqn: str, obj: Obj, module: str | None) -> dict[str, Any]:
        tid = self.types.resolve(fqn, module)
        row: dict[str, Any] = {}
        colls = self.collections_of.get(fqn, {})
        for f in self.types.all_fields(tid):
            name = f["name"]
            if name in colls:
                continue
            v = obj.get(name)
            if isinstance(v, Obj):
                row.update(self.obj_to_row(v.type or "", v, module))
            elif isinstance(v, EnumV):
                row[column_of(f)] = v.ordinal
            else:
                row[column_of(f)] = v
        return row

    def _save_collections(self, fqn: str, obj: Obj, owner_id: Any) -> None:
        for fname, table in self.collections_of.get(fqn, {}).items():
            val = obj.get(fname)
            if not isinstance(val, ListV):
                continue
            cols = self.columns(table)
            fk = next((c for c in cols if c.endswith("_id")), None)
            order = next((c for c in cols if c.endswith("_order")), None)
            val_cols = [c for c in cols if c not in (fk, order)]
            if fk is None:
                continue
            kept = [r for r in self.rows(table) if str(r.get(fk)) != str(owner_id)]
            self.rows(table)[:] = kept
            for i, item in enumerate(val.items):
                r = {fk: owner_id}
                if order:
                    r[order] = i
                if len(val_cols) == 1:
                    r[val_cols[0]] = item
                elif isinstance(item, Obj):
                    r.update({c: item.get(camel(c)) for c in val_cols})
                self.db.insert(table, r)

    # --- операции репозитория ----------------------------------------------

    def _field_col(self, fqn: str, prop: str, module: str | None) -> tuple[str | None, dict[str, Any] | None]:
        if prop.startswith("#col:"):  # колонка из нативного SQL
            return prop[5:], None
        tid = self.types.resolve(fqn, module)
        for f in self.types.all_fields(tid):
            if f["name"].lower() == prop.lower():
                return column_of(f), f
        return snake(prop), None

    def _match(self, row: dict[str, Any], col: str | None, fdef: dict[str, Any] | None, value: Any,
               module: str | None) -> Any:
        """Совпадает ли строка с условием: True, False или UNKNOWN."""
        if value is UNKNOWN:
            return UNKNOWN
        if isinstance(value, Obj):  # встраиваемый тип (TripId)
            result: Any = True
            sub_tid = self.types.resolve(value.type, module)
            for sf in self.types.all_fields(sub_tid):
                sc = column_of(sf)
                if sc not in row:
                    return UNKNOWN
                r = self._match(row, sc, sf, value.get(sf["name"]), module)
                if r is False:
                    return False
                if r is UNKNOWN:
                    result = UNKNOWN
            return result
        if col not in row:
            return UNKNOWN
        raw = row[col]
        if isinstance(value, EnumV):
            if isinstance(raw, int):
                return value.ordinal == raw if value.ordinal is not None else UNKNOWN
            return str(raw) == value.constant
        if isinstance(value, ListV):
            if not value.exact:
                return UNKNOWN
            if any(x is UNKNOWN for x in value.items):
                return UNKNOWN
            vals = [str(x).casefold() for x in value.items]
            return str(raw).casefold() in vals
        if isinstance(value, bool):
            return bool(raw) == value
        if isinstance(value, (int, float)) and isinstance(raw, (int, float, str)):
            try:
                return float(raw) == float(value)
            except ValueError:
                return False
        if isinstance(value, str) or value is None:
            # MySQL: сравнение строк по умолчанию без учёта регистра (collation *_ci)
            return (raw is None) if value is None else str(raw).casefold() == value.casefold()
        return UNKNOWN

    def select(self, fqn: str, conds: list[tuple[str, Any]], module: str | None) -> tuple[list[Obj], bool]:
        """Строки сущности под условиями [(свойство, значение)]. Возвращает (объекты, точно ли)."""
        table = self.table_of.get(fqn)
        if table is None:
            return [], False
        exact = True
        out: list[Obj] = []
        resolved = [(self._field_col(fqn, p, module), v) for p, v in conds]
        for row in self.rows(table):
            ok: Any = True
            for (col, fdef), v in resolved:
                r = self._match(row, col, fdef, v, module)
                if r is False:
                    ok = False
                    break
                if r is UNKNOWN:
                    ok = UNKNOWN
            if ok is False:
                continue
            if ok is UNKNOWN:
                exact = False
            out.append(self.row_to_obj(fqn, row, module))
        return out, exact

    def save(self, fqn: str, obj: Any, module: str | None) -> bool:
        """Вставка или обновление по ключу. Возвращает True, если строка новая."""
        table = self.table_of.get(fqn)
        if table is None or not isinstance(obj, Obj):
            return False
        id_field = self.id_field.get(fqn, "id")
        oid = obj.get(id_field)
        if oid is None or oid is UNKNOWN:
            if oid is None:
                oid = fresh_uuid()
                obj.fields[id_field] = oid
        row = self.obj_to_row(fqn, obj, module)
        id_col, _ = self._field_col(fqn, id_field, module)
        rows = self.rows(table)
        if oid is not UNKNOWN:
            for r in rows:
                if str(r.get(id_col)) == str(oid):
                    r.update({k: v for k, v in row.items() if v is not UNKNOWN})
                    self._save_collections(fqn, obj, oid)
                    return False
        self.db.insert(table, {k: v for k, v in row.items() if v is not UNKNOWN})
        if oid is not UNKNOWN:
            self._save_collections(fqn, obj, oid)
        self.saved.append((fqn, obj))
        return True

    def delete(self, fqn: str, conds: list[tuple[str, Any]], module: str | None) -> int:
        table = self.table_of.get(fqn)
        if table is None:
            return 0
        resolved = [(self._field_col(fqn, p, module), v) for p, v in conds]
        rows = self.rows(table)
        keep = []
        n = 0
        for row in rows:
            if resolved and all(self._match(row, c, f, v, module) is True for (c, f), v in resolved):
                n += 1
                continue
            keep.append(row)
        rows[:] = keep
        return n


# --- разбор имён производных запросов Spring Data ---------------------------

_PREFIXES = ("findAllBy", "findBy", "getBy", "readBy", "queryBy", "existsBy", "countBy", "deleteAllBy",
             "deleteBy", "removeBy", "findFirstBy", "findTopBy")


def derived_props(name: str) -> tuple[str, list[str]] | None:
    """`findByAccountIdAndStatus` -> ("find", ["accountId", "status"]); None — не производный запрос."""
    for p in _PREFIXES:
        if name.startswith(p) and len(name) > len(p):
            rest = name[len(p):]
            rest = re.sub(r"OrderBy\w+$", "", rest)
            parts = re.split(r"And(?=[A-Z])", rest)
            props = [x[:1].lower() + x[1:] for x in parts if x]
            props = [re.sub(r"(In|IsNull|IsNotNull|Containing|Like)$", "", x) for x in props]
            return p.replace("By", "").replace("All", "").replace("First", "").replace("Top", ""), props
    return None


_SQL_WHERE = re.compile(r"\bwhere\b(.*)$", re.IGNORECASE | re.DOTALL)
_SQL_COND = re.compile(r"(\w+)\s*(=|in)\s*\?(\d+)", re.IGNORECASE)


def native_query_conds(sql: str) -> list[tuple[str, int]] | None:
    """`SELECT * FROM t WHERE a = ?1 AND b in ?2` -> [("a", 0), ("b", 1)] (колонки, индексы аргументов)."""
    m = _SQL_WHERE.search(sql)
    if not m:
        return []
    where = m.group(1)
    if re.search(r"\bor\b", where, re.IGNORECASE):
        return None
    return [(c.group(1), int(c.group(3)) - 1) for c in _SQL_COND.finditer(where)]


def optional_of(objs: list[Obj], exact: bool, fqn: str) -> OptionalV:
    """Optional результата: при неточном условии наличие строки неизвестно, а сама строка — любая (поля UNKNOWN)."""
    if objs and exact:
        return OptionalV(objs[0])
    if not objs and exact:
        return OptionalV(None)
    if not objs:
        return OptionalV(None)
    if len(objs) == 1:
        return OptionalV(objs[0], maybe=True)
    return OptionalV(Obj(fqn, {}, open=True), maybe=True)


__all__ = [
    "TypeIndex", "World", "derived_props", "native_query_conds", "optional_of", "fresh_uuid", "snake", "camel",
    "column_of", "equals_value",
]
