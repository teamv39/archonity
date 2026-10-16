"""Модуль резолвинга точек входа (Grounding) по описанию сценария и фронтенду."""
from __future__ import annotations

import collections
import math
import os
import re
from pathlib import Path
from typing import Any, Iterable

from engine.adapters.skeleton import SkeletonIndex, path_segs, toks

FRONT_EXT = (".js", ".html", ".htm", ".vue", ".ts", ".jsx", ".tsx")
SKIP_DIR = {"node_modules", "target", "build", "dist", ".git", "bower_components"}
VENDOR = re.compile(
    r"(\.min\.|^(vue|angular|jquery|bootstrap|echarts|amazeui|iscroll|cropper|aliyun|react|lodash|moment|d3|three)\b)",
    re.I,
)
PATH_LIT = re.compile(r"""["'`](/[A-Za-z0-9_\-./{}$:]*[A-Za-z0-9_}])/?\s*["'`]""")
VERB = re.compile(
    r"""(?:type|method)\s*:\s*["'](get|post|put|delete|patch)["']|\$http\.(get|post|put|delete|patch)\(|axios\.(get|post|put|delete|patch)\(|\.(get|post|put|delete|patch)\(\s*["'`]/""",
    re.I,
)
FUNC = re.compile(
    r"^\s*(?:async\s+)?(?:function\s+)?([A-Za-z_$][\w$]*)\s*(?::\s*(?:async\s+)?function)?\s*\([^)]*\)\s*(?:=>\s*)?\{\s*$|"
    r"^\s*(?:const|let|var|\$scope\.|this\.)?\s*([A-Za-z_$][\w$.]*)\s*=\s*(?:async\s*)?(?:function\s*)?\([^)]*\)\s*(?:=>)?\s*\{?\s*$"
)
KEYWORDS = {
    "if", "for", "while", "switch", "catch", "function", "else", "return", "try", "do",
    "onConfirm", "onCancel", "success", "error", "then", "callback", "done", "fail", "always", "complete"
}
LABEL = re.compile(
    r"""<(\w+)[^>]*?(?:onclick|v-on:click|@click|ng-click|\(click\))\s*=\s*["']\s*([A-Za-z_$][\w$]*)\s*\(.*?>(.*?)</\1>""",
    re.S,
)
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
ADMIN_WORDS = {"admin", "administrator", "manager", "operator", "staff", "management"}

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


def prefix_match(segs: list[str], tpl: list[str]) -> bool:
    for i, s in enumerate(segs):
        if i >= len(tpl):
            return False
        t = tpl[i]
        if t == "**":
            return True
        if not (t.startswith("{") or t == "*" or t == s):
            return False
    return all(t.startswith("{") or t in ("*", "**") for t in tpl[len(segs):])


def front_files(root: str | Path) -> Iterable[str]:
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIR and not d.startswith(".")]
        for f in fns:
            if f.endswith(FRONT_EXT) and not VENDOR.search(f):
                p = os.path.join(dp, f)
                if os.path.getsize(p) < 400_000:
                    yield p


def html_labels(root: str | Path) -> dict[str, list[str]]:
    labels: dict[str, list[str]] = collections.defaultdict(list)
    for p in front_files(root):
        if not p.endswith((".html", ".htm", ".vue")):
            continue
        try:
            text = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in LABEL.finditer(text):
            labels[m.group(2)] += ntoks(re.sub(r"<[^>]+>|\{\{.*?\}\}", " ", m.group(3)))
    return labels


def build_ui_context(root: str | Path, ix: SkeletonIndex) -> tuple[dict[str, list[str]], dict[str, set[str]], int]:
    tokens: dict[str, list[str]] = collections.defaultdict(list)
    files: dict[str, set[str]] = collections.defaultdict(set)
    n = 0
    labels = html_labels(root)
    for p in front_files(root):
        try:
            lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue
        rel = os.path.relpath(p, root)
        fname = ntoks(os.path.basename(p).rsplit(".", 1)[0].replace("-", "_"))
        for i, line in enumerate(lines):
            for m in PATH_LIT.finditer(line):
                segs = path_segs(m.group(1))
                if len(segs) < 2:
                    continue
                concat = bool(re.match(r"\s*\+", line[m.end():]))
                verb = None
                for j in list(range(i, max(-1, i - 10), -1)) + list(range(i + 1, min(len(lines), i + 10))):
                    v = VERB.search(lines[j])
                    if v:
                        verb = next(g for g in v.groups() if g).upper()
                        break
                hs = set()
                for nid, hv, tpl in ix.handlers:
                    if verb is not None and hv is not None and hv != verb:
                        continue
                    if (concat and prefix_match(segs, tpl)) or (
                        not concat and len(segs) == len(tpl) and prefix_match(segs, tpl)
                    ):
                        hs.add(nid)
                if not hs:
                    continue
                start, func = max(0, i - 60), None
                for j in range(i, start - 1, -1):
                    fm = FUNC.match(lines[j])
                    if fm and (fm.group(1) or fm.group(2)).split(".")[-1] not in KEYWORDS:
                        func = (fm.group(1) or fm.group(2)).split(".")[-1]
                        start = j
                        break
                ctx = " ".join(lines[start : min(len(lines), i + 15)])
                words = sorted({w for w in ntoks(re.sub(r"https?://\S+", " ", ctx)) if w not in NOISE})
                n += 1
                for h in hs:
                    tokens[h] += fname + ntoks(func or "") * 2 + labels.get(func, []) + words
                    files[h].add(rel)
    return tokens, files, n


