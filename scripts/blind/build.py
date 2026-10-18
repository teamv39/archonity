"""Собирает ответ из компактного списка рёбер.

build.py <скелет> <SID> <edges.txt> <out.json>

Формат edges.txt (# -- комментарий, пустые строки пропускаются):
  E <метод>                 executes
  C <метод> -> <метод>      calls
  R <метод> -> <метод>      remote
  D <метод> -> <таблица>    data
Метод/таблица -- полный ID или однозначная подстрока ID. Неоднозначность -- ошибка.
Для calls/remote/data оба метода автоматически добавляются в executes (R19).
"""
import gzip, json, sys

sk, sid, src, dst = sys.argv[1:5]
N = json.load(gzip.open(sk))["nodes"]
methods = [k for k, v in N.items() if v["kind"] == "method"]
tables = [k for k, v in N.items() if v["kind"] == "data_resource"]
errors = []


def res(q, pool, ln):
    q = q.strip()
    if q in N:
        return q
    c = [k for k in pool if q in k]
    if len(c) == 1:
        return c[0]
    errors.append(f"строка {ln}: {len(c)} совпадений для '{q}': {c[:5]}")
    return None


ex, rels = set(), set()
for ln, line in enumerate(open(src, encoding="utf-8"), 1):
    line = line.split(" #", 1)[0].strip()
    if not line or line.startswith("#"):
        continue
    kind, rest = line[0], line[1:].strip()
    if kind == "E":
        m = res(rest, methods, ln)
        if m:
            ex.add(m)
        continue
    a, b = [x.strip() for x in rest.split("->")]
    a = res(a, methods, ln)
    b = res(b, tables if kind == "D" else methods, ln)
    if not (a and b):
        continue
    rel = {"C": "calls", "R": "remote", "D": "data"}[kind]
    rels.add((a, rel, b))
    ex.add(a)
    if kind != "D":
        ex.add(b)
if errors:
    print("\n".join(errors))
    sys.exit(1)
edges = [{"source": f"scenario:{sid}", "relation": "executes", "target": m} for m in sorted(ex)]
edges += [{"source": a, "relation": r, "target": b} for a, r, b in sorted(rels, key=lambda x: (x[1], x[0], x[2]))]
json.dump({"project": "trainticket", "scenarios": {sid: {"edges": edges}}}, open(dst, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
cnt = {}
for e in edges:
    cnt[e["relation"]] = cnt.get(e["relation"], 0) + 1
print(sid, cnt)
