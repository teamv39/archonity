"""Текстовые утилиты заземления: токены, стеммер, отрицания, BM25."""
from __future__ import annotations

import collections
import math
import re

from engine.adapters.skeleton import toks

VOWELS = set("aeiouy")
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
# Глаголы сверх VERB_SYN (22.10): частые английские слова текста шага, которых нет первым словом ни в одном шаге S0–S7
# и X1–X8, поэтому их кандидаты и ключи кеша LLM не меняются (tests/test_verb_synonyms.py). Отобраны по перефразированным
# S0–S7 (eval/paraphrase): «Find … trains» без `search` не находил поиск рейсов, «Reload my orders» — обновление
# заказов. Это словарь английского языка, а не проекта; отключение — `run_eval.py --m1-verb-synonyms off`.
# Оговорка (аудит 22.10): `reload -> refresh` и `sign -> log, login` — синонимы английского, но выбраны потому, что так
# называются обработчики проекта (`queryOrdersForRefresh`, `login`). Это подбор словаря по замеру перефразировок.
VERB_SYN_EXTRA = {
    **{v: ["get", "find", "query", "search"]
       for v in ("find", "retrieve", "fetch", "inspect", "review", "locate", "explore", "examine")},
    "reload": ["refresh"],
    **{v: ["create", "add", "new"] for v in ("purchase", "buy", "save")},
    **{v: ["update", "modify", "edit"] for v in ("alter", "amend", "adjust", "switch", "move")},
    **{v: ["delete", "remove", "cancel"] for v in ("erase", "discard", "drop")},
    "sign": ["log", "login"],
}

# Глагол создания + объект (22.10): «Create a new passenger account» — это регистрация, а BM25 без слова register не
# находил `registerUser` (перефразированный S4.1: векторы ставят его первым, BM25 — 28-м, в кандидаты не попадал).
# Синоним самого `account` не годится: «internal account balance» и «registered on the account» в S0–S7 и X1–X8 сменили
# бы кандидатов. Срабатывает, только если шаг начинается с глагола из набора и дальше есть объект; ни один шаг S0–S7
# и X1–X8 под это не подходит (tests/test_verb_synonyms.py). Выключается вместе с `VERB_SYN_EXTRA`.
VERB_OBJECT_SYN = {"account": ({"create", "make", "open", "set"}, ["register"])}


def stem(w: str) -> str:
    """Стеммер: окончания множественного числа, -ing, -ed. Синонимов нет: синонимы — работа эмбеддера (ADR-007)."""
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
    return ntoks(NEG.sub(" ", text))


def expand_query(q: list[str], extra: bool = True) -> list[str]:
    """Токены запроса и синонимы его первого слова; `extra` — с `VERB_SYN_EXTRA` (он перекрывает `VERB_SYN`)
    и `VERB_OBJECT_SYN`."""
    if not q:
        return []
    out = q + ((VERB_SYN_EXTRA.get(q[0]) if extra else None) or VERB_SYN.get(q[0], []))
    if extra:
        for obj, (verbs, syn) in VERB_OBJECT_SYN.items():
            if q[0] in verbs and obj in q[1:]:
                out += syn
    return out


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
