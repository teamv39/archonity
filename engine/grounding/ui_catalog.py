"""Каталог UI-запросов из ts-ui-dashboard (ADR-005, M1, п. 1).

Каждая запись — один HTTP-запрос, который UI отправляет через шлюз: JS-функция действия, страница, надписи кнопок,
глагол, шаблон URL, поля тела (литералы — отдельно), условия выбора варианта и сопоставленные обработчики скелета.

Разбор по AST tree-sitter-javascript. Поддерживаются вызовы `$.ajax({...})`, `$http({...})` (Angular) и позиционные
`$.get/$.post/$http.get/...`. URL вычисляется из литералов и конкатенаций (`"/cancel/" + id` → `/cancel/{id}`),
из локальной переменной с присваиваниями по веткам (каждая ветка — вариант со своим условием) и из параметра
функции-помощника (по местам её вызова в том же файле, на одну ступень вверх).
"""
from __future__ import annotations

import collections
import html.parser
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

import tree_sitter as ts
import tree_sitter_javascript as tsj

from engine.adapters.skeleton import SkeletonIndex, path_segs

logger = logging.getLogger(__name__)

VENDOR = re.compile(
    r"(\.min\.|^(vue|angular|jquery|bootstrap|echarts|amazeui|iscroll|cropper|aliyun|react|lodash|moment|d3|three|npm)\b"
    r"|^vue-upload)",
    re.I,
)
SKIP_DIR = {"node_modules", "target", "build", "dist", ".git", "bower_components"}

FUNC_TYPES = {"function_declaration", "function_expression", "function", "arrow_function", "method_definition",
              "generator_function_declaration"}
# Колбэки, которые не являются действием пользователя: поднимаемся к внешней функции
CALLBACK_NAMES = {"success", "error", "complete", "beforeSend", "onConfirm", "onCancel", "then", "callback", "done",
                  "fail", "always", "catch", "finally", "function", "ready"}
EVENT_METHODS = {"click", "change", "submit", "dblclick", "keyup", "keydown", "blur", "focus"}
AJAX_OBJ = {"$.ajax", "jQuery.ajax", "$http"}
AJAX_POS = {"$.get": "GET", "$.post": "POST", "$.getJSON": "GET", "$http.get": "GET", "$http.post": "POST",
            "$http.put": "PUT", "$http.delete": "DELETE", "axios.get": "GET", "axios.post": "POST",
            "axios.put": "PUT", "axios.delete": "DELETE"}
MAX_GUARD = 160

_JS = ts.Language(tsj.language())


@dataclass
class UIRequest:
    """Один запрос UI через шлюз (вариант URL, если путь выбирается условием)."""

    id: str
    file: str
    line: int
    function: str
    verb: str
    url: str
    via_line: int | None = None
    outer: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    guards: list[str] = field(default_factory=list)
    body_fields: list[str] = field(default_factory=list)
    body_consts: dict[str, Any] = field(default_factory=dict)
    body_cond: list[dict[str, Any]] = field(default_factory=list)
    body_opt: list[dict[str, Any]] = field(default_factory=list)
    # Поле тела -> поле элемента списка в шаблоне, из которого UI его берёт (`payMyOrder(item.trainNumber)` ->
    # `this.tripId` -> `info.tripId`): {"tripId": "trainNumber"}. Только поля, чьё имя отличается от источника
    body_src: dict[str, str] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    handlers: list[str] = field(default_factory=list)
    group: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------- узлы AST


def _text(n: ts.Node | None) -> str:
    return n.text.decode("utf-8", "replace") if n is not None and n.text is not None else ""


def _line(n: ts.Node) -> int:
    return n.start_point[0] + 1


def _norm(s: str, limit: int = MAX_GUARD) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _walk(n: ts.Node) -> Iterator[ts.Node]:
    st = [n]
    while st:
        x = st.pop()
        yield x
        st.extend(reversed(x.children))


def _string_value(n: ts.Node) -> str | None:
    if n.type == "string":
        return _text(n)[1:-1]
    if n.type == "template_string" and not any(c.type == "template_substitution" for c in n.children):
        return _text(n)[1:-1]
    return None


def _literal(n: ts.Node | None) -> tuple[bool, Any]:
    """JS-литерал → (да, значение Python)."""
    if n is None:
        return False, None
    if n.type == "parenthesized_expression" and n.named_child_count == 1:
        return _literal(n.named_children[0])
    s = _string_value(n)
    if s is not None:
        return True, s
    if n.type == "true":
        return True, True
    if n.type == "false":
        return True, False
    if n.type in ("null", "undefined"):
        return True, None
    if n.type == "number":
        t = _text(n)
        try:
            return True, int(t)
        except ValueError:
            try:
                return True, float(t)
            except ValueError:
                return False, None
    if n.type == "unary_expression" and _text(n.child_by_field_name("operator")) == "-":
        ok, v = _literal(n.child_by_field_name("argument"))
        if ok and isinstance(v, (int, float)):
            return True, -v
    return False, None


