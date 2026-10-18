"""Сведения о проекте для исполнителя M4: IR тел методов (M2) и скелет (M0).

IR — `data/ir/<module>.json` (README archparse, раздел 3.6). Цели вызовов IR не повторяет: они берутся из рёбер
скелета по ID call_site (`calls`, `runtime_dispatch`, `remote_call`, `message_delivery`, `data_access`).
"""
from __future__ import annotations

import collections
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.adapters.skeleton import SkeletonIndex, ann_paths, path_segs
from engine.executor.values import simple_name

BEAN_ANNOTATIONS = frozenset({"Service", "Component", "RestController", "Controller", "Repository", "Configuration",
                              "ControllerAdvice"})
PRIMITIVE_DEFAULTS: dict[str, Any] = {"int": 0, "long": 0, "short": 0, "byte": 0, "char": "\x00", "double": 0.0,
                                      "float": 0.0, "boolean": False}


def expr_kind(node: Any) -> str:
    """Вид выражения IR по ключу (README archparse, раздел 3.6)."""
    if not isinstance(node, dict):
        return "raw"
    for k in ("lambda", "method_ref", "new_array", "new", "call", "bin", "un", "assign", "tern", "cast", "instanceof",
              "index", "field", "enum", "const", "lit", "name", "this", "super", "class", "text"):
        if k in node:
            return k
    return "text"


@dataclass(frozen=True)
class FieldInfo:
    name: str
    type: str
    static: bool
    annotations: tuple[str, ...]
    column: str | None  # @Column(name = ...)
    init_literal: Any


@dataclass(frozen=True)
class ParamInfo:
    name: str
    type: str
    annotations: dict[str, str]  # имя аннотации -> аргументы


