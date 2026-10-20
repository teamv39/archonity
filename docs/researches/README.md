# Исследования: что читать

Обновлено 19.10.2026. Текущее состояние и план — [roadmap.md](../roadmap.md), что уже известно о балле — [agent_lessons.md](../agent_lessons.md). Отсюда читать только то, что нужно под задачу.

Статусы:

- **Действует** — выводы верны сейчас, на документ можно опираться.
- **Архив** — факт на дату верен (результат зонда, разбор посылки), контекст старый. Читать, когда проверяешь похожую гипотезу, чтобы не повторять.
- **Устарело** — выводы или план больше не верны. Не опираться. Причина — в пометке в начале файла.

## Действует

| Документ | О чём |
|---|---|
| [global_optimization_and_judges_audit.md](global_optimization_and_judges_audit.md) | Глобальный аудит перед оценкой жюри: критерии отбора при 1.0, узкие места скорости, карта специфичности M0–M5, тесты, упаковка и план killer-фич |
| [universality_audit_after_1_0.md](universality_audit_after_1_0.md) | Детальный аудит универсальности пайплайна после взятия 1.00000: сводная таблица степеней специфичности, M1, M4, World, AST |
| [metamorphic_testing.md](metamorphic_testing.md) | Метаморфное тестирование конвейера: проверка поведения без разметки эталонов (MR-1 — MR-5) |
| [two_stage_pipeline_research.md](two_stage_pipeline_research.md) | Исследование и план внедрения двухстадийного пайплайна (Stage 0: Project Profiling) для универсального Spring Boot анализатора |
| [universality_audit_19_10.md](universality_audit_19_10.md) | Аудит универсальности пайплайна на 19.10: инвентаризация подгонок под Train Ticket, M4, зонды 11–19 против правил фреймворка |
| [reaching_1_0.md](reaching_1_0.md) | Как дошли до 1.0: замер ячеек S2/S3, сломанный `@PathVariable`, правило R20 |
| [code_record_drift.md](code_record_drift.md) | Чем выдача кода отличается от рекорда 0.99457: три механизма, прототипы, как переносить в код |
| [../how_we_achieved_0_99457.md](../how_we_achieved_0_99457.md) | Путь к 0.99457, опровергнутые зонды 15–19. Раскладка остатка S2/S3 при FP = 0 — расчёт, не замер |
| [constructor_project_calls_rule.md](constructor_project_calls_rule.md) | Откуда был разрыв 0.064: лишние конструкторы. Основание [ADR-006](../adr/adr-006_constructor_visibility.md), замеры 1–10 |
| [probe_edge_classes.md](probe_edge_classes.md) | Классы рёбер для зондов, скрипт `probe_edge_classes.py`, правила зондирования |
| [m4_executor.md](m4_executor.md) | Устройство исполнителя M4 по IR |
| [m4_score_gap_and_judge.md](m4_score_gap_and_judge.md) | Почему судья не меняет выдачу ([OQ-13](../open-questions.md#oq-13)) |
| [archparse_audit_and_optimizations.md](archparse_audit_and_optimizations.md) | Аудит модуля archparse: замеры времени, code smells, план оптимизации Java AST IR |
| [model_selection.md](model_selection.md) | Выбор LLM и эмбеддингов для M1 и судьи |
| [gpu_dependence_and_cpu_fallback_study.md](gpu_dependence_and_cpu_fallback_study.md) | Работа без GPU и без кеша: что есть, замеры холодного старта (0.575 без LLM), почему legacy не запасной путь, план подстраховки (раздел 7) |

Рядом, вне этой папки: [eval/blind/notes.md](../../eval/blind/notes.md) — слепая разметка S3 и механизм `TravelResult#isStatus()` (H1).

## Архив

| Документ | Что осталось верным |
|---|---|
| [r7_score_drop.md](r7_score_drop.md) | Конструкторов сущностей с непустым телом в эталоне нет (17.10), предшественник ADR-006 |
| [r13_rabbitmq_delivery_audit.md](r13_rabbitmq_delivery_audit.md) | Посылка 2: абляция R13 опровергнута |
| [probe_orders_data_audit.md](probe_orders_data_audit.md) | Посылка 4: зондирующий SELECT к `orders` в S2 нужен |
| [route_distances_s5_audit.md](route_distances_s5_audit.md) | `route_distances` в ответ не идёт, R10 подтверждено |
| [trip_food_query_audit.md](trip_food_query_audit.md) | Каскад `getAllFood` полный |
| [assurance_enum_calls_audit.md](assurance_enum_calls_audit.md) | Вызовы методов enum остаются в ответе |
| [security_check_scope_probe_audit.md](security_check_scope_probe_audit.md) | `securityInfoCheck` исполняется во всех сценариях. Вывод раздела 3 перегнут |
| [domain_generalization_score_0_92431.md](domain_generalization_score_0_92431.md) | Разбор посылки 5 (legacy) |
| [m1_s2_step14_rebook_and_hypotheses_audit.md](m1_s2_step14_rebook_and_hypotheses_audit.md) | `rebook` на S2.14 ([OQ-11](../open-questions.md#oq-11)) |
| [m4_executor_score_0_92539.md](m4_executor_score_0_92539.md) | Посылки 8–9, исполнитель из закрытого PR #59 |
| [risk_audit_s2_s3.md](risk_audit_s2_s3.md) | Аудит legacy-движка по S2/S3 |
| [s3_hypotheses_verification_report.md](s3_hypotheses_verification_report.md) | Проверка 14 гипотез S3 на балле 0.936 |
| [s7_preserve_seat_fix.md](s7_preserve_seat_fix.md) | Правка legacy `rules.py`, на выдачу кода не влияет |
| [train_ticket_specificity_audit.md](train_ticket_specificity_audit.md) | Инвентаризация подгонок на 18.10 — исходные данные для аудита частных правил 21.10 |
| [blind_annotation_task.md](blind_annotation_task.md) | Задание слепой разметки S3, выполнено |

## Устарело

| Документ | Почему |
|---|---|
| [next_day_hypotheses_and_todo.md](next_day_hypotheses_and_todo.md) | Пул гипотез до ADR-006. Таблица статусов — справка о проверенном |
| [s2_gap_and_hypotheses.md](s2_gap_and_hypotheses.md) | Пул гипотез до ADR-006. S2.3 и S2.4 перепроверить замером 20.10 |
| [s2_s3_gap_hypotheses.md](s2_s3_gap_hypotheses.md) | Пул гипотез до ADR-006 |
| [s2_s3_mechanisms_audit.md](s2_s3_mechanisms_audit.md) | Пул гипотез до ADR-006 |
| [s3_hypotheses_and_gap_analysis.md](s3_hypotheses_and_gap_analysis.md) | Пул гипотез до ADR-006 |
| [s4_hypotheses_and_gap_analysis.md](s4_hypotheses_and_gap_analysis.md) | Пул гипотез до ADR-006 |
| [hypothesis_generation_guidelines.md](hypothesis_generation_guidelines.md) | Методика заменена разделами 4 и 7 [agent_lessons.md](../agent_lessons.md) |
| [station_food_list_step4_audit.md](station_food_list_step4_audit.md) | Шаг 4 в S2/S3 запроса не шлёт (посылки 13–14) |
| [research_score_boost_findings.md](research_score_boost_findings.md) | Вывод 3.1 про шаг 4 опровергнут посылками 13–14 |
| [Анализ зависимостей Train-Ticket (1).md](<Анализ зависимостей Train-Ticket (1).md>) | Обзор до пакета участника, под глобальный граф |
