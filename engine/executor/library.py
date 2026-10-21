"""Модели вызовов библиотек (JDK, Spring, Lombok) для исполнителя M4.

Вызов, у которого нет рёбер в скелете и нет `target` в IR, — библиотечный. Здесь считается его значение:
геттеры и сеттеры Lombok, String, числа, Optional, коллекции и стримы, ResponseEntity, UUID.
Лямбда, переданная в библиотеку, исполняется, только если библиотека её вызывает (R16).
Неизвестный вызов даёт UNKNOWN; переданные в него лямбды исполняются один раз (правило по умолчанию).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import datetime as _dt

from engine.executor.values import (
    UNKNOWN, Bean, Concat, DateV, EnumV, JsonV, Lambda, ListV, MapV, MethodRef, Obj, OptionalV, TypeRef, Wrapper,
    equals_value, num, t_not, to_jstr, tri,
)

# Часы системы по контексту скелета (context.date): 15.09.2026; время — после прогрева БД (покупки прогрева в 15:00)
NOW = _dt.datetime(2026, 9, 15, 15, 30, 0)
CALENDAR_FIELDS = {"YEAR": 1, "MONTH": 2, "DATE": 5, "DAY_OF_MONTH": 5, "HOUR": 10, "HOUR_OF_DAY": 11, "MINUTE": 12,
                   "SECOND": 13, "MILLISECOND": 14}
JDK_CONSTANTS = {
    ("Integer", "MAX_VALUE"): 2**31 - 1, ("Integer", "MIN_VALUE"): -2**31,
    ("Long", "MAX_VALUE"): 2**63 - 1, ("Long", "MIN_VALUE"): -2**63,
    ("Float", "MAX_VALUE"): 3.4028234663852886e38, ("Double", "MAX_VALUE"): 1.7976931348623157e308,
    ("Float", "MIN_VALUE"): 1.4e-45, ("Double", "MIN_VALUE"): 4.9e-324,
    ("Boolean", "TRUE"): True, ("Boolean", "FALSE"): False,
}
_JAVA_FMT = [("yyyy", "%Y"), ("MM", "%m"), ("dd", "%d"), ("HH", "%H"), ("mm", "%M"), ("ss", "%S")]


def _py_fmt(pattern: str) -> str:
    out = pattern
    for j, py in _JAVA_FMT:
        out = out.replace(j, py)
    return out


def _date_call(d: DateV, callee: str, args: list[Any]) -> Any:
    v = d.value
    a0 = args[0] if args else UNKNOWN
    if d.calendar:
        if callee == "setTime":
            d.value = a0.value if isinstance(a0, DateV) else UNKNOWN
            return None
        if callee == "getTime":
            return DateV(v)
        if callee == "get":
            if v is UNKNOWN or not isinstance(a0, int):
                return UNKNOWN
            return {1: v.year, 2: v.month - 1, 5: v.day, 10: v.hour % 12, 11: v.hour, 12: v.minute,
                    13: v.second, 14: 0}.get(a0, UNKNOWN)
        if callee == "add":
            n = args[1] if len(args) > 1 else UNKNOWN
            if v is UNKNOWN or not isinstance(a0, int) or not isinstance(n, int):
                d.value = UNKNOWN
                return None
            if a0 == 5:
                d.value = v + _dt.timedelta(days=n)
            elif a0 in (10, 11):
                d.value = v + _dt.timedelta(hours=n)
            elif a0 == 12:
                d.value = v + _dt.timedelta(minutes=n)
            elif a0 == 13:
                d.value = v + _dt.timedelta(seconds=n)
            else:
                d.value = UNKNOWN
            return None
        if callee == "set":
            d.value = UNKNOWN
            return None
        if callee == "getTimeInMillis":
            return int(v.timestamp() * 1000) if v is not UNKNOWN else UNKNOWN
        return UNKNOWN
    if callee == "getTime":
        return int(v.timestamp() * 1000) if v is not UNKNOWN else UNKNOWN
    if callee in ("before", "after", "compareTo", "equals"):
        w = a0.value if isinstance(a0, DateV) else UNKNOWN
        if v is UNKNOWN or w is UNKNOWN:
            return UNKNOWN
        if callee == "before":
            return v < w
        if callee == "after":
            return v > w
        if callee == "equals":
            return v == w
        return (v > w) - (v < w)
    if callee == "toString":
        return UNKNOWN
    return UNKNOWN


_JSON_WRITE = {"toJSONString", "writeValueAsString", "toJSON"}
_JSON_READ = {"parseObject", "readValue", "parseArray", "convertValue", "toJavaObject", "parse"}


def json_copy(v: Any, target_type: str | None = None) -> Any:
    """Значение после сериализации и разбора JSON (Jackson, fastjson): новый объект с теми же полями."""
    if isinstance(v, JsonV):
        return json_copy(v.value, target_type)
    if isinstance(v, OptionalV):
        return json_copy(v.value, target_type) if v.value is not None else None
    if isinstance(v, Wrapper):
        return json_copy(v.body, target_type)
    if isinstance(v, Obj):
        return Obj(target_type or v.type, {k: json_copy(x) for k, x in v.fields.items()}, open=v.open)
    if isinstance(v, ListV):
        return ListV([json_copy(x) for x in v.items], exact=v.exact, elem_type=v.elem_type)
    if isinstance(v, MapV):
        return MapV({k: json_copy(x) for k, x in v.data.items()}, exact=v.exact)
    return v


def _json(callee: str, args: list[Any]) -> Any:
    if callee in _JSON_WRITE:
        return JsonV(args[0]) if args else UNKNOWN
    if callee in _JSON_READ and args:
        src = args[0]
        if isinstance(src, (JsonV, Obj, ListV, MapV)):
            return json_copy(src)
    return UNKNOWN
from engine.executor.world import fresh_uuid

if TYPE_CHECKING:
    from engine.executor.interpreter import Frame, Interpreter

_LOGGER_METHODS = {"info", "warn", "error", "debug", "trace"}
_CALLABLE = (Lambda, MethodRef)


def new_library(it: Interpreter, written: str, args: list[Any]) -> Any:
    simple = written.rsplit(".", 1)[-1]
    if simple in ("ArrayList", "LinkedList", "HashSet", "TreeSet", "LinkedHashSet", "Vector"):
        is_set = simple.endswith("Set")
        out = ListV([], exact=True, is_set=is_set)
        if args and isinstance(args[0], ListV):
            out.exact = args[0].exact
            for x in args[0].items:
                _add(out, x)
        elif args and isinstance(args[0], MapV):
            out.exact = False
        return out
    if simple in ("HashMap", "TreeMap", "LinkedHashMap", "ConcurrentHashMap"):
        return MapV({}, exact=True)
    if simple in ("HttpEntity", "ResponseEntity"):
        body = args[0] if args else None
        if len(args) == 1 and isinstance(body, Obj) and (body.type or "").endswith("HttpHeaders"):
            body = None
        return Wrapper(body, "entity" if simple == "HttpEntity" else "response")
    if simple == "BigDecimal":
        return num(args[0]) if args else UNKNOWN
    if simple in ("String", "StringBuilder", "StringBuffer"):
        return args[0] if args and isinstance(args[0], str) else ("" if not args else UNKNOWN)
    if simple in ("Integer", "Long", "Double", "Float"):
        return num(args[0]) if args else UNKNOWN
    if simple == "Random":
        return Obj("java.util.Random", {}, open=True)
    if simple == "Date":
        if not args:
            return DateV(NOW)
        if len(args) == 1 and isinstance(args[0], int) and args[0] == 0:
            return DateV(_dt.datetime(1970, 1, 1))
        if 3 <= len(args) <= 6 and all(isinstance(a, int) and not isinstance(a, bool) for a in args):
            # устаревший Date(year, month, day, ...): год от 1900, месяц с 0
            y, mo, d, *rest = args
            try:
                return DateV(_dt.datetime(1900 + y, mo + 1, d, *rest))
            except ValueError:
                return DateV(UNKNOWN)
        return DateV(UNKNOWN)
    if simple == "DecimalFormat":
        return Obj("java.text.DecimalFormat", {"pattern": args[0] if args else UNKNOWN}, open=False)
    if simple == "SimpleDateFormat":
        return Obj("java.text.SimpleDateFormat", {"pattern": args[0] if args else UNKNOWN}, open=False)
    if simple in ("ObjectMapper", "Gson"):
        return Obj("com.fasterxml.jackson.databind.ObjectMapper", {}, open=True)
    return None


def _field_name(callee: str, prefix: str) -> str:
    rest = callee[len(prefix):]
    return rest[:1].lower() + rest[1:]


def _run(it: Interpreter, fn: Any, args: list[Any], fr: Frame) -> Any:
    if isinstance(fn, _CALLABLE):
        return it.call_lambda(fn, args, fr)
    return UNKNOWN


def _run_unknown_lambdas(it: Interpreter, args: list[Any], fr: Frame) -> None:
    for a in args:
        if isinstance(a, _CALLABLE):
            it.call_lambda(a, [UNKNOWN] * (len(a.params) if isinstance(a, Lambda) else 1), fr)


def call_library(it: Interpreter, fr: Frame, callee: str, recv: Any, args: list[Any], e: dict[str, Any]) -> Any:
    # Логгер
    if callee in _LOGGER_METHODS and (recv is UNKNOWN or recv is None or isinstance(recv, (Obj, Bean))):
        if recv is None or recv is UNKNOWN or isinstance(recv, Bean):
            return None
    if callee == "ok" and recv is None:
        return Wrapper(args[0] if args else None, "response")
    if callee in ("getBody",) and isinstance(recv, Wrapper):
        return recv.body
    if callee == "getBody":
        return UNKNOWN
    if isinstance(recv, TypeRef):
        return _static(it, fr, recv, callee, args)
    if recv is None and e.get("recv") is None:
        # неразрешённый вызов своего класса без рёбер — не знаем
        _run_unknown_lambdas(it, args, fr)
        return UNKNOWN
    if isinstance(recv, str):
        return _string(recv, callee, args)
    if isinstance(recv, Concat):
        if callee in ("toString", "trim", "intern"):
            return recv
        if callee in ("startsWith", "contains", "equals", "endsWith") and args and isinstance(args[0], str):
            known = recv.parts[0] if isinstance(recv.parts[0], str) else ""
            if callee == "startsWith" and known:
                if known.startswith(args[0]):
                    return True
                if len(known) >= len(args[0]):
                    return False
        return UNKNOWN
    if isinstance(recv, bool) or (isinstance(recv, (int, float))):
        return _number(recv, callee, args)
    if isinstance(recv, OptionalV):
        return _optional(it, fr, recv, callee, args)
    if isinstance(recv, ListV):
        return _list(it, fr, recv, callee, args)
    if isinstance(recv, MapV):
        return _map(recv, callee, args)
    if isinstance(recv, EnumV):
        if callee == "name" or callee == "toString":
            return recv.constant
        if callee == "ordinal":
            return recv.ordinal if recv.ordinal is not None else UNKNOWN
        if callee == "equals":
            return equals_value(recv, args[0] if args else UNKNOWN)
        found, val = _project_method(it, fr, recv, callee, args)
        if found:
            return val
        if callee.startswith("get") and not args:
            return recv.get(_field_name(callee, "get"))
        return UNKNOWN
    if isinstance(recv, DateV):
        return _date_call(recv, callee, args)
    if isinstance(recv, Wrapper):
        if callee == "getStatusCode":
            return "OK"
        return UNKNOWN
    if isinstance(recv, Obj):
        return _obj(it, fr, recv, callee, args)
    if recv is None:
        return UNKNOWN  # NPE на успешном пути не моделируем
    _run_unknown_lambdas(it, args, fr)
    return UNKNOWN


def _project_method(it: Interpreter, fr: Frame, o: Any, callee: str, args: list[Any]) -> tuple[bool, Any]:
    """Метод проекта на получателе известного типа, у вызова которого в скелете нет ребра.

    Значение считается исполнением тела. Рёбра calls/executes по умолчанию не пишутся (скелет вызов не
    разрешил, эталон по таким вызовам не проверен); `unresolved_receiver_calls=emit` пишет их (гипотеза).
    """
    tname = getattr(o, "type", None)
    if not tname:
        return False, None
    tid = it.types.resolve(tname, fr.module)
    mid = it.types.method_of(tid, callee, len(args))
    if not mid or mid not in it.ir:
        return False, None
    if getattr(it.rules, "unresolved_receiver_calls", "mute") == "emit":
        it.sink.edge("calls", fr.method, mid, ("IR_CALL", "unresolved_receiver"))
        it.sink.execute(mid, ("IR_CALL", "unresolved_receiver"), f"calls|{fr.method}|{mid}")
        return True, it.invoke(mid, o, args, fr.unit, fr.why)
    it.sink.muted += 1
    try:
        return True, it.invoke(mid, o, args, fr.unit, fr.why)
    finally:
        it.sink.muted -= 1


def _obj(it: Interpreter, fr: Frame, o: Obj, callee: str, args: list[Any]) -> Any:
    if o.fields.get("#builder"):
        # Lombok @Builder: сеттер-цепочка, build() — объект с заданными полями (остальные по умолчанию)
        if callee == "build":
            tid = it.types.resolve(o.type, fr.module)
            out = Obj(o.type, {}, open=False)
            from engine.executor.interpreter import default_value
            for f in it.types.all_fields(tid):
                out.fields[f["name"]] = default_value(f)
            out.fields.update({k: v for k, v in o.fields.items() if k != "#builder"})
            return out
        if len(args) == 1:
            o.fields[callee] = args[0]
            return o
        return o
    if o.type == "java.util.Random":
        return UNKNOWN
    if o.type == "java.text.SimpleDateFormat":
        pat = o.fields.get("pattern")
        a0 = args[0] if args else UNKNOWN
        if not isinstance(pat, str):
            return DateV(UNKNOWN) if callee == "parse" else UNKNOWN
        if callee == "parse":
            if not isinstance(a0, str):
                return DateV(UNKNOWN)
            try:
                return DateV(_dt.datetime.strptime(a0, _py_fmt(pat)))
            except ValueError:
                # SimpleDateFormat нестрогий: лишний хвост строки игнорируется, иначе ParseException
                try:
                    n = len(_dt.datetime.now().strftime(_py_fmt(pat)))
                    return DateV(_dt.datetime.strptime(a0[:n], _py_fmt(pat)))
                except ValueError:
                    return DateV(UNKNOWN)
        if callee == "format":
            if isinstance(a0, DateV) and a0.value is not UNKNOWN:
                return a0.value.strftime(_py_fmt(pat))
            return UNKNOWN
        return UNKNOWN
    if o.type == "java.text.DecimalFormat":
        pat, a0 = o.fields.get("pattern"), num(args[0]) if args else UNKNOWN
        if callee == "format" and isinstance(pat, str) and a0 is not UNKNOWN:
            digits = len(pat.split(".", 1)[1]) if "." in pat else 0
            return f"{a0:.{digits}f}"
        return UNKNOWN
    if o.type == "java.util.Iterator":
        items, i, exact = o.fields["#items"], o.fields["#i"], o.fields["#exact"]
        if callee == "hasNext":
            if i < len(items):
                return True
            return False if exact else UNKNOWN
        if callee == "next":
            o.fields["#i"] = i + 1
            return items[i] if i < len(items) else UNKNOWN
        return UNKNOWN
    if o.type == "com.fasterxml.jackson.databind.ObjectMapper":
        return _json(callee, args)
    found, val = _project_method(it, fr, o, callee, args)
    if found:
        return val
    if callee.startswith("get") and len(callee) > 3 and not args:
        name = _field_name(callee, "get")
        if name in o.fields or o.open:
            return o.get(name)
        return None
    if callee.startswith("is") and len(callee) > 2 and not args:
        name = _field_name(callee, "is")
        if name in o.fields:
            return o.fields[name]
        alt = callee[:1].lower() + callee[1:]
        if alt in o.fields:
            return o.fields[alt]
        return UNKNOWN
    if callee.startswith("set") and len(callee) > 3 and len(args) == 1:
        it.set_field(o, _field_name(callee, "set"), args[0])
        return None
    if callee == "equals":
        return equals_value(o, args[0] if args else UNKNOWN)
    if callee in ("hashCode", "toString"):
        return UNKNOWN
    if callee == "getClass":
        return UNKNOWN
    _run_unknown_lambdas(it, args, fr)
    return UNKNOWN


def _string(s: str, callee: str, args: list[Any]) -> Any:
    a0 = args[0] if args else UNKNOWN
    if callee in ("toString", "trim", "intern") and not args:
        return s.strip() if callee == "trim" else s
    if callee == "length":
        return len(s)
    if callee == "isEmpty":
        return len(s) == 0
    if callee in ("equals", "contentEquals"):
        return (s == a0) if isinstance(a0, str) else (False if a0 is None else UNKNOWN)
    if callee == "equalsIgnoreCase":
        return (s.lower() == a0.lower()) if isinstance(a0, str) else (False if a0 is None else UNKNOWN)
    if not isinstance(a0, (str, int)) and callee not in ("toLowerCase", "toUpperCase", "split", "hashCode"):
        if callee in ("startsWith", "endsWith", "contains", "indexOf", "charAt", "substring", "concat",
                      "compareTo", "replace", "matches"):
            return UNKNOWN
    if callee == "startsWith" and isinstance(a0, str):
        return s.startswith(a0)
    if callee == "endsWith" and isinstance(a0, str):
        return s.endswith(a0)
    if callee == "contains" and isinstance(a0, str):
        return a0 in s
    if callee == "indexOf" and isinstance(a0, str):
        return s.find(a0)
    if callee == "charAt" and isinstance(a0, int):
        return s[a0] if 0 <= a0 < len(s) else UNKNOWN
    if callee == "substring" and isinstance(a0, int):
        a1 = args[1] if len(args) > 1 else None
        return s[a0:a1] if a1 is None or isinstance(a1, int) else UNKNOWN
    if callee == "toLowerCase":
        return s.lower()
    if callee == "toUpperCase":
        return s.upper()
    if callee == "split" and isinstance(a0, str):
        try:
            return ListV(re.split(a0, s))
        except re.error:
            return ListV(s.split(a0))
    if callee == "concat" and isinstance(a0, str):
        return s + a0
    if callee == "replace" and isinstance(a0, str) and len(args) > 1 and isinstance(args[1], str):
        return s.replace(a0, args[1])
    if callee == "compareTo" and isinstance(a0, str):
        return (s > a0) - (s < a0)
    return UNKNOWN


def _number(n: Any, callee: str, args: list[Any]) -> Any:
    a0 = num(args[0]) if args else UNKNOWN
    if callee in ("intValue", "longValue"):
        return int(n)
    if callee in ("doubleValue", "floatValue"):
        return float(n)
    if callee == "toString":
        return to_jstr(n)
    if callee == "compareTo" and a0 is not UNKNOWN:
        return (n > a0) - (n < a0)
    if callee == "equals":
        return (n == a0) if a0 is not UNKNOWN else UNKNOWN
    if a0 is UNKNOWN:
        return UNKNOWN
    if callee == "add":
        return n + a0
    if callee == "subtract":
        return n - a0
    if callee == "multiply":
        return n * a0
    if callee == "divide":
        return n / a0 if a0 else UNKNOWN
    if callee == "setScale":
        return round(n, int(a0))
    if callee in ("max", "min"):
        return max(n, a0) if callee == "max" else min(n, a0)
    return UNKNOWN


def _optional(it: Interpreter, fr: Frame, o: OptionalV, callee: str, args: list[Any]) -> Any:
    v = o.value
    if callee == "isPresent":
        return UNKNOWN if v is UNKNOWN or o.maybe else v is not None
    if callee == "isEmpty":
        return UNKNOWN if v is UNKNOWN or o.maybe else v is None
    if o.maybe and callee in ("orElse", "orElseGet", "orElseThrow"):
        if callee == "orElseGet" and args:
            _run(it, args[0], [], fr)
        return UNKNOWN if callee == "orElse" else v
    if callee == "get":
        return v if v is not None else UNKNOWN
    if callee == "orElse":
        if v is UNKNOWN:
            return UNKNOWN
        return v if v is not None else (args[0] if args else None)
    if callee in ("orElseGet", "orElseThrow"):
        # supplier вызывается только для пустого Optional (R16)
        if v is None:
            r = _run(it, args[0], [], fr) if args else UNKNOWN
            return r if callee == "orElseGet" else UNKNOWN
        return v
    if callee == "ifPresent":
        if v is not None and args:
            _run(it, args[0], [v], fr)
        return None
    if callee == "map":
        if v is None:
            return o
        return OptionalV(_run(it, args[0], [v], fr) if args else UNKNOWN)
    return UNKNOWN


def _list(it: Interpreter, fr: Frame, lst: ListV, callee: str, args: list[Any]) -> Any:
    a0 = args[0] if args else UNKNOWN
    if callee == "size":
        return len(lst.items) if lst.exact else UNKNOWN
    if callee == "isEmpty":
        # у неточного списка элементы только возможные (UNKNOWN-плечи, неточный запрос): пустота неизвестна
        return (not lst.items) if lst.exact else UNKNOWN
    if callee in ("add", "addAll", "clear", "remove", "set"):
        it.touch_list(lst)
    if callee == "add":
        if len(args) == 1:
            return _add(lst, a0)
        else:
            lst.items.insert(a0 if isinstance(a0, int) else len(lst.items), args[1] if len(args) > 1 else UNKNOWN)
            if not isinstance(a0, int):
                lst.exact = False
        return True
    if callee == "addAll":
        if isinstance(a0, ListV):
            for x in a0.items:
                _add(lst, x)
            lst.exact = lst.exact and a0.exact
        else:
            lst.exact = False
        return True
    if callee == "get":
        if isinstance(a0, int) and 0 <= a0 < len(lst.items):
            if lst.exact or a0 < len(lst.items):
                return lst.items[a0]
        return UNKNOWN
    if callee in ("contains", "indexOf", "remove"):
        # library вызывает equals элемента (блок 8: Order#equals из list.contains)
        _element_equals(it, fr, lst, a0)
        if callee == "remove" and isinstance(a0, int) and not isinstance(a0, bool) and not lst.is_set:
            if lst.exact and 0 <= a0 < len(lst.items):
                return lst.items.pop(a0)
            lst.exact = False
            return UNKNOWN
        idx, sure = _find(lst, a0)
        if callee == "contains":
            return True if idx >= 0 and lst.exact else (False if sure else UNKNOWN)
        if callee == "indexOf":
            return idx if idx >= 0 and sure else (-1 if sure else UNKNOWN)
        if idx >= 0:
            lst.items.pop(idx)
            if not sure:
                lst.exact = False
            return True
        if not sure:
            lst.exact = False
            return UNKNOWN
        return False
    if callee in ("removeAll", "retainAll"):
        it.touch_list(lst)
        if not isinstance(a0, ListV):
            lst.exact = False
            return UNKNOWN
        keep = []
        for x in lst.items:
            idx, sure = _find(a0, x)
            hit = idx >= 0
            if (callee == "removeAll") != hit:
                keep.append(x)
            if not sure:
                lst.exact = False
        lst.items[:] = keep
        lst.exact = lst.exact and a0.exact
        return True
    if callee == "containsAll" and isinstance(a0, ListV):
        res: Any = True
        for x in a0.items:
            idx, sure = _find(lst, x)
            if idx < 0:
                if sure:
                    return False
                res = UNKNOWN
        return res if a0.exact else UNKNOWN
    if callee in ("iterator", "listIterator"):
        return Obj("java.util.Iterator", {"#items": list(lst.items), "#i": 0, "#exact": lst.exact}, open=False)
    if callee in ("stream", "parallelStream", "toArray", "sorted", "distinct"):
        if callee == "sorted" and args:
            _run(it, a0, [lst.items[0] if lst.items else UNKNOWN] * 2, fr)
        return ListV(list(lst.items), exact=lst.exact, elem_type=lst.elem_type)
    if callee in ("sort",):
        if args and lst.items:
            _run(it, a0, [lst.items[0], lst.items[-1]], fr)
        return None
    if callee == "filter":
        out, exact = [], lst.exact
        for x in lst.items:
            r = tri(_run(it, a0, [x], fr))
            if r is True:
                out.append(x)
            elif r is UNKNOWN:
                out.append(x)
                exact = False
        if not lst.items and not lst.exact:
            _run(it, a0, [UNKNOWN], fr)
        return ListV(out, exact=exact)
    if callee == "map":
        items = [_run(it, a0, [x], fr) for x in lst.items]
        if not lst.items and not lst.exact:
            _run(it, a0, [UNKNOWN], fr)
        return ListV(items, exact=lst.exact)
    if callee == "forEach":
        for x in lst.items or ([] if lst.exact else [UNKNOWN]):
            _run(it, a0, [x], fr)
        return None
    if callee in ("collect", "toList"):
        return ListV(list(lst.items), exact=lst.exact)
    if callee == "count":
        return len(lst.items) if lst.exact else UNKNOWN
    if callee in ("findFirst", "findAny"):
        if lst.items:
            return OptionalV(lst.items[0]) if lst.exact else OptionalV(UNKNOWN)
        return OptionalV(None) if lst.exact else OptionalV(UNKNOWN)
    if callee in ("anyMatch", "allMatch", "noneMatch"):
        rs = [tri(_run(it, a0, [x], fr)) for x in lst.items]
        if callee == "anyMatch":
            if True in rs:
                return True
            return False if lst.exact and UNKNOWN not in rs else UNKNOWN
        if callee == "allMatch":
            if False in rs:
                return False
            return True if lst.exact and UNKNOWN not in rs else UNKNOWN
        if True in rs:
            return False
        return True if lst.exact and UNKNOWN not in rs else UNKNOWN
    if callee in ("hasNext", "next"):
        return UNKNOWN
    if callee == "clear":
        lst.items.clear()
        lst.exact = True
        return None
    if callee == "set":
        return UNKNOWN
    _run_unknown_lambdas(it, args, fr)
    return UNKNOWN


def _find(lst: ListV, v: Any) -> tuple[int, bool]:
    """Индекс первого равного элемента и уверенность (False — равенство с частью элементов неизвестно)."""
    sure = lst.exact
    for i, x in enumerate(lst.items):
        r = equals_value(x, v)
        if r is True:
            return i, sure
        if r is UNKNOWN:
            sure = False
    return -1, sure


def _add(lst: ListV, v: Any) -> Any:
    if lst.is_set:
        idx, sure = _find(lst, v)
        if idx >= 0:
            return False
        if not sure and v is UNKNOWN:
            lst.exact = False
    lst.items.append(v)
    return True


def _element_equals(it: Interpreter, fr: Frame, lst: ListV, probe: Any) -> None:
    """list.contains(x) вызывает x.equals(элемент): проектный equals исполняется (без ребра calls)."""
    if not lst.items or not isinstance(probe, Obj) or not probe.type:
        return
    tid = it.types.resolve(probe.type, fr.module)
    eq = it.types.method_of(tid, "equals", 1)
    if eq and eq in it.ir and getattr(it.rules, "element_callbacks", "on") != "off":
        it.sink.execute(eq, ("STATE", "ELEMENT_CALLBACK:contains(m4)"), f"library|{fr.method}|contains")
        it.invoke(eq, probe, [lst.items[0]], fr.unit, ("STATE", "ELEMENT_CALLBACK:contains(m4)"))


def _map(m: MapV, callee: str, args: list[Any]) -> Any:
    a0 = args[0] if args else UNKNOWN
    hashable = isinstance(a0, (str, int, float, bool)) or a0 is None
    if callee == "put":
        if hashable:
            m.data[a0] = args[1] if len(args) > 1 else UNKNOWN
        else:
            m.exact = False
        return None
    if callee in ("get", "getOrDefault"):
        if hashable and a0 in m.data:
            return m.data[a0]
        if m.exact and hashable:
            return args[1] if callee == "getOrDefault" and len(args) > 1 else None
        return UNKNOWN
    if callee == "containsKey":
        if hashable and a0 in m.data:
            return True
        return False if m.exact and hashable else UNKNOWN
    if callee in ("keySet",):
        return ListV(list(m.data.keys()), exact=m.exact, is_set=True)
    if callee in ("values",):
        return ListV(list(m.data.values()), exact=m.exact)
    if callee == "size":
        return len(m.data) if m.exact else UNKNOWN
    if callee == "isEmpty":
        return (not m.data) if m.exact else (False if m.data else UNKNOWN)
    if callee == "entrySet":
        return ListV([Obj("java.util.Map$Entry", {"key": k, "value": v}, open=False) for k, v in m.data.items()],
                     exact=m.exact)
    return UNKNOWN


def _static(it: Interpreter, fr: Frame, t: TypeRef, callee: str, args: list[Any]) -> Any:
    simple = t.fqn.rsplit(".", 1)[-1]
    a0 = args[0] if args else UNKNOWN
    if simple in ("JSON", "JSONObject", "JSONArray") and (callee in _JSON_WRITE or callee in _JSON_READ):
        return _json(callee, args)
    tid = it.types.resolve(t.fqn, fr.module)
    if tid and callee == "builder" and not args:
        return Obj(t.fqn, {"#builder": True}, open=False)
    if tid and it.types.is_enum(tid):
        if callee == "values":
            return ListV([it.enum_const(tid, c) for c, _ in it.types.enum_constants(tid)])
        if callee == "valueOf" and isinstance(a0, str):
            return it.enum_const(tid, a0)
        return UNKNOWN
    if simple == "Calendar" and callee == "getInstance":
        return DateV(NOW, calendar=True)
    if simple == "UUID" and callee == "randomUUID":
        return fresh_uuid()
    if simple == "UUID" and callee in ("fromString", "nameUUIDFromBytes"):
        return a0 if isinstance(a0, str) and callee == "fromString" else UNKNOWN
    if simple in ("String",) and callee == "valueOf":
        return to_jstr(a0)
    if simple in ("String",) and callee == "format":
        return UNKNOWN
    if simple in ("Integer", "Long") and callee in ("parseInt", "valueOf", "parseLong"):
        n = num(a0)
        return int(n) if n is not UNKNOWN else UNKNOWN
    if simple in ("Double", "Float") and callee in ("parseDouble", "valueOf", "parseFloat"):
        n = num(a0)
        return float(n) if n is not UNKNOWN else UNKNOWN
    if simple == "Math":
        ns = [num(a) for a in args]
        if any(n is UNKNOWN for n in ns):
            return UNKNOWN
        fn = {"abs": abs, "max": max, "min": min, "round": round}.get(callee)
        return fn(*ns) if fn else UNKNOWN
    if simple == "Optional":
        if callee == "of":
            return OptionalV(a0)
        if callee == "ofNullable":
            return OptionalV(UNKNOWN if a0 is UNKNOWN else a0)
        if callee == "empty":
            return OptionalV(None)
    if simple in ("Arrays", "List", "Set", "Collections", "Stream") and callee in ("asList", "of", "singletonList",
                                                                                  "emptyList", "stream"):
        if callee in ("stream", "asList") and len(args) == 1 and isinstance(a0, ListV):
            return ListV(list(a0.items), exact=a0.exact, elem_type=a0.elem_type)
        if any(a is UNKNOWN for a in args) and callee == "asList" and len(args) == 1:
            return ListV([], exact=False)
        return ListV(list(args))
    if simple == "Collections" and callee == "sort":
        return None
    if simple == "Objects":
        if callee in ("isNull", "nonNull"):
            if a0 is UNKNOWN:
                return UNKNOWN
            return (a0 is None) if callee == "isNull" else (a0 is not None)
        if callee == "equals" and len(args) == 2:
            return equals_value(args[0], args[1])
        if callee == "requireNonNull":
            return a0
    if simple == "StringUtils" and callee in ("isEmpty", "hasText", "hasLength", "isBlank", "isNotEmpty"):
        if a0 is UNKNOWN or isinstance(a0, Concat):
            return UNKNOWN
        empty = a0 is None or (isinstance(a0, str) and (a0 == "" if callee in ("isEmpty", "hasLength", "isNotEmpty")
                                                         else a0.strip() == ""))
        return empty if callee in ("isEmpty", "isBlank") else (not empty)
    if simple in ("ResponseEntity",) and callee == "ok":
        return Wrapper(a0 if args else None, "response")
    if simple == "System" and callee == "currentTimeMillis":
        return UNKNOWN
    _run_unknown_lambdas(it, args, fr)
    return UNKNOWN


__all__ = ["call_library", "new_library", "json_copy", "t_not"]