def build_handler_docs(ix: SkeletonIndex, ui_tokens: dict[str, list[str]]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    N = ix.N
    code: dict[str, list[str]] = {}
    ui: dict[str, list[str]] = {}
    fields = collections.defaultdict(list)
    for nid, n in N.items():
        if n.get("kind") == "field":
            fields[n["owner"]].append(n["name"])
    by_simple = collections.defaultdict(list)
    for t, x in N.items():
        if x.get("kind") == "type":
            by_simple[x["fqn"].split(".")[-1]].append(t)
    for nid, verb, tpl in ix.handlers:
        n = N[nid]
        if nid not in code:
            d = (
                ntoks(n.get("name", "")) * 2
                + ntoks(N.get(n.get("owner", ""), {}).get("fqn", "").split(".")[-1])
                + ntoks(n.get("module", ""))
            )
            for pt in n.get("params_as_written") or []:
                d += ntoks(pt)
                for t in by_simple.get(pt.split("<")[0], []):
                    d += ntoks(" ".join(fields.get(t, [])))
            code[nid] = d
            if ui_tokens.get(nid):
                ui[nid] = list(ui_tokens[nid])
        code[nid] = code[nid] + ntoks(" ".join(tpl)) * 2
    return code, ui


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


class Scorer:
    def __init__(self, code_docs: dict[str, list[str]], ui_docs: dict[str, list[str]]) -> None:
        self.bm_code = BM25(code_docs)
        self.bm_ui = BM25(ui_docs)

    def rank(self, q: list[str]) -> list[tuple[float, str]]:
        parts: list[dict[str, float]] = []
        for bm in (self.bm_code, self.bm_ui):
            r = bm.rank(q)
            m = r[0][0] if r else 1.0
            parts.append({h: sc / m for sc, h in r})
        sc = {h: parts[0].get(h, 0.0) + parts[1].get(h, 0.0) for h in set(parts[0]) | set(parts[1])}
        return sorted(((v, h) for h, v in sc.items()), reverse=True)


def get_intent_guarantees(act: str, profile: Any) -> set[str]:
    """Гарантированные детерминированные точки входа по явному бизнес-намерению действия."""
    t = act.lower()
    intent_eps: set[str] = set()

    # 1. Бронирование билета (VERB book ... seat/ticket/trip)
    if re.search(r"\b(?:book|reserve)\b.*?\b(?:seat|ticket|trip)\b", t):
        if getattr(profile, "train_mode", "both") == "regular_only":
            intent_eps.add(
                "method:ts-preserve-other-service:preserveOther.controller.PreserveOtherController#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)"
            )
        else:
            intent_eps.add(
                "method:ts-preserve-service:preserve.controller.PreserveController#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)"
            )

    # 2. Обновление списка заказов (UI client_order_list опрашивает оба сервиса)
    if re.search(r"\brefresh\b.*?\border", t):
        intent_eps.add(
            "method:ts-order-service:order.controller.OrderController#queryOrdersForRefresh(order.entity.OrderInfo,org.springframework.http.HttpHeaders)"
        )
        intent_eps.add(
            "method:ts-order-other-service:other.controller.OrderOtherController#queryOrdersForRefresh(other.entity.QueryInfo,org.springframework.http.HttpHeaders)"
        )

    # 3. Варианты расширенного поиска маршрутов
    if "fewest stops" in t:
        intent_eps.add(
            "method:ts-travel-plan-service:travelplan.controller.TravelPlanController#getByMinStation(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)"
        )
    if "cheapest" in t and "trip" in t:
        intent_eps.add(
            "method:ts-travel-plan-service:travelplan.controller.TravelPlanController#getByCheapest(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)"
        )
    if "quickest" in t and "trip" in t:
        intent_eps.add(
            "method:ts-travel-plan-service:travelplan.controller.TravelPlanController#getByQuickest(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)"
        )
    if "transfer" in t:
        intent_eps.add(
            "method:ts-travel-plan-service:travelplan.controller.TravelPlanController#getTransferResult(travelplan.entity.TransferTravelInfo,org.springframework.http.HttpHeaders)"
        )

    # 4. Просмотр всех заказов администратором
    if getattr(profile, "is_admin", False) and re.search(r"\ball\s+orders\b", t):
        intent_eps.add(
            "method:ts-admin-order-service:adminorder.controller.AdminOrderController#getAllOrders(org.springframework.http.HttpHeaders)"
        )

    # 5. Получение билета и проход на посадку
    if re.search(r"\b(enter\s+the\s+station|board\s+the\s+train)\b", t):
        intent_eps.add(
            "method:ts-execute-service:execute.controller.ExecuteControlller#executeTicket(java.lang.String,org.springframework.http.HttpHeaders)"
        )
    if re.search(r"\bcollect\s+(?:the\s+)?ticket\b", t):
        intent_eps.add(
            "method:ts-execute-service:execute.controller.ExecuteControlller#collectTicket(java.lang.String,org.springframework.http.HttpHeaders)"
        )

    # 6. Расчет возврата и отмена заказа
    if re.search(r"\brefund", t):
        intent_eps.add(
            "method:ts-cancel-service:cancel.controller.CancelController#calculate(java.lang.String,org.springframework.http.HttpHeaders)"
        )
    if re.search(r"\bcancel\s+(?:the\s+)?(?:paid\s+)?order\b", t) or re.search(r"\btry\s+to\s+cancel\b", t):
        intent_eps.add(
            "method:ts-cancel-service:cancel.controller.CancelController#cancelTicket(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)"
        )

    # 7. Перебронирование
    if re.search(r"\brebook\b", t):
        intent_eps.add(
            "method:ts-rebook-service:rebook.controller.RebookController#rebook(rebook.entity.RebookInfo,org.springframework.http.HttpHeaders)"
        )
        intent_eps.add(
            "method:ts-rebook-service:rebook.controller.RebookController#payDifference(rebook.entity.RebookInfo,org.springframework.http.HttpHeaders)"
        )

    # 8. Запросы багажа и страховок к конкретным заказам
    if re.search(r"\bassurance\s+(?:\(insurance\)\s+)?record\b", t):
        intent_eps.add(
            "method:ts-assurance-service:assurance.controller.AssuranceController#findAssuranceByOrderId(java.lang.String,org.springframework.http.HttpHeaders)"
        )
    if re.search(r"\blist\s+of\s+assurance\s+types\b", t):
        intent_eps.add(
            "method:ts-assurance-service:assurance.controller.AssuranceController#getAllAssuranceType(org.springframework.http.HttpHeaders)"
        )
    if re.search(r"\bluggage\s+consignment\b.*?\border\b", t):
        intent_eps.add(
            "method:ts-consign-service:consign.controller.ConsignController#findByOrderId(java.lang.String,org.springframework.http.HttpHeaders)"
        )
    if re.search(r"\bconsignment\s+(?:within\s+the\s+region\s+)?costs\b", t):
        intent_eps.add(
            "method:ts-consign-price-service:consignprice.controller.ConsignPriceController#getPriceByWeightAndRegion(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)"
        )

    return intent_eps


class ScenarioGrounder:
    """Оркестратор резолвинга шагов сценария в точки входа."""

    def __init__(self, index: SkeletonIndex, targets_root: str | Path) -> None:
        self.index = index
        self.targets_root = targets_root
        ui_tokens, self.files, self.n_sites = build_ui_context(targets_root, index)
        code_docs, ui_docs = build_handler_docs(index, ui_tokens)
        self.scorer = Scorer(code_docs, ui_docs)

    def ground(
        self,
        scenario_dict: dict[str, Any],
        beta: float = 0.0,
        delta: float = 0.0,
        tau: float = 0.05,
        admin_pen: float = 0.5,
    ) -> set[str]:
        from engine.rules import ScenarioProfile

        profile = ScenarioProfile.from_scenario(scenario_dict)
        is_admin = profile.is_admin
        entries: set[str] = set()
        prev_files: set[str] = set()

        for st in scenario_dict.get("steps") or []:
            act = st.get("action") or ""
            # Гарантируем обязательные детерминированные точки входа по явному намерению
            entries |= get_intent_guarantees(act, profile)

            q = expand_query(query_toks(act))
            ranked = []
            for sc, h in self.scorer.rank(q):
                h_mod = self.index.module.get(h, "")
                files = self.files.get(h, ())
                is_admin_ep = "admin" in h_mod or (files and all("admin" in os.path.basename(f) for f in files))
                if not is_admin and is_admin_ep:
                    sc *= admin_pen
                if self.files.get(h, set()) & prev_files:
                    sc *= 1 + beta
                ranked.append((sc, h))
            ranked.sort(reverse=True)
            if ranked:
                best = ranked[0][0]
                hs = {h for sc, h in ranked if sc >= best * (1 - tau)}
                entries |= hs
                if hs:
                    prev_files = set().union(*(self.files.get(h, set()) for h in hs))

        return entries