class Program:
    """IR и индексы скелета, нужные интерпретатору."""

    def __init__(self, index: SkeletonIndex, ir_dir: str | Path) -> None:
        self.index = index
        self.N = index.N
        self.methods: dict[str, dict[str, Any]] = {}
        self.modules_loaded: list[str] = []
        for f in sorted(Path(ir_dir).glob("*.json")):
            doc = json.loads(f.read_text(encoding="utf-8"))
            self.methods.update(doc.get("methods") or {})
            self.modules_loaded.append(doc.get("module", f.stem))

        # Рёбра скелета по call_site
        self.cs_edges: dict[str, dict[str, list[str]]] = collections.defaultdict(lambda: collections.defaultdict(list))
        for e in index.sk.get("edges", []):
            if e["type"] in ("calls", "runtime_dispatch", "remote_call", "message_delivery", "data_access", "creates"):
                src = e["source"]
                if src.startswith("call:"):
                    self.cs_edges[src][e["type"]].append(e["target"])

        # Типы, поля, методы по владельцу
        self.types_by_fqn: dict[str, list[str]] = collections.defaultdict(list)
        self.fields_by_type: dict[str, list[FieldInfo]] = collections.defaultdict(list)
        self.methods_by_owner: dict[str, list[str]] = collections.defaultdict(list)
        self.params_by_method: dict[str, list[ParamInfo]] = collections.defaultdict(list)
        field_rows: list[tuple[str, int, FieldInfo]] = []
        param_rows: list[tuple[str, int, ParamInfo]] = []
        for nid, n in self.N.items():
            kind = n.get("kind")
            if kind == "type":
                self.types_by_fqn[n.get("fqn", "")].append(nid)
            elif kind == "field":
                anns = n.get("annotations") or []
                col = next((_ann_name_arg(a.get("args") or "") for a in anns if a.get("name") == "Column"), None)
                fi = FieldInfo(
                    name=n.get("name", ""),
                    type=n.get("type") or n.get("type_raw") or "",
                    static="static" in (n.get("modifiers") or []),
                    annotations=tuple(a.get("name", "") for a in anns),
                    column=col,
                    init_literal=n.get("init_literal"),
                )
                field_rows.append((n.get("owner", ""), int(n.get("line") or 0), fi))
            elif kind == "method":
                self.methods_by_owner[n.get("owner", "")].append(nid)
            elif kind == "parameter":
                anns = {a.get("name", ""): a.get("args") or "" for a in n.get("annotations") or []}
                pi = ParamInfo(name=n.get("name", ""), type=n.get("type") or "", annotations=anns)
                param_rows.append((n.get("method", ""), int(n.get("index") or 0), pi))
        for owner, _, fi in sorted(field_rows, key=lambda r: (r[0], r[1])):
            self.fields_by_type[owner].append(fi)
        for mid, _, pi in sorted(param_rows, key=lambda r: (r[0], r[1])):
            self.params_by_method[mid].append(pi)

        # Суперклассы проекта: тип -> [тип] (рёбра extends между узлами типов)
        self.supertypes: dict[str, list[str]] = collections.defaultdict(list)
        for e in index.sk.get("edges", []):
            if e["type"] == "extends" and self.N.get(e["source"], {}).get("kind") == "type" \
                    and self.N.get(e["target"], {}).get("kind") == "type":
                self.supertypes[e["source"]].append(e["target"])

        # Обработчики: метод -> [(глагол, сегменты шаблона пути)]
        self.handler_templates: dict[str, list[tuple[str | None, list[str]]]] = collections.defaultdict(list)
        for nid, verb, segs in index.handlers:
            self.handler_templates[nid].append((verb, segs))

        # Аргументы констант enum: по всем ссылкам в IR (README 3.6: литералы аргументов в объявлении enum)
        self.enum_args: dict[str, dict[str, list[Any]]] = collections.defaultdict(dict)
        for m in self.methods.values():
            for node in _walk(m.get("body")):
                if "enum" in node and "constant" in node:
                    known = self.enum_args[node["enum"]].get(node["constant"])
                    if not known:  # ссылка без аргументов не затирает аргументы, найденные в другом месте
                        self.enum_args[node["enum"]][node["constant"]] = node.get("args") or []

    # --- методы и типы --------------------------------------------------------------------------------------------

    def ir(self, method_id: str) -> dict[str, Any] | None:
        return self.methods.get(method_id)

    def owner_of(self, method_id: str) -> str:
        return self.N.get(method_id, {}).get("owner", "")

    def owner_fqn(self, method_id: str) -> str:
        return self.N.get(self.owner_of(method_id), {}).get("fqn", "")

    def module_of(self, node_id: str) -> str:
        return self.N.get(node_id, {}).get("module", "")

    def is_abstract(self, method_id: str) -> bool:
        return bool(self.N.get(method_id, {}).get("abstract"))

    def is_static(self, method_id: str) -> bool:
        return "static" in (self.N.get(method_id, {}).get("modifiers") or [])

    def type_node(self, fqn: str, module: str | None = None) -> str | None:
        """Узел типа по FQN: сначала в модуле вызова, потом ts-common, потом любой."""
        nodes = self.types_by_fqn.get(fqn) or []
        if not nodes:
            return None
        for pref in (module, "ts-common"):
            for t in nodes:
                if pref and self.N[t].get("module") == pref:
                    return t
        return nodes[0]

    def resolve_simple(self, name: str, module: str) -> str:
        """FQN типа проекта по простому имени (импорт со звёздочкой): сначала модуль, потом ts-common."""
        if "." in name:
            return name
        if not hasattr(self, "_by_simple"):
            self._by_simple: dict[str, list[str]] = collections.defaultdict(list)
            for fqn in self.types_by_fqn:
                self._by_simple[simple_name(fqn)].append(fqn)
        for fqn in self._by_simple.get(name, []):
            if any(self.N[t].get("module") == module for t in self.types_by_fqn[fqn]):
                return fqn
        for fqn in self._by_simple.get(name, []):
            if any(self.N[t].get("module") == "ts-common" for t in self.types_by_fqn[fqn]):
                return fqn
        return name

    def is_project_type(self, fqn: str) -> bool:
        return fqn in self.types_by_fqn

    def type_annotations(self, type_node: str | None) -> set[str]:
        if not type_node:
            return set()
        return {a.get("name", "") for a in self.N.get(type_node, {}).get("annotations") or []}

    def is_bean_type(self, type_node: str | None) -> bool:
        return bool(self.type_annotations(type_node) & BEAN_ANNOTATIONS)

    def instance_fields(self, type_node: str | None) -> list[FieldInfo]:
        return [f for f in self.fields_by_type.get(type_node or "", []) if not f.static]

    def field_info(self, type_node: str | None, name: str) -> FieldInfo | None:
        return next((f for f in self.fields_by_type.get(type_node or "", []) if f.name == name), None)

    def enum_constants(self, type_node: str | None) -> list[str]:
        """Константы enum в порядке объявления: статические поля самого типа enum."""
        if not type_node:
            return []
        fqn = self.N.get(type_node, {}).get("fqn", "")
        return [f.name for f in self.fields_by_type.get(type_node, []) if f.static and f.type == fqn]

    def enum_source_args(self, type_node: str | None, root: Path) -> dict[str, list[dict[str, Any]]]:
        """Литералы аргументов констант из объявления enum в исходнике: `TRAFFIC_ACCIDENT(1, "...", 3.0)`.

        Нужны для констант, на которые в телах методов нет прямой ссылки (берутся через `values()`), — в IR их
        аргументов нет. Аргумент не литерал — константы в ответе нет.
        """
        if not hasattr(self, "_enum_src"):
            self._enum_src: dict[str, dict[str, list[dict[str, Any]]]] = {}
        if not type_node:
            return {}
        if type_node not in self._enum_src:
            n = self.N.get(type_node, {})
            out: dict[str, list[dict[str, Any]]] = {}
            try:
                text = (root / n.get("file", "")).read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            m = re.search(r"\benum\s+" + re.escape(n.get("fqn", "").rsplit(".", 1)[-1].rsplit("$", 1)[-1]) + r"\b[^{]*\{",
                          text)
            body = _strip_comments(text[m.end():]) if m else ""
            for name, raw in _enum_constants(body):
                args = [_java_literal(a) for a in _split_args(raw)] if raw is not None else []
                if all(a is not None for a in args):
                    out[name] = args
            self._enum_src[type_node] = out
        return self._enum_src[type_node]

    def find_methods(self, type_node: str | None, name: str, argc: int | None = None) -> list[str]:
        out = []
        for mid in self.methods_by_owner.get(type_node or "", []):
            n = self.N[mid]
            if n.get("name") != name:
                continue
            if argc is not None and len(self.params_by_method.get(mid, [])) != argc:
                continue
            out.append(mid)
        return out

    def lookup_method(self, type_node: str | None, name: str, argc: int) -> str | None:
        """Явный (не Lombok) неабстрактный метод типа или его суперкласса: цель вызова по фактическому типу."""
        seen: set[str] = set()
        while type_node and type_node not in seen:
            seen.add(type_node)
            found = [m for m in self.find_methods(type_node, name, argc) if not self.is_abstract(m)]
            if len(found) == 1:
                return found[0]
            if found:
                return None  # перегрузки с тем же числом аргументов: по типам аргументов не выбираем
            supers = self.supertypes.get(type_node) or []
            type_node = supers[0] if len(supers) == 1 else None
        return None

    def implementations(self, method_id: str) -> list[str]:
        """Реализации абстрактного метода по `overrides` (CHA), без абстрактных."""
        return sorted(m for m in self.index.cha(method_id) if not self.is_abstract(m))

    # --- call_site ------------------------------------------------------------------------------------------------

    def call_site(self, cs: str | None) -> dict[str, Any]:
        return self.N.get(cs or "", {}) if cs and cs.startswith("call:") else {}

    def edges(self, cs: str | None, etype: str) -> list[str]:
        if not cs or not cs.startswith("call:"):
            return []
        return list(self.cs_edges.get(cs, {}).get(etype, ()))

    def is_handler(self, method_id: str) -> bool:
        return method_id in self.handler_templates


