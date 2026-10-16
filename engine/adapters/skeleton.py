"""Адаптер и индексатор скелета проекта skeleton/trainticket.json.gz."""
from __future__ import annotations

import collections
import gzip
import json
import re
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if p.suffix == ".gz":
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def path_segs(p: str) -> list[str]:
    return [s for s in re.split(r"[/]+", p.split("?")[0]) if s]


def match_path(req: list[str], tpl: list[str]) -> bool:
    """Сегменты запроса против шаблона Spring: {x} — один сегмент, ** — хвост."""
    if not tpl:
        return not req
    t = tpl[0]
    if t == "**":
        return True
    if not req:
        return False
    if t.startswith("{") or t == "*" or t == req[0]:
        return match_path(req[1:], tpl[1:])
    return False


def ann_paths(anns: list[dict[str, Any]] | None) -> list[tuple[str | None, list[str]]]:
    out: list[tuple[str | None, list[str]]] = []
    for a in anns or []:
        if a["name"].endswith("Mapping"):
            vals = re.findall(r'"([^"]*)"', a.get("args") or "")
            verb = a["name"].replace("Mapping", "").upper()
            out.append((verb if verb != "REQUEST" else None, vals or [""]))
    return out


def toks(t: str | None) -> list[str]:
    return [
        w.lower()
        for w in re.findall(
            r"[A-Za-z][a-z0-9]+|[A-Z]+(?![a-z])",
            re.sub(r"([a-z])([A-Z])", r"\1 \2", t or ""),
        )
        if len(w) > 2
    ]


class SkeletonIndex:
    """Индекс скелета графа микросервисов."""

    def __init__(self, skeleton_dict: dict[str, Any]) -> None:
        self.sk = skeleton_dict
        self.project: str = skeleton_dict.get("project", "trainticket")
        self.N: dict[str, dict[str, Any]] = skeleton_dict["nodes"]

        self.handlers: list[tuple[str, str | None, list[str]]] = []
        for nid, n in self.N.items():
            if n.get("kind") != "method":
                continue
            mp = ann_paths(n.get("annotations"))
            if not mp:
                continue
            cls_paths = [
                v
                for _, vals in ann_paths(self.N.get(n["owner"], {}).get("annotations"))
                for v in vals
            ] or [""]
            for verb, vals in mp:
                for v in vals:
                    for cp in cls_paths:
                        self.handlers.append((nid, verb, path_segs(cp + "/" + v)))

        self.cs_method = {
            nid: n["method"] for nid, n in self.N.items() if n.get("kind") == "call_site"
        }
        self.calls: dict[str, set[str]] = collections.defaultdict(set)
        self.over: dict[str, set[str]] = collections.defaultdict(set)
        self.wiring: dict[str, dict[str, set[str]]] = collections.defaultdict(
            lambda: collections.defaultdict(set)
        )

        for e in skeleton_dict.get("edges", []):
            etype = e["type"]
            src = e["source"]
            tgt = e["target"]
            if etype == "calls":
                caller = self.cs_method.get(src, src)
                self.calls[caller].add(tgt)
            elif etype == "overrides":
                self.over[tgt].add(src)
            elif etype in ("remote_call", "message_delivery", "runtime_dispatch", "data_access"):
                caller = self.cs_method.get(src, src)
                self.wiring[etype][caller].add(tgt)

        self.module = {
            nid: n.get("module") for nid, n in self.N.items() if n.get("kind") == "method"
        }
        self.units = {
            n.get("name", ""): set(n.get("deployment_units") or [n.get("name", "")])
            for n in self.N.values()
            if n.get("kind") == "module"
        }
        self.size = collections.Counter(u for us in self.units.values() for u in us)
        self.stmts: dict[str, list[str]] = collections.defaultdict(list)
        for e in skeleton_dict.get("edges", []):
            if e["type"] == "contains" and e["target"].startswith("stmt:"):
                self.stmts[e["source"]].append(e["target"])

    def unit_of(self, m: str) -> str:
        mod = self.module.get(m, "")
        units = self.units.get(mod, {mod})
        return min(units, key=lambda u: (self.size.get(u, 0), u))

    def cha(self, m: str) -> set[str]:
        out, st = set(), [m]
        while st:
            x = st.pop()
            for o in self.over.get(x, ()):
                if o not in out:
                    out.add(o)
                    st.append(o)
        return out

    def handlers_for(self, method: str | None, path: str, host: str | None = None) -> set[str]:
        segs = path_segs(path)
        out = set()
        for nid, verb, tpl in self.handlers:
            if host and host not in (self.N[nid].get("module") or ""):
                continue
            if (verb is None or method is None or verb == method) and match_path(segs, tpl):
                out.add(nid)
        return out

    def handler_docs(self) -> dict[str, list[str]]:
        docs: dict[str, list[str]] = {}
        for nid, _, tpl in self.handlers:
            docs.setdefault(nid, []).extend(
                toks(" ".join(tpl)) * 3
                + toks(self.N[nid].get("name", "")) * 2
                + toks(self.N[nid].get("module", ""))
            )
        return docs
