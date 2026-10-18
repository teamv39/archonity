"""Вызов репозитория Spring Data в исполнителе M4: события SQL и результат из состояния (ADR-005, M4).

Рёбра data — от метода с call_site репозитория к таблицам его `data_access` (R10), таблицы ленивых коллекций —
только если метод их загрузил (`EntityFacts.collection_table_loaded`). Конструкторы сущностей при загрузке строк
(R7) решает `engine.entities.hydration`, тела конструкторов исполняются по IR. Результат чтения — строки дампа
и состояния M3 по аргументам finder-метода; если аргументы неизвестны — `Unknown` с подсказкой `expects`
(D2–D4: чего ждёт успешный путь).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from engine.entities import RepositoryCall, hydration
from engine.executor import library
from engine.executor.values import MISSING, NONNULL, Coll, Obj, Opt, Unknown, is_unknown, simple_name

if TYPE_CHECKING:
    from engine.executor.interp import Frame, StepRun

MAX_ROWS = 20
FINDER = re.compile(r"^(?:find|get|query|read|search|stream|count|exists|delete|remove)"
                    r"(?:All|First|Top\d*|Distinct)?By(.+)$")
OPERATOR_SUFFIX = re.compile(r"(Between|LessThan|LessThanEqual|GreaterThan|GreaterThanEqual|Before|After|Like|"
                             r"NotLike|Containing|StartingWith|EndingWith|In|NotIn|Not|IsNull|IsNotNull|Null|NotNull|"
                             r"True|False|IgnoreCase|Exists)$")
OR_SPLIT = re.compile(r"Or(?=[A-Z])")


def call(run: StepRun, frame: Frame, node: dict[str, Any], recv: Any, args: list[Any], rc: RepositoryCall | None,
         tables: list[str], line: int, col: int) -> Any:
    included: list[str] = []
    for t in sorted(tables):
        loaded = run.ex.collection_table_loaded(frame.method_id, t)
        if loaded is not None and not loaded[0]:
            run.prune("data", frame.method_id, t, "STATE", loaded[1], line=line, col=col)
            continue
        if run.emit("data", frame, t, line=line, col=col, extra=("STATE", loaded[1]) if loaded else None):
            included.append(t)
    if rc is not None and not run.silent:
        hydrate(run, frame, rc, included)
    return result(run, frame, node, args, rc, tables)


def hydrate(run: StepRun, frame: Frame, rc: RepositoryCall, included: list[str]) -> None:
    """Конструкторы сущности, которые Hibernate вызвал на этом вызове (R7): исполнение без ребра calls."""
    entities = run.index.entities
    mode = getattr(run.ex.builder.rules, "entity_constructors_on_load", "project_calls")
    if mode == "off":
        return
    table = next((t for t in sorted(rc.tables) if t in included), None)
    if table is None:
        return
    is_new_user = bool(getattr(run.state, "is_new_user", False) or getattr(run.profile, "is_new_user", False))
    decision = hydration(rc, run.state, run.index.table_resource_to_db, is_new_user,
                         allowed=entities.allowed_ctors(mode))
    via = f"data|{frame.method_id}|{rc.main_table or table}"
    if not decision.ctors:
        if run.ctx.ledger is not None and rc.entity and rc.entity.no_arg_ctor and rc.entity.ctor_statements > 0:
            run.ctx.ledger.prune("executes", f"scenario:{run.ctx.ledger.scenario_id}", rc.entity.no_arg_ctor,
                                 "STATE", decision.rule, via=via, line=rc.line, col=rc.col)
        return
    for ctor in decision.ctors:
        owner = run.program.N.get(ctor, {}).get("owner", "")
        obj = Obj(run.program.N.get(owner, {}).get("fqn", ""), src="new", origin="entity loaded by Hibernate")
        run.invoke(ctor, frame.unit, [], this=obj, caller=frame, via=via, call_line=rc.line,
                   reason=("STATE", decision.rule))


def result(run: StepRun, frame: Frame, node: dict[str, Any], args: list[Any], rc: RepositoryCall | None,
           tables: list[str]) -> Any:
    callee = node.get("callee", "")
    op = rc.operation if rc is not None else _operation(callee)
    shape = _shape(run, node, callee)
    if op == "SAVE":
        return args[0] if args else None
    if op == "DELETE" or shape == "void":
        return None
    if op == "MODIFY":
        return Unknown(f"rows updated by {callee}", "number", src="repo")
    entity_type = rc.entity.type if rc is not None and rc.entity else None
    table = (rc.main_table if rc is not None else None) or (sorted(tables)[0] if tables else None)
    target = next(iter(run.program.edges(node.get("call"), "calls")), None)
    rows = query_rows(run, frame, table, entity_type, callee, args, target)
    origin = f"{callee}({', '.join(_desc(a) for a in args)}) in {simple_name(entity_type) or 'repository'}"
    if rows is None:
        return _unknown_result(op, shape, rc, origin, entity_type)
    if op == "EXISTS":
        return bool(rows)
    if op == "COUNT":
        return len(rows)
    objs = [row_obj(run, frame, entity_type, r) for r in rows[:MAX_ROWS]]
    if shape == "optional":
        return Opt(bool(rows), objs[0] if objs else None, origin, "state")
    if shape == "list":
        return Coll(objs, origin=origin, src="state", elem_type=entity_type)
    return objs[0] if objs else None


def _operation(callee: str) -> str:
    for prefix, op in (("save", "SAVE"), ("delete", "DELETE"), ("remove", "DELETE"), ("exists", "EXISTS"),
                       ("count", "COUNT")):
        if callee.startswith(prefix):
            return op
    return "READ"


def _shape(run: StepRun, node: dict[str, Any], callee: str) -> str:
    """Форма результата: по типу возврата метода репозитория в скелете, иначе по имени."""
    p = run.program
    ret = ""
    for t in p.edges(node.get("call"), "calls"):
        ret = p.N.get(t, {}).get("return_raw") or p.N.get(t, {}).get("return") or ""
        if ret:
            break
    s = simple_name(ret)
    if s == "Optional" or (not ret and callee == "findById"):
        return "optional"
    if s in ("List", "ArrayList", "Set", "Collection", "Iterable", "Page") or ret.endswith("[]") or (
            not ret and callee.startswith("findAll")):
        return "list"
    if s == "void":
        return "void"
    return "single"


def _desc(v: Any) -> str:
    if isinstance(v, str):
        return repr(v[:40])
    if is_unknown(v):
        return "?"
    if isinstance(v, Obj):
        return v.simple
    return repr(v)


def _unknown_result(op: str, shape: str, rc: RepositoryCall | None, origin: str, entity_type: str | None) -> Any:
    """Результат с неизвестными аргументами: что ждёт успешный путь (expects archparse), D2–D4."""
    expects = rc.expects if rc is not None else None
    present = True if expects == "ROWS" else False if expects == "EMPTY" else MISSING
    if op == "EXISTS":
        return Unknown(f"{origin} finds rows", "bool", present, src="repo", rule="D3" if present is not MISSING
                       else None)
    if op == "COUNT":
        return Unknown(f"count of {origin}", "number", src="repo")
    if shape == "optional":
        flag = Unknown(f"{origin} finds a row", "bool", present, src="repo",
                       rule="D3" if present is not MISSING else None)
        return Opt(flag, Unknown(f"row of {origin}", "object", NONNULL, src="repo", type=entity_type, rule="D2"),
                   origin, "repo")
    if shape == "list":
        flag = Unknown(f"{origin} returns rows", "bool", present, src="repo",
                       rule="D4" if present is not MISSING else None)
        return Coll(None, flag, origin, "repo", entity_type)
    default = None if expects == "EMPTY" else NONNULL
    return Unknown(f"row of {origin}", "object", default, src="repo", type=entity_type, rule="D2")


def query_rows(run: StepRun, frame: Frame, table: str | None, entity_type: str | None, callee: str,
               args: list[Any], target: str | None = None) -> list[dict[str, Any]] | None:
    """Строки таблицы по finder-методу Spring Data или простому нативному @Query; None — не определить
    (аргумент неизвестен, сложный запрос)."""
    db = getattr(run.state, "db_state", None)
    if table is None or db is None or not hasattr(db, "get_table"):
        return None
    name = run.index.table_resource_to_db(table)
    rows = db.get_table(name)
    columns = set(db.get_columns(name)) if hasattr(db, "get_columns") else set()
    if callee in ("findAll", "count") and not args:
        return list(rows)
    native = native_query(run, target)
    if native is not None:
        filters: list[tuple[str, Any]] = []
        for col, op, i in native:
            arg = args[i - 1] if 0 < i <= len(args) else None
            value = _in_values(arg) if op == "in" else (None if is_unknown(arg) or isinstance(arg, (Obj, Coll)) else arg)
            if value is None or (columns and col not in columns):
                return None
            filters.append((col, value))
        return [r for r in rows if all(cell_matches(r.get(c), v) for c, v in filters)]
    if callee in ("findById", "existsById", "deleteById", "getById", "getOne"):
        props = ["Id"]
    else:
        m = FINDER.match(callee)
        if not m:
            return None
        body = m.group(1).split("OrderBy", 1)[0]
        if OR_SPLIT.search(body):
            return None
        props = [p for p in re.split(r"And(?=[A-Z])", body) if p]
        if any(OPERATOR_SUFFIX.search(p) and not (p.endswith("In") and not p.endswith("NotIn")) for p in props):
            return None
    if len(props) != len(args):
        return None
    tn = run.program.type_node(entity_type or "", run.program.module_of(frame.method_id)) if entity_type else None
    filters = []
    for prop, arg in zip(props, args):
        arg = arg.fields.get("v") if isinstance(arg, Obj) and arg.simple == "UUID" else arg
        if prop.endswith("In"):  # findByStationNameIn(List): IN по свойству
            col, value = column_of(run, tn, prop[:-2]), _in_values(arg)
            if col is None or value is None or (columns and col not in columns):
                return None
            filters.append((col, value))
            continue
        if isinstance(arg, Obj) and arg.src not in ("enum", "bean") and arg.type != library.DATE_TYPE:
            # Встроенный объект (@Embedded TripId): колонки его полей в строке сущности
            sub = embedded_filters(run, tn, prop, arg, columns)
            if sub is None:
                return None
            filters.extend(sub)
            continue
        if is_unknown(arg) or isinstance(arg, Coll) or (isinstance(arg, Obj) and not _comparable(arg)):
            return None
        col = column_of(run, tn, prop)
        if col is None or (columns and col not in columns):
            return None
        filters.append((col, arg))
    return [r for r in rows if all(cell_matches(r.get(c), v) for c, v in filters)]


class InValues:
    """Условие `колонка IN (...)` нативного @Query или finder'а с суффиксом In."""

    def __init__(self, values: list[Any]) -> None:
        self.values = {_key(x) for x in values}


