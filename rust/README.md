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

Зависимости идут в одну сторону: `model` <- `io` <- `m4` <- `exec`.

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
