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
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

# Добавляем корень проекта в путь поиска модулей
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from engine import attention  # только стандартная библиотека: рамка Р2 работает, даже если конвейер не импортируется
from engine.artifacts import ArtifactMismatch  # тоже только стандартная библиотека

if TYPE_CHECKING:
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
        "--artifacts-dir",
        type=Path,
        default=ROOT_DIR / "data",
        help="Артефакты проекта: ir/ (IR тел методов), entity_ir.json (archparse), ui_catalog.json (кеш каталога UI, "
             "создаётся сам). Для другого проекта — отдельная папка: data/ не трогается",
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
        "--ctors",
        choices=("all", "caller_only", "off"),
        default="caller_only",
        help="Видимость конструкторов (R7, ADR-006): caller_only — конструктор в ответе, только если из него исполнился "
             "вызов проекта, рёбер calls в конструктор нет (по умолчанию, посылка 10); all — как до ADR-006 "
             "(new — всегда, загрузка Hibernate — с вызовом проекта в теле); off — без конструкторов (отладка)",
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
        "--jackson-ctor",
        choices=("on", "off"),
        default="on",
        help="M4, R7: Jackson создаёт тело запроса рукописным конструктором без аргументов (RebookInfo вызывает "
             "Date2String); on — конструктор исполняется, в ответ его пропускает проекция R7 (по умолчанию), off — нет",
    )
    parser.add_argument(
        "--lombok-tostring",
        choices=("on", "off"),
        default="on",
        help="M4, R5: аргумент SLF4J info/warn/error по шаблону с {} форматируется Lombok-toString, рукописные "
             "геттеры полей исполняются (TravelResult#isStatus); on (по умолчанию) или off",
    )
    parser.add_argument(
        "--unbound-handlers",
        choices=("rebind", "keep"),
        default="rebind",
        help="R20: M1 выбрал обработчик, который Spring вызвать не может (@PathVariable не совпадает с шаблоном "
             "пути, getFoodStoresOfStation): rebind — шаг через рабочий обработчик того же контроллера с тем же "
             "входом (по умолчанию, посылка 27: 1.00000), keep — как выбрал M1",
    )
    parser.add_argument(
        "--engine",
        choices=("python", "rust"),
        default="python",
        help="Исполнение шагов (ADR-008): python — весь конвейер в Python (умолчание, рекорд); rust — M1 в Python, "
             "дальше M4, правила и запись выдачи в бинарнике archonity-exec. Без отката: нет бинарника или он "
             "упал — пустая выдача и рамка Р2",
    )
    parser.add_argument(
        "--rust-bin",
        type=Path,
        default=ROOT_DIR / "rust" / "target" / "release" / "archonity-exec",
        help="Бинарник archonity-exec (сборка: cd rust && cargo build --release --locked)",
    )
    parser.add_argument(
        "--no-eval",
        action="store_true",
        help="Пропустить автоматический вызов evaluate_golden.py",
    )
    parser.add_argument(
        "--m4-unresolved-calls",
        choices=("mute", "emit"),
        default="emit",
        help="M4: метод проекта на получателе известного типа без ребра в скелете (TripId#toString): emit — писать "
             "рёбра calls/executes (по умолчанию, подтверждено платформой: 0.93625), mute — только значение",
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
    parser.add_argument(
        "--require-cache",
        action="store_true",
        help="M1: только кеш (как --no-server); код выхода 2, если хоть одного ответа LLM нет в cache/llm — "
             "выдача тогда построена не моделью (m1_report.json, README «Проверка без кеша»)",
    )
    parser.add_argument("--no-embed", action="store_true", help="M1 без dense-ретривера (только BM25)")
    parser.add_argument("--embed-model", choices=("on", "off"), default="on",
                        help="M1: на промахе кеша векторов (новые сценарии) загрузить эмбеддер из models/ "
                             "(on, по умолчанию; S1–S7 берут векторы из cache/emb) или работать на одном BM25 (off). "
                             "С --require-cache модель не грузится")
    # Режим CPU (исследование GPU, раздел 7.5): сервер LLM без видеокарты отвечает минутами, а не секундами
    parser.add_argument("--llm-timeout", type=float, default=300,
                        help="M1: таймаут одного вызова сервера LLM, с (на CPU вызов выбора — 2–7 минут)")
    parser.add_argument("--select-votes", type=int, default=5,
                        help="M1 v8: выборок голосования сверх жадного ответа (0 — только жадный, в 6 раз меньше "
                             "вызовов выбора; рекорд — 5)")
    parser.add_argument("--m1-top-k", type=int, default=10, help="M1: кандидатов поиска в промпте выбора")
    parser.add_argument("--m1-index", choices=("on", "off"), default="on",
                        help="M1 v8: индекс всех обработчиков в системном промпте выбора; off — выбор только из "
                             "кандидатов, контекст ~3 тыс. токенов вместо ~10 (на CPU ответ быстрее в разы)")
    parser.add_argument("--select-reasoning", choices=("on", "off"), default="on",
                        help="M1 v8: рассуждение в ответе выбора; off — ответ вдвое короче")
    parser.add_argument("--llm-cache", type=Path, default=None,
                        help="M1: папка кеша ответов LLM (по умолчанию cache/llm); для прогона другой модели")
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


def build_pipeline(args: argparse.Namespace, m1_options: dict) -> ArchonityPipeline:
    from engine.pipeline import ArchonityPipeline

    return ArchonityPipeline(
        skeleton_path=args.skeleton,
        targets_root=args.targets,
        artifacts_dir=args.artifacts_dir,
        constructors=args.ctors,
        collection_tables_on_read=args.collection_tables,
        element_callbacks=args.element_callbacks,
        rabbitmq_delivery=args.rabbitmq_delivery,
        jackson_ctor=args.jackson_ctor,
        lombok_tostring=args.lombok_tostring,
        unbound_handlers=args.unbound_handlers,
        m1_options=m1_options,
        unresolved_receiver_calls=args.m4_unresolved_calls,
        m4_success_retry=args.m4_success_retry,
        build_m4=args.engine == "python",
    )


def write_empty_submission(scenarios: list[Path], out: Path) -> None:
    """Последний рубеж Р2: конвейер не собрался — блок `{"edges": []}` на каждый сценарий, проект — из файлов."""
    project, ids = "", []
    for sp in scenarios:
        try:
            sc = json.loads(sp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            sc = {}
        project = project or sc.get("project", "")
        ids.append(sc.get("id") or sp.stem)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"project": project, "scenarios": {sid: {"edges": []} for sid in sorted(ids)}}, f,
                  ensure_ascii=False, indent=1)


