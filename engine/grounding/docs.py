"""Документы обработчиков для поиска кандидатов (ADR-005, M1, п. 2).

Документ обработчика — короткий текст из скелета, исходника и каталога UI:
- вариант `code`: глагол и путь, `Класс#метод(параметры)`, поля DTO тела, исходник метода с комментарием над ним;
- вариант `code_ui`: то же плюс UI — функция действия, надписи кнопок, страница, сообщения.

Один и тот же текст идёт и в BM25 (токенами), и в эмбеддер.
"""
from __future__ import annotations

import collections
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.adapters.skeleton import SkeletonIndex
from engine.grounding.text import ntoks
from engine.grounding.ui_catalog import UICatalog

RENDERS = ("code", "code_ui")
SRC_LINES = 30
SKIP_PARAM_TYPES = {"HttpHeaders", "HttpServletRequest", "HttpServletResponse"}
# Ответ с кодом статуса в исходнике: `new Response<>(2, "Please pay the different money!", data)`
STATUS_ANSWER = re.compile(r'new\s+[A-Z]\w*(?:<[^>]*>)?\s*\(\s*(-?\d+)\s*,\s*"((?:[^"\\]|\\.)*)"')
REACH_DEPTH = 4
SERVICE_CALLS, CALLS_DEPTH = 12, 3


@dataclass
class HandlerInfo:
    """Что известно об обработчике без LLM: пути, параметры, DTO тела, исходник."""

    id: str
    module: str
    cls: str
    name: str
    routes: list[tuple[str, str]]  # (глагол, путь)
    params: list[dict[str, Any]]  # name, type, source: body|path|query|header|other
    body_type: str | None
    body_fields: list[dict[str, str]]  # name, type
    source: str
    ui: list[Any] = field(default_factory=list)

    @property
    def signature(self) -> str:
        args = ", ".join(f"{p['type_raw']} {p['name']}" for p in self.params if p["type_raw"] not in SKIP_PARAM_TYPES)
        return f"{self.cls}#{self.name}({args})"


def _param_source(anns: list[dict[str, Any]]) -> str:
    names = {a["name"] for a in anns or []}
    if "RequestBody" in names:
        return "body"
    if "PathVariable" in names:
        return "path"
    if "RequestParam" in names:
        return "query"
    if "RequestHeader" in names:
        return "header"
    return "other"


def ir_text(e: Any) -> str:
    """Выражение IR (M2) как текст Java: `priceOld.compareTo(priceNew) > 0`."""
    if not isinstance(e, dict):
        return "?"
    if "bin" in e:
        return f"{ir_text(e.get('l'))} {e['bin']} {ir_text(e.get('r'))}"
    if "un" in e:
        inner = e.get("e")
        t = ir_text(inner)
        return f"{e['un']}({t})" if isinstance(inner, dict) and "bin" in inner else f"{e['un']}{t}"
    if "callee" in e:
        args = ", ".join(ir_text(a) for a in e.get("args") or [])
        recv = e.get("recv")
        return f"{ir_text(recv)}.{e['callee']}({args})" if recv else f"{e['callee']}({args})"
    if "lit" in e:
        v = e["lit"]
        return "null" if v is None else (f'"{v}"' if isinstance(v, str) else str(v).lower() if isinstance(v, bool)
                                         else str(v))
    if "constant" in e:
        return f"{str(e.get('enum') or '').rsplit('.', 1)[-1]}.{e['constant']}"
    if "field" in e:
        return f"{ir_text(e.get('of'))}.{e['field']}" if e.get("of") else e["field"]
    if "name" in e:
        return e["name"]
    if "this" in e:
        return "this"
    if "new" in e:
        return f"new {e['new']}(...)"
    return "?"