def _in_values(arg: Any) -> InValues | None:
    if not isinstance(arg, Coll) or arg.items is None or any(
            x is None or is_unknown(x) or isinstance(x, (Obj, Coll)) for x in arg.items):
        return None
    return InValues(arg.items)


NATIVE_SELECT = re.compile(r"^\s*SELECT\s+\*\s+FROM\s+(\w+)\s+WHERE\s+(.+?)\s*$", re.I)
NATIVE_COND = re.compile(r"^(\w+)\s*(=|IN)\s*\?(\d+)$", re.I)


def native_query(run: StepRun, method_id: str | None) -> list[tuple[str, str, int]] | None:
    """Условия простого нативного @Query: `SELECT * FROM t WHERE a = ?1 AND b IN ?2` -> [(колонка, =|in, номер)]."""
    if not method_id:
        return None
    ann = next((a for a in run.program.N.get(method_id, {}).get("annotations") or [] if a.get("name") == "Query"), None)
    m = re.search(r'value\s*=\s*"([^"]*)"', (ann or {}).get("args") or "") if ann else None
    sel = NATIVE_SELECT.match(m.group(1)) if m else None
    if sel is None:
        return None
    out = []
    for cond in re.split(r"\s+AND\s+", sel.group(2), flags=re.I):
        c = NATIVE_COND.match(cond.strip())
        if c is None:
            return None
        out.append((c.group(1), c.group(2).lower() if c.group(2).lower() == "in" else "=", int(c.group(3))))
    return out


