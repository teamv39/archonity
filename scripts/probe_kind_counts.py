"""Замер FP и FN по видам рёбер в каждом сценарии по баллам платформы.

Идея (eval/blind/notes.md, раздел 7). Для пары «сценарий × вид» неизвестны совпадения I и размер эталона G,
известен размер ответа P. Две посылки дают два уравнения:

    drop_<вид>: вид убран во всех сценариях  -> балл сценария падает на IoU1/4,  IoU1 = I / (P + G - I)
    add_<вид>:  к виду добавлено k заведомо лишних рёбер -> IoU2 = I / (P + G - I + k)

Отсюда U = P + G - I = k * IoU2 / (IoU1 - IoU2), I = IoU1 * U, FP = P - I, FN = U - P.

Заведомо лишние рёбра берутся из сервисов, которых сценарий не касается (список UNRELATED минус сервисы,
которые есть в ответе этого сценария; для S6 — без ts-admin-*). Это замер, а не кандидат в финальную посылку:
после него рекорд перезаливается.

    python scripts/probe_kind_counts.py make  <рекорд.json> <скелет.json.gz> <папка>
    python scripts/probe_kind_counts.py solve <папка>/manifest.json <баллы.txt>

Формат баллы.txt: строка на посылку, «имя S1 S2 S3 S4 S5 S6 S7» (баллы сценариев из таблицы платформы);
имя base — рекорд, остальные — имена файлов зондов без .json (drop_calls, add_calls, ...).
"""
from __future__ import annotations

import collections
import gzip
import json
import sys
from pathlib import Path

KINDS = ("executes", "calls", "remote", "data")
SCEN = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
UNRELATED = {
    "ts-admin-user-service", "ts-admin-route-service", "ts-admin-order-service", "ts-admin-basic-info-service",
    "ts-wait-order-service", "ts-food-delivery-service", "ts-news-service", "ts-avatar-service",
    "ts-voucher-service", "ts-ticket-office-service",
}


def svc(node_id: str) -> str:
    return node_id.split(":")[1]


def make(base_p: str, sk_p: str, out_p: str) -> None:
    base = json.loads(Path(base_p).read_text(encoding="utf-8"))
    sk = json.load(gzip.open(sk_p))
    N = sk["nodes"]
    out = Path(out_p)
    out.mkdir(parents=True, exist_ok=True)

    # пулы рёбер из скелета по сервису-источнику
    pool = {k: collections.defaultdict(set) for k in KINDS}
    for nid, n in N.items():
        if n["kind"] == "method" and not n.get("abstract"):
            pool["executes"][svc(nid)].add(nid)
    disp = collections.defaultdict(set)
    for e in sk["edges"]:
        if e["type"] == "runtime_dispatch":
            disp[e["source"]].add(e["target"])
    for e in sk["edges"]:
        cs = N.get(e["source"])
        if not cs or cs["kind"] != "call_site":
            continue
        m, t = cs["method"], e["target"]
        if e["type"] in ("calls", "runtime_dispatch"):
            if e["type"] == "calls" and disp.get(e["source"]):
                continue
            if N.get(t, {}).get("kind") == "method" and not N[t].get("abstract"):
                pool["calls"][svc(m)].add((m, t))
        elif e["type"] in ("remote_call", "message_delivery"):
            pool["remote"][svc(m)].add((m, t))
        elif e["type"] == "data_access":
            pool["data"][svc(m)].add((m, t))

    sc = base["scenarios"]
    manifest = {"P": {}, "k": {}, "safe_services": {}}
    added = {k: {} for k in KINDS}
    for s in SCEN:
        edges = sc[s]["edges"]
        used = {svc(e["target"]) for e in edges if e["relation"] == "executes"}
        safe = sorted(UNRELATED - used - ({x for x in UNRELATED if x.startswith("ts-admin-")} if s == "S6" else set()))
        manifest["safe_services"][s] = safe
        have = {(e["source"], e["relation"], e["target"]) for e in edges}
        manifest["P"][s], manifest["k"][s] = {}, {}
        for k in KINDS:
            P = sum(1 for e in edges if e["relation"] == k)
            cand = sorted(x for sv in safe for x in pool[k][sv])
            if k == "executes":
                cand = [x for x in cand if (f"scenario:{s}", k, x) not in have]
            else:
                cand = [x for x in cand if (x[0], k, x[1]) not in have]
            take = cand[:P]  # k ≈ P: так погрешность U минимальна
            manifest["P"][s][k], manifest["k"][s][k] = P, len(take)
            added[k][s] = take

    for k in KINDS:
        drop = json.loads(json.dumps(base))
        add = json.loads(json.dumps(base))
        for s in SCEN:
            drop["scenarios"][s]["edges"] = [e for e in sc[s]["edges"] if e["relation"] != k]
            extra = [{"source": f"scenario:{s}", "relation": k, "target": x} if k == "executes"
                     else {"source": x[0], "relation": k, "target": x[1]} for x in added[k][s]]
            add["scenarios"][s]["edges"] = sc[s]["edges"] + extra
        for name, obj in ((f"drop_{k}", drop), (f"add_{k}", add)):
            (out / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("P (размер ответа) и k (добавлено лишних):")
    for s in SCEN:
        print(" ", s, {k: (manifest["P"][s][k], manifest["k"][s][k]) for k in KINDS}, "сервисы:", len(manifest["safe_services"][s]))


def solve(man_p: str, scores_p: str) -> None:
    man = json.loads(Path(man_p).read_text(encoding="utf-8"))
    sc = {}
    for line in Path(scores_p).read_text(encoding="utf-8").split("\n"):
        p = line.split()
        if len(p) == 8:
            sc[p[0]] = dict(zip(SCEN, map(float, p[1:])))
    base = sc["base"]
    print(f"{'':4} {'вид':9} {'P':>4} {'k':>4} {'IoU':>6} {'G':>6} {'I':>6} {'FP':>6} {'FN':>6}")
    for s in SCEN:
        for k in KINDS:
            P, kk = man["P"][s][k], man["k"][s][k]
            if f"drop_{k}" not in sc:
                continue
            iou1 = 4 * (base[s] - sc[f"drop_{k}"][s])
            line = f"{s:4} {k:9} {P:4} {kk:4} {iou1:6.3f}"
            if f"add_{k}" in sc and kk:
                iou2 = iou1 - 4 * (base[s] - sc[f"add_{k}"][s])
                if iou1 - iou2 > 1e-9:
                    U = kk * iou2 / (iou1 - iou2)
                    I = iou1 * U
                    line += f" {U - P + I:6.1f} {I:6.1f} {P - I:6.1f} {U - P:6.1f}"
            print(line)
    print("Погрешность: баллы сценариев даны с 3 знаками, IoU ±0.004, FP/FN — порядка ±5 рёбер.")
    print("Для точного счёта по одной паре — зонд только в этом сценарии и итог с 5 знаками.")


if __name__ == "__main__":
    if sys.argv[1] == "make":
        make(*sys.argv[2:5])
    else:
        solve(*sys.argv[2:4])
