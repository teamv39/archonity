"""Кандидаты обработчиков для шага: BM25 + плотные эмбеддинги → RRF, плюс близнецы (ADR-005, M1, п. 2)."""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from engine.grounding.docs import HandlerCatalog
from engine.grounding.text import BM25, expand_query, query_toks

RRF_K = 60


class Embedder(Protocol):
    name: str

    def embed_docs(self, docs: list[tuple[str, str]]) -> np.ndarray | None: ...

    def embed_queries(self, texts: list[str]) -> np.ndarray | None: ...


def _norm_seg(s: str) -> str:
    return re.sub(r"other|\d+", "", s.lower())


def twin_groups(cat: HandlerCatalog) -> dict[str, list[str]]:
    """Близнецы: обработчики разных модулей с одинаковым путём после снятия `other` и цифр в сегментах
    (`travelservice` / `travel2service`, `order/refresh` / `orderOther/refresh`, `preserve` / `preserveOther`)."""
    groups: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    for nid, h in cat.handlers.items():
        for verb, path in h.routes:
            key = (verb, "/".join(_norm_seg(s) for s in path.split("/")))
            groups[key].add(nid)
    out: dict[str, set[str]] = collections.defaultdict(set)
    for members in groups.values():
        mods = {cat.handlers[m].module for m in members}
        if len(members) < 2 or len(mods) < 2:
            continue
        for m in members:
            out[m] |= {x for x in members if cat.handlers[x].module != cat.handlers[m].module}
    return {k: sorted(v) for k, v in out.items()}


def rrf(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[float, str]]:
    sc: dict[str, float] = collections.defaultdict(float)
    for r in rankings:
        for i, h in enumerate(r):
            sc[h] += 1.0 / (k + i + 1)
    return sorted(((v, h) for h, v in sc.items()), key=lambda x: (-x[0], x[1]))


@dataclass
class Ranked:
    """Результат поиска для одного запроса: списки по ретриверам и итог."""

    bm25: list[str]
    dense: list[str]
    fused: list[str]

    def candidates(self, k: int, twins: dict[str, list[str]]) -> list[str]:
        """top-k итога, близнец ставится сразу за своим обработчиком."""
        out: list[str] = []
        for h in self.fused[:k]:
            for x in [h] + twins.get(h, []):
                if x not in out:
                    out.append(x)
        return out


class Retriever:
    def __init__(self, cat: HandlerCatalog, mode: str = "code_ui", embedder: Embedder | None = None) -> None:
        self.cat = cat
        self.mode = mode
        self.ids = sorted(cat.handlers)
        self.bm25 = BM25({nid: cat.bm25_tokens(nid, mode) for nid in self.ids})
        self.twins = twin_groups(cat)
        self.embedder = embedder
        self.doc_vecs: np.ndarray | None = None
        if embedder is not None:
            self.doc_vecs = embedder.embed_docs([(cat.handlers[nid].signature, cat.render(nid, mode)) for nid in self.ids])

    def rank_bm25(self, query: str) -> list[str]:
        ranked = [h for _, h in self.bm25.rank(expand_query(query_toks(query)))]
        return ranked + [h for h in self.ids if h not in set(ranked)]

    def rank_dense(self, queries: list[str]) -> list[list[str]]:
        if self.embedder is None or self.doc_vecs is None:
            return [[] for _ in queries]
        q = self.embedder.embed_queries(queries)
        if q is None:
            return [[] for _ in queries]
        sims = q @ self.doc_vecs.T
        return [[self.ids[i] for i in np.argsort(-row, kind="stable")] for row in sims]

    def search(self, queries: list[str]) -> list[Ranked]:
        dense = self.rank_dense(queries)
        out = []
        for q, d in zip(queries, dense):
            b = self.rank_bm25(q)
            fused = [h for _, h in rrf([b, d])] if d else b
            out.append(Ranked(b, d, fused))
        return out