def _walk(x: Any):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)


def walk(x: Any):
    """Все узлы-словари поддерева IR."""
    return _walk(x)


def _strip_comments(text: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", " ", text, flags=re.S)


def _enum_constants(body: str) -> list[tuple[str, str | None]]:
    """Константы enum до первой `;` верхнего уровня: [(имя, текст аргументов или None)]."""
    out: list[tuple[str, str | None]] = []
    i, depth, n = 0, 0, len(body)
    while i < n:
        m = re.match(r"\s*(?:@\w+(?:\([^)]*\))?\s*)*([A-Z_][A-Z0-9_]*)\s*", body[i:])
        if not m:
            break
        name, i = m.group(1), i + m.end()
        raw = None
        if i < n and body[i] == "(":
            start, depth = i + 1, 1
            i += 1
            in_str = None
            while i < n and depth:
                ch = body[i]
                if in_str:
                    if ch == "\\":
                        i += 1
                    elif ch == in_str:
                        in_str = None
                elif ch in "\"'":
                    in_str = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                i += 1
            raw = body[start:i - 1]
        out.append((name, raw))
        rest = body[i:].lstrip()
        if rest.startswith("{"):  # тело константы: в Train Ticket не встречается
            break
        if rest.startswith(","):
            i = n - len(rest) + 1
            continue
        break
    return out


def _split_args(raw: str) -> list[str]:
    parts, cur, in_str, depth = [], "", None, 0
    for i, ch in enumerate(raw):
        if in_str:
            cur += ch
            if ch == in_str and raw[i - 1] != "\\":
                in_str = None
            continue
        if ch in "\"'":
            in_str = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _java_literal(s: str) -> dict[str, Any] | None:
    """Литерал Java как узел IR `lit` (README archparse 3.6); не литерал — None."""
    if re.fullmatch(r'"(?:[^"\\]|\\.)*"', s):
        return {"lit": re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s[1:-1]),
                "type": "String"}
    if re.fullmatch(r"'(?:[^'\\]|\\.)'", s):
        return {"lit": s[1:-1], "type": "char"}
    if s in ("true", "false"):
        return {"lit": s == "true", "type": "boolean"}
    if s == "null":
        return {"lit": None, "type": "null"}
    if re.fullmatch(r"-?\d+[lL]?", s):
        return {"lit": int(s.rstrip("lL")), "type": "int"}
    if re.fullmatch(r"-?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?[dDfF]?", s):
        return {"lit": float(s.rstrip("dDfF")), "type": "double"}
    return None