def rust_rule_args(args: argparse.Namespace) -> list[str]:
    """Режимы правил для `archonity-exec`: имена `RuntimeRules`, значения как у флагов CLI."""
    rules = {
        "constructors": args.ctors,
        "collection_tables_on_read": args.collection_tables,
        "element_callbacks": args.element_callbacks,
        "rabbitmq_delivery": args.rabbitmq_delivery,
        "jackson_ctor": args.jackson_ctor,
        "lombok_tostring": args.lombok_tostring,
        "unbound_handlers": args.unbound_handlers,
        "unresolved_receiver_calls": args.m4_unresolved_calls,
        "m4_success_retry": args.m4_success_retry,
    }
    out: list[str] = []
    for name, value in rules.items():
        out += ["--rule", f"{name}={value}"]
    return out


def run_rust(args: argparse.Namespace, pipeline: ArchonityPipeline, scenarios: list[Path]) -> list[dict]:
    """`--engine rust` (ADR-008): M1 в Python пишет `step_requests_raw.json`, `archonity-exec` строит выдачу.
    Возвращает сбои Rust-части; исключение — если бинарник не отработал (откат на Python не делаем)."""
    raw = pipeline.ground_all(scenarios)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    raw_path = args.out.parent / "step_requests_raw.json"
    with open(raw_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(raw, f, ensure_ascii=False, indent=1)
    if not args.rust_bin.is_file():
        raise FileNotFoundError(f"нет бинарника {args.rust_bin}: cd rust && cargo build --release --locked")
    cmd = [str(args.rust_bin), "--step-requests", str(raw_path), "--skeleton", str(args.skeleton),
           "--targets", str(args.targets), "--ir-dir", str(Path(args.artifacts_dir) / "ir"),
           "--entity-ir", str(Path(args.artifacts_dir) / "entity_ir.json"),
           "--configs-topology", str(ROOT_DIR / "facts" / "configs_topology.json"),
           "-o", str(args.out), *rust_rule_args(args)]
    res = subprocess.run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"archonity-exec завершился с кодом {res.returncode}")
    failures_path = args.out.parent / "exec_failures.json"
    return json.loads(failures_path.read_text(encoding="utf-8")) if failures_path.is_file() else []