def _callee(n: ts.Node) -> str:
    return re.sub(r"\s+", "", _text(n.child_by_field_name("function")))


def _func_name(fn: ts.Node) -> str | None:
    """Имя функции по месту объявления: `function f`, метод Vue, `x.f = function`, `f: function`, `$("#id").click(fn)`."""
    nm = fn.child_by_field_name("name")
    if nm is not None:
        return _text(nm)
    p = fn.parent
    if p is None:
        return None
    if p.type == "variable_declarator":
        return _text(p.child_by_field_name("name"))
    if p.type == "assignment_expression":
        left = p.child_by_field_name("left")
        if left is not None and left.type == "member_expression":
            return _text(left.child_by_field_name("property"))
        return _text(left)
    if p.type == "pair":
        return _text(p.child_by_field_name("key")).strip("'\"")
    if p.type == "arguments" and p.parent is not None and p.parent.type == "call_expression":
        f = p.parent.child_by_field_name("function")
        if f is not None and f.type == "member_expression":
            meth = _text(f.child_by_field_name("property"))
            obj = f.child_by_field_name("object")
            sel = _selector(obj)
            if meth in EVENT_METHODS and sel:
                return f"{meth}:{sel}"
            if meth == "on" and sel:
                return f"on:{sel}"
            first = p.named_children[0] if p.named_children else None
            label = _string_value(first) if first is not None and first != fn else None
            if f is not None and f.type == "member_expression" and label:
                return f"{_text(f.child_by_field_name('property'))}:{label}"
        if f is not None and _text(f) in ("$", "jQuery"):
            return "ready"
    return None


def _selector(obj: ts.Node | None) -> str | None:
    """`$("#id")` → `#id`."""
    if obj is None or obj.type != "call_expression" or _text(obj.child_by_field_name("function")) not in ("$", "jQuery"):
        return None
    args = obj.child_by_field_name("arguments")
    if args is None or not args.named_children:
        return None
    s = _string_value(args.named_children[0])
    return s.strip() if s else None


def _functions_up(n: ts.Node) -> list[ts.Node]:
    out, p = [], n.parent
    while p is not None:
        if p.type in FUNC_TYPES:
            out.append(p)
        p = p.parent
    return out


def _action_fn(n: ts.Node) -> ts.Node | None:
    """Узел функции действия: ближайшая именованная функция, не колбэк."""
    for f in _functions_up(n):
        nm = _func_name(f)
        if nm and nm not in CALLBACK_NAMES:
            return f
    return None


RESPONSE_CB = {"success", "then", "done"}


def _response_of(fn: ts.Node) -> str | None:
    """Если функция — обработчик ответа запроса (`success: function`, `$http(...).success(fn)`), то `VERB url` запроса."""
    p = fn.parent
    call = None
    if p is not None and p.type == "pair" and _text(p.child_by_field_name("key")).strip("'\"") in RESPONSE_CB:
        obj = p.parent
        args = obj.parent if obj is not None else None
        call = args.parent if args is not None and args.type == "arguments" else None
    elif p is not None and p.type == "arguments" and p.parent is not None and p.parent.type == "call_expression":
        f = p.parent.child_by_field_name("function")
        if f is not None and f.type == "member_expression" and _text(f.child_by_field_name("property")) in RESPONSE_CB:
            call = f.child_by_field_name("object")
    if call is None or call.type != "call_expression" or _callee(call) not in AJAX_OBJ:
        return None
    args = call.child_by_field_name("arguments")
    if args is None or not args.named_children or args.named_children[0].type != "object":
        return None
    props = {_text(x.child_by_field_name("key")).strip("'\""): x.child_by_field_name("value")
             for x in args.named_children[0].named_children if x.type == "pair"}
    verb = _string_value(props["type"] if "type" in props else props.get("method")) if (
        "type" in props or "method" in props) else "GET"
    url = props.get("url")
    url_s = (_string_value(url) or _text(url)) if url is not None else "?"
    return f"in the response handler of {(verb or 'GET').upper()} {_norm(url_s, 80)}"


def _action_name(n: ts.Node) -> tuple[str, list[str]]:
    """Ближайшая именованная функция, не колбэк, и цепочка имён наружу."""
    names = [nm for nm in (_func_name(f) for f in _functions_up(n)) if nm]
    for nm in names:
        if nm not in CALLBACK_NAMES:
            return nm, names
    return (names[0] if names else "<top>"), names


def _params(fn: ts.Node) -> list[str]:
    ps = fn.child_by_field_name("parameters") or fn.child_by_field_name("parameter")
    if ps is None:
        return []
    if ps.type == "identifier":
        return [_text(ps)]
    out = []
    for c in ps.named_children:
        if c.type == "identifier":
            out.append(_text(c))
        elif c.type == "assignment_pattern":
            out.append(_text(c.child_by_field_name("left")))
    return out


