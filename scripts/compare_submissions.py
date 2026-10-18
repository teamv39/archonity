#!/usr/bin/env python3
"""Сравнение двух submission.json ребро в ребро: по сценариям и видам рёбер.

    python scripts/compare_submissions.py A.json B.json [--scenario S3] [--show 30] [--decisions output/decisions.json]

«Только A» и «только B» — множества (relation, source, target). С --decisions у рёбер A печатаются шаги и правило
из журнала решений.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def load(path: Path) -> dict[str, set[tuple[str, str, str]]]:
    sc = json.loads(path.read_text(encoding="utf-8"))["scenarios"]
    return {sid: {(e["relation"], e["source"], e["target"]) for e in v["edges"]} for sid, v in sc.items()}


def short(x: str) -> str:
    return x.split(":", 2)[-1].split("(")[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--scenario", action="append", help="только эти сценарии (можно несколько раз)")
    ap.add_argument("--show", type=int, default=0, help="сколько рёбер расхождения печатать на сценарий")
    ap.add_argument("--decisions", type=Path, help="decisions.json прогона A: шаги и правило у рёбер")
    args = ap.parse_args()

    a, b = load(args.a), load(args.b)
    dec = json.loads(args.decisions.read_text(encoding="utf-8"))["scenarios"] if args.decisions else {}
    for sid in sorted(set(a) | set(b)):
        if args.scenario and sid not in args.scenario:
            continue
        x, y = a.get(sid, set()), b.get(sid, set())
        only_a, only_b = x - y, y - x
        by = {k: (sum(r == k for r, _, _ in only_a), sum(r == k for r, _, _ in only_b))
              for k in ("executes", "calls", "remote", "data")}
        kinds = ", ".join(f"{k} −{n}/+{m}" for k, (n, m) in by.items() if n or m) or "совпадают"
        print(f"{sid}: A {len(x)}, B {len(y)}, только A {len(only_a)}, только B {len(only_b)} ({kinds})")
        if not args.show:
            continue
        for tag, edges in (("-", only_a), ("+", only_b)):
            for rel, s, t in sorted(edges)[: args.show]:
                v = dec.get(sid, {}).get(f"{rel}|{s}|{t}", {})
                why = f"  [шаги {v.get('steps')}, {v.get('rule', '')[:60]}]" if v else ""
                print(f"  {tag} {rel:8} {short(s)} -> {short(t)}{why}")


if __name__ == "__main__":
    main()
