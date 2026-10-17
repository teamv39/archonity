"""Текстовые утилиты заземления: токены, стеммер, отрицания, BM25.

Перенесено из engine/resolver.py без изменения поведения; resolver импортирует отсюда.
"""
from __future__ import annotations

import collections
import math
import re

from engine.adapters.skeleton import toks

VOWELS = set("aeiouy")
NOISE = set(
    """ajax json type url data success error function result status headers authorization bearer token session storage content
application alert console log window location reload var let const this that return true false null undefined push length
document href value text html attr disabled true string object new array get post put delete method dataType contentType
xhrFields withCredentials responseJSON message indexOf setItem getItem stringify parse then catch async await response
request params query body import export default class extends require module exports """.split()
)
NEG = re.compile(
    r"\b(?:no|not|without|non)[- ]+([a-z][a-z-]*(?:\s+[a-z][a-z-]*){0,2}?)(?=\s*(?:,|;|\band\b|\bor\b|\)|$))",
    re.I,
)

READ_VERBS = {
    "view", "look", "open", "check", "search", "browse", "ask", "see", "list", "show", "read", "find", "get", "query", "display"
}
VERB_SYN = {
    **{v: ["get", "find", "query"] for v in READ_VERBS},
    **{v: ["create", "add", "new"] for v in ("book", "reserve", "create", "add", "register", "place", "submit", "make")},
    **{v: ["update", "modify", "edit"] for v in ("change", "edit", "modify", "update", "set", "rename")},
    **{v: ["delete", "remove", "cancel"] for v in ("cancel", "delete", "remove", "withdraw")},
}

# Дополнительные бизнес-синонимы
DOMAIN_SYN = {
    "consignments": ["consign", "consigns", "consignee"],
    "consignment": ["consign", "consigns", "consignee"],
    "luggage": ["consign", "consigns", "baggage"],
    "contacts": ["contact", "contacts"],
    "account": ["user", "account"],
    "orders": ["order", "orders"],
}


def stem(w: str) -> str:
    """Улучшенный стеммер: обрабатывает окончания и специфические суффиксы."""
    w_lower = w.lower()
    if w_lower in DOMAIN_SYN:
        return DOMAIN_SYN[w_lower][0]

    if len(w) >= 5 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) >= 5 and w.endswith("es") and w[-3] in "sxz" or w.endswith(("ches", "shes")):
        w = w[:-2]
    elif len(w) >= 4 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    for suf in ("ing", "ed"):
        if w.endswith(suf) and len(w) - len(suf) >= 4 and any(c in VOWELS for c in w[:-len(suf)]):
            w = w[:-len(suf)]
            if len(w) > 4 and w[-1] == w[-2] and w[-1] not in VOWELS:
                w = w[:-1]
            break
    return w


def ntoks(t: str | None) -> list[str]:
    return [stem(w) for w in toks(t)]


def query_toks(text: str) -> list[str]:
    """Токены подписи шага без отрицаемых слов."""
    base_tokens = ntoks(NEG.sub(" ", text))
    expanded: list[str] = []
    for t in base_tokens:
        expanded.append(t)
        if t in DOMAIN_SYN:
            expanded.extend(DOMAIN_SYN[t])
    return expanded


def expand_query(q: list[str]) -> list[str]:
    if not q:
        return []
    return q + (VERB_SYN.get(q[0], []) if q else [])


class BM25:
    def __init__(self, docs: dict[str, list[str]], k1: float = 1.2, b: float = 0.75) -> None:
        self.ids = list(docs)
        D = [docs[i] for i in self.ids]
        self.tf = [collections.Counter(d) for d in D]
        self.len = [len(d) for d in D]
        self.avg = sum(self.len) / max(1, len(D))
        self.k1, self.b = k1, b
        df = collections.Counter(t for c in self.tf for t in c)
        self.idf = {t: math.log(1 + (len(D) - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def rank(self, q: list[str]) -> list[tuple[float, str]]:
        q_cnt = collections.Counter(q)
        sc = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for t, qn in q_cnt.items():
                if t in tf:
                    s += (
                        self.idf[t]
                        * tf[t]
                        * (self.k1 + 1)
                        / (tf[t] + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
                        * min(qn, 3)
                    )
            if s > 0:
                sc.append((s, self.ids[i]))
        return sorted(sc, reverse=True)