def _guards(n: ts.Node, stop: ts.Node | None) -> list[str]:
    """Условия ветвлений между узлом и `stop` (снаружи внутрь)."""
    out: list[str] = []
    child, p = n, n.parent
    while p is not None and p != stop:
        if p.type == "if_statement":
            cond = _norm(_text(_unparen(p.child_by_field_name("condition"))))
            if _contains(p.child_by_field_name("consequence"), child):
                out.append(cond)
            elif _contains(p.child_by_field_name("alternative"), child):
                out.append(f"!({cond})")
        elif p.type == "ternary_expression":
            cond = _norm(_text(p.child_by_field_name("condition")))
            if _contains(p.child_by_field_name("consequence"), child):
                out.append(cond)
            elif _contains(p.child_by_field_name("alternative"), child):
                out.append(f"!({cond})")
        elif p.type == "switch_case":
            out.append(_norm("case " + _text(p.child_by_field_name("value"))))
        elif p.type in FUNC_TYPES:
            resp = _response_of(p)
            if resp:
                out.append(resp)
        child, p = p, p.parent
    return list(reversed(out))


def _unparen(n: ts.Node | None) -> ts.Node | None:
    while n is not None and n.type == "parenthesized_expression" and n.named_child_count == 1:
        n = n.named_children[0]
    return n


def _contains(outer: ts.Node | None, inner: ts.Node) -> bool:
    return outer is not None and outer.start_byte <= inner.start_byte and inner.end_byte <= outer.end_byte


def _placeholder(n: ts.Node) -> str:
    """Имя переменной части пути: `orderId`, `item.id` → `id`, `sessionStorage.getItem("client_id")` → `client_id`."""
    if n.type == "identifier":
        return _text(n)
    if n.type == "member_expression":
        return _text(n.child_by_field_name("property"))
    if n.type == "call_expression":
        args = n.child_by_field_name("arguments")
        if args is not None and args.named_children:
            s = _string_value(args.named_children[0])
            if s:
                return s
        f = n.child_by_field_name("function")
        if f is not None and f.type == "member_expression":
            return _text(f.child_by_field_name("property"))
        return _text(f) or "var"
    if n.type == "parenthesized_expression" and n.named_children:
        return _placeholder(n.named_children[0])
    return "var"


# ---------------------------------------------------------------- разбор файла


@dataclass
class _Ctx:
    """Привязка параметров функции-помощника к аргументам места вызова."""

    env: dict[str, ts.Node]
    via: ts.Node | None
    guards: list[str]


