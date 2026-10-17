#!/usr/bin/env python3
"""run_eval.py — Единый CLI-раннер пайплайна Archonity и локальной оценки IoU.

Использование:
    uv run python run_eval.py
    uv run python run_eval.py --gold hackaton/tt-challenge/gold/S0.json -o output/submission.json
"""
from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
from pathlib import Path

# Добавляем корень проекта в путь поиска модулей
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from engine.pipeline import ArchonityPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Archonity: генерация submission.json и расчет метрики IoU",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--skeleton",
        type=Path,
        default=ROOT_DIR / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz",
        help="Путь к графу-скелету",
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=ROOT_DIR / "hackaton" / "tt-challenge" / "targets" / "trainticket",
        help="Корень исходников проекта (targets/trainticket)",
    )
    parser.add_argument(
        "--scenarios",
        nargs="*",
        default=None,
        help="Файлы сценариев (по умолчанию hackaton/tt-challenge/scenarios/*.json)",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=ROOT_DIR / "hackaton" / "tt-challenge" / "gold" / "S0.json",
        help="Путь к эталону gold/S0.json для локальной оценки",
    )
    parser.add_argument(
        "-o", "--out",
        type=Path,
        default=ROOT_DIR / "output" / "submission.json",
        help="Путь для сохранения итогового submission.json",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=ROOT_DIR / "data" / "runtime_and_topology_rules.json",
        help="Путь к файлу правил отсева мертвого кода",
    )
    parser.add_argument(
        "--reparse",
        action="store_true",
        help="Принудительный перезапуск archparse gradle перед прогоном",
    )
    parser.add_argument(
        "--no-eval",
        action="store_true",
        help="Пропустить автоматический вызов evaluate_golden.py",
    )
    parser.add_argument(
        "--grounder",
        choices=("legacy", "m1"),
        default="legacy",
        help="Заземление шагов: legacy (engine/resolver.py) или m1 (engine/grounding, ADR-005)",
    )
    parser.add_argument("--no-llm", action="store_true", help="M1 без LLM: первый кандидат")
    parser.add_argument("--no-server", action="store_true", help="M1: ответы LLM только из кеша")
    parser.add_argument("--no-cache", action="store_true", help="M1: пересчитать ответы LLM")
    parser.add_argument("--no-embed", action="store_true", help="M1 без dense-ретривера (только BM25)")
    return parser.parse_args()


def resolve_scenario_paths(args_scenarios: list[str] | None) -> list[Path]:
    if args_scenarios:
        paths: list[Path] = []
        for s in args_scenarios:
            for p in glob.glob(s):
                paths.append(Path(p))
        return sorted(paths, key=lambda x: x.name)

    default_pattern = str(ROOT_DIR / "hackaton" / "tt-challenge" / "scenarios" / "*.json")
    return [Path(p) for p in sorted(glob.glob(default_pattern), key=lambda x: Path(x).name)]


def print_evaluation_summary(eval_res: dict) -> None:
    score = eval_res.get("score", 0.0)
    print("\n" + "=" * 65)
    print(f"📊 РЕЗУЛЬТАТЫ ОЦЕНКИ (evaluate_golden.py): ИТОГОВЫЙ СКОР: {score:.4f}")
    print("=" * 65)

    scenarios = eval_res.get("scenarios", {})
    if "S0" in scenarios:
        s0 = scenarios["S0"]
        sets = s0.get("sets", {})
        print(f"\nДетализация калибровочного сценария S0 (балл: {s0.get('score', 0.0):.4f}):")
        print(f"{'Связь':<12} | {'IoU':<8} | {'Precision':<10} | {'Recall':<8} | {'TP':<5} | {'Pred':<5} | {'Gold':<5}")
        print("-" * 65)
        for rel in ("executes", "calls", "remote", "data"):
            data = sets.get(rel, {})
            iou = data.get("iou", 0.0)
            prec = data.get("precision", 0.0)
            rec = data.get("recall", 0.0)
            tp = data.get("tp", 0)
            pred = data.get("pred", 0)
            gold = data.get("gold", 0)
            print(f"{rel:<12} | {iou:<8.3f} | {prec:<10.3f} | {rec:<8.3f} | {tp:<5} | {pred:<5} | {gold:<5}")

    print("\nСтатус валидации формата остальных сценариев:")
    for sid, sdata in sorted(scenarios.items()):
        if sid == "S0":
            continue
        status = sdata.get("status", "unknown")
        accepted = sdata.get("accepted", 0)
        rejected = sum(sdata.get("rejected", {}).values())
        print(f"  {sid}: статус '{status}', принято рёбер: {accepted}, отклонено: {rejected}")

    if errors := eval_res.get("errors"):
        print("\nОШИБКИ:")
        for err in errors:
            print(f"  ❌ {err}")

    if warnings := eval_res.get("warnings"):
        print("\nПРЕДУПРЕЖДЕНИЯ:")
        for w in warnings:
            print(f"  ⚠️  {w}")

    print("=" * 65 + "\n")


