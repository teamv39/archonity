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
from engine.grounding.text import ntoks
from engine.grounding.ui_catalog import UICatalog

RENDERS = ("code", "code_ui")
SRC_LINES = 30
SKIP_PARAM_TYPES = {"HttpHeaders", "HttpServletRequest", "HttpServletResponse"}


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
        """Токены для BM25: весь текст плюс имя метода и путь ещё раз (как в resolver)."""
        h = self.handlers[nid]
        extra = ntoks(h.name) * 2 + ntoks(" ".join(p for _, p in h.routes))
        if mode == "code_ui":
            for r in h.ui:
                extra += ntoks(r.function) + ntoks(" ".join(r.labels))
        return ntoks(self.render(nid, mode)) + extra