def embedded_filters(run: StepRun, entity_tn: str | None, prop: str, obj: Obj,
                     columns: set[str]) -> list[tuple[str, Any]] | None:
    """Фильтры по колонкам полей встроенного объекта (поле сущности @Embedded или тип @Embeddable).

    None — объект не встроенный, поле неизвестно или колонки нет в таблице.
    """
    p = run.program
    fi = p.field_info(entity_tn, prop[:1].lower() + prop[1:])
    tn = p.type_node(obj.type)
    embedded = fi is not None and ({"Embedded", "EmbeddedId"} & set(fi.annotations)
                                   or "Embeddable" in p.type_annotations(tn))
    if tn is None or not embedded:
        return None
    out: list[tuple[str, Any]] = []
    for f in p.instance_fields(tn):
        v = obj.fields.get(f.name)
        col = f.column or snake(f.name)
        if v is None or is_unknown(v) or (columns and col not in columns) or (isinstance(v, Obj) and not _comparable(v)):
            return None
        out.append((col, v))
    return out or None


def _comparable(v: Obj) -> bool:
    return v.src == "enum" or (v.type == library.DATE_TYPE and not is_unknown(v.fields.get("v")))


def cell_matches(cell: Any, v: Any) -> bool:
    """Значение колонки равно аргументу finder'а: enum — по порядковому номеру или имени, дата — по значению,
    InValues — одному из значений списка."""
    if isinstance(v, InValues):
        return _key(cell) in v.values
    if isinstance(v, Obj) and v.src == "enum":
        return str(cell) in (str(v.fields.get("__ordinal__")), str(v.fields.get("__name__")))
    if isinstance(v, Obj) and v.type == library.DATE_TYPE:
        t = v.fields.get("v")
        s = str(cell)
        return s == t.strftime("%Y-%m-%d %H:%M:%S") or (len(s) == 10 and s == t.strftime("%Y-%m-%d")
                                                         and t.time() == library.dt.time())
    return _key(cell) == _key(v)


