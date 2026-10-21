"""Навигатор по скелету для ручной разметки.

sk.py m <подстрока>        -- методы, ID которых содержит подстроку
sk.py cs <метод|подстрока> -- call_site метода по строкам с целями рёбер
sk.py in <метод|подстрока> -- входящие calls/runtime_dispatch/remote_call к методу
sk.py t <подстрока>        -- таблицы
"""
import gzip, json, sys, collections

SK = sys.argv[1]
d = json.load(gzip.open(SK))
N = d["nodes"]
out = collections.defaultdict(list)
inc = collections.defaultdict(list)
for e in d["edges"]:
    if e["type"] in ("calls", "runtime_dispatch", "remote_call", "data_access", "message_delivery", "creates"):
        out[e["source"]].append((e["type"], e["target"]))
        inc[e["target"]].append((e["type"], e["source"]))
cs_by_m = collections.defaultdict(list)
for k, v in N.items():
    if v["kind"] == "call_site":
        cs_by_m[v["method"]].append(k)


def resolve(q):
    if q in N:
        return q
    c = [k for k, v in N.items() if v["kind"] == "method" and q in k]
    if len(c) != 1:
        print(f"!! {len(c)} совпадений для {q}")
        for x in c[:40]:
            print("   ", x)
        sys.exit(1)
    return c[0]


def short(t):
    return t.replace("method:", "")


cmd, q = sys.argv[2], sys.argv[3]
if cmd == "m":
    for k, v in N.items():
        if v["kind"] == "method" and q in k:
            print(k, f"[{v['file']}:{v['line']}-{v['end']}]", "ABSTRACT" if v.get("abstract") else "")
elif cmd == "t":
    for k, v in N.items():
        if v["kind"] == "data_resource" and q in k:
            print(k)
elif cmd == "cs":
    m = resolve(q)
    v = N[m]
    print(m, f"[{v['file']}:{v['line']}-{v['end']}]")
    for c in sorted(cs_by_m[m], key=lambda c: (N[c]["line"], N[c].get("col", 0))):
        cv = N[c]
        tg = out.get(c, [])
        s = f"  @{cv['line']}:{cv.get('col')} {cv.get('receiver')}.{cv['callee']}{cv.get('args_text','')[:60]} <{cv.get('receiver_type')}>"
        if cv.get("method_ref"):
            s += " [ref]"
        print(s)
        for t, x in tg:
            print(f"      {t:16} {short(x)}")
elif cmd == "in":
    m = resolve(q)
    for t, s in inc.get(m, []):
        src = N[s]["method"] if s in N and N[s]["kind"] == "call_site" else s
        print(f"{t:16} {short(src)}  ({s.split('@')[-1]})")
