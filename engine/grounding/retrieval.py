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


def _module_marker(base: str, variant: str) -> str | None:
    """Токен, которым имя модуля-варианта отличается от базового: вставленный токен (`ts-order-other-service`)
    или суффикс токена (`ts-travel2-service`); None — имена отличаются иначе."""
    tb, tv = base.split("-"), variant.split("-")
    if len(tv) == len(tb) + 1:
        for i in range(len(tv)):
            if tv[:i] + tv[i + 1:] == tb:
                return tv[i].lower()
    if len(tv) == len(tb):
        diff = [i for i in range(len(tb)) if tb[i] != tv[i]]
        if len(diff) == 1 and tv[diff[0]].startswith(tb[diff[0]]):
            return tv[diff[0]][len(tb[diff[0]]):].lower()
    return None


def twin_markers(cat: HandlerCatalog, min_share: float = 0.5) -> list[str]:
    """Маркеры близнецов из самого проекта. Модуль — близнец другого, если его имя отличается одним токеном и
    после снятия токена в сегментах путей совпадает больше `min_share` маршрутов (по Жаккару) — сервис повторяет
    API для другого вида данных. В Train Ticket: `other` (order, preserve) и `2` (travel), доли 0.92–1.0;
    у прочих пар с вставленным токеном (`admin`, `food`, `plan`) — не выше 0.33."""
    routes: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)
    for h in cat.handlers.values():
        routes[h.module].update(h.routes)
    out: set[str] = set()
    for base in sorted(routes):
        for variant in sorted(routes):
            mk = _module_marker(base, variant) if base != variant else None
            if not mk:
                continue
            strip = re.compile(re.escape(mk))
            ra = {(v, "/".join(strip.sub("", s.lower()) for s in p.split("/"))) for v, p in routes[base]}
            rv = {(v, "/".join(strip.sub("", s.lower()) for s in p.split("/"))) for v, p in routes[variant]}
            if len(ra & rv) / len(ra | rv) > min_share:
                out.add(mk)
    return sorted(out, key=lambda m: (-len(m), m))


def twin_groups(cat: HandlerCatalog) -> dict[str, list[str]]:
    """Близнецы: обработчики разных модулей с одинаковым путём после снятия маркера близнеца в сегментах
    (`travelservice` / `travel2service`, `order/refresh` / `orderOther/refresh`, `preserve` / `preserveOther`).
    Маркеры — `twin_markers`."""
    mks = twin_markers(cat)
    marker = re.compile("|".join(re.escape(m) for m in mks)) if mks else None
    groups: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    for nid, h in cat.handlers.items():
        for verb, path in h.routes:
            key = (verb, "/".join(marker.sub("", s.lower()) if marker else s.lower() for s in path.split("/")))
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

    def warm_loads_model(self, queries: list[str]) -> bool:
        """Загрузит ли `warm(queries)` модель эмбеддера: у шагов новые тексты (`StepGrounder.prepare`)."""
        check = getattr(self.embedder, "loads_model_for_queries", None)
        return self.doc_vecs is not None and check is not None and bool(queries) and check(list(dict.fromkeys(queries)))

    def warm(self, queries: list[str]) -> None:
        """Векторы запросов одной пачкой, с повторами один раз: `search` потом берёт их из кеша эмбеддера, модель
        второй раз не нужна. Без dense (нет эмбеддера, векторов обработчиков) ничего не делает."""
        if self.embedder is not None and self.doc_vecs is not None and queries:
            self.embedder.embed_queries(list(dict.fromkeys(queries)))

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
