# Памятка находок по результатам разбора пула методов archparse

**Дата:** 16.10.2026  
**Модуль:** `archparse`
**Артефакт:** `data/pool_ir.json` (34 метода, 127 веток, 1645 вызовов, 100% совпадение; таблица ниже описывает исходные 14 методов с узлами `call_site` скелета).

---

## 1. Сводка совпадений со скелетом (Проверка по п. 3.2 README)

Все 1041 вызов (`calls`), извлечённые из тел методов пула, по координатам `(file, line, col)`на 100% сопоставлены с узлами `call_site` графа-скелета (`skeleton/trainticket.json.gz`), без расхождений:

| Класс и метод | Ветки (branches) | Вызовы (calls) | Совпадение со скелетом |
|---|---:|---:|:---:|
| `CancelServiceImpl#cancelOrder` | 9 | 83 | 83/83 (100%) |
| `CancelServiceImpl#calculateRefund(String,...)` | 6 | 34 | 34/34 (100%) |
| `CancelServiceImpl#calculateRefund(Order)` | 2 | 30 | 30/30 (100%) |
| `ExecuteServiceImpl#ticketExecute` | 6 | 32 | 32/32 (100%) |
| `ExecuteServiceImpl#ticketCollect` | 6 | 36 | 36/36 (100%) |
| `InsidePaymentServiceImpl#pay` | 5 | 80 | 80/80 (100%) |
| `InsidePaymentServiceImpl#setOrderStatus` | 1 | 10 | 10/10 (100%) |
| `RebookServiceImpl#rebook` | 16 | 98 | 98/98 (100%) |
| `RebookServiceImpl#updateOrder` | 1 | 7 | 7/7 (100%) |
| `PreserveServiceImpl#preserve` | 16 | 257 | 257/257 (100%) |
| `PreserveOtherServiceImpl#preserve` | 16 | 256 | 256/256 (100%) |
| `ConsignServiceImpl#updateConsignRecord` | 2 | 44 | 44/44 (100%) |
| `OrderServiceImpl#queryOrders` | 8 | 37 | 37/37 (100%) |
| `OrderOtherServiceImpl#queryOrders` | 8 | 37 | 37/37 (100%) |
| **ИТОГО** | **102** | **1041** | **1041/1041 (100%)** |

---

## 2. Сравнение с текущими эвристиками `engine/rules.py`

### 2.1. `RebookServiceImpl#rebook`
* **Что в коде (IR):**
  - Ветка смены семейства поезда: `tripGD(oldTripId) ^ tripGD(newTripId)`.
    - Если семейство меняется (G/D $\leftrightarrow$ Regular) $\to$ вызываются `createOrder(...)` и `deleteOrder(...)`.
    - Если семейство поезда то же $\to$ вызывается приватный `updateOrder(...)`.
  - Ветка цены:
    - Если билет дороже $\to$ `payDifferentMoney(...)`.
    - Если билет дешевле (как в S2) $\to$ `drawBackMoney(...)`.
    - Если цена равна $\to$ разница не выплачивается.
  - Статус-гейт: `status == NOTPAID`, `CHANGE`, `COLLECTED` завершаются `early_exit` (нельзя перебронировать). Разрешён только `PAID` (`status == 1`).
* **Что в `rules.py` сейчас:**
  - `createOrder`, `deleteOrder`, `payDifferentMoney` безусловно исключены через `is_dead_code_method` (`"RebookServiceImpl" in method_id`).
  - **Вывод для движка:** на S2 это даёт правильный результат (перебронирование дешевле, тот же тип поезда). Перебронирование есть только в S2 и S7, смены типа поезда или доплаты в них нет, поэтому безусловный отсев сейчас безопасен. Он станет FN только при появлении таких сценариев.

### 2.2. `InsidePaymentServiceImpl#pay`
* **Что в коде (IR):**
  - Диспатч сервиса заказов: `if (info.getTripId().startsWith("G") || info.getTripId().startsWith("D"))` $\to$ запрос в `ts-order-service`, иначе $\to$ `ts-order-other-service`.
  - Ветка внешнего/внутреннего платежа: вычисляется `totalExpand.compareTo(money) > 0`.
    - Если баланс достаточен $\to$ прямой расчет, `ts-payment-service` не вызывается.
    - Если баланса не хватает $\to$ вызывается внешний `ts-payment-service` (line 110).
  - Статус-гейт: `if (order.getStatus() != OrderStatus.NOTPAID.getCode())` $\to$ ранний выход (оплатить можно только `NOTPAID`).
