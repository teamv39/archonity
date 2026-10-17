#!/usr/bin/env python3
"""scripts/decision_log.py — Журнал решений для сценариев (Блок 0 плана archparse).

Для каждого исполняемого метода сценария (S2, S3 и др.) берёт исходящие рёбра
скелета и показывает, что решило судьбу каждого ребра:
1. IR (AST Guard из pool_ir.json) -> активно / отсечено по условию AST
2. RULE (эвристики rules.py) -> отсечено правилом (образует список риска)
3. DEFAULT -> включено по умолчанию обходом скелета или отсечено по умолчанию
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# Корень проекта
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.adapters.skeleton import SkeletonIndex
from engine.pipeline import ArchonityPipeline
from engine.rules import RuntimeRules, ScenarioProfile
from engine.state import ScenarioState


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
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Опциональный путь для сохранения отчета в JSON",
    )
    return parser.parse_args()


def load_scenario(scen_id: str) -> dict[str, Any]:
    candidates = [
        ROOT / "hackaton" / "tt-challenge" / "scenarios" / f"{scen_id}.json",
        ROOT / "hackaton" / "tt-challenge" / "scenarios" / f"{scen_id.lower()}.json",
    ]
    for c in candidates:
        if c.is_file():
            with open(c, "r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(f"Сценарий {scen_id} не найден.")


def analyze_scenario_decisions(
    pipeline: ArchonityPipeline,
    scenario_dict: dict[str, Any],
) -> dict[str, Any]:
    sid = scenario_dict.get("id", "S?")
    profile = ScenarioProfile.from_scenario(scenario_dict)
    index: SkeletonIndex = pipeline.index
    rules: RuntimeRules = pipeline.rules

    # 1. Запуск пайплайна для получения реально исполненных методов и связей
    methods, pred_calls, pred_remote, pred_data = pipeline.run_scenario(scenario_dict)

    pool_ir = getattr(index, "pool_ir", None)
    edge_guards = getattr(index, "edge_guards", {})

    decisions_by_cat = {
        "IR_PASS": [],
        "IR_PRUNED": [],
        "RULE_PRUNED": [],
        "DEFAULT_INCLUDED": [],
        "DEFAULT_PRUNED": [],
    }

    # Анализируем каждый выполненный метод
    for m in sorted(methods):
        u = index.unit_of(m)
        is_in_pool = pool_ir.has_method(m) if pool_ir else False

        # --- A. Calls (внутрисервисные) ---
        for t in index.calls.get(m, ()):
            dispatch_targets = (
                {t}
                | index.cha(t)
                | index.wiring["runtime_dispatch"].get(m, set())
            )
            for x in dispatch_targets:
                if index.N.get(x, {}).get("abstract"):
                    decisions_by_cat["DEFAULT_PRUNED"].append({
                        "caller": m, "type": "calls", "target": x,
                        "decider": "DEFAULT_ABSTRACT", "status": "PRUNED",
                    })
                    continue

                target_mod = index.module.get(x, "")
                if u not in index.units.get(target_mod, ()):
                    decisions_by_cat["DEFAULT_PRUNED"].append({
                        "caller": m, "type": "calls", "target": x,
                        "decider": "CROSS_UNIT", "status": "PRUNED",
                    })
                    continue

                # 1. Проверяем IR Guard
                guards = edge_guards.get((m, "calls", x)) or edge_guards.get((m, "calls", t))
                if guards and pool_ir:
                    passes = any(pool_ir.evaluate_guard(m, g, profile) for g in guards)
                    if not passes:
                        decisions_by_cat["IR_PRUNED"].append({
                            "caller": m, "type": "calls", "target": x,
                            "decider": "IR_GUARD", "status": "PRUNED",
                            "guards": [list(g) for g in guards],
                        })
                        continue
                    else:
                        # Guard пройден, но может ли еще отфильтровать rule?
                        if rules.is_dead_code_method(x, profile=profile) or rules.is_dead_code_edge(m, "calls", x, profile=profile):
                            decisions_by_cat["RULE_PRUNED"].append({
                                "caller": m, "type": "calls", "target": x,
                                "decider": "RULE_OVERRIDE_IR", "status": "PRUNED",
                            })
                            continue
                        decisions_by_cat["IR_PASS"].append({
                            "caller": m, "type": "calls", "target": x,
                            "decider": "IR_GUARD", "status": "INCLUDED",
                            "guards": [list(g) for g in guards],
                        })
                        continue

                # 2. Если нет IR guard, проверяем эвристические правила rules.py
                if rules.is_dead_code_method(x, profile=profile):
                    decisions_by_cat["RULE_PRUNED"].append({
                        "caller": m, "type": "calls", "target": x,
                        "decider": "RULE_METHOD", "status": "PRUNED",
                        "rule_reason": f"is_dead_code_method({x})",
                    })
                    continue

                if rules.is_dead_code_edge(m, "calls", x, profile=profile):
                    decisions_by_cat["RULE_PRUNED"].append({
                        "caller": m, "type": "calls", "target": x,
                        "decider": "RULE_EDGE", "status": "PRUNED",
                        "rule_reason": f"is_dead_code_edge({m} -> {x})",
                    })
                    continue

                if "Exception#<init>" in x:
                    decisions_by_cat["DEFAULT_PRUNED"].append({
                        "caller": m, "type": "calls", "target": x,
                        "decider": "DEFAULT_EXCEPTION", "status": "PRUNED",
                    })
                    continue

                decisions_by_cat["DEFAULT_INCLUDED"].append({
                    "caller": m, "type": "calls", "target": x,
                    "decider": "DEFAULT_REACHABILITY", "status": "INCLUDED",
                })

        # --- B. Remote (межсервисные) ---
        remote_targets = (
            index.wiring["remote_call"].get(m, set())
            | index.wiring["message_delivery"].get(m, set())
        )
        for t in remote_targets:
            guards = (
                edge_guards.get((m, "remote_call", t))
                or edge_guards.get((m, "message_delivery", t))
            )
            if guards and pool_ir:
                passes = any(pool_ir.evaluate_guard(m, g, profile) for g in guards)
                if not passes:
                    decisions_by_cat["IR_PRUNED"].append({
                        "caller": m, "type": "remote", "target": t,
                        "decider": "IR_GUARD", "status": "PRUNED",
                        "guards": [list(g) for g in guards],
                    })
                    continue
                else:
                    if rules.is_dead_code_method(t, profile=profile) or rules.is_dead_code_edge(m, "remote", t, profile=profile):
                        decisions_by_cat["RULE_PRUNED"].append({
                            "caller": m, "type": "remote", "target": t,
                            "decider": "RULE_OVERRIDE_IR", "status": "PRUNED",
                        })
                        continue
                    decisions_by_cat["IR_PASS"].append({
                        "caller": m, "type": "remote", "target": t,
                        "decider": "IR_GUARD", "status": "INCLUDED",
                        "guards": [list(g) for g in guards],
                    })
                    continue

            if rules.is_dead_code_method(t, profile=profile):
                decisions_by_cat["RULE_PRUNED"].append({
                    "caller": m, "type": "remote", "target": t,
                    "decider": "RULE_METHOD", "status": "PRUNED",
                    "rule_reason": f"is_dead_code_method({t})",
                })
                continue

            if rules.is_dead_code_edge(m, "remote", t, profile=profile):
                decisions_by_cat["RULE_PRUNED"].append({
                    "caller": m, "type": "remote", "target": t,
                    "decider": "RULE_EDGE", "status": "PRUNED",
                    "rule_reason": f"is_dead_code_edge({m} -> {t})",
                })
                continue

            decisions_by_cat["DEFAULT_INCLUDED"].append({
                "caller": m, "type": "remote", "target": t,
                "decider": "DEFAULT_REACHABILITY", "status": "INCLUDED",
            })

        # --- C. Data (база данных) ---
        for tbl in index.wiring["data_access"].get(m, set()):
            guards = edge_guards.get((m, "data_access", tbl))
            if guards and pool_ir:
                passes = any(pool_ir.evaluate_guard(m, g, profile) for g in guards)
                if not passes:
                    decisions_by_cat["IR_PRUNED"].append({
                        "caller": m, "type": "data", "target": tbl,
                        "decider": "IR_GUARD", "status": "PRUNED",
                        "guards": [list(g) for g in guards],
                    })
                    continue
                else:
                    if rules.is_dead_code_edge(m, "data", tbl, profile=profile):
                        decisions_by_cat["RULE_PRUNED"].append({
                            "caller": m, "type": "data", "target": tbl,
                            "decider": "RULE_OVERRIDE_IR", "status": "PRUNED",
                        })
                        continue
                    decisions_by_cat["IR_PASS"].append({
                        "caller": m, "type": "data", "target": tbl,
                        "decider": "IR_GUARD", "status": "INCLUDED",
                        "guards": [list(g) for g in guards],
                    })
                    continue

            if rules.is_dead_code_edge(m, "data", tbl, profile=profile):
                decisions_by_cat["RULE_PRUNED"].append({
                    "caller": m, "type": "data", "target": tbl,
                    "decider": "RULE_EDGE", "status": "PRUNED",
                    "rule_reason": f"is_dead_code_edge({m} -> {tbl})",
                })
                continue

            decisions_by_cat["DEFAULT_INCLUDED"].append({
                "caller": m, "type": "data", "target": tbl,
                "decider": "DEFAULT_REACHABILITY", "status": "INCLUDED",
            })

    return {
        "scenario_id": sid,
        "executed_methods_count": len(methods),
        "in_pool_methods_count": sum(1 for m in methods if pool_ir and pool_ir.has_method(m)),
        "summary": {cat: len(items) for cat, items in decisions_by_cat.items()},
        "risk_list": decisions_by_cat["RULE_PRUNED"],
        "decisions": decisions_by_cat,
    }


def print_report(res: dict[str, Any]) -> None:
    sid = res["scenario_id"]
    summary = res["summary"]
    total = sum(summary.values())
    risk = res["risk_list"]

    print("\n" + "=" * 70)
    print(f"ЖУРНАЛ РЕШЕНИЙ ДЛЯ СЦЕНАРИЯ {sid}")
    print(f"Исполненных методов: {res['executed_methods_count']} (в IR-пуле: {res['in_pool_methods_count']})")
    print(f"Всего проверенных исходящих рёбер скелета: {total}")
    print("-" * 70)
    print(f"  IR_PASS (включено по AST Guard):           {summary.get('IR_PASS', 0):>4}")
    print(f"  IR_PRUNED (отсечено по AST Guard):         {summary.get('IR_PRUNED', 0):>4}")
    print(f"  RULE_PRUNED [РИСК] (отсечено rules.py):     {summary.get('RULE_PRUNED', 0):>4}")
    print(f"  DEFAULT_INCLUDED (включено по умолчанию):   {summary.get('DEFAULT_INCLUDED', 0):>4}")
    print(f"  DEFAULT_PRUNED (служебное отсечение):      {summary.get('DEFAULT_PRUNED', 0):>4}")
    print("=" * 70)

    print(f"\n[СПИСОК РИСКА]: {len(risk)} рёбер, судьбу которых решили эвристики rules.py (не AST IR):\n")
    # Группируем по вызывающему классу/методу для наглядности
    by_caller = defaultdict(list)
    for r in risk:
        by_caller[r["caller"]].append(r)

    for caller, items in sorted(by_caller.items(), key=lambda kv: len(kv[1]), reverse=True):
        short_caller = caller.replace("method:", "").split("#")[0].split(":")[-1] + "#" + caller.split("#")[-1].split("(")[0]
        print(f"  Caller: {short_caller} ({len(items)} рёбер):")
        for item in items[:6]:
            tgt = item["target"].replace("method:", "").split("#")[0].split(":")[-1] + "#" + item["target"].split("#")[-1].split("(")[0] if "method:" in item["target"] else item["target"]
            print(f"    - [{item['type']}] -> {tgt} ({item.get('rule_reason', item['decider'])})")
        if len(items) > 6:
            print(f"    ... и ещё {len(items) - 6} рёбер")


def main() -> int:
    args = parse_args()
    print("Инициализация SkeletonIndex и ArchonityPipeline...")
    targets_root = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"
    pipeline = ArchonityPipeline(
        skeleton_path=args.skeleton,
        targets_root=targets_root,
        ir_path=args.ir,
    )

    all_results = {}
    for sid in args.scenarios:
        scen_dict = load_scenario(sid)
        res = analyze_scenario_decisions(pipeline, scen_dict)
        print_report(res)
        all_results[sid] = res

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Убираем огромные дампы для чистоты
        clean_out = {
            sid: {
                "scenario_id": r["scenario_id"],
                "executed_methods_count": r["executed_methods_count"],
                "in_pool_methods_count": r["in_pool_methods_count"],
                "summary": r["summary"],
                "risk_list": r["risk_list"],
            }
            for sid, r in all_results.items()
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(clean_out, f, indent=2, ensure_ascii=False)
        print(f"\nОтчёт сохранён в {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