def main() -> None:
    args = parse_args()

    scenarios = resolve_scenario_paths(args.scenarios)
    if not scenarios:
        print("Ошибка: не найдено ни одного файла сценариев!", file=sys.stderr)
        sys.exit(1)

    print(f"Archonity Pipeline Runner")
    print(f"Скелет:     {args.skeleton}")
    print(f"Исходники:  {args.targets}")
    print(f"Сценариев:  {len(scenarios)} ({', '.join(s.stem for s in scenarios)})")
    print(f"Выход:      {args.out}")
    print(f"Правила:    {args.rules}")
    print("-" * 60)

    # 0. Подготовка AST IR тел методов (archparse)
    from engine.ir import ensure_pool_ir

    pool_ir_path = ensure_pool_ir(reparse=args.reparse, project_root=ROOT_DIR)
    print(f"AST IR:     {pool_ir_path}")

    # Запуск пайплайна
    m1_options = None
    if args.grounder == "m1":
        from engine.grounding.llm import LLMClient

        m1_options = {
            "embedder": None if args.no_embed else "qwen3-4b",
            "llm": None if args.no_llm else LLMClient(use_server=not args.no_server, refresh=args.no_cache),
        }
    print(f"Grounder:   {args.grounder}")
    pipeline = ArchonityPipeline(
        skeleton_path=args.skeleton,
        targets_root=args.targets,
        rules_path=args.rules,
        ir_path=pool_ir_path,
        grounder=args.grounder,
        m1_options=m1_options,
    )

    print("Генерация графов для сценариев...")
    adapter = pipeline.run_all(scenarios, output_path=args.out)
    print(f"Сабмишн успешно сохранен в: {args.out}")

    canonical_out = args.out.parent / "canonical_graph.json"
    adapter.save_canonical_graph(canonical_out)
    print(f"Канонический граф для visualizer/ сохранен в: {canonical_out}")

    evidence_out = args.out.parent / "evidence.json"
    adapter.save_evidence_log(evidence_out)
    print(f"Evidence Log сохранен в: {evidence_out}")

    if args.grounder == "m1":
        steps_out = args.out.parent / "step_requests.json"
        with open(steps_out, "w", encoding="utf-8") as f:
            json.dump(pipeline.step_requests, f, ensure_ascii=False, indent=1)
        print(f"StepRequest (M1) сохранены в: {steps_out}")

    decisions_out = args.out.parent / "decisions.json"
    with open(decisions_out, "w", encoding="utf-8") as f:
        json.dump(pipeline.ledger.to_dict(), f, ensure_ascii=False, indent=1)
    print(f"Журнал решений (evidence v2) сохранен в: {decisions_out}")

    # Синхронизация с visualizer/public/data/
    vis_data_dir = ROOT_DIR / "visualizer" / "public" / "data"
    if vis_data_dir.is_dir():
        import shutil
        shutil.copy(canonical_out, vis_data_dir / "canonical_graph.json")
        shutil.copy(evidence_out, vis_data_dir / "evidence.json")
        shutil.copy(args.out, vis_data_dir / "submission.json")
        print(f"Файлы синхронизированы с {vis_data_dir}")

    # Оценка через evaluate_golden.py
    if not args.no_eval and args.gold.is_file():
        eval_script = ROOT_DIR / "hackaton" / "tt-challenge" / "platform" / "evaluate_golden.py"
        if eval_script.is_file():
            print("\nЗапуск официального валидатора evaluate_golden.py...")
            cmd = [
                sys.executable,
                str(eval_script),
                str(args.gold),
                str(args.out),
                "--json",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode in (0, 3):
                try:
                    eval_data = json.loads(res.stdout)
                    print_evaluation_summary(eval_data)
                except json.JSONDecodeError:
                    print(res.stdout)
            else:
                print("Ошибка при запуске evaluate_golden.py:", file=sys.stderr)
                print(res.stderr, file=sys.stderr)
                print(res.stdout)


if __name__ == "__main__":
    main()
