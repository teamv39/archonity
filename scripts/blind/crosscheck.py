"""crosscheck.py <скелет> <ответ.json> <SID> -- рёбра скелета от исполненных методов, которых нет в ответе."""
import gzip, json, sys, collections

sk, ans, sid = sys.argv[1:4]
d = json.load(gzip.open(sk))
N = d["nodes"]
edges = json.load(open(ans, encoding="utf-8"))["scenarios"][sid]["edges"]
ex = {e["target"] for e in edges if e["relation"] == "executes"}
have = {(e["source"], e["relation"], e["target"]) for e in edges if e["relation"] != "executes"}
by_cs = collections.defaultdict(list)
for e in d["edges"]:
    if e["type"] in ("calls", "runtime_dispatch", "remote_call", "data_access", "message_delivery"):
        by_cs[e["source"]].append(e)
rel = {"calls": "calls", "runtime_dispatch": "calls", "remote_call": "remote", "message_delivery": "remote", "data_access": "data"}
miss = collections.defaultdict(list)
for cs, es in by_cs.items():
    n = N.get(cs)
    if not n or n["kind"] != "call_site" or n["method"] not in ex:
        continue
    disp = {e["target"] for e in es if e["type"] == "runtime_dispatch"}
    for e in es:
        t = e["target"]
        if e["type"] == "calls" and disp:
            continue  # интерфейс, в ответ идёт реализация
        if e["type"] == "calls" and N.get(t, {}).get("abstract"):
            continue  # репозиторий без реализации
        if (n["method"], rel[e["type"]], t) not in have:
            miss[n["method"]].append(f"@{n['line']} {e['type']:16} {t.replace('method:', '')}")
for m in sorted(miss):
    print(m.replace("method:", ""))
    for x in miss[m]:
        print("   ", x)
