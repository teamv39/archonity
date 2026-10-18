"""Модели вызовов библиотеки для исполнителя M4: Java, Spring, Lombok (ADR-005, M4).

Вызов без рёбер скелета и без цели в IR — библиотека или сгенерированный метод (R4): геттеры и сеттеры Lombok
работают с полями объекта, коллекции и Optional — со своими элементами, лямбды исполняет хост (R16).
Немоделируемый вызов даёт `Unknown` с происхождением.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from engine.executor.values import (
    MISSING, NONNULL, Coll, Iter, Lambda, Obj, Opt, Sym, TypeRef, Unknown, is_unknown, java_str, not_, simple_name,
    truth,
)

if TYPE_CHECKING:
    from engine.executor.interp import Frame, StepRun

MAX_ITEMS = 20
PH = "\x00"
LIST_TYPES = frozenset({"ArrayList", "LinkedList", "HashSet", "TreeSet", "LinkedHashSet", "Vector", "ArrayDeque",
                        "CopyOnWriteArrayList", "PriorityQueue"})
MAP_TYPES = frozenset({"HashMap", "LinkedHashMap", "TreeMap", "ConcurrentHashMap", "Hashtable"})


def unbox(v: Any) -> Any:
    """Число из BigDecimal и обёрток, иначе само значение."""
    if isinstance(v, Obj) and v.simple in ("BigDecimal", "AtomicInteger", "AtomicLong") and "v" in v.fields:
        return v.fields["v"]
    return v


def literal(text: Any, type_str: str | None) -> Any:
    """`init_literal` скелета (строка) по типу поля."""
    s = simple_name(type_str)
    try:
        if s in ("int", "Integer", "long", "Long", "short", "byte"):
            return int(str(text))
        if s in ("double", "Double", "float", "Float"):
            return float(str(text))
        if s in ("boolean", "Boolean"):
            return str(text).lower() == "true"
    except ValueError:
        return Unknown(f"constant {text}", "object", src="field")
    return text


def decap(name: str) -> str:
    """java.beans.Introspector.decapitalize."""
    if len(name) > 1 and name[0].isupper() and name[1].isupper():
        return name
    return name[:1].lower() + name[1:]


def accessor(run: StepRun, obj: Any, callee: str, nargs: int) -> tuple[str, str] | None:
    """Геттер или сеттер Lombok: (get|set, имя поля)."""
    if nargs == 0 and callee.startswith("get") and len(callee) > 3 and callee[3].isupper():
        base, kind = callee[3:], "get"
        cands = [decap(base), base]
    elif nargs == 0 and callee.startswith("is") and len(callee) > 2 and callee[2].isupper():
        base, kind = callee[2:], "get"
        cands = [decap(base), callee, base]
    elif nargs == 1 and callee.startswith("set") and len(callee) > 3 and callee[3].isupper():
        base, kind = callee[3:], "set"
        cands = [decap(base), "is" + base, base]
    else:
        return None
    if isinstance(obj, Obj):
        for c in cands:
            if c in obj.fields:
                return kind, c
        tn = run.program.type_node(obj.type)
        names = {f.name for f in run.program.instance_fields(tn)}
        for c in cands:
            if c in names:
                return kind, c
    return kind, cands[0]


# --- конструкторы -------------------------------------------------------------------------------------------------

def construct(run: StepRun, fqn: str, args: list[Any], frame: Frame) -> Any:
    """`new` библиотечного типа; None — тип проекта (конструктор исполняет интерпретатор)."""
    if run.program.is_project_type(fqn):
        return None
    s = simple_name(fqn)
    if s in LIST_TYPES:
        if args and isinstance(args[0], Coll):
            src = args[0]
            return Coll(list(src.items) if src.items is not None else None, src.nonempty, src.origin, src.src)
        if args and is_unknown(args[0]) and getattr(args[0], "kind", "") == "collection":
            return Coll(None, _nonempty_of(args[0]), args[0].origin, args[0].src)
        return Coll([], src="new", origin=f"new {s}")
    if s in MAP_TYPES:
        return Obj("java.util.HashMap", {"__map__": {}}, src="new")
    if s == "HttpHeaders":
        return Obj("org.springframework.http.HttpHeaders", {"__map__": {}}, src="new")
    if s == "HttpEntity":
        body, headers = None, None
        for a in args:
            if isinstance(a, Obj) and a.simple == "HttpHeaders":
                headers = a
            elif body is None:
                body = a
        return Obj("org.springframework.http.HttpEntity", {"body": body, "headers": headers}, src="new")
    if s == "ResponseEntity":
        return Obj("org.springframework.http.ResponseEntity", {"body": args[0] if args else None}, src="new")
    if s == "BigDecimal":
        return Obj("java.math.BigDecimal", {"v": _number(args[0]) if args else 0}, src="new")
    if s in ("String",):
        return args[0] if args and isinstance(args[0], str) else ""
    if s in ("StringBuilder", "StringBuffer"):
        return Obj("java.lang.StringBuilder", {"v": args[0] if args and isinstance(args[0], str) else ""}, src="new")
    if s == "Date":
        return Obj("java.util.Date", {"v": args[0] if args else Unknown("current date", "number", src="library")},
                   src="new")
    if s.endswith("Exception") or s.endswith("Error"):
        return Obj(fqn, {"message": args[0] if args else None}, src="new")
    return Obj(fqn, src="library", origin=f"new {s}")


def _number(v: Any) -> Any:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return Unknown(f"number {v!r}", "number")
    return unbox(v) if isinstance(v, Obj) else Unknown("number", "number")


def _nonempty_of(u: Unknown) -> Any:
    return u.child("nonempty", lambda: Unknown(f"{u.origin} is not empty", "bool", src=u.src,
                                               default=True if u.default is NONNULL else MISSING,
                                               rule="D4" if u.default is NONNULL else None))


# --- вызовы -------------------------------------------------------------------------------------------------------

def call(run: StepRun, frame: Frame, node: dict[str, Any], recv: Any, args: list[Any]) -> Any:
    callee = node.get("callee", "")
    if node.get("recv") is None:
        return _implicit(run, frame, node, callee, args)
    if isinstance(recv, TypeRef):
        return _static(run, frame, node, recv, callee, args)
    if isinstance(recv, Lambda):
        return run.call_lambda(recv, args, frame, callee)
    if isinstance(recv, str):
        return _string(recv, callee, args)
    if isinstance(recv, bool) or isinstance(recv, (int, float)):
        return _boxed(recv, callee, args)
    if isinstance(recv, Coll):
        return _collection(run, frame, recv, callee, args)
    if isinstance(recv, Iter):
        return _iterator(recv, callee)
    if isinstance(recv, Opt):
        return _optional(run, frame, recv, callee, args)
    if isinstance(recv, Obj):
        return _object(run, frame, recv, callee, args)
    if is_unknown(recv):
        return _unknown(run, recv, callee, args)
    return Unknown(f"{callee}() on {recv!r}", "object")


def _implicit(run: StepRun, frame: Frame, node: dict[str, Any], callee: str, args: list[Any]) -> Any:
    if callee == "ok":  # статический импорт ResponseEntity.ok
        return Obj("org.springframework.http.ResponseEntity", {"body": args[0] if args else None}, src="new")
    this = frame.this
    if isinstance(this, (Obj, Unknown)):
        acc = accessor(run, this, callee, len(args))
        if acc is not None:
            if acc[0] == "get":
                return run.read_field(this, acc[1], frame)
            if isinstance(this, Obj):
                this.fields[acc[1]] = args[0]
            return None
    return Unknown(f"{callee}() at line {frame.line}", "object")


def _static(run: StepRun, frame: Frame, node: dict[str, Any], t: TypeRef, callee: str, args: list[Any]) -> Any:
    cs = run.program.call_site(node.get("call"))
    fqn = cs.get("receiver_type") or t.name
    s = simple_name(fqn) or t.simple
    a0 = args[0] if args else None
    p = run.program
    tn = p.type_node(fqn, p.module_of(frame.method_id)) if p.is_project_type(fqn) else None
    if tn and p.N[tn].get("type_kind") == "enum":
        if callee == "values":
            return Coll([run.ex.enum_value(fqn, c, None, run) for c in p.enum_constants(tn)], src="enum")
        if callee == "valueOf" and isinstance(a0, str):
            return run.ex.enum_value(fqn, a0, None, run)
    if s == "String":
        if callee == "valueOf":
            sv = java_str(unbox(a0))
            return sv if sv is not None else Unknown(f"String.valueOf({_desc(a0)})", "string", NONNULL)
        return Unknown(f"String.{callee}(...)", "string", NONNULL)
    if s == "StringUtils" or s == "ObjectUtils":
        if callee in ("isEmpty", "isBlank", "hasText", "hasLength", "isNotEmpty", "isNotBlank"):
            empty = _is_empty(a0, blank=callee in ("isBlank", "hasText", "isNotBlank"))
            neg = callee in ("hasText", "hasLength", "isNotEmpty", "isNotBlank")
            return not_(empty) if neg else empty
        if callee == "equals" and len(args) == 2:
            return _equals(args[0], args[1])
    if s == "Objects":
        if callee == "isNull":
            return _is_null(a0)
        if callee == "nonNull":
            return not_(_is_null(a0))
        if callee == "equals" and len(args) == 2:
            return _equals(args[0], args[1])
        if callee == "requireNonNull":
            return a0
    if s in ("Integer", "Long", "Short", "Byte") and callee in ("parseInt", "parseLong", "valueOf"):
        if isinstance(a0, (int, float)) and not isinstance(a0, bool):
            return int(a0)
        if isinstance(a0, str) and re.fullmatch(r"-?\d+", a0.strip()):
            return int(a0)
        return Unknown(f"{s}.{callee}({_desc(a0)})", "number")
    if s in ("Double", "Float") and callee in ("parseDouble", "parseFloat", "valueOf"):
        n = _number(a0)
        return float(n) if isinstance(n, (int, float)) else Unknown(f"{s}.{callee}({_desc(a0)})", "number")
    if s == "Boolean" and callee in ("parseBoolean", "valueOf"):
        return a0.lower() == "true" if isinstance(a0, str) else a0 if isinstance(a0, bool) else Unknown(
            f"Boolean.{callee}", "bool")
    if s == "Math" and callee in ("max", "min", "abs") and args and all(isinstance(unbox(a), (int, float))
                                                                       for a in args):
        vals = [unbox(a) for a in args]
        return max(vals) if callee == "max" else min(vals) if callee == "min" else abs(vals[0])
    if s == "UUID":
        if callee == "randomUUID":
            return Obj("java.util.UUID", {"v": Unknown("random UUID", "string", NONNULL)}, src="new")
        if callee == "fromString":
            return Obj("java.util.UUID", {"v": a0}, src="new")
    if s == "Arrays" and callee == "asList":
        return args[0] if len(args) == 1 and isinstance(a0, Coll) else Coll(list(args), src="new")
    if s in ("List", "Set") and callee == "of":
        return Coll(list(args), src="new")
    if s == "Collections":
        if callee in ("emptyList", "emptySet"):
            return Coll([], src="new")
        if callee in ("singletonList", "singleton"):
            return Coll([a0], src="new")
        if callee.startswith("unmodifiable") or callee.startswith("synchronized"):
            return a0
        if callee in ("sort", "reverse", "shuffle"):
            return None
    if s == "ResponseEntity" and callee == "ok":
        return Obj("org.springframework.http.ResponseEntity", {"body": a0}, src="new")
    if s == "Thread" and callee == "sleep":
        return None
    return Unknown(f"{s}.{callee}({', '.join(_desc(a) for a in args)})", "object", src="library")


def _desc(v: Any) -> str:
    if isinstance(v, str):
        return repr(v[:30])
    if isinstance(v, (int, float, bool)) or v is None:
        return repr(v)
    if isinstance(v, Unknown):
        return v.origin
    if isinstance(v, Obj):
        return v.simple
    return type(v).__name__


def _is_null(v: Any) -> Any:
    if v is None:
        return True
    if is_unknown(v):
        return Sym("==", (v, None))
    return False


def _is_empty(v: Any, blank: bool = False) -> Any:
    if v is None:
        return True
    if isinstance(v, str):
        return (v.strip() if blank else v) == ""
    if isinstance(v, Coll):
        return not_(v.nonempty)
    if isinstance(v, Unknown):
        return v.child("isEmpty", lambda: Unknown(f"{v.origin} is empty", "bool", src=v.src))
    return False if not is_unknown(v) else Sym("isEmpty", (v,))


def _equals(a: Any, b: Any) -> Any:
    a, b = unbox(a), unbox(b)
    if is_unknown(a) or is_unknown(b):
        return Sym("==", (a, b))
    if a is None or b is None:
        return a is b
    if isinstance(a, Obj) or isinstance(b, Obj):
        return a is b
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return False
    return a == b


def _string(s: str, callee: str, args: list[Any]) -> Any:
    a0 = args[0] if args else None
    if callee in ("equals", "contentEquals"):
        return _equals(s, a0)
    if callee == "equalsIgnoreCase":
        return Sym("==", (s, a0)) if is_unknown(a0) else (isinstance(a0, str) and s.lower() == a0.lower())
    if callee in ("startsWith", "endsWith", "contains") and isinstance(a0, str):
        return {"startsWith": s.startswith, "endsWith": s.endswith, "contains": s.__contains__}[callee](a0)
    if callee == "isEmpty":
        return s == ""
    if callee == "length":
        return len(s)
    if callee in ("trim", "strip"):
        return s.strip()
    if callee == "toUpperCase":
        return s.upper()
    if callee == "toLowerCase":
        return s.lower()
    if callee in ("toString", "intern"):
        return s
    if callee == "charAt" and isinstance(a0, int) and 0 <= a0 < len(s):
        return s[a0]
    if callee == "substring" and isinstance(a0, int):
        b = args[1] if len(args) > 1 else len(s)
        return s[a0:b] if isinstance(b, int) else Unknown("substring", "string")
    if callee == "indexOf" and isinstance(a0, str):
        return s.find(a0)
    if callee == "split" and isinstance(a0, str) and not re.search(r"[\\\[\](){}.*+?^$|]", a0):
        return Coll(list(s.split(a0)), src="new")
    if callee == "replace" and len(args) == 2 and isinstance(a0, str) and isinstance(args[1], str):
        return s.replace(a0, args[1])
    if callee == "concat" and isinstance(a0, str):
        return s + a0
    if callee == "compareTo" and isinstance(a0, str):
        return (s > a0) - (s < a0)
    return Unknown(f"String.{callee}", "string" if callee != "matches" else "bool")


def _boxed(v: Any, callee: str, args: list[Any]) -> Any:
    a0 = unbox(args[0]) if args else None
    if callee in ("intValue", "longValue", "shortValue"):
        return int(v)
    if callee in ("doubleValue", "floatValue"):
        return float(v)
    if callee == "booleanValue":
        return bool(v)
    if callee == "equals":
        return _equals(v, a0)
    if callee == "compareTo" and isinstance(a0, (int, float)):
        return (v > a0) - (v < a0)
    if callee == "toString":
        return java_str(v)
    return Unknown(f"{type(v).__name__}.{callee}", "object")


def _collection(run: StepRun, frame: Frame, c: Coll, callee: str, args: list[Any]) -> Any:
    a0 = args[0] if args else None
    items = c.items
    if callee == "add":
        if items is not None:
            if len(args) == 2 and isinstance(a0, int):
                items.insert(a0, args[1])
            else:
                items.append(a0)
        else:
            c.nonempty = True
        return True
    if callee == "addAll":
        if items is not None and isinstance(a0, Coll) and a0.items is not None:
            items.extend(a0.items)
        else:
            other = a0.nonempty if isinstance(a0, Coll) else MISSING
            c.items = None
            c.nonempty = True if (c.nonempty is True or other is True) else Unknown(
                f"{c.origin} is not empty after addAll", "bool", src=c.src)
        return True
    if callee == "size":
        if items is not None:
            return len(items)
        return Unknown(f"size of {c.origin}", "number", src=c.src)
    if callee == "isEmpty":
        return not_(c.nonempty)
    if callee == "get":
        if items is not None and isinstance(a0, int) and 0 <= a0 < len(items):
            return items[a0]
        return _element(c)
    if callee == "contains":
        if items is not None and not is_unknown(a0):
            return any(_equals(x, a0) is True for x in items) or (
                Sym("contains", (c.origin, a0)) if any(is_unknown(x) for x in items) else False)
        return Unknown(f"{c.origin} contains {_desc(a0)}", "bool", src=c.src)
    if callee in ("remove", "clear", "set", "sort", "removeIf"):
        if callee == "clear" and items is not None:
            items.clear()
        elif callee == "remove" and items is not None:
            if isinstance(a0, int) and 0 <= a0 < len(items):
                items.pop(a0)
            else:
                for i, x in enumerate(items):
                    if x is a0:
                        items.pop(i)
                        break
        elif callee == "set" and items is not None and isinstance(a0, int) and 0 <= a0 < len(items):
            items[a0] = args[1]
        elif callee == "sort" and isinstance(a0, Lambda) and items and len(items) > 1:
            run.call_lambda(a0, [items[0], items[1]], frame, "sort")
        return None
    if callee == "iterator":
        return Iter(c)
    if callee in ("stream", "parallelStream", "toArray", "collect", "toList", "sorted", "distinct", "boxed",
                  "unmodifiableList"):
        if callee == "sorted" and isinstance(a0, Lambda) and items and len(items) > 1:
            run.call_lambda(a0, [items[0], items[1]], frame, "sorted")
        return c
    if callee in ("forEach", "peek", "filter", "map", "flatMap", "anyMatch", "allMatch", "noneMatch", "mapToInt",
                  "mapToDouble"):
        return _stream_op(run, frame, c, callee, a0)
    if callee in ("findFirst", "findAny"):
        if items is not None:
            return Opt(bool(items), items[0] if items else None, src=c.src)
        return Opt(c.nonempty, _element(c), src=c.src)
    if callee == "count":
        return len(items) if items is not None else Unknown(f"count of {c.origin}", "number")
    if callee == "subList" and items is not None and len(args) == 2 and all(isinstance(a, int) for a in args):
        return Coll(items[args[0]:args[1]], src=c.src)
    if callee == "indexOf" and items is not None:
        return next((i for i, x in enumerate(items) if _equals(x, a0) is True), -1)
    if callee in ("sum",):
        if items is not None and all(isinstance(unbox(x), (int, float)) for x in items):
            return sum(unbox(x) for x in items)
    return Unknown(f"{callee}() of {c.origin}", "object", src=c.src)


def _element(c: Coll) -> Any:
    src = c.src if c.src in ("remote", "repo", "call", "state") else "library"
    return Unknown(f"element of {c.origin or 'collection'}", "object", NONNULL if src != "library" else MISSING,
                   src=src, type=c.elem_type, rule="D2" if src != "library" else None)


def _stream_op(run: StepRun, frame: Frame, c: Coll, op: str, fn: Any) -> Any:
    """Операции потока с лямбдой: лямбда исполняется на элементах (R16), только если они есть."""
    if not isinstance(fn, Lambda):
        return c if op not in ("anyMatch", "allMatch", "noneMatch") else Unknown(f"{op} of {c.origin}", "bool")
    elems = list(c.items[:MAX_ITEMS]) if c.items is not None else (
        [_element(c)] if truth(c.nonempty) is not False else [])
    results = [run.call_lambda(fn, [x], frame, op) for x in elems]
    if op in ("forEach", "peek"):
        return None if op == "forEach" else c
    if op in ("map", "mapToInt", "mapToDouble", "flatMap"):
        if c.items is None:
            return Coll(None, c.nonempty, c.origin, c.src)
        return Coll(results, src=c.src)
    if op == "filter":
        if c.items is None:
            return Coll(None, Unknown(f"filtered {c.origin} is not empty", "bool", src=c.src), c.origin, c.src)
        kept = [x for x, r in zip(elems, results) if truth(r) is not False]
        return Coll(kept, src=c.src)
    if c.items is None or any(truth(r) is None for r in results):
        return Unknown(f"{op} of {c.origin}", "bool", src=c.src)
    if op == "anyMatch":
        return any(truth(r) for r in results)
    if op == "allMatch":
        return all(truth(r) for r in results)
    return not any(truth(r) for r in results)


def _iterator(it: Iter, callee: str) -> Any:
    c = it.coll
    if callee == "hasNext":
        if c.items is not None:
            return it.pos < min(len(c.items), MAX_ITEMS)
        return c.nonempty if it.pos == 0 else False
    if callee == "next":
        it.pos += 1
        if c.items is not None and it.pos - 1 < len(c.items):
            return c.items[it.pos - 1]
        return _element(c)
    if callee == "remove":
        return None
    return Unknown(f"Iterator.{callee}", "object")


def _optional(run: StepRun, frame: Frame, o: Opt, callee: str, args: list[Any]) -> Any:
    a0 = args[0] if args else None
    present = o.present
    t = truth(present)
    if t is None and run.expected == "success":
        t = truth(present.default) if isinstance(present, Unknown) and present.default is not MISSING else None
    if callee == "isPresent":
        if isinstance(present, bool) and o.src == "state":
            run.taint = True
        return present
    if callee == "isEmpty":
        return not_(present)
    if callee == "get":
        return o.value
    if callee == "orElse":
        return o.value if t is True else a0 if t is False else Unknown(f"value of {o.origin}", "object")
    if callee in ("orElseThrow", "orElseGet"):
        if t is False:
            if callee == "orElseGet" and isinstance(a0, Lambda):
                return run.call_lambda(a0, [], frame, callee)
            exc = run.call_lambda(a0, [], frame, callee) if isinstance(a0, Lambda) else Obj(
                "java.util.NoSuchElementException", src="new")
            from engine.executor.interp import ThrowSignal

            raise ThrowSignal(exc, frame.line)
        return o.value  # пустой Optional на успешном пути не ожидается: лямбда не исполняется (R16)
    if callee == "ifPresent" and isinstance(a0, Lambda):
        if t is not False:
            run.call_lambda(a0, [o.value], frame, callee)
        return None
    if callee == "map" and isinstance(a0, Lambda):
        if t is False:
            return Opt(False)
        return Opt(present, run.call_lambda(a0, [o.value], frame, callee), o.origin, o.src)
    return Unknown(f"Optional.{callee}", "object")


def _object(run: StepRun, frame: Frame, o: Obj, callee: str, args: list[Any]) -> Any:
    s = o.simple
    a0 = args[0] if args else None
    if s in ("Logger",) or o.type.endswith("Logger"):
        return None
    if s in ("ResponseEntity", "HttpEntity"):
        if callee == "getBody":
            return o.fields.get("body")
        if callee == "getHeaders":
            return o.fields.get("headers")
        if callee == "getStatusCode":
            return "OK"
        if callee == "getStatusCodeValue":
            return 200
    if s == "BigDecimal":
        v = o.fields.get("v")
        other = unbox(a0)
        if callee in ("add", "subtract", "multiply", "divide"):
            if isinstance(v, (int, float)) and isinstance(other, (int, float)):
                try:
                    r = {"add": v + other, "subtract": v - other, "multiply": v * other,
                         "divide": v / other if other else 0}[callee]
                except ZeroDivisionError:
                    r = 0
                return Obj("java.math.BigDecimal", {"v": r}, src="new")
            return Obj("java.math.BigDecimal", {"v": Unknown(f"BigDecimal.{callee}", "number")}, src="new")
        if callee == "compareTo":
            if isinstance(v, (int, float)) and isinstance(other, (int, float)):
                return (v > other) - (v < other)
            return Unknown("BigDecimal.compareTo", "number")
        if callee in ("doubleValue", "floatValue"):
            return float(v) if isinstance(v, (int, float)) else Unknown("BigDecimal value", "number")
        if callee in ("intValue", "longValue"):
            return int(v) if isinstance(v, (int, float)) else Unknown("BigDecimal value", "number")
        if callee in ("setScale", "abs", "negate", "stripTrailingZeros"):
            return o
        if callee in ("toString", "toPlainString"):
            sv = java_str(v)
            return sv if sv is not None else Unknown("BigDecimal string", "string", NONNULL)
    if s == "UUID" and callee == "toString":
        return o.fields.get("v")
    if s in ("StringBuilder", "StringBuffer"):
        if callee == "append":
            cur, add = o.fields.get("v"), java_str(unbox(a0)) if not is_unknown(a0) else None
            o.fields["v"] = cur + add if isinstance(cur, str) and add is not None else Unknown("built string",
                                                                                                "string", NONNULL)
            return o
        if callee == "toString":
            return o.fields.get("v")
    if s == "Date":
        if callee in ("before", "after", "equals"):
            return Unknown(f"date comparison Date.{callee}", "bool", src="library")
        if callee == "getTime":
            return Unknown("Date.getTime", "number")
        if callee == "toString":
            return Unknown("date string", "string", NONNULL)
    if isinstance(o.fields.get("__map__"), dict):
        return _map(o, callee, args)
    if o.src == "enum":
        if callee in ("name", "toString"):
            return o.fields.get("__name__")
        if callee == "ordinal":
            return o.fields.get("__ordinal__")
        if callee == "equals":
            return a0 is o if not is_unknown(a0) else Sym("==", (o, a0))
    if callee == "getMessage" and "message" in o.fields:
        return o.fields.get("message")
    if callee == "equals":
        return _equals(o, a0)
    acc = accessor(run, o, callee, len(args))
    if acc is not None:
        if acc[0] == "get":
            return run.read_field(o, acc[1], frame)
        o.fields[acc[1]] = a0
        return None
    if callee == "toString":
        return Unknown(f"{s}.toString()", "string", NONNULL)
    if callee == "hashCode":
        return Unknown(f"{s}.hashCode()", "number")
    if o.src == "bean" and s == "RestTemplate":
        return Unknown(f"response of external RestTemplate.{callee}", "object", src="remote")
    return Unknown(f"{s}.{callee}()", "object", src="library")


def _map(o: Obj, callee: str, args: list[Any]) -> Any:
    m: dict[Any, Any] = o.fields["__map__"]
    a0 = args[0] if args else None
    key = a0 if isinstance(a0, (str, int, float, bool)) else None
    if callee in ("put", "add", "set"):
        if key is not None:
            m[key] = args[1] if len(args) > 1 else None
        else:
            o.fields["__map__"] = m  # ключ неизвестен: содержимое неточно
        return None
    if callee in ("get", "getOrDefault"):
        if key is not None and key in m:
            return m[key]
        return args[1] if callee == "getOrDefault" and len(args) > 1 else Unknown(f"map value for {_desc(a0)}",
                                                                                 "object")
    if callee == "containsKey":
        return key in m if key is not None else Unknown("map contains key", "bool")
    if callee in ("keySet",):
        return Coll(list(m.keys()), src="new")
    if callee in ("values",):
        return Coll(list(m.values()), src="new")
    if callee == "entrySet":
        return Coll([Obj("java.util.Map$Entry", {"key": k, "value": v}, src="new") for k, v in m.items()], src="new")
    if callee == "size":
        return len(m)
    if callee == "isEmpty":
        return not m
    if callee == "remove" and key is not None:
        return m.pop(key, None)
    return Unknown(f"Map.{callee}", "object")


def _unknown(run: StepRun, u: Any, callee: str, args: list[Any]) -> Any:
    a0 = args[0] if args else None
    if isinstance(u, Sym):
        if callee == "equals":
            return Sym("==", (u, a0))
        return Unknown(f"{callee}() of a computed value", "object")
    acc = accessor(run, u, callee, len(args))
    if acc is not None and acc[0] == "get":
        return run.read_field(u, acc[1])
    if acc is not None:
        return None
    kind = u.kind
    if callee == "equals":
        return Sym("==", (u, unbox(a0)))
    if callee in ("startsWith", "endsWith", "contains", "equalsIgnoreCase", "matches"):
        return Sym(callee, (u, a0))
    if callee == "isEmpty":
        if kind == "collection":
            return not_(_nonempty_of(u))
        return _is_empty(u)
    if callee == "size":
        nonempty = _nonempty_of(u)
        return u.child("size", lambda: Unknown(f"size of {u.origin}", "number", src=u.src,
                                               default=1 if nonempty.default is True else MISSING,
                                               rule="D4" if nonempty.default is True else None))
    if callee in ("isPresent",):
        return u.child("present", lambda: Unknown(f"{u.origin} is present", "bool", src=u.src,
                                                  default=True if u.default is NONNULL else MISSING,
                                                  rule="D3" if u.default is NONNULL else None))
    if callee in ("get", "orElseThrow") and kind == "optional":
        return u.child("value", lambda: Unknown(f"value of {u.origin}", "object", NONNULL, src=u.src, rule="D2"))
    if callee in ("iterator", "stream"):
        c = Coll(None, _nonempty_of(u), u.origin, u.src)
        return Iter(c) if callee == "iterator" else c
    if callee == "get" and kind == "collection":
        return u.child("get", lambda: Unknown(f"element of {u.origin}", "object", NONNULL if u.default is NONNULL
                                              else MISSING, src=u.src, rule="D2" if u.default is NONNULL else None))
    if callee in ("toString", "trim", "toUpperCase", "toLowerCase", "substring", "replace"):
        return u.child(callee, lambda: Unknown(f"{callee}() of {u.origin}", "string", u.default, src=u.src,
                                               rule=u.rule))
    if callee in ("intValue", "doubleValue", "longValue", "booleanValue", "getTime", "length", "hashCode",
                  "compareTo"):
        return Unknown(f"{callee}() of {u.origin}", "number" if callee != "booleanValue" else "bool", src=u.src)
    if callee in ("before", "after"):
        return Unknown(f"{u.origin}.{callee}({_desc(a0)})", "bool", src=u.src)
    return u.child(f"{callee}()", lambda: Unknown(f"{callee}() of {u.origin}", "object", src=u.src))


def call_method_ref(run: StepRun, lam: Lambda, args: list[Any]) -> Any:
    """Ссылка на метод библиотеки (`SimpleGrantedAuthority::new`)."""
    ref = str(lam.node.get("method_ref") or "")
    if ref.endswith("::new"):
        return Obj(ref[:-5], {"args": args}, src="new")
    return Unknown(f"{ref}({', '.join(_desc(a) for a in args)})", "object")


# --- HTTP ---------------------------------------------------------------------------------------------------------

def http_verb(callee: str, args: list[Any]) -> str | None:
    if callee == "exchange":
        v = args[1] if len(args) > 1 else None
        return v.upper() if isinstance(v, str) else None
    return {"getForObject": "GET", "getForEntity": "GET", "postForObject": "POST", "postForEntity": "POST",
            "put": "PUT", "delete": "DELETE", "patchForObject": "PATCH"}.get(callee)


def request_parts(callee: str, args: list[Any]) -> tuple[Any, Any]:
    """(тело, заголовки) запроса RestTemplate."""
    entity = None
    if callee == "exchange" and len(args) > 2:
        entity = args[2]
    elif callee in ("postForObject", "postForEntity", "put", "patchForObject") and len(args) > 1:
        entity = args[1]
    if isinstance(entity, Obj) and entity.simple == "HttpEntity":
        return entity.fields.get("body"), entity.fields.get("headers")
    return entity, None


def _url_parts(v: Any) -> list[Any]:
    if isinstance(v, Sym) and v.op == "+" and len(v.args) == 2:
        return _url_parts(v.args[0]) + _url_parts(v.args[1])
    if isinstance(v, str):
        return [v]
    s = java_str(unbox(v)) if not is_unknown(v) and not isinstance(v, Obj) else None
    if s is not None:
        return [s]
    if isinstance(v, Obj) and v.simple == "UUID":
        return _url_parts(v.fields.get("v"))
    return [v]


def url_segments(url: Any) -> tuple[list[Any], dict[str, Any]]:
    """Сегменты пути и query-параметры URL: строка или неизвестное значение (сегмент из одного неизвестного)."""
    vals: list[Any] = []
    text = ""
    for p in _url_parts(url):
        if isinstance(p, str):
            text += p
        else:
            vals.append(p)
            text += f"{PH}{len(vals) - 1}{PH}"
    if "://" in text:
        after = text.split("://", 1)[1]
        i = after.find("/")
        text = after[i:] if i >= 0 else ""
    elif text.startswith(PH):
        j = text.find(PH, 1)
        rest = text[j + 1:]
        if rest.startswith("/"):
            text = rest
    path, _, q = text.partition("?")

    def seg_value(seg: str) -> Any:
        if PH not in seg:
            return seg
        m = re.fullmatch(PH + r"(\d+)" + PH, seg)
        if m:
            return vals[int(m.group(1))]
        return Unknown(f"URL segment {re.sub(PH + r'\d+' + PH, '{?}', seg)}", "string", src="remote")

    segs = [seg_value(s) for s in path.split("/") if s]
    query: dict[str, Any] = {}
    for kv in q.split("&"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            if PH not in k:
                query[k] = seg_value(v)
    return segs, query


def url_text(url: Any) -> str:
    out = []
    for p in _url_parts(url):
        out.append(p if isinstance(p, str) else "{?}")
    return "".join(out)
