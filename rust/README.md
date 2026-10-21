# rust/

Перенос engine на Rust ([ADR-008](../docs/adr/adr-008_rust_engine_boundary.md), раздел работы — [rust_port_split.md](../docs/researches/rust_port_split.md)). Python остаётся рабочим движком, пока Rust не прошёл контрольную точку.

```
cd rust && cargo build --release --locked
target/release/archonity-exec --help
```

| crate | Что | Владелец |
|---|---|---|
| `archonity-model` | значения M4, `StepRequest`, рёбра шага, флаги правил | Денис |
| `archonity-io` | скелет, дамп БД, `entity_ir.json`, мир БД, журнал решений, запись выдачи | Паша |
| `archonity-m4` | интерпретатор, библиотека, шаг сценария | Денис |
| `archonity-exec` | бинарник: сценарии, R20, Spring Security, R19, M5 | Паша |

Зависимости идут в одну сторону: `model` <- `io` <- `m4` <- `exec`. Чужие файлы не правим, новую зависимость добавляем только в `Cargo.toml` своего crate.

Этап 0: все публичные сигнатуры с `todo!("<этап>")`, метка — кто и когда пишет тело (`P1`–`P3` у Паши, `D1`–`D3` у Дениса, `этап 1` — `archonity-model`). Конструкторы `World`, `TypeIndex` и других структур `io` определяет владелец: здесь дана форма, которую читает M4.

## Оракулы Python

```
python scripts/rust_oracles.py steps  <папка>     # step_requests_raw.json, raw_steps.json (+ trace при ARCHONITY_TRACE=<файл>)
python scripts/rust_oracles.py slices <папка>     # slices.json: скелет, дамп БД, entity_ir
python scripts/handler_sweep.py . <файл>          # ответ по каждому обработчику
```

`submission.json` из оракула совпадает с рекордом (`94463c41…`). Форматы файлов описаны в шапке `scripts/rust_oracles.py`.
