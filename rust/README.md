# rust/

Перенос engine на Rust ([ADR-008](../docs/adr/adr-008_rust_engine_boundary.md)). Python-движок остаётся отдельным запасным вариантом (`run_eval.py --engine python`), переключения на него при сбое Rust нет.

```
cd rust && cargo build --release --locked
python run_eval.py --engine rust -o output/submission.json
```

Граница: M1 (поиск, эмбеддер, LLM, кеш) остаётся на Python и пишет `step_requests_raw.json`. Всё дальше делает `archonity-exec`: R20, M4, правило Spring Security, R19, M5, запись `submission.json`, `evidence.json`, `decisions.json`, `step_requests.json`, `m4_unknowns.json`. Сбои шагов и сценариев (Р2) бинарник пишет в `exec_failures.json`, рамку и `ATTENTION.txt` собирает `run_eval.py`.

| crate | Что |
|---|---|
| `archonity-model` | значения M4 (`Value`), `StepRequest`, рёбра шага, флаги правил, форматирование чисел как в Python |
| `archonity-io` | скелет, дамп БД, `entity_ir.json`, мир БД, журнал решений, `submission.json`, `evidence.json` |
| `archonity-m4` | интерпретатор IR, библиотека JDK/Spring, шаг сценария (`StepExecutor`) |
| `archonity-exec` | бинарник `archonity-exec`: сценарии, R20, Spring Security, R19, M5 |
| `archonity-parse` | бинарник `archonity-parse`: разбор исходников (tree-sitter-java) в `data/ir/<module>.json` и `data/entity_ir.json`; перенос `archparse` ([ADR-009](../docs/adr/adr-009_archparse_rust.md)) |

Зависимости идут в одну сторону: `model` <- `io` <- `m4` <- `exec`. `archonity-parse` автономен (читает скелет сам) и пишет файлы, которые читает `archonity-io`.

## Разбор исходников (archonity-parse)

```
target/release/archonity-parse --mode all --targets-dir <targets> --skeleton <skeleton.json.gz> -o <папка артефактов>
# --mode bodies: -o папка IR; --mode entities: -o файл; по умолчанию bodies, data/ir
python run_eval.py --engine rust --parse-sources     # то же перед прогоном; scripts/run_final.sh включает по умолчанию
pytest tests/test_rust_parse.py                       # байт в байт с data/ir и data/entity_ir.json
```

Формат записи — Jackson `INDENT_OUTPUT`, как у Java-версии (не Python `json.dump`): `"k" : v`, массивы в строку, `Double.toString`. Оракул — закоммиченные `data/ir/*.json` и `data/entity_ir.json`, построенные Java-`archparse`. На 21.10: 42 файла IR и `entity_ir.json` совпадают побайтно, покрытие скелета полное (1196 методов, 8961 call_site).

## Проверка против Python

Результат Rust равен Python байт в байт: `submission.json` (рекорд `94463c41…`), `decisions.json`, `evidence.json`, `m4_unknowns.json`, `step_requests.json`. Проверки:

```
pytest tests/test_rust_engine.py                                   # оба движка на S0–S7, сравнение файлов
python scripts/rust_oracles.py steps  <папка> [сценарии...]        # step_requests_raw.json, raw_steps.json (+ trace при ARCHONITY_TRACE)
python scripts/rust_oracles.py sweep  <папка>                      # sweep_steps.json: 262 обработчика как одношаговые сценарии
python scripts/rust_oracles.py slices <папка>                      # slices.json: скелет, дамп БД, entity_ir
target/release/replay_steps <скелет> <entity_ir> <ir> <исходники> <raw_steps.json> <выход>
python scripts/rust_compare.py <raw_steps.json> <выход>            # рёбра и журнал решений по шагам
```

`replay_steps` гонит `StepExecutor` по шагам оракула (после R20), `rust_compare.py` показывает расхождения по рёбрам и записям журнала. На 21.10: S0–S7, X1–X8 и 262 обработчика — расхождений 0.

## Известные приближения

- Идентичность примитивов (`ident`) в журнале плеч сравнивает значения, а не адреса, как Python.
- `timestamp()` у naive datetime считается как UTC.
- `canonical_graph.json` и `visualizer/` при `--engine rust` не обновляются (открытый вопрос ADR-008).
