# rust/ — движок Archonity на Rust

На Rust написаны разбор исходников и всё, что строит ответ: исполнение шагов, правила фреймворка, проекция на рёбра и запись `submission.json`. На Python остаётся только M1: сопоставление текста шага с обработчиком через локальные модели. Граница описана в [ADR-008](../docs/adr/adr-008_rust_engine_boundary.md), перенос разбора — в [ADR-009](../docs/adr/adr-009_archparse_rust.md).

## Сборка и запуск

Версия Rust закреплена в `rust-toolchain.toml` (1.99.1), `rustup` ставит её сам. Для tree-sitter нужен компилятор C (`cc` или `gcc`).

```bash
cd rust && cargo build --release --locked && cd ..
python run_eval.py --engine rust --parse-sources -o output/submission.json
```

`scripts/run_final.sh` делает то же самое одной командой.

## Состав

| Крейт | Что делает |
|---|---|
| `archonity-parse` | бинарник: разбирает исходники Java (tree-sitter) в IR тел методов `data/ir/<module>.json` и факты JPA `data/entity_ir.json` |
| `archonity-exec` | бинарник: читает шаги от M1 (`step_requests_raw.json`) и строит ответ — исполнение, правило Spring Security, проекция, `submission.json` и `evidence.json` |
| `archonity-m4` | интерпретатор IR: тела методов, библиотека JDK и Spring, переходы в другие сервисы, мир БД сценария |
| `archonity-io` | чтение скелета, дампа БД и `entity_ir.json`, журнал решений, запись выдачи |
| `archonity-model` | общие типы: значения, `StepRequest`, рёбра, флаги правил |

Зависимости идут в одну сторону: `model` ← `io` ← `m4` ← `exec`. `archonity-parse` от них не зависит: он сам читает скелет и пишет файлы, которые потом читает `archonity-io`.

## Тесты

```bash
cd rust && cargo test --release --locked
```

Кроме модульных тестов есть два теста паритета. Им нужен пакет задачи в `hackaton/tt-challenge/`, без него они пропускаются с сообщением.

- `archonity-parse` по исходникам и скелету даёт `data/ir/` и `data/entity_ir.json` байт в байт.
- `archonity-exec` по шагам M1 для S0–S7 даёт рекорд `eval/records/submission_p27_1.00000.json` (балл 1.0, sha256 `94463c41…`) байт в байт.

## Rust и Python

Python-движок с той же логикой остаётся запасным путём: если `archonity-exec` не собрался или упал, `run_eval.py` повторяет прогон на Python и пишет предупреждение в `ATTENTION.txt`. Выдачи совпадают байт в байт: на S0–S7, на своих и перефразированных сценариях и на всех 262 обработчиках проекта, каждый из которых прогнан как сценарий из одного шага.
