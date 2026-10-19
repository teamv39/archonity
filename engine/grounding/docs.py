"""Документы обработчиков для поиска кандидатов (ADR-005, M1, п. 2).

Документ обработчика — короткий текст из скелета, исходника и каталога UI:
- вариант `code`: глагол и путь, `Класс#метод(параметры)`, поля DTO тела, исходник метода с комментарием над ним;
- вариант `code_ui`: то же плюс UI — функция действия, надписи кнопок, страница, сообщения.

Один и тот же текст идёт и в BM25 (токенами), и в эмбеддер.
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.adapters.skeleton import SkeletonIndex
from engine.grounding.text import DOMAIN_SYN, ntoks
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


class HandlerCatalog:
    """Все обработчики скелета с их описанием и UI-запросами."""

    def __init__(self, ix: SkeletonIndex, targets_root: str | Path, ui: UICatalog) -> None:
        self.ix = ix
        self.root = Path(targets_root)
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

    def bm25_tokens(self, nid: str, mode: str = "code_ui", syn: dict[str, list[str]] | None = DOMAIN_SYN) -> list[str]:
        """Токены для BM25: весь текст плюс имя метода и путь ещё раз (как в resolver); `syn` — см. `text.stem`."""
        h = self.handlers[nid]
        extra = ntoks(h.name, syn) * 2 + ntoks(" ".join(p for _, p in h.routes), syn)
        if mode == "code_ui":
            for r in h.ui:
                extra += ntoks(r.function, syn) + ntoks(" ".join(r.labels), syn)
        return ntoks(self.render(nid, mode), syn) + extra
