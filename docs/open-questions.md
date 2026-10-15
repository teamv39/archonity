# Открытые вопросы и архитектурные дилеммы (Open Questions)

Документ фиксирует нерешенные проектные вопросы, альтернативные варианты реализации и темы для командного обсуждения между участниками (@Pavelgrr7, @vocisyy, @ischademadda).

---

## Сводная таблица вопросов

| ID | Вопрос | Область | Статус в RFC-05 | Приоритет |
|---|---|---|---|---|
| [OQ-01](#oq-01-evidence-schema) | Формат и структура `evidence.json` | Explainability / Visualizer | Согласовано (ADR-001 / RFC-05) | Высокий |
| [OQ-02](#oq-02-skeleton-dataset) | Формат `skeleton.json` и интеграция со срезанными ребрами Train Ticket | Dataset / Pipeline | Согласовано (Адаптеры + CanonicalGraph) | Критический (к 16.10) |
| [OQ-03](#oq-03-reachability-failures) | Обработка разрывов в Call Graph при Reachability Analysis | Java AST / Dead Code | Согласовано (Reachability + unresolved_calls) | Средний |
| [OQ-04](#oq-04-transitive-closure-rules) | Правила и ограничения транзитивного замыкания ($A \to B \to C$) | Graph Engine / IoU | Согласовано (Изоляция БД + Green zone) | Высокий |

---

## Детальное описание вопросов

### <a id="oq-01-evidence-schema"></a> OQ-01: Формат и структура `evidence.json`

**Контекст:**
Согласно [AGENTS.md](../AGENTS.md), каждое добавленное в итоговый граф ребро обязано иметь запись в `evidence.json` с указанием источника (`AST_EXACT`, `CONFIG`, `ML_PREDICTED`, `TRANSITIVE`), файла/строки и веса уверенности `confidence`. Кроме того, [ADR-002](adr/adr-002_react_flow_visualizer.md) требует отображения этих данных в сайдбаре визуализатора при клике на ребро.

**Варианты реализации:**

#### Вариант 1 (Словарь по `edge_id` с `primary_evidence` и `all_traces`)
Ключом верхнего уровня выступает составной идентификатор ребра (`source->target:relation_type`). Внутри хранится основное доказательство (наивысший приоритет: `AST_EXACT` > `CONFIG` > `ML_PREDICTED` > `TRANSITIVE`) и массив всех найденных подтверждений (полезно, если между сервисами есть несколько разных вызовов из разных классов).

```json
{
  "ts-travel-service->ts-seat-service:REST_HTTP": {
    "source": "ts-travel-service",
    "target": "ts-seat-service",
    "relation_type": "REST_HTTP",
    "primary_evidence": {
      "source_type": "AST_EXACT",
      "confidence": 1.0,
      "file_path": "src/main/java/travel/service/TravelServiceImpl.java",
      "line_number": 115,
      "call_chain": [
        "travel.controller.TravelController.getRoutes",
        "travel.service.TravelServiceImpl.querySeat"
      ],
      "matched_endpoint": "POST /api/v1/seatservice/seat"
    },
    "all_traces": [
      {
        "source_type": "AST_EXACT",
        "file_path": "src/main/java/travel/service/TravelServiceImpl.java",
        "line_number": 115
      }
    ]
  }
}
```

*Плюсы:* Мгновенный доступ $O(1)$ по `edge_id` из визуализатора и Graph Engine; отсутствие дублирования ребер при агрегации нескольких вызовов.  
*Минусы:* Более сложная вложенная структура при валидации Pydantic.

#### Вариант 2 (Плоский массив `EvidenceRecord`)
Массив объектов, где каждая запись представляет один факт подтверждения связи. Если между $A$ и $B$ существует 3 вызова, в массиве будет 3 записи с одинаковой парой $(source, target)$.

```json
[
  {
    "edge_id": "ts-travel-service->ts-seat-service:REST_HTTP",
    "source": "ts-travel-service",
    "target": "ts-seat-service",
    "relation_type": "REST_HTTP",
    "source_type": "AST_EXACT",
    "confidence": 1.0,
    "file_path": "src/main/java/travel/service/TravelServiceImpl.java",
    "line_number": 115,
    "code_snippet": "restTemplate.postForObject(...)"
  }
]
```

*Плюсы:* Простая и прозрачная валидация, естественный лог для добавления записей стримом (`append-only`).  
*Минусы:* Визуализатор обязан группировать массив в HashMap при загрузке.

#### Вариант 3 (Встраивание evidence в `submission.json` + отдельная выжимка)
Если схема организаторов допускает поле `metadata` / `evidence` у ребер графа, хранить метаданные прямо в итоговом файле посылки, а `evidence.json` генерировать как независимую выжимку для локального инспектора.

*Плюсы:* Единственный источник правды (`Single Source of Truth`).  
*Минусы:* Риск не пройти строгую валидацию NSUTS, если схема организаторов запрещает дополнительные поля (`additionalProperties: false`).

> **Решение (согласовано в [RFC-05](rfc/rfc-05_hybrid_recovery_pipeline_and_arbitration.md) и [ADR-001](adr/adr-001_data_contracts_and_system_architecture.md)):** Принят Вариант 1 (словарь по `edge_id` с полями `primary_evidence` и полным трейсом). Обеспечивает $O(1)$ доступ при визуализации и полностью покрывает требования трассировки.

---

### <a id="oq-02-skeleton-dataset"></a> OQ-02: Формат `skeleton.json` и интеграция со срезанными ребрами Train Ticket

**Контекст:**
В репозитории Train Ticket (склонированном через `setup_data.sh`) уже содержится архитектурный граф, у которого организаторами вырезаны ключевые runtime-ребра. 16 октября ожидается публикация пакета участника с официальной JSON-схемой и бейзлайном.

**Ключевые развилки:**

1. **Архитектурный изоляционный слой (Canonical Graph vs Direct Schema):**
   - *Рекомендация:* Graph Engine оперирует внутренней канонической моделью `CanonicalGraph` (`NetworkX` + Pydantic).
   - Чтение скелета оформляется через адаптер `SkeletonAdapter(skeleton_path) -> CanonicalGraph`.
   - Запись результата оформляется через адаптер `SubmissionAdapter(canonical_graph) -> submission.json`.
   - Это гарантирует, что любые изменения формата схемы 16 октября потребуют правки только одного файла адаптера, не задевая JavaParser, ML и логику резолвинга.
2. **Гранулярность узлов в скелете:**
   - Содержит ли скелет только узлы сервисов или также узлы баз данных (таблицы MySQL, коллекции Mongo) и очереди (RabbitMQ)?
   - Требуется сопоставить ID узлов в `skeleton.json` с именами папок сервисов в Train Ticket (например, `ts-travel-service` vs `ts-travel-plan-service`).

> **Решение (согласовано в [RFC-05](rfc/rfc-05_hybrid_recovery_pipeline_and_arbitration.md)):** Принят Вариант 1 (Canonical Graph + Adapters). Внутреннее представление строится на Pydantic + NetworkX, а чтение `skeleton.json` и генерация `submission.json` изолированы в отдельных адаптерах.

---

### <a id="oq-03-reachability-failures"></a> OQ-03: Обработка разрывов в Call Graph при Reachability Analysis

**Контекст:**
При статическом анализе Java-кода в Spring Boot встречаются ситуации, когда детерминированный Call Graph прерывается:
- Вызов метода через интерфейс с несколькими реализациями без явного `@Qualifier`.
- Асинхронные цепочки (`@Async`, `CompletableFuture`, реактивные потоки `Mono`/`Flux`).
- Обработка через кастомные диспетчеры и фабрики.

Если метод, содержащий обращение к внешнему сервису или БД, формально не достижим от контроллера по детерминированному AST-дереву:

**Варианты решений:**
1. **Строгий отсев (`is_reachable = false`):**
   - Считать код мертвым и полностью исключать его из детерминированного графа.
   - *Риск:* Ложноотрицательные срабатывания ($FN$) и падение метрики IoU, если вызов в рантайме на самом деле происходит.
2. **Передача в ML со специальным признаком (`UNRESOLVED_CALL_GRAPH`):**
   - Пометить вызов флагом `reachability_uncertain: true` и передать его в пул кандидатов для ML-классификатора Миши.
   - Модель CatBoost примет решение на основе сходства имен методов, DTO и топологии скелета.
3. **Эвристический поиск публичных маршрутов (Fallback Heuristics):**
   - Если класс аннотирован `@Service` и внедрен через `@Autowired` в активный контроллер, все его `public` методы условно считаются достижимыми, даже если прямой вызов в AST не найден.

> **Решение (согласовано в [RFC-05](rfc/rfc-05_hybrid_recovery_pipeline_and_arbitration.md)):** Двухступенчатая схема: детерминированный анализ достижимости (Reachability в NetworkX от корней Controller/MessageListener/ScheduledTask) отсекает мертвый код. Вызовы, достижимые, но с динамическим таргетом, передаются в список `unresolved_calls` для ML-ранжирования и трёхзонного арбитража.

---

### <a id="oq-04-transitive-closure-rules"></a> OQ-04: Правила и ограничения транзитивного замыкания ($A \to B \to C$)

**Контекст:**
В регламенте сказано: «Цепочки вызовов необходимо раскручивать полностью. Если $A \to B$ и $B \to C$, то изменение в $C$ аффектит $A$». Однако бесконтрольное транзитивное замыкание графа из 40 микросервисов может привести к взрывному росту числа ребер (клике), что обрушит IoU за счет ложноположительных срабатываний ($FP$).

**Правила фильтрации транзитивности:**
1. **Изоляция хранилищ данных (Data Store Isolation):**
   - Регламент жестко гласит: обращение сервиса к таблице БД — это прямое независимое ребро $S \to T$.
   - Транзитивное ребро вида $A \to B \to Table \implies A \to Table$ **запрещено**.
2. **Ограничение глубины (Hop Limit):**
   - Ограничить цепочку косвенных вызовов $k$ шагами (например, $k \le 3$), если в архитектуре Train Ticket не встречаются сквозные синхронные цепочки большей длины.
3. **Разделение типов связей в схеме:**
   - Если целевая схема организаторов требует отличать `DIRECT_HTTP` от `TRANSITIVE_DEPENDENCY`, адаптер обязан выставлять соответствующий тип ребра.

> **Решение (согласовано в [RFC-05](rfc/rfc-05_hybrid_recovery_pipeline_and_arbitration.md)):**
> 1. Узлы БД строго изолированы от транзитивности: обращения к таблицам — только прямые независимые рёбра.
> 2. Транзитивное замыкание строится исключительно по рёбрам зелёной зоны ($P \ge 0.85$ или детерминированные факты AST), исключая каскадное накопление False Positives.