def _ann_name_arg(args: str) -> str | None:
    m = re.search(r'name\s*=\s*"([^"]*)"', args) or re.search(r'^\(\s*"([^"]*)"', args.strip())
    return m.group(1) if m else None


def ann_value(args: str) -> str | None:
    """Значение аннотации: `("orderId")`, `(value = "x")`, `(name = "x")`; пусто — None."""
    m = re.search(r'(?:value|name)\s*=\s*"([^"]*)"', args) or re.search(r'^\(\s*"([^"]*)"', args.strip())
    return m.group(1) if m else None


def match_template(req: list[Any], tpl: list[str], lenient: bool = False) -> dict[str, Any] | None:
    """Сопоставление сегментов URL с шаблоном Spring. Сегмент не-строка — неизвестное значение.

    Неизвестный сегмент совпадает с переменной и `*`, а при `lenient` — и с литералом шаблона.
    Возвращает значения переменных шаблона (строка или неизвестное значение) или None, если не совпало.
    """
    out: dict[str, Any] = {}
    i = 0
    for t in tpl:
        if t == "**":
            return out
        if i >= len(req):
            return None
        r = req[i]
        if t.startswith("{") and t.endswith("}"):
            out[t[1:-1].split(":", 1)[0]] = r
        elif t == "*":
            pass
        elif not isinstance(r, str):
            if not lenient:
                return None
        elif r != t:
            return None
        i += 1
    return out if i == len(req) else None


__all__ = ["Program", "FieldInfo", "ParamInfo", "expr_kind", "walk", "ann_value", "match_template", "ann_paths",
           "path_segs", "simple_name", "PRIMITIVE_DEFAULTS"]