def _key(v: Any) -> str:
    """Строка для сравнения с колонкой: MySQL 8 сравнивает строки без учёта регистра (collation utf8mb4_0900_ai_ci)."""
    return str(v).lower()


def column_of(run: StepRun, type_node: str | None, prop: str) -> str | None:
    """Колонка свойства сущности: @Column(name), иначе snake_case; `Id` — поле с @Id."""
    p = run.program
    fields = p.instance_fields(type_node) if type_node else []
    name = prop[:1].lower() + prop[1:]
    if prop == "Id":
        idf = next((f for f in fields if "Id" in f.annotations), None)
        if idf is not None:
            return idf.column or snake(idf.name)
        return "id"
    fi = next((f for f in fields if f.name == name), None)
    if fi is not None:
        return fi.column or snake(fi.name)
    return snake(name) if not fields else None


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def row_obj(run: StepRun, frame: Frame, entity_type: str | None, row: dict[str, Any], depth: int = 0) -> Obj:
    """Строка дампа как объект сущности: поля по колонкам, значения по типам полей.

    Поле-enum хранится в БД порядковым номером (JPA ORDINAL) или именем; встроенный объект (`@Embedded`,
    `@Embeddable`) собирается из колонок той же строки.
    """
    p = run.program
    module = p.module_of(frame.method_id)
    tn = p.type_node(entity_type or "", module) if entity_type else None
    fields: dict[str, Any] = {}
    for f in p.instance_fields(tn):
        col = f.column or snake(f.name)
        ftn = p.type_node(f.type, module) if p.is_project_type(f.type) else None
        if ftn and p.N[ftn].get("type_kind") == "enum":
            if col in row:
                fields[f.name] = _enum_from_db(run, f.type, ftn, row[col])
        elif ftn and depth == 0 and ("Embedded" in f.annotations or "Embeddable" in p.type_annotations(ftn)):
            fields[f.name] = row_obj(run, frame, f.type, row, depth + 1)
        elif col in row:
            fields[f.name] = convert(row[col], f.type)
    if not fields:
        fields = {_camel(k): v for k, v in row.items()}
    ent = run.index.entities.entities.get(entity_type or "") if depth == 0 else None
    for table, (fname, _fetch) in (ent.collections.items() if ent is not None else ()):
        items = collection_items(run, tn, table, fname, row)
        if items is not None:
            fields[fname] = items
    rid = row.get("id") or next(iter(row.values()), "")
    return Obj(entity_type or "row", fields, src="state", origin=f"{simple_name(entity_type) or 'row'} {rid}")


