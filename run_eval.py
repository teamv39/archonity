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
        "--entity-ctors",
        choices=("body", "project_calls", "off"),
        default="project_calls",
        help="Режим правила R7 (конструкторы сущностей при загрузке из БД): project_calls — только конструкторы "
             "с вызовом проектного метода (по умолчанию), body — любое непустое тело (опровергнуто платформой), off — выключено",
    )
    parser.add_argument(
        "--collection-tables",
        choices=("loaded", "all"),
        default="loaded",
        help="Таблицы ленивых коллекций при чтении (R10): loaded — только коллекции, которые метод загрузил сам "
             "(по умолчанию), all — все таблицы data_access исполненного вызова (поведение до 17.10)",
    )
    parser.add_argument(
        "--element-callbacks",
        choices=("on", "off"),
        default="on",
        help="equals сущности из list.contains(x) на результате чтения (блок 8): on — исполняется, если чтение "
             "вернуло строки (по умолчанию), off — не учитывать (поведение до 17.10)",
    )
    parser.add_argument(
        "--rabbitmq-delivery",
        choices=("on", "off"),
        default="on",
        help="Асинхронная доставка RabbitMQ (правило R13): on — учитывать межсервисное ребро к потребителю (по умолчанию), off — абляция (исключить потребителя)",
    )
    parser.add_argument(
        "--station-food-collection",
        choices=("store_browse_only", "store_only", "step4_store_only", "all", "off"),
        default="store_browse_only",
        help="Таблица коллекции блюд station_food_list: store_browse_only — при просмотре каталога магазинов только магазины (по умолчанию), all — учитывать везде, off — исключить везде",
    )
    parser.add_argument(
        "--probe-orders-data",
        choices=("on", "off"),
        default="on",
        help="Зондирующий SELECT в S2 (шаги 9 и 10 к ts-order-service.orders): on — учитывать (по умолчанию), off — абляция (исключить)",
    )
    parser.add_argument(
        "--enum-member-calls",
        choices=("on", "off"),
        default="on",
        help="Вызовы методов перечисления AssuranceType (Гипотеза 3.1): on — учитывать вызовы геттеров перечисления в getAllAssuranceTypes (по умолчанию), off — абляция (исключить на шаге 15 в S3)",
    )
    parser.add_argument(
        "--trip-food-query",
        choices=("cascade", "direct_train_food"),
        default="cascade",
        help="Режим запроса еды поездки в getAllFood (Гипотеза 1.1 / 4.1): cascade — опрашивать станционную еду (по умолчанию), direct_train_food — абляция (только поездное меню в S1/S4)",
    )
    parser.add_argument(
        "--route-distances-collection",
        choices=("pruned", "included"),
        default="pruned",
        help="Таблица коллекции route_distances (Гипотеза 5.1): pruned — отсекать при getRouteByStartAndEnd (по умолчанию), included — абляция (включать в S5)",
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
        default="m1",
        help="Заземление шагов: m1 (engine/grounding, ADR-005; ответы LLM из cache/, без сервера — только кеш) "
             "или legacy (engine/resolver.py)",
    )
    parser.add_argument(
        "--executor",
        choices=("legacy", "ir", "m4"),
        default="legacy",
        help="Исполнитель шага: legacy — обход скелета с правилами (по умолчанию), ir (синоним m4) — M4 по IR тел "
             "методов data/ir (ADR-005, трёхзначная логика, мир БД сценария); требует --grounder m1",
    )
    parser.add_argument(
        "--m4-unresolved-calls",
        choices=("mute", "emit"),
        default="mute",
        help="M4: метод проекта на получателе известного типа без ребра в скелете (TripId#toString): mute — только "
             "значение, emit — писать рёбра calls/executes (подтверждено платформой: 0.93625)",
    )
    parser.add_argument(
        "--m4-success-retry",
        choices=("on", "off"),
        default="on",
        help="M4: шаг ожидает успех, а по значениям M1 отказал — повтор с нормализованными, затем неизвестными "
             "строковыми параметрами (on по умолчанию)",
    )
    parser.add_argument("--no-llm", action="store_true", help="M1 без LLM: первый кандидат")
    parser.add_argument("--no-server", action="store_true", help="M1: ответы LLM только из кеша")
    parser.add_argument("--no-cache", action="store_true", help="M1: пересчитать ответы LLM")
    parser.add_argument("--no-embed", action="store_true", help="M1 без dense-ретривера (только BM25)")
    parser.add_argument(
        "--judge",
        choices=("on", "cache", "off"),
        default="off",
        help="Судья M4 для условий UNKNOWN, где иначе исполнились бы оба плеча: on — кеш, на промахе сервер; "
             "cache — только кеш; off — без судьи (по умолчанию)",
    )
    parser.add_argument("--judge-budget", type=int, default=400, help="M4: вызовов сервера судьи на прогон")
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


def print_m4_stats(stats: dict) -> None:
    """Счётчики M4: плоские значения в строку, вложенные словари построчно с отступом."""
    print("Статистика M4:")
    for key, value in stats.items():
        if isinstance(value, dict):
            print(f"  {key}:")
            for k, v in value.items():
                print(f"    {k}: {v}")
        else:
            print(f"  {key}: {value}")


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

    if args.executor == "m4" and args.grounder != "m1":
        print("Ошибка: --executor m4 требует --grounder m1 (нужны params и expected_outcome из StepRequest)",
              file=sys.stderr)
        sys.exit(2)

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
    if args.executor == "m4":
        args.executor = "ir"
    print(f"Executor:   {args.executor}")
    pipeline = ArchonityPipeline(
        skeleton_path=args.skeleton,
        targets_root=args.targets,
        rules_path=args.rules,
        ir_path=pool_ir_path,
        entity_constructors_on_load=args.entity_ctors,
        collection_tables_on_read=args.collection_tables,
        element_callbacks=args.element_callbacks,
        rabbitmq_delivery=args.rabbitmq_delivery,
        station_food_collection=args.station_food_collection,
        probe_orders_data=args.probe_orders_data,
        enum_member_calls=args.enum_member_calls,
        trip_food_query=args.trip_food_query,
        route_distances_collection=args.route_distances_collection,
        grounder=args.grounder,
        m1_options=m1_options,
        executor=args.executor,
        unresolved_receiver_calls=args.m4_unresolved_calls,
        m4_success_retry=args.m4_success_retry,
        m4_judge=args.judge,
        m4_judge_budget=args.judge_budget,
    )

    print("Генерация графов для сценариев...")
    adapter = pipeline.run_all(scenarios, output_path=args.out)
    print(f"Сабмишн успешно сохранен в: {args.out}")
    if pipeline.m4 is not None:
        print_m4_stats(pipeline.m4.stats())

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

    if pipeline.m4 is not None:
        unknowns_out = args.out.parent / "m4_unknowns.json"
        with open(unknowns_out, "w", encoding="utf-8") as f:
            json.dump(pipeline.m4.unknowns, f, ensure_ascii=False, indent=1)
        print(f"Условия UNKNOWN исполнителя M4 сохранены в: {unknowns_out}")

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