def write_artifacts(args: argparse.Namespace, pipeline: ArchonityPipeline, adapter) -> None:
    """Отчёты рядом с выдачей и синхронизация visualizer/. Выдачу не трогают: она уже записана."""
    print_m4_stats(pipeline.m4.stats())

    canonical_out = args.out.parent / "canonical_graph.json"
    adapter.save_canonical_graph(canonical_out)
    print(f"Канонический граф для visualizer/ сохранен в: {canonical_out}")

    evidence_out = args.out.parent / "evidence.json"
    adapter.save_evidence_log(evidence_out)
    print(f"Evidence Log сохранен в: {evidence_out}")

    steps_out = args.out.parent / "step_requests.json"
    with open(steps_out, "w", encoding="utf-8") as f:
        json.dump(pipeline.step_requests, f, ensure_ascii=False, indent=1)
    print(f"StepRequest (M1) сохранены в: {steps_out}")

    unknowns_out = args.out.parent / "m4_unknowns.json"
    with open(unknowns_out, "w", encoding="utf-8") as f:
        json.dump(pipeline.m4.unknowns, f, ensure_ascii=False, indent=1)
    print(f"Условия UNKNOWN исполнителя M4 сохранены в: {unknowns_out}")

    decisions_out = args.out.parent / "decisions.json"
    with open(decisions_out, "w", encoding="utf-8") as f:
        json.dump(pipeline.ledger.to_dict(), f, ensure_ascii=False, indent=1)
    print(f"Журнал решений (evidence v2) сохранен в: {decisions_out}")

    # Синхронизация с visualizer/
    vis_data_dir = ROOT_DIR / "visualizer" / "public" / "data"
    if vis_data_dir.is_dir():
        try:
            from scripts.export_visualizer_data import export_all
            export_all()
        except Exception as e:
            import shutil
            shutil.copy(canonical_out, vis_data_dir / "canonical_graph.json")
            shutil.copy(evidence_out, vis_data_dir / "evidence.json")
            shutil.copy(args.out, vis_data_dir / "submission.json")
            print(f"Файлы базово синхронизированы с {vis_data_dir} (export_all: {e})")


