# ADR-008: Граница Python и Rust в engine

## Статус

**Принят 21.10.2026** (Денис; влит PR #119). Условие Р1 из [roadmap](../roadmap.md) — «да, отдельной дорожкой с жёсткой контрольной точкой». Этап 0 — `rust/`, `scripts/rust_oracles.py`. Планы: [rust_port_plan.md](../researches/rust_port_plan.md), раздел работы — [rust_port_split.md](../researches/rust_port_split.md).

## Контекст

README организаторов даёт **×1.10 к итоговому баллу** (не выше 1.0), если «анализ кода и построение ответа» на Rust. Тонкая обёртка надбавку не получает. Выдача Python — запасной вариант: рекорд 1.0, sha256 `94463c41…5a08`.

Граница уже есть в коде. M1 (`StepGrounder.ground`) строит `StepRequest` по тексту шага и истории шагов и результатов M4 не читает. Остальное — M4, правило Spring Security, M5, правило R19 — работает по `StepRequest`, скелету, IR и дампу БД. Состояние в `pipeline.py` одно: `ScenarioContext` (пассажир).

Одно место не чистое: R20 (`StepGrounder.rebind`, `engine/grounding/binding.py`) стоит внутри цикла шагов, и `step_requests.json` пишется **после** замены. Rust-стороне нужен шаг до замены.

## Решения

### 1. Что на каком языке

| Python | Rust (`archonity-exec`) |
|---|---|
| сценарии, M1 (BM25, эмбеддер, LLM, кеш), профиль проекта, `m1_report.json`, ATTENTION.txt (Р2), оркестрация `run_eval.py` | загрузка скелета, IR, `entity_ir.json`, дампа БД; мир БД; M4 (интерпретатор, библиотека, шаг); R20; правило Spring Security; R19; M5; запись `submission.json`, `evidence.json`, `decisions.json` |

M1 остаётся на Python: это сопоставление текста шага с обработчиком через локальные модели, а не анализ кода. Что такое деление засчитают, по словам Дениса (21.10), организаторы подтвердили; текста ответа в репозитории нет, внести в [testing_system.md](../testing_system.md) раздел 1. archparse (M2) остаётся на Java до отдельного решения.

### 2. Вход и выход Rust

- Вход: `step_requests_raw.json` — `StepRequest` каждого шага **до R20**, по сценариям, в порядке сценария. Пишет Python (этап 0: `scripts/rust_oracles.py steps`, затем `run_eval.py --engine rust`); существующий `step_requests.json` (после R20) не меняется.
- Остальной вход: те же файлы, что у Python (`--skeleton`, `--targets`, `data/ir/`, `data/entity_ir.json`, дамп из `context/`), и флаги правил `RuntimeRules` теми же именами.
- Выход: `submission.json`, `evidence.json`, `decisions.json` рядом с выдачей. Байт в байт с Python, включая порядок ключей и формат чисел.
- `m4_unknowns.json` и `canonical_graph.json` пишет Python-часть (`run_eval.py`) только для визуализатора и отладки. В Rust не переносим (см. «Открыто», 1).

### 3. Режим `run_eval.py --engine python|rust`

- Умолчание `python`, пока Rust не прошёл контрольную точку (22.10, середина дня).
- `rust`: Python прогоняет только M1 и пишет `step_requests_raw.json`, затем запускает `archonity-exec` и читает его артефакты для `m1_report.json`.
- Переключения на Python при сбое Rust нет (решение Дениса 21.10). Python-движок — отдельный запасной вариант на случай, если Rust не пройдёт контрольную точку: тогда сдаём прогон с `--engine python`. Сбой Rust внутри прогона обрабатывает механизм Р2, как сбой любого этапа: шаг без рёбер, пустой блок сценария, `ATTENTION.txt`.

### 4. Сборка у организаторов

Сеть при сборке у организаторов есть (Денис, 21.10; та же сеть нужна `fetch_models.py`, см. [run_on_a100.md](../run_on_a100.md)). Поэтому: `cargo build --release --locked` в `scripts/run_final.sh`, `Cargo.lock` в репозитории, зависимости с crates.io. Нужен актуальный stable Rust; `run_final.sh` ставит его через `rustup` в `~/.cargo`, если `cargo` не найден. `cargo vendor` не нужен. Готовый бинарник в репозиторий не кладём: надбавку дают за исходный код. Требования и шаги добавляем в [run_on_a100.md](../run_on_a100.md) вместе с `--engine rust`.

### 5. Владение и контракт

По [rust_port_split.md](../researches/rust_port_split.md): у каждого файла в `rust/` один владелец, этап 0 (workspace, сигнатуры с `todo!()`, оракулы Python) вливается первым. Правка сигнатуры после этапа 0 — отдельный маленький PR.

### 6. Оракулы

Python выдачу не меняет: sha256 `submission.json` прежний. Новое только в записи артефактов:

- `step_requests_raw.json` (пункт 2);
- сырые рёбра и записи журнала по шагам, до Spring Security и M5 (`scripts/rust_oracles.py`);
- трасса вызовов интерпретатора при `ARCHONITY_TRACE=1`, по умолчанию выключена;
- срезы загрузчиков (индекс скелета, таблицы дампа, `EntityFacts`) в JSON.

Ответ по каждому из 262 обработчиков — `scripts/handler_sweep.py`, он уже есть.

## Последствия

- На время переноса правка M4 на Python делается только с механизмом и дублируется в Rust тем, кто владеет файлом (план, «Двойная поддержка»).
- Python не удаляем до контрольной точки; после неё решаем отдельно.
- В Rust не переносим доменные литералы Train Ticket (roadmap, П2) и судью M4 (`judge.py`, по умолчанию выключен).
- Строки в [rust_port_split.md](../researches/rust_port_split.md) устарели после PR #110 (например, `adapters/skeleton.py` 348 → 201, `interpreter.py` 1431 → 1401): объём меньше, чем в плане.

## Открыто

1. Нужны ли визуализатору `canonical_graph.json` и `m4_unknowns.json` при `--engine rust` (пункт 2). Если да, строим их из `submission.json` и `evidence.json` на Python.