def _status_returns(stmts: list[dict[str, Any]], guard: tuple[str, ...]):
    """(код, условия) для `return new X(<int>, "<str>", ...)` в теле IR; условия — стек `if` сверху вниз."""
    for s in stmts:
        if not isinstance(s, dict):
            continue
        if s.get("op") == "return":
            args = (s.get("expr") or {}).get("args") or []
            if (s.get("expr") or {}).get("new") and len(args) >= 2 and isinstance(args[0].get("lit"), int) \
                    and not isinstance(args[0].get("lit"), bool) and isinstance(args[1].get("lit"), str):
                yield args[0]["lit"], guard
            continue
        if s.get("op") == "if":
            cond = ir_text(s.get("cond"))
            yield from _status_returns(s.get("then") or [], guard + (cond,))
            yield from _status_returns(s.get("else") or [], guard + (f"!({cond})",))
            continue
        for v in s.values():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "op" in v[0]:
                yield from _status_returns(v, guard)


class HandlerCatalog:
    """Все обработчики скелета с их описанием и UI-запросами."""

    def __init__(self, ix: SkeletonIndex, targets_root: str | Path, ui: UICatalog,
                 ir_dir: str | Path | None = None) -> None:
        """`ir_dir` — IR тел методов (`data/ir`, выход M2): по нему `answer_guards` видит условия возвратов."""
        self.ix = ix
        self.root = Path(targets_root)
        self.ir_dir = Path(ir_dir) if ir_dir else None
        self._ir: dict[str, dict[str, Any]] = {}
        self._lines: dict[str, list[str]] = {}
        self._answers: dict[str, dict[int, list[str]]] = {}
        N = ix.N
        params: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        fields: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
        types_by_fqn: dict[str, str] = {}
        for nid, n in N.items():
            k = n.get("kind")
            if k == "parameter":
                params[n["method"]].append(n)
            elif k == "field" and "static" not in (n.get("modifiers") or []):
                fields[n["owner"]].append({"name": n["name"], "type": n.get("type_raw") or n.get("type") or ""})
            elif k == "type":
                types_by_fqn.setdefault(n["fqn"], nid)
        routes: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
        for nid, verb, tpl in ix.handlers:
            r = (verb or "ANY", "/" + "/".join(tpl))
            if r not in routes[nid]:
                routes[nid].append(r)
        by_handler = ui.by_handler()
        self.handlers: dict[str, HandlerInfo] = {}
        for nid in sorted(routes):
            n = N[nid]
            ps = []
            for p in sorted(params.get(nid, []), key=lambda x: x["index"]):
                ps.append({"name": p["name"], "type": p.get("type", ""), "type_raw": p.get("type_raw", ""),
                           "source": _param_source(p.get("annotations"))})
            body = next((p for p in ps if p["source"] == "body"), None)
            body_type = body["type"] if body else None
            bfields = fields.get(types_by_fqn.get(body_type or "", ""), []) if body_type else []
            self.handlers[nid] = HandlerInfo(
                id=nid, module=n.get("module", ""), cls=N[n["owner"]]["fqn"].split(".")[-1], name=n["name"],
                routes=routes[nid], params=ps, body_type=body_type, body_fields=bfields,
                source=self._source(n), ui=by_handler.get(nid, []),
            )

    def _source(self, n: dict[str, Any]) -> str:
        """Исходник метода с комментарием над ним, без аннотаций маппинга и пустых строк."""
        p = self.root / n.get("file", "")
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        start, end = n.get("line", 1) - 1, min(n.get("end", n.get("line", 1)), len(lines))
        j = start - 1
        while j >= 0 and re.match(r"\s*(@|/\*|\*|//)", lines[j]):
            j -= 1
        body = [ln.strip() for ln in lines[j + 1:end] if ln.strip() and not re.match(r"\s*@", ln)]
        return "\n".join(body[:SRC_LINES])

    def _method_lines(self, n: dict[str, Any]) -> list[str]:
        f = n.get("file", "")
        if f not in self._lines:
            try:
                self._lines[f] = (self.root / f).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                self._lines[f] = []
        return self._lines[f][n.get("line", 1) - 1:n.get("end", n.get("line", 1))]

    def reach(self, nid: str, depth: int = REACH_DEPTH) -> list[str]:
        """Методы модуля обработчика, достижимые из него по вызовам скелета (с реализациями интерфейсов), в порядке
        обхода в ширину; сам обработчик первый."""
        ix = self.ix
        module = ix.N.get(nid, {}).get("module")
        seen, frontier = [nid], [nid]
        for _ in range(depth):
            nxt = []
            for m in frontier:
                for c in sorted(set(ix.calls.get(m, ())) | set(ix.over.get(m, ()))):
                    if c not in seen and ix.N.get(c, {}).get("module") == module:
                        seen.append(c)
                        nxt.append(c)
            frontier = nxt
        return seen

    def answers(self, nid: str) -> dict[int, list[str]]:
        """Ответы обработчика с кодом статуса: литералы `new X(<код>, "<сообщение>", ...)` в методах `reach`.
        По ним видно, что значит статус, который проверяет UI в обработчике ответа."""
        if nid in self._answers:
            return self._answers[nid]
        out: dict[int, list[str]] = {}
        for m in sorted(self.reach(nid)):
            for code, msg in STATUS_ANSWER.findall("\n".join(self._method_lines(self.ix.N[m]))):
                msgs = out.setdefault(int(code), [])
                if msg not in msgs:
                    msgs.append(msg)
        self._answers[nid] = out
        return out

    def answer_guards(self, nid: str) -> dict[int, list[str]]:
        """Условия, при которых обработчик возвращает ответ с кодом статуса: стек условий ветвлений IR над
        `return new X(<код>, "<сообщение>", ...)` в методах `reach`, по коду. Без IR — пусто."""
        out: dict[int, list[str]] = {}
        for m in self.reach(nid):
            body = self._ir_method(m)
            for code, guard in _status_returns(body or [], ()):
                text = " && ".join(guard) or "always"
                if text not in out.setdefault(code, []):
                    out[code].append(text)
        return out

    def _ir_method(self, nid: str) -> list[dict[str, Any]] | None:
        module = self.ix.N.get(nid, {}).get("module")
        if not module or self.ir_dir is None:
            return None
        if module not in self._ir:
            try:
                self._ir[module] = json.loads((self.ir_dir / f"{module}.json").read_text(encoding="utf-8"))["methods"]
            except (OSError, ValueError, KeyError):
                self._ir[module] = {}
        return (self._ir[module].get(nid) or {}).get("body")

    def service_calls(self, nid: str, limit: int = SERVICE_CALLS) -> list[str]:
        """Имена методов модуля, которые выполняет обработчик (`reach`), без конструкторов, абстрактных методов и
        коротких (геттеры, сеттеры): что делает обработчик внутри — `drawBackMoney`, `createConsign`."""
        N = self.ix.N
        own = N.get(nid, {}).get("name")
        out: list[str] = []
        for m in self.reach(nid, CALLS_DEPTH)[1:]:
            n = N.get(m, {})
            name = n.get("name")
            if n.get("kind") != "method" or not name or name in ("<init>", own) or n.get("abstract") \
                    or n.get("end", 0) - n.get("line", 0) < 3 or name in out:
                continue
            out.append(name)
        return out[:limit]

    def render(self, nid: str, mode: str = "code_ui") -> str:
        h = self.handlers[nid]
        out = [f"{v} {p}" for v, p in h.routes]
        out.append(f"{h.signature} in {h.module}")
        if h.body_fields:
            out.append(f"Body {h.body_type.split('.')[-1] if h.body_type else ''}: "
                       + ", ".join(f["name"] for f in h.body_fields))
        if h.source:
            out.append(h.source)
        if mode == "code_ui":
            for r in h.ui[:6]:
                page = ", ".join(Path(pg).stem for pg in r.pages) or Path(r.file).stem
                bits = [f"UI page {page}: action {r.function}"]
                if r.labels:
                    bits.append("buttons " + ", ".join(f'"{x}"' for x in r.labels[:4]))
                if r.messages:
                    bits.append("messages " + "; ".join(f'"{m}"' for m in r.messages[:3]))
                out.append(", ".join(bits))
        return "\n".join(out)

    def bm25_tokens(self, nid: str, mode: str = "code_ui") -> list[str]:
        """Токены для BM25: весь текст плюс имя метода и путь ещё раз."""
        h = self.handlers[nid]
        extra = ntoks(h.name) * 2 + ntoks(" ".join(p for _, p in h.routes))
        if mode == "code_ui":
            for r in h.ui:
                extra += ntoks(r.function) + ntoks(" ".join(r.labels))
        return ntoks(self.render(nid, mode)) + extra