def evaluate(args: argparse.Namespace) -> None:
    """Локальная оценка evaluate_golden.py. Он принимает только сценарии эталона (`scenarios_all`), поэтому на
    других (закрытые сценарии, eval/own) оценка пропускается, а не печатает ошибку."""
    eval_script = ROOT_DIR / "hackaton" / "tt-challenge" / "platform" / "evaluate_golden.py"
    if args.no_eval or not args.gold.is_file() or not eval_script.is_file():
        return
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    known = set(gold.get("scenarios_all") or []) | set(gold.get("scenarios") or {})
    ids = set(json.loads(args.out.read_text(encoding="utf-8")).get("scenarios") or {})
    if unknown := sorted(ids - known):
        print(f"\nЛокальная оценка пропущена: сценариев {', '.join(unknown)} нет в эталоне {args.gold.name}")
        return
    print("\nЗапуск официального валидатора evaluate_golden.py...")
    cmd = [sys.executable, str(eval_script), str(args.gold), str(args.out), "--json"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode in (0, 3):
        try:
            print_evaluation_summary(json.loads(res.stdout))
        except json.JSONDecodeError:
            print(res.stdout)
    else:
        print("Ошибка при запуске evaluate_golden.py:", file=sys.stderr)
        print(res.stderr, file=sys.stderr)
        print(res.stdout)


def main() -> None:
    args = parse_args()

    scenarios = resolve_scenario_paths(args.scenarios)
    if not scenarios:
        print("Ошибка: не найдено ни одного файла сценариев!", file=sys.stderr)
        sys.exit(1)

    print(f"Archonity Pipeline Runner")
    print(f"Скелет:     {args.skeleton}")
    print(f"Исходники:  {args.targets}")
    print(f"Артефакты:  {args.artifacts_dir}")
    print(f"Сценариев:  {len(scenarios)} ({', '.join(s.stem for s in scenarios)})")
    print(f"Выход:      {args.out}")
    print("-" * 60)

    # Р2: выдача строится всегда, сбой виден в рамке последней строкой и в ATTENTION.txt, код выхода 0
    attention.clear(args.out)
    failures: list[dict] = []
    m1_options: dict = {}
    pipeline = adapter = None
    rust_done = False
    try:
        from engine.grounding.llm import LLMClient

        m1_options = {
            "embedder": None if args.no_embed else "qwen3-4b",
            "allow_embed_model": args.embed_model == "on" and not args.require_cache,
            "llm": None if args.no_llm else LLMClient(use_server=not (args.no_server or args.require_cache),
                                                      refresh=args.no_cache and not args.require_cache,
                                                      timeout=args.llm_timeout,
                                                      **({"cache_dir": args.llm_cache} if args.llm_cache else {})),
            "votes": args.select_votes,
            "top_k": args.m1_top_k,
            "index": args.m1_index == "on",
            "reasoning": args.select_reasoning == "on",
        }
        pipeline = build_pipeline(args, m1_options)
    except Exception as e:  # noqa: BLE001
        failures.append(attention.failure(None, None, "сборка конвейера", e))
        # Чужие артефакты (IR, entity_ir): LLM и эмбеддер ни при чём, повтор не поможет; текст с командой пересборки
        # — в рамке, трассы не нужно
        if not isinstance(e, ArtifactMismatch):
            traceback.print_exc()
            print("Повтор сборки в аварийном режиме: M1 без LLM и эмбеддера", file=sys.stderr)
            m1_options = {**m1_options, "llm": None, "embedder": None, "allow_embed_model": False}
            try:
                pipeline = build_pipeline(args, m1_options)
            except Exception as e2:  # noqa: BLE001
                traceback.print_exc()
                failures.append(attention.failure(None, None, "сборка конвейера без LLM", e2))

    if pipeline is not None:
        print("Генерация графов для сценариев...")
        try:
            if args.engine == "rust":
                rust_failures = run_rust(args, pipeline, scenarios)
                rust_done = True
                failures.extend(rust_failures)
            else:
                adapter = pipeline.run_all(scenarios, output_path=args.out)
            print(f"Сабмишн успешно сохранен в: {args.out}")
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            failures.append(attention.failure(None, None, "прогон сценариев", e))
        failures[:0] = pipeline.failures
    empty_fallback = adapter is None and not rust_done
    if empty_fallback:
        write_empty_submission(scenarios, args.out)
        print(f"Записан аварийный сабмишн с пустыми блоками: {args.out}", file=sys.stderr)

    m1_report = None
    if pipeline is not None:
        try:
            from engine.grounding.report import format_m1_report, m1_report as make_m1_report

            llm = m1_options.get("llm")
            emb = pipeline.m1.retriever.embedder
            m1_report = make_m1_report(pipeline.step_requests, llm.stats if llm is not None else None,
                                       getattr(emb, "misses", 0), llm.requested if llm is not None else ())
            print(format_m1_report(m1_report))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            failures.append(attention.failure(None, None, "отчёт M1", e))
        if adapter is not None:
            try:
                write_artifacts(args, pipeline, adapter)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                failures.append(attention.failure(None, None, "отчёты прогона", e))
    try:
        evaluate(args)
    except Exception as e:  # noqa: BLE001
        print(f"Локальная оценка не выполнена: {type(e).__name__}: {e}", file=sys.stderr)

    if m1_report is not None:
        with open(args.out.parent / "m1_report.json", "w", encoding="utf-8") as f:
            json.dump({**m1_report, "failures": failures}, f, ensure_ascii=False, indent=1)

    code = 0
    if args.require_cache:
        from engine.grounding.report import cache_only

        if m1_report is None or not cache_only(m1_report):
            print("--require-cache: выдача построена не целиком из кеша LLM (m1_report.json) — код выхода 2",
                  file=sys.stderr)
            code = 2

    if empty_fallback or attention.needed(failures, m1_report):
        attention.write(failures, m1_report, args.out, empty_fallback=empty_fallback)
        text = "\n".join(attention.lines(failures, m1_report, args.out, empty_fallback=empty_fallback))
        sys.stdout.flush()
        print(text, file=sys.stderr)
        sys.stderr.flush()
        print(text)
    sys.exit(code)


if __name__ == "__main__":
    main()
