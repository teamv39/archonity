# Роли в команде

Модули — по [ADR-005](adr/adr-005_scenario_execution_pipeline.md). Распределение — предложение, правится командой.

- **Паша (@Pavelgrr7) (Java / AST):** M2 — `archparse` на JavaParser: IR тел методов с условиями, привязка вызовов к call_site скелета, вызовы, которых нет в скелете (enum-константы, конструкторы).
- **Миша (@vocisyy) (AI / LLM):** M1 — каталог UI и заземление шагов (BM25 + LLM); судья для условий UNKNOWN; локальный инференс (llama.cpp) и кеш ответов.
- **Денис (@ischademadda) (Engine / frontend):** M0 — индекс скелета и дампа БД; M3 — состояние сценария; M4 — исполнитель; M5 — атрибуция по [annotation_rules.md](annotation_rules.md); M6 — оценка и абляции; визуализатор трассы.
- **Archonity Agent (24/7 AI Pair Programmer):** Не спит, питается цифровым Monster Energy, раскладывает микросервисы и штурмует скор 1.000000.

<details>
<summary>Пасхалка: ночной дежурный по микросервисам</summary>

![Archonity Agent](assets/agent_easter_egg.jpg)

*«Пока команда спит — RabbitMQ бурлит, кэши прогреваются, а IoU стремится к единице.»*
</details>