* **Что в `rules.py` сейчас:**
  - Диспатч G/D определяется глобальным флагом сценария `ScenarioProfile.train_mode`, а не по конкретному заказу, переданному в запросе шага.
  - Внешний платеж отсекается флагом `has_external_payment` по наличию слов `empty balance` / `external payment` в тексте сценария.

### 2.3. `ExecuteServiceImpl#ticketExecute` и `#ticketCollect`
* **Что в коде (IR):**
  - Статус-гейт исполнения: `if (order.getStatus() != OrderStatus.COLLECTED.getCode())` $\to$ `LOGGER.error`, ранний выход (`early_exit: true`).
  - Метод `executeOrder` вызывается **только** после прохождения проверки на статус `COLLECTED`.
  - В `ticketCollect`: статус-гейт `if (order.getStatus() != OrderStatus.PAID.getCode())` $\to$ ранний выход (`early_exit: true`).
* **Что в `rules.py` сейчас:**
  - Отказ в S7 отслеживается regex'ом `has_refused_cancel/rebook`, но для исполнения билета статус-проверка в `rules.py` отсутствует в явном виде.

### 2.4. Enum-константы (`OrderStatus` и `SeatClass`)
* **Что в коде (IR):**
  - Все вызовы `OrderStatus.XXX.getCode()` (линии 52, 53 в Cancel; 50, 56 в Execute; 70 в InsidePayment; 64, 67, 69, 72 в Rebook) получают атрибут `"enum_constant": {"type": "edu.fudan.common.entity.OrderStatus", "constant": "..."}`.
* **Что в `rules.py` / `graph/builder.py` сейчас:**
  - Ранее в скелете `receiver_type=None` для этих вызовов приводил к потере рёбер `calls`/`executes` на метод `getCode()`.
  - В `builder.py` существовал только частичный хардкод для конструктора `Order#<init>()`. Теперь M4 имеет полную карту всех статусных проверок для добавления рёбер R7.

---

## 3. Расширение пула (17.10.2026, Блоки 0 и 1 пп. 1–2 плана S2/S3)

* **Артефакт:** `pool_ir.json` (52 метода, 1980 вызовов, 100% совпадение со скелетом через `verify_pool_ir.py`).
* **Эффект на выдачу:** нулевой. Выдача с пулом из 52 методов совпадает с выдачей с пулом из 34 во всех сценариях S0–S7. Новые ветки либо «ошибка, ранний выход» (успешный путь и так в ответе), либо G/D-диспатч, который уже решали правила по `train_mode`. Рост числа рёбер «с подтверждением по AST» — перекладка рёбер между категориями, а не рост точности.
* **Инструмент измерения (Блок 0):** журнал решений `engine/decisions.py`, его пишет `GraphBuilder`; `scripts/decision_log.py` только читает журнал. Первая версия скрипта повторяла обход сама и расходилась с выдачей: в S2 не видела 21 ребро (enum-вызовы R7 и рёбра правил фреймворка).
  - S2, рёбра ответа по источнику решения: вызовы 194 по достижимости скелета (`SKELETON`), 16 по веткам IR, 14 по вызовам IR (R7), 9 по правилам фреймворка; межсервисные 35 / 3; таблицы 35 / 1 / 1 (фреймворк). Отсеяно: 18 рёбер правилами `rules.py`, 5 ветками IR.
  - S3: вызовы 166 `SKELETON`, 9 IR, 6 R7, 9 фреймворк; межсервисные 27 / 3; таблицы 36 / 1 / 1. Отсеяно: 8 `rules.py`, 4 ветками IR.

### 3.1. Реализованный пул методов (Блок 1, пп. 1 и 2)
1. **Диспатч обычный / скоростной поезд:**
   - `SeatServiceImpl`: `distributeSeat`, `getLeftTicketOfInterval`.
   - `TravelServiceImpl` (ts-travel2-service): `getTripAllDetailInfo`, `getTickets`, `getTicketsByBatch`, `getRouteByTripId`.
   - `OrderOtherServiceImpl`: `create`, `getSoldTickets`, `modifyOrder`, `queryOrdersForRefresh`.