class _FileParser:
    def __init__(self, rel: str, src: bytes) -> None:
        self.rel = rel
        self.tree = ts.Parser(_JS).parse(src)
        self.root = self.tree.root_node
        self.calls_by_name: dict[str, list[ts.Node]] = collections.defaultdict(list)
        self._state: dict[str, tuple[str, int]] | None = None
        for n in _walk(self.root):
            if n.type == "call_expression":
                f = n.child_by_field_name("function")
                if f is None:
                    continue
                if f.type == "identifier":
                    self.calls_by_name[_text(f)].append(n)
                elif f.type == "member_expression":
                    self.calls_by_name[_text(f.child_by_field_name("property"))].append(n)

    # --- значения выражений

    def _scope_assignments(self, name: str, at: ts.Node) -> tuple[list[tuple[ts.Node, ts.Node]], ts.Node | None]:
        """Присваивания `name = expr` / `var name = expr` в ближайшей функции, где они есть: [(узел, значение)], функция."""
        for fn in _functions_up(at) + [self.root]:
            found = []
            for n in _walk(fn):
                if n.type == "variable_declarator" and _text(n.child_by_field_name("name")) == name:
                    v = n.child_by_field_name("value")
                    if v is not None:
                        found.append((n, v))
                elif n.type == "assignment_expression":
                    left = n.child_by_field_name("left")
                    if left is not None and left.type == "identifier" and _text(left) == name:
                        found.append((n, n.child_by_field_name("right")))
            if found:
                return found, fn
        return [], None

    def _param_owner(self, name: str, at: ts.Node) -> ts.Node | None:
        for fn in _functions_up(at):
            if name in _params(fn):
                return fn
        return None

    def url_variants(self, expr: ts.Node, ctx: _Ctx, top: bool = True) -> list[tuple[str, list[str]]]:
        """Выражение URL → [(шаблон, условия)]."""
        s = _string_value(expr)
        if s is not None:
            return [(s, [])]
        t = expr.type
        if t == "parenthesized_expression" and expr.named_children:
            return self.url_variants(expr.named_children[0], ctx, top)
        if t == "template_string":
            out = ""
            for c in expr.children:
                if c.type == "template_substitution":
                    inner = c.named_children[0] if c.named_children else c
                    out += "{" + _placeholder(inner) + "}"
                elif c.type not in ("`",):
                    out += _text(c)
            return [(out, [])]
        if t == "binary_expression" and _text(expr.child_by_field_name("operator")) == "+":
            left = self.url_variants(expr.child_by_field_name("left"), ctx, top=False)
            right = self.url_variants(expr.child_by_field_name("right"), ctx, top=False)
            return [(a + b, ga + gb) for a, ga in left for b, gb in right]
        if t == "ternary_expression":
            cond = _norm(_text(expr.child_by_field_name("condition")))
            return ([(u, [cond] + g) for u, g in self.url_variants(expr.child_by_field_name("consequence"), ctx, top)]
                    + [(u, [f"!({cond})"] + g)
                       for u, g in self.url_variants(expr.child_by_field_name("alternative"), ctx, top)])
        if t == "identifier":
            name = _text(expr)
            if name in ctx.env:
                return self.url_variants(ctx.env[name], _Ctx({}, None, []), top)
            assigns, scope = self._scope_assignments(name, expr)
            stringy = [(n, v) for n, v in assigns if v is not None and _is_stringy(v)]
            if stringy:
                out = []
                for n, v in stringy:
                    g = _guards(n, scope)
                    out += [(u, g + gg) for u, gg in self.url_variants(v, ctx, top)]
                return out
        return [("{" + _placeholder(expr) + "}", [])]

    def body(self, expr: ts.Node | None, ctx: _Ctx,
             seen: frozenset[str] = frozenset()
             ) -> tuple[list[str], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Тело запроса → (поля, литералы без условий, литералы под условием, поля только под условием).

        Поле только под условием: каждое присваивание стоит под общим условием, без него UI поле не шлёт."""
        if expr is None:
            return [], {}, [], []
        if expr.type == "identifier" and _text(expr) in ctx.env:
            return self.body(ctx.env[_text(expr)], _Ctx({}, None, []), seen)
        if expr.type == "call_expression" and _callee(expr) == "JSON.stringify":
            args = expr.child_by_field_name("arguments")
            return self.body(args.named_children[0] if args and args.named_children else None, ctx, seen)
        if expr.type == "object":
            return (*self._object_fields(expr, None), [])
        if expr.type != "identifier":
            return [], {}, [], []
        name = _text(expr)
        assigns, scope = self._scope_assignments(name, expr)
        if name not in seen:
            for _, v in assigns:
                if v is not None and v.type == "call_expression" and _callee(v) == "JSON.stringify":
                    return self.body(v, ctx, seen | {name})
        fields: list[str] = []
        consts: dict[str, Any] = {}
        cond: list[dict[str, Any]] = []
        opt: list[dict[str, Any]] = []
        seen: dict[str, list[tuple[bool, Any, list[str]]]] = collections.defaultdict(list)
        for _, v in assigns:
            if v is not None and v.type == "object":
                f, c, cc = self._object_fields(v, scope)
                fields += f
                for k in f:
                    if k in c:
                        seen[k].append((True, c[k], []))
                    else:
                        seen[k].append((False, None, []))
        if scope is not None:
            for n in _walk(scope):
                if n.type != "assignment_expression":
                    continue
                left = n.child_by_field_name("left")
                if left is None or left.type != "member_expression" or _text(left.child_by_field_name("object")) != name:
                    continue
                k = _text(left.child_by_field_name("property"))
                ok, val = _literal(n.child_by_field_name("right"))
                seen[k].append((ok, val, _guards(n, scope)))
                if k not in fields:
                    fields.append(k)
        for k, vals in seen.items():
            if all(ok and not g for ok, _, g in vals) and len({json.dumps(v) for _, v, _ in vals}) == 1:
                consts[k] = vals[0][1]
            else:
                for ok, val, g in vals:
                    if ok:
                        cond.append({"field": k, "value": val, "guards": g})
            common: list[str] = []
            for parts in zip(*(g for _, _, g in vals)):
                if len(set(parts)) != 1:
                    break
                common.append(parts[0])
            if common and all(g for _, _, g in vals):
                opt.append({"field": k, "guards": common})
        return fields, consts, cond, opt

    def _object_fields(self, obj: ts.Node, scope: ts.Node | None) -> tuple[list[str], dict[str, Any], list[dict[str, Any]]]:
        fields, consts = [], {}
        for p in obj.named_children:
            if p.type == "pair":
                k = _text(p.child_by_field_name("key")).strip("'\"")
                fields.append(k)
                ok, v = _literal(p.child_by_field_name("value"))
                if ok:
                    consts[k] = v
            elif p.type == "shorthand_property_identifier":
                fields.append(_text(p))
        return fields, consts, []

    # --- контексты вызова

    def state_params(self) -> dict[str, tuple[str, int]]:
        """Состояние компонента из параметров его методов: `this.P = p` в методе `m(…, p, …)` -> {P: (m, индекс p)}.
        Свойство, которое присваивают из разных мест, не берётся."""
        if self._state is None:
            found: dict[str, set[tuple[str, int]]] = collections.defaultdict(set)
            for fn in _walk(self.root):
                if fn.type not in FUNC_TYPES:
                    continue
                name, params = _func_name(fn), _params(fn)
                if not name or not params:
                    continue
                for n in _walk(fn):
                    if n.type != "assignment_expression":
                        continue
                    left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
                    if left is not None and left.type == "member_expression" \
                            and _text(left.child_by_field_name("object")) == "this" \
                            and right is not None and right.type == "identifier" and _text(right) in params \
                            and self._param_owner(_text(right), n) == fn:
                        found[_text(left.child_by_field_name("property"))].add((name, params.index(_text(right))))
            self._state = {k: next(iter(v)) for k, v in found.items() if len(v) == 1}
        return self._state

    def _is_this(self, n: ts.Node | None) -> bool:
        """`this` или переменная, которой присвоен `this` (`var that = this`)."""
        if n is None:
            return False
        if n.type == "this":
            return True
        if n.type != "identifier":
            return False
        assigns, _ = self._scope_assignments(_text(n), n)
        return bool(assigns) and all(v is not None and v.type == "this" for _, v in assigns)

    def _source(self, v: ts.Node | None) -> tuple[str, int] | None:
        """Значение поля тела — параметр метода UI, прямо или через состояние компонента: (метод, индекс)."""
        if v is None:
            return None
        if v.type == "member_expression" and self._is_this(v.child_by_field_name("object")):
            return self.state_params().get(_text(v.child_by_field_name("property")))
        if v.type == "identifier":
            owner = self._param_owner(_text(v), v)
            name = _func_name(owner) if owner is not None else None
            if name:
                return name, _params(owner).index(_text(v))
        return None

    def body_sources(self, expr: ts.Node | None, ctx: _Ctx,
                     seen: frozenset[str] = frozenset()) -> dict[str, list[Any]]:
        """Поля тела, значение которых — параметр метода UI: {поле: [метод, индекс]}. Аргумент на месте вызова
        метода в шаблоне страницы сопоставляет `build_catalog`."""
        if expr is None:
            return {}
        if expr.type == "identifier" and _text(expr) in ctx.env:
            return self.body_sources(ctx.env[_text(expr)], _Ctx({}, None, []), seen)
        if expr.type == "call_expression" and _callee(expr) == "JSON.stringify":
            args = expr.child_by_field_name("arguments")
            return self.body_sources(args.named_children[0] if args and args.named_children else None, ctx, seen)
        out: dict[str, list[Any]] = {}
        if expr.type == "object":
            for pr in expr.named_children:
                src = self._source(pr.child_by_field_name("value")) if pr.type == "pair" else None
                if src:
                    out[_text(pr.child_by_field_name("key")).strip("'\"")] = list(src)
            return out
        if expr.type != "identifier":
            return {}
        name = _text(expr)
        assigns, scope = self._scope_assignments(name, expr)
        for _, v in assigns:
            if v is not None and v.type == "call_expression" and _callee(v) == "JSON.stringify" and name not in seen:
                return self.body_sources(v, ctx, seen | {name})
            if v is not None and v.type == "object":
                out.update(self.body_sources(v, ctx, seen))
        if scope is not None:
            for n in _walk(scope):
                left = n.child_by_field_name("left") if n.type == "assignment_expression" else None
                if left is None or left.type != "member_expression" or _text(left.child_by_field_name("object")) != name:
                    continue
                src = self._source(n.child_by_field_name("right"))
                if src:
                    out[_text(left.child_by_field_name("property"))] = list(src)
        return out

    def contexts(self, call: ts.Node, used: Iterable[ts.Node]) -> list[_Ctx]:
        """Если URL/тело берутся из параметров функции-помощника — по контексту на каждое её место вызова."""
        owner = None
        for n in used:
            if n.type == "identifier":
                owner = self._param_owner(_text(n), call)
                if owner is not None:
                    break
        if owner is None:
            return [_Ctx({}, None, [])]
        name = _func_name(owner)
        params = _params(owner)
        sites = [c for c in self.calls_by_name.get(name or "", []) if not _contains(owner, c)]
        if not sites:
            return [_Ctx({}, None, [])]
        out = []
        for site in sites:
            args = site.child_by_field_name("arguments")
            a = args.named_children if args is not None else []
            env = {p: a[i] for i, p in enumerate(params) if i < len(a)}
            out.append(_Ctx(env, site, _guards(site, _action_fn(site))))
        return out

    def requests(self) -> Iterator[dict[str, Any]]:
        for call in _walk(self.root):
            if call.type != "call_expression":
                continue
            callee = _callee(call)
            args = call.child_by_field_name("arguments")
            a = args.named_children if args is not None else []
            if callee in AJAX_OBJ and a and a[0].type == "object":
                props = {}
                for p in a[0].named_children:
                    if p.type == "pair":
                        props[_text(p.child_by_field_name("key")).strip("'\"")] = p.child_by_field_name("value")
                url = props.get("url")
                if url is None:
                    continue
                verb_node = props.get("type") or props.get("method")
                verb = (_string_value(verb_node) or "GET").upper() if verb_node is not None else "GET"
                data = props.get("data")
                msg_root = a[0]
            elif callee in AJAX_POS and a:
                url, verb = a[0], AJAX_POS[callee]
                data = a[1] if len(a) > 1 and verb != "GET" else None
                msg_root = args
            else:
                continue
            used = [url] + ([data] if data is not None else [])
            for ctx in self.contexts(call, used):
                yield self._record(call, url, verb, data, msg_root, ctx)

    def _record(self, call: ts.Node, url: ts.Node, verb: str, data: ts.Node | None, msg_root: ts.Node,
                ctx: _Ctx) -> dict[str, Any]:
        inner_guards = _guards(call, _action_fn(call))
        anchor = ctx.via if ctx.via is not None else call
        func, outer = _action_name(anchor)
        fields, consts, cond, opt = self.body(data, ctx)
        # условие, под которым стоит и сам запрос, поле не отделяет: без него не уходит весь запрос
        call_guards = set(_guards(call, None))
        opt = [{"field": o["field"], "guards": g} for o in opt
               if (g := [x for x in o["guards"] if x not in call_guards])]
        msgs = []
        for n in _walk(msg_root):
            s = _string_value(n)
            if s and n != url and re.search(r"[A-Za-z]{3,}\s+[A-Za-z]", s) and "Bearer" not in s \
                    and not s.startswith("/") and "application/" not in s:
                msgs.append(_norm(s, 80))
        return {
            "line": _line(call),
            "via_line": _line(ctx.via) if ctx.via is not None else None,
            "function": func,
            "outer": outer,
            "verb": verb,
            "variants": [(_clean_url(u), list(dict.fromkeys(ctx.guards + inner_guards + g)))
                         for u, g in self.url_variants(url, ctx)],
            "body_fields": fields,
            "body_consts": consts,
            "body_cond": cond,
            "body_opt": opt,
            "body_src": self.body_sources(data, ctx),
            "messages": list(dict.fromkeys(msgs)),
        }

    def event_bindings(self) -> dict[str, list[str]]:
        """`$("#id").click(function(){ f(); })` → {f: ["#id"]}, {"click:#id": ["#id"]}."""
        out: dict[str, list[str]] = collections.defaultdict(list)
        for fn in _walk(self.root):
            if fn.type not in FUNC_TYPES:
                continue
            nm = _func_name(fn)
            if not nm or ":" not in nm:
                continue
            sel = nm.split(":", 1)[1]
            out[nm].append(sel)
            for n in _walk(fn):
                if n.type == "call_expression":
                    f = n.child_by_field_name("function")
                    if f is not None and f.type == "identifier":
                        out[_text(f)].append(sel)
        return out


def _is_stringy(v: ts.Node) -> bool:
    if v.type in ("string", "template_string"):
        return True
    if v.type == "binary_expression":
        return any(_is_stringy(c) for c in (v.child_by_field_name("left"), v.child_by_field_name("right")) if c)
    if v.type == "ternary_expression":
        return any(_is_stringy(c) for c in (v.child_by_field_name("consequence"), v.child_by_field_name("alternative"))
                   if c)
    if v.type == "parenthesized_expression" and v.named_children:
        return _is_stringy(v.named_children[0])
    return False


def _clean_url(u: str) -> str:
    u = u.strip()
    u = re.sub(r"^https?://[^/]+", "", u)
    return u


# ---------------------------------------------------------------- HTML


class _HtmlScan(html.parser.HTMLParser):
    """Надписи элементов: по id и по вызываемой функции (onclick / ng-click / v-on:click / @click); подключённые скрипты."""

    VOID = {"input", "br", "img", "hr", "meta", "link", "area", "base", "col", "embed", "source", "wbr"}
    CLICK = ("onclick", "ng-click", "v-on:click", "@click", "(click)")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict[str, str], list[str]]] = []
        self.by_id: dict[str, str] = {}
        self.by_func: dict[str, list[str]] = collections.defaultdict(list)
        self.call_args: dict[str, list[list[str]]] = collections.defaultdict(list)
        self.scripts: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        self._args(a)
        if tag == "script" and a.get("src"):
            self.scripts.append(a["src"])
        if tag == "title":
            self._in_title = True
        if tag in self.VOID:
            self._close(tag, a, [a.get("value", ""), a.get("placeholder", ""), a.get("title", "")])
            return
        self.stack.append((tag, a, []))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                while len(self.stack) > i:
                    t, a, buf = self.stack.pop()
                    self._close(t, a, buf)
                return

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self.stack:
            self.stack[-1][2].append(data)

    def _args(self, a: dict[str, str]) -> None:
        """Аргументы вызовов в обработчиках клика: `payMyOrder(index, item.id)` -> call_args["payMyOrder"]."""
        for k in self.CLICK:
            for m in re.finditer(r"([A-Za-z_$][\w$]*)\s*\(([^()]*)\)", a.get(k) or ""):
                self.call_args[m.group(1)].append([x.strip() for x in m.group(2).split(",")] if m.group(2).strip() else [])

    def _close(self, tag: str, a: dict[str, str], buf: list[str]) -> None:
        txt = _norm(re.sub(r"\{\{.*?\}\}", " ", " ".join(buf)), 80)
        if self.stack:
            self.stack[-1][2].append(txt)
        if not txt:
            return
        if a.get("id"):
            self.by_id.setdefault("#" + a["id"], txt)
        for k in self.CLICK:
            if a.get(k):
                for m in re.finditer(r"([A-Za-z_$][\w$]*)\s*\(", a[k]):
                    self.by_func[m.group(1)].append(txt)


# ---------------------------------------------------------------- сопоставление с обработчиками


def match_handlers(verb: str, url: str, handlers: list[tuple[str, str | None, list[str]]]) -> list[str]:
    """Шаблон URL из UI против шаблонов @RequestMapping. `{x}` в UI совпадает с переменной обработчика,
    литерал обработчика берётся, только если точнее ничего нет."""
    segs = path_segs(url.split("?")[0])
    if not segs:
        return []

    def score(tpl: list[str], fold: bool) -> int | None:
        if len(tpl) != len(segs) and not (tpl and tpl[-1] == "**" and len(segs) >= len(tpl) - 1):
            return None
        sc = 0
        for s, t in zip(segs, tpl):
            if t == "**":
                return sc
            ui_var, h_var = s.startswith("{"), t.startswith("{") or t == "*"
            if h_var:
                sc += 0 if ui_var else 1
            elif ui_var:
                sc -= 1
            elif (s.lower() == t.lower()) if fold else (s == t):
                sc += 2
            else:
                return None
        return sc

    for fold in (False, True):
        best, out = None, []
        for nid, hv, tpl in handlers:
            if hv is not None and hv != verb:
                continue
            sc = score(tpl, fold)
            if sc is None:
                continue
            if best is None or sc > best:
                best, out = sc, [nid]
            elif sc == best and nid not in out:
                out.append(nid)
        if out:
            return sorted(out)
    return []


# ---------------------------------------------------------------- каталог


def ui_files(ui_root: Path) -> Iterator[Path]:
    for dp, dns, fns in os.walk(ui_root):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIR and not d.startswith("."))
        for f in sorted(fns):
            if f.endswith((".js", ".html", ".htm")) and not VENDOR.search(f):
                p = Path(dp) / f
                if p.stat().st_size < 400_000:
                    yield p


@dataclass
class UICatalog:
    requests: list[UIRequest]
    unresolved: list[dict[str, Any]]
    pages_title: dict[str, str]

    def by_handler(self) -> dict[str, list[UIRequest]]:
        out: dict[str, list[UIRequest]] = collections.defaultdict(list)
        for r in self.requests:
            for h in r.handlers:
                out[h].append(r)
        return out

    def siblings(self, r: UIRequest) -> list[UIRequest]:
        """Другие запросы той же UI-функции (варианты по условию и функции, шлющие несколько запросов)."""
        return [x for x in self.requests if x.file == r.file and x.function == r.function and x.id != r.id]

    def to_dict(self) -> dict[str, Any]:
        return {"requests": [r.to_dict() for r in self.requests], "unresolved": self.unresolved,
                "pages_title": self.pages_title}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UICatalog:
        reqs = [UIRequest(**r) for r in d.get("requests", [])]
        return cls(requests=reqs, unresolved=d.get("unresolved", []), pages_title=d.get("pages_title", {}))

def find_ui_dir(targets_root: str | Path, ix: SkeletonIndex) -> str | None:
    """Модуль веб-интерфейса: каталог верхнего уровня, который не модуль Java скелета, с наибольшим числом
    HTML-страниц (в Train Ticket — `ts-ui-dashboard`). None — страниц нет."""
    root = Path(targets_root)
    java = {n.get("module") for n in ix.N.values() if n.get("module")}
    best: tuple[int, str] | None = None
    for d in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in java and not p.name.startswith(".")):
        pages = sum(1 for f in ui_files(d) if f.suffix in (".html", ".htm"))
        if pages and (best is None or pages > best[0]):
            best = (pages, d.name)
    return best[1] if best else None


def _template_sources(raw: dict[str, list[Any]], call_args: dict[str, list[list[str]]]) -> dict[str, str]:
    """{поле: [метод, индекс]} -> {поле: F}, если на всех местах вызова метода в шаблонах аргумент — `x.F` элемента
    списка (`v-for="item in myOrders"`) и F не совпадает с именем поля."""
    out: dict[str, str] = {}
    for k, (method, i) in raw.items():
        found = set()
        for args in call_args.get(method, ()):
            m = re.fullmatch(r"[A-Za-z_$][\w$]*\.([A-Za-z_$][\w$]*)", args[i]) if i < len(args) else None
            found.add(m.group(1) if m else None)
        if len(found) == 1 and None not in found and (f := next(iter(found))) != k:
            out[k] = f
    return out


def build_catalog(
    targets_root: str | Path,
    ix: SkeletonIndex,
    ui_dir: str | None = None,
    cache_path: str | Path | None = None,
    force_rebuild: bool = False,
) -> UICatalog:
    """Каталог всех UI-запросов проекта, сопоставленных с обработчиками скелета; `ui_dir` — по `find_ui_dir`."""
    resolved_cache = (
        Path(cache_path)
        if cache_path
        else Path(__file__).resolve().parent.parent.parent / "data" / "ui_catalog.json"
    )
    if not force_rebuild and resolved_cache.is_file():
        try:
            with open(resolved_cache, "r", encoding="utf-8") as f:
                d = json.load(f)
            return UICatalog.from_dict(d)
        except Exception as e:
            logger.debug("Не удалось загрузить кэш UI-каталога из %s: %s", resolved_cache, e)

    root = Path(targets_root)
    ui_dir = ui_dir or find_ui_dir(root, ix)
    if ui_dir is None:
        return UICatalog([], [], {})
    ui_root = root / ui_dir
    script_pages: dict[str, list[str]] = collections.defaultdict(list)
    by_id: dict[str, str] = {}
    by_func: dict[str, list[str]] = collections.defaultdict(list)
    call_args: dict[str, list[list[str]]] = collections.defaultdict(list)
    titles: dict[str, str] = {}
    js: list[Path] = []
    for p in ui_files(ui_root):
        rel = p.relative_to(root).as_posix()
        if p.suffix == ".js":
            js.append(p)
            continue
        sc = _HtmlScan()
        try:
            sc.feed(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001 — битый HTML не должен ронять каталог
            pass
        titles[rel] = _norm(sc.title, 80)
        for k, v in sc.by_id.items():
            by_id.setdefault(k, v)
        for k, v in sc.by_func.items():
            by_func[k] += v
        for k, v in sc.call_args.items():
            call_args[k] += v
        for s in sc.scripts:
            if re.match(r"^(https?:)?//", s):
                continue
            sp = (p.parent / s.split("?")[0]).resolve()
            try:
                script_pages[sp.relative_to(root.resolve()).as_posix()].append(rel)
            except ValueError:
                pass

    requests: list[UIRequest] = []
    unresolved: list[dict[str, Any]] = []
    for p in js:
        rel = p.relative_to(root).as_posix()
        fp = _FileParser(rel, p.read_bytes())
        bindings = fp.event_bindings()
        for rec in fp.requests():
            base = f"{rel}:{rec['line']}" + (f"<{rec['via_line']}" if rec["via_line"] else "")
            labels = list(dict.fromkeys(
                by_func.get(rec["function"], [])
                + [by_id[s] for nm in [rec["function"]] + rec["outer"] for s in bindings.get(nm, []) if s in by_id]
            ))
            for k, (url, guards) in enumerate(rec["variants"]):
                hs = match_handlers(rec["verb"], url, ix.handlers)
                r = UIRequest(
                    id=base + (f"#{k}" if len(rec["variants"]) > 1 else ""),
                    file=rel, line=rec["line"], via_line=rec["via_line"], function=rec["function"],
                    outer=rec["outer"], pages=sorted(set(script_pages.get(rel, []))), labels=labels,
                    verb=rec["verb"], url=url, guards=guards, body_fields=rec["body_fields"],
                    body_consts=rec["body_consts"], body_cond=rec["body_cond"], body_opt=rec["body_opt"],
                    body_src=_template_sources(rec["body_src"], call_args), messages=rec["messages"],
                    handlers=hs, group=base,
                )
                if hs:
                    requests.append(r)
                else:
                    unresolved.append({"id": r.id, "verb": r.verb, "url": url, "function": r.function})
    catalog = UICatalog(requests, unresolved, titles)
    try:
        resolved_cache.parent.mkdir(parents=True, exist_ok=True)
        with open(resolved_cache, "w", encoding="utf-8") as f:
            json.dump(catalog.to_dict(), f, ensure_ascii=False, indent=1)
    except Exception as e:
        logger.debug("Не удалось сохранить кэш UI-каталога в %s: %s", resolved_cache, e)
    return catalog


def main() -> None:
    import argparse

    from engine.adapters.skeleton import load_json

    ap = argparse.ArgumentParser(description="Каталог UI-запросов модуля веб-интерфейса")
    ap.add_argument("--skeleton", default="hackaton/tt-challenge/skeleton/trainticket.json.gz")
    ap.add_argument("--targets", default="hackaton/tt-challenge/targets/trainticket")
    ap.add_argument("-o", "--out", default="output/ui_catalog.json")
    a = ap.parse_args()
    ix = SkeletonIndex(load_json(a.skeleton))
    cat = build_catalog(a.targets, ix)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(cat.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    covered = {h for r in cat.requests for h in r.handlers}
    all_h = {nid for nid, _, _ in ix.handlers}
    print(f"запросов UI {len(cat.requests)}, не сопоставлено {len(cat.unresolved)}, "
          f"обработчиков с UI {len(covered)} из {len(all_h)} -> {a.out}")
    for u in cat.unresolved:
        print(f"  ? {u['verb']:6} {u['url']:70} {u['id']} ({u['function']})")


if __name__ == "__main__":
    main()
