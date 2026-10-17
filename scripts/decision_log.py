#!/usr/bin/env python3
"""scripts/decision_log.py — Журнал решений по рёбрам сценариев (Блок 0 плана archparse).

Скрипт не пересчитывает обход сам: он запускает пайплайн и читает журнал решений,
который пишет GraphBuilder (engine/decisions.py). Поэтому отчёт совпадает с submission.json;
это проверяется на каждом прогоне.

Отчёт по сценарию:
1. Сводка: рёбра ответа и отсеянные рёбра по видам и по источнику решения (source_type).
2. Список риска A: рёбра ответа, включённые только достижимостью в скелете (SKELETON),
   сгруппированные по вызывающему методу. Условий на этих рёбрах движок не проверял.
3. Список риска B: рёбра, отсеянные эвристиками rules.py, со строкой сработавшего правила.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.pipeline import ArchonityPipeline

RELATIONS = ("executes", "calls", "remote", "data")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Журнал решений по рёбрам сценария")
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=["S2", "S3"],
        help="Идентификаторы сценариев (по умолчанию S2, S3)",
    )
    parser.add_argument(
        "--skeleton",
        type=Path,
        default=ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz",
        help="Путь к trainticket.json.gz",
    )
    parser.add_argument(
        "--ir",
        type=Path,
        default=ROOT / "data" / "pool_ir.json",
        help="Путь к pool_ir.json",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Сколько вызывающих методов показать в списке риска A",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Опциональный путь для сохранения отчета в JSON",
    )
    return parser.parse_args()


def load_scenario(scen_id: str) -> dict[str, Any]:
    path = ROOT / "hackaton" / "tt-challenge" / "scenarios" / f"{scen_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Сценарий {scen_id} не найден: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def short(node: str) -> str:
    """Короткое имя: Класс#метод для методов, имя таблицы для таблиц."""
    if node.startswith("res:table:"):
        return node.split(":", 2)[2]
    if "#" in node:
        cls = node.split("#")[0].split(".")[-1]
        return f"{cls}#{node.split('#')[1].split('(')[0]}"
    return node


def analyze(pipeline: ArchonityPipeline, scenario_dict: dict[str, Any]) -> dict[str, Any]:
    sid = scenario_dict["id"]
    methods, calls, remote, data = pipeline.run_scenario(scenario_dict)
    ledger = pipeline.ledger

    # Инвариант: журнал описывает ровно ответ сценария
    answer = {("executes", f"scenario:{sid}", m) for m in methods}
    answer |= {("calls", s, t) for s, t in calls}
    answer |= {("remote", s, t) for s, t in remote}
    answer |= {("data", s, t) for s, t in data}
    in_ledger = ledger.final_edges(sid)
    if in_ledger != answer:
        raise RuntimeError(
            f"{sid}: журнал расходится с ответом: {len(in_ledger - answer)} лишних, {len(answer - in_ledger)} пропущено"
        )

    entries = ledger.scenario_dict(sid)
    pool_ir = pipeline.index.pool_ir

    summary: Counter[tuple[str, str, str]] = Counter()
    by_caller: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rule_pruned: list[dict[str, Any]] = []
    for key, e in entries.items():
        relation, source, target = key.split("|", 2)
        summary[("included" if e["included"] else "pruned", relation, e["source_type"])] += 1
        if e["included"] and e["source_type"] == "SKELETON" and relation != "executes":
            by_caller[source].append({"relation": relation, "target": target, "steps": e["steps"]})
        if not e["included"] and e["source_type"] == "DEFAULT_RULE":
            rule_pruned.append({"relation": relation, "source": source, "target": target, "rule": e["rule"]})

    risk_a = [
        {
            "caller": caller,
            "in_pool": pool_ir.has_method(caller),
            "edges": sorted(items, key=lambda x: (x["relation"], x["target"])),
        }
        for caller, items in sorted(by_caller.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    return {
        "scenario_id": sid,
        "summary": {"|".join(k): v for k, v in sorted(summary.items())},
        "risk_skeleton_included": risk_a,
        "risk_rule_pruned": sorted(rule_pruned, key=lambda x: (x["rule"], x["source"], x["target"])),
    }


def print_report(res: dict[str, Any], top: int) -> None:
    sid = res["scenario_id"]
    summary = {tuple(k.split("|")): v for k, v in res["summary"].items()}
    source_types = sorted({k[2] for k in summary})

    print("\n" + "=" * 78)
    print(f"ЖУРНАЛ РЕШЕНИЙ: {sid}  (журнал совпадает с ответом сценария)")
    print("=" * 78)
    header = f"{'':<10}{'':<10}" + "".join(f"{st:>15}" for st in source_types)
    print(header)
    for status in ("included", "pruned"):
        for rel in RELATIONS:
            row = [summary.get((status, rel, st), 0) for st in source_types]
            if any(row):
                label = "в ответе" if status == "included" else "отсеяно"
                print(f"{label:<10}{rel:<10}" + "".join(f"{n:>15}" for n in row))

    risk_a = res["risk_skeleton_included"]
    total_a = sum(len(r["edges"]) for r in risk_a)
    print(f"\n[РИСК A] {total_a} рёбер ответа включены только достижимостью скелета ({len(risk_a)} методов).")
    print("         [IR] — метод в пуле, но ни одно правило не решило его ветки.\n")
    for r in risk_a[:top]:
        mark = "[IR]" if r["in_pool"] else "    "
        print(f"  {mark} {short(r['caller'])} ({len(r['edges'])}):")
        for e in r["edges"][:6]:
            print(f"         {e['relation']:<7} -> {short(e['target'])}  шаги {e['steps']}")
        if len(r["edges"]) > 6:
            print(f"         ... и ещё {len(r['edges']) - 6}")
    if len(risk_a) > top:
        print(f"  ... и ещё {len(risk_a) - top} методов (--top, -o)")

    risk_b = res["risk_rule_pruned"]
    print(f"\n[РИСК B] {len(risk_b)} рёбер отсеяны эвристиками rules.py:\n")
    for e in risk_b:
        print(f"  {e['rule']:<14} {e['relation']:<7} {short(e['source'])} -> {short(e['target'])}")


def main() -> int:
    args = parse_args()
    pipeline = ArchonityPipeline(
        skeleton_path=args.skeleton,
        targets_root=ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket",
        ir_path=args.ir,
    )

    results = {}
    for sid in args.scenarios:
        res = analyze(pipeline, load_scenario(sid))
        print_report(res, args.top)
        results[sid] = res

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\nОтчёт сохранён в {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
