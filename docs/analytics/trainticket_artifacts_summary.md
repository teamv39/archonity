# Итоги подготовки аналитических артефактов Train-Ticket

> **Устарело.** Написано до выхода пакета участника, под задачу глобального графа сервисов. Действующий пайплайн — [ADR-005](../adr/adr-005_scenario_execution_pipeline.md), правила разметки — [annotation_rules.md](../annotation_rules.md). Внимание: здесь `ts-travel2-service` и `ts-admin-*` названы мёртвым кодом — это неверно (travel2 обслуживает обычные поезда, S6 целиком админский).

В рамках системного анализа бенчмарка `FudanSELab/train-ticket` и требований стандартов `ADR-001` (удалён, в истории git), [ADR-002](file:///Users/shteppinson/dev/hacks/archonity/docs/adr/adr-002_data_structures_and_graph_storage.md), [ADR-003](file:///Users/shteppinson/dev/hacks/archonity/docs/adr/adr-003_graph_machine_learning_pipeline.md), `ADR-004` (удалён, в истории git) и [RFC-05](file:///Users/shteppinson/dev/hacks/archonity/docs/rfc/rfc-05_hybrid_recovery_pipeline_and_arbitration.md) подготовлен комплект из 11 машиночитаемых JSON-файлов и аналитического справочника. Программный код на Java и Python не создавался, все артефакты представляют собой валидные структуры данных и спецификации.

## 1. Реестр артефактов и ссылок

### Артефакт 1: Инфраструктура, шлюзы, БД и очереди
- Файл: [facts/configs_topology.json](file:///Users/shteppinson/dev/hacks/archonity/facts/configs_topology.json)
- Назначение: базовый реестр конфигурационных фактов сетевой топологии, маршрутизации шлюзов, персистентности и очередей сообщений.
- Состав:
  - `services_network`: порты и контекстные пути сервисов, внешняя точка входа `ts-ui-dashboard` (порт 8080, NodePort 32677), алиас `ts-basic-service` <-> `ts-basic-info-service`.
  - `gateway_routes`: правило Nginx проксирования (`/api/v1/` -> `http://ts-gateway-service:18888`), 43 маршрута Spring Cloud Gateway с корректными предикатами путей.
  - `database_topology`: маппинг 27 сервисов на 25 таблиц и коллекций MySQL и MongoDB (`ts-server-mysql:3306`, `ts-server-mongo:27017`), блок `shared_persistency` (группы разделяемых таблиц `orders`, `user`/`auth_user`, общий контур Mongo), флаг `"is_terminal_sink": true` на всех узлах хранилищ.
  - `messaging_topology`: брокер RabbitMQ (порты 5672/15672), очередь `email`, продюсеры `ts-order-service` и `ts-inside-payment-service` (`PRODUCES_MESSAGE`), консьюмер `ts-notification-service` (`CONSUMES_MESSAGE`).

### Артефакт 2: Факты по 4 полиглот-сервисам
- Файлы:
  - [facts/ts-ticket-office-service.json](file:///Users/shteppinson/dev/hacks/archonity/facts/ts-ticket-office-service.json) (JavaScript / Express, порт 16108, 3 эндпоинта, доступ к коллекции `office` в MongoDB).
  - [facts/ts-voucher-service.json](file:///Users/shteppinson/dev/hacks/archonity/facts/ts-voucher-service.json) (Python / Django, порт 16101, 2 эндпоинта, исходящий вызов в `ts-order-service`, доступ к таблице `voucher` в MySQL).
  - [facts/ts-avatar-service.json](file:///Users/shteppinson/dev/hacks/archonity/facts/ts-avatar-service.json) (Python / Flask, порт 17001, 2 эндпоинта загрузки и получения аватаров).
  - [facts/ts-news-service.json](file:///Users/shteppinson/dev/hacks/archonity/facts/ts-news-service.json) (Go / Webgo, порт 12862, эндпоинт чтения новостей).
- Назначение: готовые входные факты не-Java сервисов, полностью соответствующие схеме раздела 3.2 ADR-001 (`inbound_endpoints`, `outbound_calls`, `db_access`, `messaging`, `internal_call_graph`).

### Артефакт 3: Правила отсева мертвого кода и топологии
- Файл: [data/runtime_and_topology_rules.json](file:///Users/shteppinson/dev/hacks/archonity/data/runtime_and_topology_rules.json)
- Назначение: конфигурация этапа 2 пайплайна (фильтрация и правила топологии) для защиты метрики IoU от False Positives.
- Состав:
  - `active_runtime_scenarios`: 4 эталонных сценария (`Ticket_Preservation`, `Inside_Payment`, `Ticket_Cancellation`, `Travel_Route_Planning`), 24 пошаговых ребра с дуальной типизацией (`relation_type` и `edge_type_adr003`), методами вызывающей стороны и сниппетами.
  - `dead_code_candidates`: группы отсечения (`admin_cluster` из 5 сервисов, `canary_duplicates` — `ts-travel2-service`, `slow_train_branch` — сервисы `*-other`, `unreferenced_endpoints` — капча и аватары).
  - `topology_hub_exclusions`: узлы, временно исключаемые при расчете HITS и структурных окрестностей (`ts-eureka-service`, `ts-eureka-auth-server`, `ts-config-service`, `rabbitmq`, `zipkin`, `ts-gateway-service`).

### Артефакт 4: Досье и ловушки для LLM-as-a-Judge
- Файл: [data/llm_judge_dossiers_and_traps.json](file:///Users/shteppinson/dev/hacks/archonity/data/llm_judge_dossiers_and_traps.json)
- Назначение: датасет для промптинга, калибровки и constrained decoding локального арбитра `Qwen2.5-Coder-7B` в серой зоне ($0.35 \le P < 0.85$, этап 4 RFC-05).
- Состав:
  - `same_domain_fp_traps`: 4 группы архитектурных ловушек со схожими DTO, но без HTTP-вызовов (включая прямой доступ `ts-admin-order-service` к БД `orders` в обход REST).
  - `few_shot_verdicts`: 4 эталонных досье с CoT-аргументацией (`CONFIRMED_DIRECT_CALL`, `CONFIRMED_CONFIG_CALL`, `SAME_DOMAIN_NO_CALL`, `UNRELATED`).
  - `gbnf_grammar_specification`: грамматика GBNF для `llama-cpp-python` / `ollama`, гарантирующая валидный JSON вердикта.

### Артефакт 5: Демо-срез для визуализатора
- Файлы:
  - [visualizer/src/data/demo_submission.json](file:///Users/shteppinson/dev/hacks/archonity/visualizer/src/data/demo_submission.json) (19 узлов, 27 рёбер).
  - [visualizer/src/data/demo_evidence.json](file:///Users/shteppinson/dev/hacks/archonity/visualizer/src/data/demo_evidence.json) (27 записей доказательств по типам `AST_EXACT`, `CONFIG`, `ML_HIGH_CONFIDENCE`, `LLM_JUDGE_VERIFIED`, `TRANSITIVE`).
  - [visualizer/src/data/demo_facts.json](file:///Users/shteppinson/dev/hacks/archonity/visualizer/src/data/demo_facts.json) (массив фактов по 12 сервисам для раскрытия карточек и боковых портов в ELK.js).
  - Зеркальные копии в [visualizer/public/data/](file:///Users/shteppinson/dev/hacks/archonity/visualizer/public/data/) для статической раздачи в production.
- Исправления в загрузчике визуализатора:
  - В [visualizer/src/adapters/dataLoader.ts](file:///Users/shteppinson/dev/hacks/archonity/visualizer/src/adapters/dataLoader.ts) поддержан канонический формат `facts.json` (массив верхнего уровня), устранена потеря ребер при совпадении `READS_DB`/`WRITES_DB`, добавлен парсинг вердиктов RFC-05.
  - В [visualizer/src/components/modals/DataLoaderModal.tsx](file:///Users/shteppinson/dev/hacks/archonity/visualizer/src/components/modals/DataLoaderModal.tsx) добавлен пресет быстрой загрузки полного демо-графа Train Ticket.

### Артефакт 6: Аналитический справочник
- Файл: [docs/analytics/trainticket_reference.md](file:///Users/shteppinson/dev/hacks/archonity/docs/analytics/trainticket_reference.md)
- Назначение: настольный справочник разработчиков `archparse/` и `engine/`.
- Состав:
  - Чек-лист детекции версий `v0.2.0` vs `v1.0.0` по файловой системе (шаги 1–6).
  - Каталог паттернов `RestTemplate` со структурой узлов AST JavaParser (`BinaryExpr`, `StringLiteralExpr`, `FieldDeclaration`, `MethodCallExpr`) и правилами распаковки `ParameterizedTypeReference<Response<T>>` и списков.
  - Матрицы Ground-Truth: SANER 2024 (Zenodo 8106860), Graal-Prophet, MicroHECL, DeepTraLog с правилами нормализации путей.

## 2. Ключевые архитектурные решения

1. **Изоляция баз данных при транзитивном замыкании**:
   Узлы таблиц и коллекций помечены `"is_terminal_sink": true`. Транзитивные рёбра строятся строго между микросервисами (`ts-gateway-service -> ts-travel-service:TRANSITIVE`), исключая ложные транзитивные связи к БД и очередям (ADR-003 п. 7.3, ADR-004 п. 6.1, RFC-05 п. 3.5).

2. **Корректность предикатов Spring Cloud Gateway**:
   В `ts-gateway-service` предикаты путей внутри одного маршрута объединены через запятую в рамках одного выражения `Path=`, предотвращая логическую коллизию `AND` в Spring Cloud Gateway.

3. **Синхронизация контрактов связей (ADR-001 vs ADR-003)**:
   В сценариях сохранены типы визуализатора (`relation_type`: `REST_HTTP`, `MESSAGE_QUEUE`, `DATABASE`) параллельно с графовыми типами ADR-003 (`edge_type_adr003`: `CALLS_HTTP`, `PRODUCES_MESSAGE`, `CONSUMES_MESSAGE`, `WRITES_DB`, `READS_DB`).

4. **Антипаттерны shared persistence**:
   Выделены 4 группы разделяемой персистентности (`orders`, `orders_other`, общая схема `ts` для `user` и `auth_user`, общий кластер Mongo), где каждый сервис соединяется с таблицей независимым ребром без прямого межсервисного HTTP-ребра.

## 3. Результаты верификации

- Синтаксис и структура всех 11 JSON-файлов проверены скриптом верификации (0 ошибок).
- Сборка фронтенд-визуализатора `npm run build` (`tsc -b && vite build`) завершена успешно.
- Линтер `oxlint` по кодовой базе визуализатора: 0 warnings, 0 errors.
- Markdown-справочник проверен на совместимость с GitHub Markdown без нерендеримых LaTeX-конструкций.

## 4. Примерный вектор задач команды в рамках хакатона (Action Items)

Сформированные артефакты закрывают рутинную подготовительную часть анализа и позволяют команде сразу перейти к максимизации метрики IoU и подготовке к защите перед жюри:

### 4.1. Быстрый первый сабмит (Baseline за 1–2 часа)
- **Цель:** Получить первый рабочий скор в системе тестирования NSUTS.
- **Действие:** Денис в модуле `engine/` пишет объединитель графа: берет входной `skeleton.json` от организаторов, накладывает конфигурационные рёбра из [facts/configs_topology.json](file:///Users/shteppinson/dev/hacks/archonity/facts/configs_topology.json) и 4 полиглотных сервиса из [facts/](file:///Users/shteppinson/dev/hacks/archonity/facts/), применяет фильтрацию [runtime_and_topology_rules.json](file:///Users/shteppinson/dev/hacks/archonity/data/runtime_and_topology_rules.json) и строит транзитивное замыкание (исключая узлы с `is_terminal_sink: true`).

### 4.2. Стримы разработки по ролям участников
1. **Паша (Java / AST-парсер `archparse/`):**
   - Использует правила AST из [docs/analytics/trainticket_reference.md](file:///Users/shteppinson/dev/hacks/archonity/docs/analytics/trainticket_reference.md) (JavaParser: `BinaryExpr`, `StringLiteralExpr`, цепочки `UriComponentsBuilder`, извлечение generic-параметра из `ParameterizedTypeReference<Response<T>>`).
   - Фокусируется только на ядре Java/Spring Boot (не тратя время на написание парсеров под Go, Python и Node.js, так как они уже зафиксированы в `facts/`).
   - Генерирует факты `service_facts.json` для всех оставшихся Java-сервисов Train Ticket.

2. **Миша (AI / Link Prediction & Local Judge):**
   - Разворачивает локальный инференс `Qwen2.5-Coder-7B` через `llama-cpp-python` / `ollama` с GBNF-грамматикой из [data/llm_judge_dossiers_and_traps.json](file:///Users/shteppinson/dev/hacks/archonity/data/llm_judge_dossiers_and_traps.json).
   - Подключает Few-Shot промпты и калибрует модель на распознавание семантических ловушек (одинаковые DTO без HTTP-связи).
   - Настраивает трехзонный арбитраж по RFC-05 для рёбер серой зоны ($0.35 \le P < 0.85$).

3. **Денис (Graph Engine, фильтрация и UI):**
   - Реализует DFS-отсев недостижимого кода от публичных точек входа (Nginx, Gateway, контроллеры) на базе [data/runtime_and_topology_rules.json](file:///Users/shteppinson/dev/hacks/archonity/data/runtime_and_topology_rules.json).
   - Подключает локальный бенчмарк IoU по матрицам SANER 2024 / DeepTraLog для оценки качества без расходования попыток в NSUTS.
   - Подготавливает FastMCP-сервер на Python (`get_blast_radius`, `explain_edge`) для защиты перед жюри.

### 4.3. Подготовка материалов для жюри (6 ноября)
- **Evidence Log:** Полная объяснимость каждого ребра (`AST_EXACT`, `CONFIG`, `ML_HIGH_CONFIDENCE`, `LLM_JUDGE_VERIFIED`, `TRANSITIVE`) по образцу [visualizer/src/data/demo_evidence.json](file:///Users/shteppinson/dev/hacks/archonity/visualizer/src/data/demo_evidence.json).
- **Интерактивный UI:** Готовый визуализатор `visualizer/` на базе ELK.js и React Flow с карточками сервисов и подсветкой транзитивных путей.
- **Ablation Study в README:** Таблица поэтапного прироста метрики IoU (Baseline -> +Конфиги/БД -> +Отсев мертвого кода -> +Java AST -> +LLM-арбитраж).

