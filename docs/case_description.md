# TechArena 2026: Семантический граф микросервисной архитектуры

## 1. Паспорт задачи и организационные вводные

* **Заказчик и куратор:** R&D центр Huawei (команда IDE / Software Development Tools), куратор — Михаил Кулаков.
* **Бизнес-цель:** Создание легковесного анализатора исходного кода, способного без рантайм-запуска предсказывать путь исполнения сценария для помощи ИИ-агентам в навигации по микросервисным проектам, локализации дефектов и оценке радиуса поражения (blast radius).
* **Целевой проект:** Open-source бенчмарк **Train Ticket** (`FudanSELab/train-ticket`, 41 микросервис, основное ядро на Java / Spring Boot / Spring Cloud, вспомогательные сервисы на Go, Python, Node.js; веб-интерфейс `ts-ui-dashboard`, СУБД MySQL 8, MongoDB, брокер RabbitMQ).
* **Таймлайн:**
  * **16 октября 2026:** Публикация официального пакета участника (исходники, скелет, сценарии, контекст БД, открытый эталон S0 и бейзлайны).
  * **22 октября 2026:** Дедлайн сдачи решений в систему тестирования NSUTS.
  * **6 ноября 2026:** Очное награждение топ-10 команд в Новосибирске.
* **Формат сдачи:**
  * В систему тестирования загружается ZIP-архив с исходным кодом решения и **одним обязательным файлом `submission.json` в корне архива** ([hackaton/sample/README.md](file:///Users/shteppinson/dev/hacks/archonity/hackaton/sample/README.md)).
  * По завершении соревнования код лучших решений перезапускается и верифицируется организаторами на предмет соблюдения правил Local-First и статического анализа.

---

## 2. Входные и выходные данные

### 2.1. Входные данные пакета участника ([hackaton/tt-challenge/](file:///Users/shteppinson/dev/hacks/archonity/hackaton/tt-challenge))
1. **Исходный код проекта (`targets/trainticket/`):**
   * Полные исходные тексты бэкенд-сервисов (Java 21 / Spring Boot).
   * Исходный код веб-интерфейса `ts-ui-dashboard/` (JS/HTML). Бизнес-лексика шагов сценариев соответствует кнопкам, функциям и полям фронтенда.
2. **Граф-скелет проекта (`skeleton/trainticket.json.gz`):**
   * Сжатый JSON, содержащий вершины (`nodes`) и потенциальные связи (`edges`).
   * Виды вершин (`kind`): `method`, `call_site` (строка и колонка вызова), `data_resource` (`res:table:...`), `config_entry` (настройки шлюза), `module`, `type`, `parameter`, `field`.
   * Потенциальные связи: `calls`, `runtime_dispatch`, `remote_call`, `message_delivery`, `data_access`. Скелет задает пространство возможных связей, но не указывает, какие из них активируются в конкретном сценарии.
3. **Описания сценариев (`scenarios/`):**
   * 8 файлов сценариев (`S0.json` ... `S7.json`).
   * Текстовое описание действий пользователя на английском языке (название, описание, последовательность шагов).
   * Один шаг сценария соответствует одному клиентскому запросу через шлюз (`ts-gateway-service:18888`). Точные URL и тела запросов не заданы — их необходимо сопоставлять по коду UI и контроллеров.
4. **Контекст исполнения (`context/`):**
   * `context/db-after-warmup.sql.gz`: дамп MySQL с состоянием всех баз данных после предварительного прогревочного прохода. Состояние сбрасывается перед каждым сценарием; сценарии изолированы и не влияют друг на друга.
   * Учетная запись по умолчанию: пассажир `fdse_microservice` / `111111`, баланс счета 10 000, в контактах одна запись `Contacts_One`.
   * Системное время: 15 сентября 2026; дата всех бронирований: 1 октября 2026.
5. **Открытый эталон для калибровки (`gold/S0.json`):**
   * Размеченный эталон связей для сценария S0 (34 `executes`, 24 `calls`, 0 `remote`, 7 `data`).
   * Сценарии S1–S7 скрыты и оцениваются платформой.

### 2.2. Выходные данные (`submission.json`)
Единый JSON-файл с результатами по всем выданным сценариям (S0–S7):
```json
{
  "project": "trainticket",
  "scenarios": {
    "S0": {
      "edges": [
        {
          "source": "scenario:S0",
          "relation": "executes",
          "target": "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)"
        }
      ]
    },
    "S1": { "edges": [ ... ] },
    "S7": { "edges": [ ... ] }
  }
}
```

Каждое ребро задается полями `source`, `relation`, `target`. Поддерживаются 4 типа отношений (`relation`):

| Отношение | Источник (`source`) | Приёмник (`target`) | Семантика |
|:---|:---|:---|:---|
| **`executes`** | `scenario:S<N>` | `method:...` | Метод проекта выполнился хотя бы один раз в данном сценарии. |
| **`calls`** | `method:...` | `method:...` | Первый метод проекта напрямую вызвал второй. При вызове через интерфейс указывается **конкретная реализовавшаяся реализация** (`ServiceImpl`). |
| **`remote`** | `method:...` | `method:...` (другого сервиса) | Межсервисный вызов (HTTP через `RestTemplate` или асинхронное сообщение RabbitMQ), обработанный методом целевого сервиса. |
| **`data`** | `method:...` | `res:table:<service>.<table_name>` | SQL-обращение к таблице БД. Источником выступает **метод, в котором расположен вызов репозитория**; включает таблицы основных сущностей и таблицы коллекций (`user_roles`, `route_stations`). |

*Все идентификаторы методов и таблиц обязаны строго копироваться из `nodes` графа-скелета.*

---

## 3. Технические ограничения (Hard Constraints)

1. **Категорический запрет динамического анализа:** Запрещено запускать анализируемый проект или его сервисы, собирать runtime-трассы или дампы трафика. Разрешён только статический анализ кода, AST, парсинг конфигов, текстовый поиск, NLP и ML-модели. Нарушение влечет дисквалификацию.
2. **Строгий Local-First:** Запрещены любые вызовы внешних облачных API (OpenAI, Anthropic и др.). Все парсеры и модели должны выполняться строго локально.
3. **Среда исполнения:** Инференс и сборка графа производятся на локальных ресурсах участников; платформа принимает готовый ZIP-архив с файлом `submission.json` и кодом.
4. **Бонус за Rust:** За реализацию анализа кода и построения ответа на **Rust** начисляется надбавка **10%** к итоговому баллу: $\text{Итог} \times 1.10$ (но не выше 1.0). Надбавка применяется после проверки кода организаторами. Тонкая обёртка на Rust вокруг скриптов на Python надбавку не получает.

---

## 4. Метрика и правила построения графа

### 4.1. Формула оценки
* Оценка вычисляется отдельно для каждого сценария и каждого из 4 видов связи как коэффициент Жаккара (**IoU — Intersection over Union**):
  $$\text{IoU} = \frac{|P \cap G|}{|P \cup G|} = \frac{TP}{TP + FP + FN}$$
  где $P$ — множество предсказанных рёбер данного вида, а $G$ — эталонное множество.
* Если и в $P$, и в $G$ рёбер данного вида нет, балл равен **1.0**. Если в $G$ рёбер нет, а в $P$ добавлено хотя бы одно ложное ребро, балл равен **0.0**.
* Балл за сценарий — среднее арифметическое IoU по 4 видам связей.
* **Итоговый балл:** среднее арифметическое по 7 скрытым сценариям ($S_1 \dots S_7$). Открытый сценарий $S_0$ в итоговый балл не входит.

### 4.2. Границы разметки и правила фильтрации
* **Изоляция библиотечного кода:** В граф включаются только методы самого проекта. Методы Spring, Jackson, Hibernate, сгенерированные Lombok-методы, а также геттеры/конструкторы, вызванные фреймворком через reflection, в граф не включаются.
* **Фильтры сервлетов:** Фильтр `JWTFilter#doFilterInternal` исполняется, но ребро `calls` от фильтра к обработчику контроллера не ставится (контроллер запускает диспетчер Spring, а не метод фильтра).
* **Мертвый код:** Если шаг сценария содержит условие (например, «без страховки» или отказ в валидации), код невызванных веток отсекается. При возникновении ошибки учитывается код, успевший выполниться до отказа.
* **Базы данных:** Каждая таблица, к которой ушел SQL, формирует отдельное ребро `data`. Таблицы коллекций (`user_roles`, `route_stations`) являются отдельными вершинами.

---

## 5. Доступные инструменты и бейзлайны организаторов ([hackaton/tt-challenge/platform/](file:///Users/shteppinson/dev/hacks/archonity/hackaton/tt-challenge/platform))

1. **[evaluate_golden.py](file:///Users/shteppinson/dev/hacks/archonity/hackaton/tt-challenge/platform/evaluate_golden.py):**
   * Официальный скрипт валидации формата и расчета IoU.
   * Позволяет локально рассчитывать точный скор на открытом эталоне `gold/S0.json` и верифицировать корректность ID вершин для $S_1 \dots S_7$.
2. **[baseline_nlp.py](file:///Users/shteppinson/dev/hacks/archonity/hackaton/tt-challenge/platform/baseline_nlp.py):**
   * Сопоставляет подписи шагов с текстами UI (JS-функции, надписи кнопок, пути) и кодом методов через BM25, после чего выполняет статическое замыкание.
   * Результат на открытом $S_0$: **IoU = 0.431** (`executes` 0.475, `calls` 0.533, `remote` 0.000, `data` 0.714).
   * Результат на скрытых сценариях: около **0.50**.
3. **[baseline_closure.py](file:///Users/shteppinson/dev/hacks/archonity/hackaton/tt-challenge/platform/baseline_closure.py):**
   * Статическое замыкание от точек входа по всем возможным путям скелета без учета условий ветвления.
4. **[baseline_bm25.py](file:///Users/shteppinson/dev/hacks/archonity/hackaton/tt-challenge/platform/baseline_bm25.py):**
   * Поиск похожих методов по BM25 (результат на скрытых сценариях: **0.09–0.13**).

---

## 6. Связь с архитектурой Archonity и аналитическими наработками

Разработка ведется в соответствии с принятыми архитектурными решениями и подготовленной аналитической базой:

1. **Архитектура и контракты:**
   * [docs/roadmap.md](file:///Users/shteppinson/dev/hacks/archonity/docs/roadmap.md) — генеральный план разработки пайплайна до 22 октября.
   * [ADR-001](file:///Users/shteppinson/dev/hacks/archonity/docs/adr/adr-001_data_contracts_and_system_architecture.md) — контракты данных и модульная изоляция.
   * [ADR-002](file:///Users/shteppinson/dev/hacks/archonity/docs/adr/adr-002_react_flow_visualizer.md) — визуализатор на React Flow с инспектором доказательств.
   * [ADR-003](file:///Users/shteppinson/dev/hacks/archonity/docs/adr/adr-003_multimodal_ai_architecture.md) — мультимодальный анализ признаков (UniXcoder, BM25, DTO Jaccard).
   * [ADR-004](file:///Users/shteppinson/dev/hacks/archonity/docs/adr/adr-004_hybrid_recovery_pipeline_and_arbitration.md) — гибридный пайплайн и трехзонный арбитраж с локальным `Qwen2.5-Coder-7B`.
2. **Аналитические артефакты ([docs/analytics/trainticket_artifacts_summary.md](file:///Users/shteppinson/dev/hacks/archonity/docs/analytics/trainticket_artifacts_summary.md)):**
   * [facts/configs_topology.json](file:///Users/shteppinson/dev/hacks/archonity/facts/configs_topology.json) — предикаты маршрутизации шлюза, топология 25 таблиц MySQL/Mongo, очередь RabbitMQ `email`.
   * [facts/](file:///Users/shteppinson/dev/hacks/archonity/facts/) — готовые факты по 4 полиглотным сервисам (Node.js, Python, Go).
   * [data/runtime_and_topology_rules.json](file:///Users/shteppinson/dev/hacks/archonity/data/runtime_and_topology_rules.json) — правила отсева неактивных административных сервисов и канареечных дубликатов.
   * [data/llm_judge_dossiers_and_traps.json](file:///Users/shteppinson/dev/hacks/archonity/data/llm_judge_dossiers_and_traps.json) — семантические ловушки ($FP$) и грамматика вердиктов арбитра.
   * [docs/analytics/trainticket_reference.md](file:///Users/shteppinson/dev/hacks/archonity/docs/analytics/trainticket_reference.md) — каталог AST-паттернов `RestTemplate` JavaParser.
3. **Распределение ролей в команде:**
   * Подробно зафиксировано в [team_roles.md](file:///Users/shteppinson/dev/hacks/archonity/docs/team_roles.md).
4. **Фичи для защиты перед жюри:**
   * **Evidence Log:** привязка к каждому добавленному ребру файла, строки и обоснования решения.
   * **Интерактивный UI ([visualizer/](file:///Users/shteppinson/dev/hacks/archonity/visualizer)):** автономный SPA на React Flow + ELK.js с режимом визуального сравнения $TP/FP/FN$ и инспектором доказательств.
   * **Локальный FastMCP-сервер:** сервер поверх графа с методами `get_blast_radius` и `explain_edge`.
   * **Ablation Study:** документирование прироста IoU по этапам пайплайна (Baseline 0.431 $\to$ +Условия веток $\to$ +Точные таблицы $\to$ +LLM-арбитраж).