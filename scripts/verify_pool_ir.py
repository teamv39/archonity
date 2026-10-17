#!/usr/bin/env python3
"""verify_pool_ir.py — Проверка сопоставления calls из pool_ir.json с узлами call_site скелета (п. 3.2 README)."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Проверка сопоставления pool_ir.json со скелетом")
    parser.add_argument(
        "--ir",
        type=Path,
        default=Path("data/pool_ir.json"),
        help="Путь к pool_ir.json"
    )
    parser.add_argument(
        "--skeleton",
        type=Path,
        default=Path("hackaton/tt-challenge/skeleton/trainticket.json.gz"),
        help="Путь к trainticket.json.gz"
    )
    args = parser.parse_args()

    if not args.ir.exists():
        # Запуск из archparse/
        alt_ir = Path("../data/pool_ir.json")
        if alt_ir.exists():
            args.ir = alt_ir
        else:
            print(f"Error: IR file not found: {args.ir}")
            return 1

    if not args.skeleton.exists():
        alt_sk = Path("../hackaton/tt-challenge/skeleton/trainticket.json.gz")
        if alt_sk.exists():
            args.skeleton = alt_sk
        else:
            print(f"Error: Skeleton file not found: {args.skeleton}")
            return 1

    with open(args.ir, "r", encoding="utf-8") as f:
        pool_ir = json.load(f)

    with gzip.open(args.skeleton, "rt", encoding="utf-8") as f:
        skeleton = json.load(f)

    sk_nodes = skeleton.get("nodes", {})
    sk_call_sites = {}
    for nid, node in sk_nodes.items():
        if node.get("kind") == "call_site":
            key = (node.get("file"), node.get("line"), node.get("col"))
            sk_call_sites[key] = (nid, node)

    print(f"Total skeleton call sites indexed: {len(sk_call_sites)}")
    print(f"Verifying {len(pool_ir)} methods from {args.ir}...\n")

    total_matched = 0
    total_calls = 0
    all_ok = True

    for mir in pool_ir:
        mid = mir["method_id"]
        calls = mir["calls"]
        matched = 0
        missing = []
        for c in calls:
            key = (c["file"], c["line"], c["col"])
            if key in sk_call_sites:
                matched += 1
            else:
                missing.append(c)

        total_matched += matched
        total_calls += len(calls)
        node = sk_nodes.get(mid)
        if node is None:
            print(f"  [FAIL] method_id not in skeleton: {mid}")
            all_ok = False
        else:
            ir_keys = {(c["line"], c["col"]) for c in calls}
            sk_keys = {(n.get("line"), n.get("col")) for (f, _l, _c), (_i, n) in sk_call_sites.items() if n.get("method") == mid}
            uncovered = sk_keys - ir_keys
            if uncovered:
                print(f"  [FAIL] {len(uncovered)} skeleton call_sites not in IR (first: {sorted(uncovered)[:3]})")
                all_ok = False
        status = "MATCHED (100%)" if len(missing) == 0 else f"{len(missing)} MISSING"
        print(f"  {mid}: {matched}/{len(calls)} calls -> {status}")

        if missing:
            all_ok = False
            for m in missing[:5]:
                print(f"    [MISSING] line {m['line']} col {m['col']} callee {m['callee']} receiver {m['receiver']}")

    print(f"\nResult: {total_matched}/{total_calls} calls matched.")
    if all_ok:
        print("[SUCCESS] All calls match skeleton geometry (file, line, col) exactly!")
        return 0
    else:
        print("[FAIL] Some calls did not match skeleton.")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