2. **Перебронирование:**
   - `RebookServiceImpl`: `getOrderByRebookInfo`, `getTripAllDetailInformation`, `dipatchSeat`, `drawBackMoney`, `queryTrainTypeByName`, `getRouteByRouteId`, `checkTime`.
   - `InsidePaymentServiceImpl`: `drawBack`.

### 3.2. Что осталось на будущее
1. **Блок 1, пункты 3 и 4 (хелперы):**
   - Хелперы отмены `CancelServiceImpl`: `getOrderByIdFromOrder`, `getOrderByIdFromOrderOther`, `drawbackMoney`.
   - Хелперы `PreserveOtherServiceImpl`: `dipatchSeat`, `createOrder`, `getAccount`, `getContactsById`, `checkSecurity`, `createFoodOrder`.
2. **Блок 2:** Пул методов для S3 (`PreserveServiceImpl` опции, `AssuranceServiceImpl`, `ConsignServiceImpl`).
3. **Блок 4:** Таблица правил `branch_rules.json` вместо хардкода в `engine/ir.py`.

---

## 4. Конструкторы сущностей при загрузке из БД (17.10.2026)

* **Артефакт:** `data/entity_ir.json`, режим `--mode entities` (контракт — README, раздел 3.5): 28 сущностей, 273 вызова репозиториев (100% совпадение с `call_site` скелета в обе стороны), 25 IR конструкторов без аргументов.
* **Что нашли.** Hibernate вызывает конструктор без аргументов у каждой загруженной строки. Движок учитывал это только для `Order` (хардкод в `builder.py`). В проекте ещё 10 сущностей с непустым конструктором без аргументов. По эталону S0: `Order#<init>()` есть, пустого `Contacts#<init>()` нет, хотя контакты загружаются. Правило «непустое тело» сходится с обоими случаями.
* **Что сделано.** Хардкод `Order` удалён. Решение принимает `engine/entities.py` по фактам archparse: вид операции, ожидание успешного пути (`EMPTY` у проверок «уже существует»), id при `save` (merge), строки по состоянию и дампу.
* **Эффект на выдачу** (только новые `executes`, ни одного удалённого ребра, S0 = 1.0000):

| Сценарий | Добавлено | Конструкторы |
|---|---:|---|
| S1 | 10 | Assurance, Config, Money, PriceConfig, Route, StationFoodStore, Station, TrainFood, travel.Trip, user.User |
| S2 | 7 | Config, PriceConfig, Route, StationFoodStore, Station, travel2.Trip, user.User |
| S3 | 9 | Assurance, Config, Money, PriceConfig, Route, StationFoodStore, Station, travel.Trip, user.User |
| S4 | 9 | Assurance, Config, PriceConfig, Route, StationFoodStore, Station, TrainFood, travel.Trip, user.User |
| S5 | 8 | Config, Money, PriceConfig, Route, Station, travel.Trip, travel2.Trip, user.User |
| S6 | 5 | Config, Money, Station, travel.Trip, user.User |
| S7 | 7 | Config, Money, PriceConfig, Route, Station, travel.Trip, user.User |

* **Итог платформы.** Режим `body` дал 0.8842 против 0.8927: все 55 добавленных конструкторов лишние. Причина записана у организаторов (REFERENCE, «Во-вторых»): конструкторы, вызванные библиотекой лишь через отражение, не включаются. Режим по умолчанию переключён на `project_calls` (только конструкторы с вызовом проектного метода, как `Order`): выдача равна посылке на 0.8927 ребро в ребро, хардкод не вернулся. Разбор: [r7_score_drop.md](../docs/researches/r7_score_drop.md).

---

## 5. Ленивые коллекции JPA (17.10.2026)

* **Что нашли.** Скелет даёт вызову репозитория таблицы коллекций в `data_access`, движок выдавал их всегда, когда вызов исполнился. По README и R10 таблица коллекции идёт в ответ, только если коллекция загрузилась. Ленивую коллекцию, которую метод только вернул, загружает сериализация ответа после возврата, проектного кадра с этой таблицей на стеке уже нет. Прецедент в S0: у `loadUserByUsername` в `data_access` есть `user_roles`, в эталоне нет.
* **Что сделано.** archparse пишет коллекции сущностей (`collections`, 6 таблиц, все совпадают со скелетом) и для чтений — какие ленивые коллекции метод загружает сам (`collections_loaded`), с заходом на уровень в проектный метод, которому передана сущность. Решение — `EntityFacts.collection_table_loaded`, режим `collection_tables_on_read` (`loaded` по умолчанию, `all` — откат).
* **Эффект на выдачу** (только удалённые `data`, S0 = 1.0000, режим `all` равен прежней выдаче ребро в ребро):