def collection_items(run: StepRun, type_node: str | None, table: str, fname: str, row: dict[str, Any]) -> Coll | None:
    """Элементы коллекции сущности (`@ElementCollection`) из её таблицы: первая колонка — ключ владельца,
    колонка `<поле>` — значение (иначе элемент — встраиваемый объект по колонкам), `<поле>_order` — порядок.
    Значения нужны условиям; ребро data к таблице коллекции решает R10 отдельно."""
    db = getattr(run.state, "db_state", None)
    cols = list(db.get_columns(table)) if db is not None and hasattr(db, "get_columns") else []
    if not cols:
        return None
    key = row.get(column_of(run, type_node, "Id") or "id")
    join, value_col, order_col = cols[0], snake(fname), f"{snake(fname)}_order"
    rows = [r for r in db.get_table(table) if str(r.get(join)) == str(key)]
    if order_col in cols:
        rows.sort(key=lambda r: int(r.get(order_col) or 0))
    fi = run.program.field_info(type_node, fname)
    elem = fi.type.split("<", 1)[1].rstrip(">").strip() if fi and "<" in fi.type else None
    if value_col in cols:
        items = [convert(r.get(value_col), elem) for r in rows]
    else:
        items = [Obj(elem or "row", {_camel(c): v for c, v in r.items() if c != join}, src="state",
                     origin=f"{simple_name(elem) or 'element'} of {fname}") for r in rows]
    return Coll(items, origin=f"{fname} of the database row", src="state", elem_type=elem)


def _enum_from_db(run: StepRun, fqn: str, type_node: str, raw: Any) -> Any:
    """Константа enum по значению колонки: порядковый номер или имя."""
    consts = run.program.enum_constants(type_node)
    s = str(raw)
    if s.lstrip("-").isdigit() and 0 <= int(s) < len(consts):
        return run.ex.enum_value(fqn, consts[int(s)], None, run)
    if s in consts:
        return run.ex.enum_value(fqn, s, None, run)
    return Unknown(f"{simple_name(fqn)} value {s!r} from the database", "object", src="state")


def _camel(col: str) -> str:
    head, *rest = col.split("_")
    return head + "".join(x.title() for x in rest)


def convert(v: Any, type_str: str | None) -> Any:
    s = simple_name(type_str)
    if v is None or (isinstance(v, str) and v.upper() == "NULL"):
        return None
    try:
        if s in ("int", "Integer", "long", "Long", "short", "Short", "byte"):
            return int(float(v)) if not isinstance(v, bool) else int(v)
        if s in ("double", "Double", "float", "Float"):
            return float(v)
        if s in ("boolean", "Boolean"):
            return str(v).lower() in ("1", "true", "b'\\x01'")
        if s == "String":
            return str(v) if not hasattr(v, "value") else str(int(v))
    except (TypeError, ValueError):
        return v
    if hasattr(v, "value") and not isinstance(v, (str, int, float)):  # IntEnum состояния M3
        return int(v)
    return v
