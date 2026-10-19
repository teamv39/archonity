"""Шаги без запроса в UI (eval/m1_steps.json: no_ui, disputed): сколько уникальных рёбер они дают в выдаче.

python unique_noui.py <m1_steps.json> <decisions.json> <step_requests.json>
Уникальное ребро — включённое ребро, у которого все шаги ⊆ {этот шаг}.
"""
import json
import sys
from collections import Counter

m1 = json.load(open(sys.argv[1], encoding="utf-8"))["scenarios"]
dec = json.load(open(sys.argv[2], encoding="utf-8"))["scenarios"]
sr = json.load(open(sys.argv[3], encoding="utf-8"))
for sid in sorted(m1):
    if sid == "S0":
        continue
    handlers = {r["step"]: r["handler"] for r in sr.get(sid, [])}
    for st in m1[sid]:
        if st["status"] == "ok":
            continue
        n = st["n"]
        uniq = Counter()
        for key, rec in dec.get(sid, {}).items():
            if rec.get("included") and rec.get("steps") == [n]:
                uniq[key.split("|")[0]] += 1
        h = handlers.get(n, "-").split(":")[-1].split("(")[0]
        print(f"{sid}.{n:<2} {st['status']:<9} uniq={sum(uniq.values()):<3} {dict(uniq)}  {st['action'][:55]} -> {h}")