| Сценарий | Удалено | Рёбра |
|---|---:|---|
| S1 | 3 | `getRouteById` -> `route_stations`, `route_distances`; `listTrainFoodByTripId` -> `train_food_list` |
| S2, S3, S6, S7 | 2 | `getRouteById` -> `route_stations`, `route_distances` |
| S4 | 3 | как S1 |
| S5 | 3 | `getRouteById` -> обе; `getRouteByStartAndEnd` -> `route_distances` |

* **Итог платформы.** 0.91709 против 0.90208 у посылки M1 (+0.0150). Гипотеза подтверждена.
  - Разница выдачи с базой — только эти 17 рёбер `data`. `executes`, `calls`, `remote` и заземление шагов не менялись: M1 (`engine/grounding`) не читает `entity_ir.json`, правило работает после заземления, в обходе.
  - Величина: +0.015 в среднем по S1–S7 — это примерно +0.06 к IoU `data` на сценарий. Для 2–3 удалённых рёбер из 33–44 такой прирост получается, только если все 17 лишние, а IoU `data` до правки был около 0.85–0.9. Ожидали +0.012–0.015, вышло по верхней границе.
  - Предположение: выдача `dev` без R10 совпадает с посылкой M1 на 0.90208. Архива той посылки у нас нет, сверено только по коду.
  - Режим `all` оставлен для абляций. Отдельная посылка на 0.89271 в счёт не идёт: `pack_submission.py` упаковал устаревший `output/submission.json` (выдача без M1 и R10). Перед упаковкой обязательно `python run_eval.py`.

---

## 6. Методы, которые вызывает фреймворк (17.10.2026, блок 8)

* **Как искали.** 467 методов скелета с телом без входящих `calls`/`runtime_dispatch`/`remote_call`/`message_delivery`, и места, где проектный код отдаёт управление библиотеке (`contains`, `remove`, пулы потоков, `@Async`). Сверка с README и REFERENCE: не учитываются методы библиотек, сгенерированные Lombok и вызванные «лишь через отражение»; проектный метод, который библиотека вызывает обычным вызовом, учитывается (методы `User` в S0).
* **Что уже учтено или не исполняется.** Методы `UserDetails` и `JWTFilter` — в движке, сходятся с S0. Слушатели RabbitMQ — по `message_delivery` (доставка еды в S1–S4). `MyCallable#call` запускает только `queryInParallel`, его нет в сценариях. `@Async sendAsyncCallToPaymentService` нигде не вызывается. `@ExceptionHandler` в auth — только при ошибке входа. Колбэков JPA и `Comparable` нет. Неявный `toString` у `TripId`/`LeftTicketInfo` на путях не найден. Методы старта (`main`, бины, `InitData#run`) и фоновые потоки (`PollThread`) — не путь запроса.
* **Что сделано.** Пропущен один механизм: `accountOrders.contains(order)` в `create` вызывает рукописный `Order#equals` для каждого заказа владельца. archparse пишет `element_callbacks` у чтения (4 места), движок добавляет `equals` в `executes`, если чтение вернуло строки по состоянию (то же условие, что у R7). Режим `element_callbacks` (`on` по умолчанию, `off` — откат).
* **Эффект на выдачу:** плюс 1 `executes` в S1, S3, S6, S7 (`order.entity.Order#equals`) и в S2, S5 (`other.entity.Order#equals`), S4 без изменений (у нового пользователя заказов нет), S0 = 1.0000. Режим `off` равен прежней выдаче ребро в ребро.
* **Итог платформы.** 0.91827 против 0.91709 (+0.00118). Гипотеза подтверждена: одно верное ребро из примерно 185 `executes` даёт около +0.0014 на сценарий, в шести сценариях из семи — около +0.0012 в среднем, что и вышло. Режим `off` оставлен для абляций.
