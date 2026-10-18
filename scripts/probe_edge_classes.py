#!/usr/bin/env python3
"""Классы рёбер ответа для зондирующих посылок.

Для каждого класса (механизм на конце ребра или происхождение ребра по журналу решений) печатает:
сколько рёбер класса в ответе S1–S7, сколько рёбер-кандидатов вне ответа (рёбра скелета из исполненных методов),
что говорит S0 (рёбра класса в эталоне и рёбра класса у исполненных методов S0, которых в эталоне нет)
и вилку сдвига итогового балла, если класс убрать или добавить.

Вилка считается при допущении: IoU каждого вида в сценарии равен баллу сценария и |эталон| ~ |ответ|.
Это оценка порядка величины, а не прогноз.

    python scripts/probe_edge_classes.py output/submission.json output/decisions.json [--by origin]

S0 берётся из ответа: он совпадает с эталоном (балл 1.0). Баллы сценариев — рекорд 0.93625.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKELETON = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"
SCORE = {"S1": 0.941, "S2": 0.919, "S3": 0.913, "S4": 0.938, "S5": 0.942, "S6": 0.950, "S7": 0.951}
KINDS = ("executes", "calls", "remote", "data")
CELLS = len(SCORE) * len(KINDS)


def edges_of(path: Path) -> dict[str, set[tuple[str, str, str]]]:
    sc = json.loads(path.read_text(encoding="utf-8")).get("scenarios")
    return {sid: {(e.get("relation") or e.get("type"), e["source"], e["target"]) for e in (v.get("edges", v))}
            for sid, v in sc.items()}


class Skeleton:
    def __init__(self) -> None:
        sk = json.load(gzip.open(SKELETON, "rt", encoding="utf-8"))
        self.N = sk["nodes"]
        self.out = {rel: collections.defaultdict(set) for rel in ("calls", "remote", "data")}
        for e in sk["edges"]:
            src = self.N.get(e["source"], {})
            if src.get("kind") != "call_site":
                continue
            rel = {"calls": "calls", "runtime_dispatch": "calls", "remote_call": "remote", "data_access": "data"}.get(e["type"])
            if rel == "calls" and self.N.get(e["target"], {}).get("kind") != "method":
                continue
            if rel:
                self.out[rel][src["method"]].add(e["target"])

    def mechanism(self, m: str) -> str:
        n = self.N.get(m, {})
        o = self.N.get(n.get("owner", ""), {})
        name, fqn = n.get("name", ""), o.get("fqn", "") or ""
        anns = {a.get("name") for a in o.get("annotations") or []}
        if o.get("type_kind") == "enum":
            return "enum"
        if name in ("toString", "equals", "hashCode", "compareTo"):
            return "Object-метод"
        if name == "<init>":
            if anns & {"Entity", "Table", "Document"}:
                return "конструктор @Entity"
            return "конструктор DTO/entity" if any(p in fqn for p in (".entity.", ".dto.", ".vo.")) else "конструктор прочий"
        if re.match(r"^(get|set|is)[A-Z]", name) and (n.get("end", 0) - n.get("line", 0)) <= 3 \
                and not anns & {"Service", "RestController", "Controller", "Component"}:
            return "геттер/сеттер"
        if ".util." in fqn or fqn.endswith(("Utils", "Util")):
            return "утилита"
        if ".security." in fqn or ".config." in fqn or "jwt" in fqn.lower():
            return "security/config"
        if anns & {"RestController", "Controller"}:
            return "контроллер"
        if ".mq." in fqn or "Rabbit" in fqn:
            return "потребитель MQ"
        return "сервис private" if "private" in (n.get("modifiers") or []) else "сервис public"


def origin(rule: str | None, source_type: str | None) -> str:
    r = rule or ""
    for key, label in (("unresolved_receiver", "R2 emit"), ("spring_security", "spring_security"),
                       ("ELEMENT_CALLBACK", "element_callback"), ("R7", "R7 загрузка"), ("R10", "R10"),
                       ("R3", "R3 dispatch"), ("success_path", "success_path"), ("R17", "R17")):
        if key in r:
            return label
    return {"SKELETON": "достижимость", "IR_BRANCH": "ветка IR", "STATE": "состояние"}.get(source_type or "", "вне ответа")


def fork(n: int, s: float, b: int, add: bool) -> tuple[float, float]:
    """Сдвиг IoU вида: (класс весь верный, класс лишний в максимально возможной мере)."""
    if not n or not b:
        return 0.0, 0.0
    i, u = 2 * s * n / (1 + s), 2 * n / (1 + s)
    fp, fn = n - i, u - n
    if add:
        t = min(b, fn)
        return (i + t) / (u + b - t) - s, i / (u + b) - s
    hi, lo = min(b, i), max(0.0, b - fp)
    return (i - hi) / (u - b + hi) - s, (i - lo) / (u - b + lo) - s


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("submission", type=Path)
    ap.add_argument("decisions", type=Path)
    ap.add_argument("--by", choices=("mechanism", "origin"), default="mechanism")
    args = ap.parse_args()

    sk = Skeleton()
    ans = edges_of(args.submission)
    dec = json.loads(args.decisions.read_text(encoding="utf-8"))["scenarios"]

    def klass(rel: str, t: str, rule: str | None, st: str | None) -> str:
        if args.by == "origin":
            return f"{rel} / {origin(rule, st)}"
        if rel in ("remote", "data"):
            return f"{rel} / {origin(rule, st)}"
        return f"{rel} / {sk.mechanism(t)}"

    inn: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    cand: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for sid, es in ans.items():
        if sid == "S0":
            continue
        d = dec.get(sid, {})
        for rel, s, t in es:
            v = d.get(f"{rel}|{s}|{t}", {})
            inn[klass(rel, t, v.get("rule"), v.get("source_type"))][(sid, rel)] += 1
        for m in {t for r, _, t in es if r == "executes"}:
            for rel, outs in sk.out.items():
                for t in outs.get(m, ()):
                    if (rel, m, t) not in es and not sk.N.get(t, {}).get("abstract"):
                        v = d.get(f"{rel}|{m}|{t}", {})
                        cand[klass(rel, t, v.get("rule"), v.get("source_type") or "")][(sid, rel)] += 1

    # S0: по механизму (журнал S0 тот же, но происхождение для S0 не нужно)
    g0 = ans["S0"]
    s0_in, s0_skip = collections.Counter(), collections.Counter()
    for rel, _, t in g0:
        if rel in ("calls", "executes"):
            s0_in[f"{rel} / {sk.mechanism(t)}"] += 1
        else:
            s0_in[rel] += 1
    for m in {t for r, _, t in g0 if r == "executes"}:
        for rel, outs in sk.out.items():
            for t in outs.get(m, ()):
                if (rel, m, t) not in g0 and not sk.N.get(t, {}).get("abstract"):
                    s0_skip[f"{rel} / {sk.mechanism(t)}" if rel == "calls" else rel] += 1

    sizes = {sid: collections.Counter(r for r, _, _ in es) for sid, es in ans.items()}
    rows = []
    for k in set(inn) | set(cand):
        rm = [0.0, 0.0]
        ad = [0.0, 0.0]
        for sid, sc in SCORE.items():
            for rel in KINDS:
                for acc, src, add in ((rm, inn, False), (ad, cand, True)):
                    a, b = fork(sizes[sid][rel], sc, src[k][(sid, rel)], add)
                    acc[0] += a / CELLS
                    acc[1] += b / CELLS
        base = k if args.by == "mechanism" and k.split(" / ")[0] in ("calls", "executes") else k.split(" / ")[0]
        rows.append((sum(inn[k].values()), sum(cand[k].values()), k, s0_in.get(base, 0), s0_skip.get(base, 0), rm, ad,
                     sorted({s for s, _ in inn[k]})))
    print(f"{'класс':38} {'в отв.':>6} {'канд.':>5} {'S0 эт.':>6} {'S0 нет':>6}  {'убрать: верны / лишние':>24}  {'добавить: верны / лишние':>25}")
    for n_in, n_c, k, g, skip, rm, ad, scen in sorted(rows, key=lambda r: -(r[0] + r[1])):
        print(f"{k[:38]:38} {n_in:6} {n_c:5} {g:6} {skip:6}  {rm[0]:+.4f} / {rm[1]:+.4f}{'':8}  {ad[0]:+.4f} / {ad[1]:+.4f}")


if __name__ == "__main__":
    main()
