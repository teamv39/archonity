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
    rows = query_rows(run, frame, table, entity_type, callee, args)
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
               args: list[Any]) -> list[dict[str, Any]] | None:
    """Строки таблицы по finder-методу Spring Data; None — не определить (аргумент неизвестен, свой @Query)."""
    db = getattr(run.state, "db_state", None)
    if table is None or db is None or not hasattr(db, "get_table"):
        return None
    name = run.index.table_resource_to_db(table)
    rows = db.get_table(name)
    columns = set(db.get_columns(name)) if hasattr(db, "get_columns") else set()
    if callee in ("findAll", "count") and not args:
        return list(rows)
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
        if any(OPERATOR_SUFFIX.search(p) for p in props):
            return None
    if len(props) != len(args):
        return None
    tn = run.program.type_node(entity_type or "", run.program.module_of(frame.method_id)) if entity_type else None
    filters: list[tuple[str, Any]] = []
    for prop, arg in zip(props, args):
        arg = arg.fields.get("v") if isinstance(arg, Obj) and arg.simple == "UUID" else arg
        if is_unknown(arg) or isinstance(arg, (Obj, Coll)):
            return None
        col = column_of(run, tn, prop)
        if col is None or (columns and col not in columns):
            return None
        filters.append((col, arg))
    return [r for r in rows if all(str(r.get(c)) == str(v) for c, v in filters)]


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
    rid = row.get("id") or next(iter(row.values()), "")
    return Obj(entity_type or "row", fields, src="state", origin=f"{simple_name(entity_type) or 'row'} {rid}")


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
