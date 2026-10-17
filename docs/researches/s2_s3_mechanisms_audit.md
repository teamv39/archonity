# Аудит механизмов S2 и S3 по правилам разметки (annotation_rules.md)

**Дата:** 17.10.2026  
**Связанные документы:** [annotation_rules.md](../annotation_rules.md), [risk_audit_s2_s3.md](risk_audit_s2_s3.md), [adr-005](../adr/adr-005_scenario_execution_pipeline.md)

---

## 1. Контекст и постановка проблемы

В сценарии $S_0$ (калибровочный эталон, IoU = 1.0000) выполняются только операции чтения личного кабинета: аутентификация, контакты, просмотр заказов обоих типов и багажа.

Сценарии $S_2$ и $S_3$ на платформе показывают стабильное плато: **$S_2 \approx 0.873$**, **$S_3 \approx 0.875$**. При объёме ~450 рёбер недобор ~0.125 IoU означает суммарно **50–60 ошибочных рёбер (FP + FN)**.

Аудит по журналу решений подтвердил, что условия внутри исполняемых методов считаются корректно. Потери сосредоточены в механизмах мутации и асинхронного взаимодействия, которые в $S_0$ отсутствуют вовсе:
1. Покупка билетов (`preserve`, `preserveOther`).
2. Оплата (`inside-payment` -> `payment`).
3. Отмена заказа и расчет возврата (`cancel-service`).
4. Перебронирование (`rebook-service`).
5. Заказ питания и асинхронная доставка через очередь (`food-service`, `delivery`, `rabbitmq`).

---

## 2. Количественная разбивка рёбер по 5 механизмам

Данные сверены по исходному коду Java, графу-скелету `skeleton/trainticket.json.gz` и текущему `submission.json`:
* **$S_2$ (всего 489 рёбер):** 181 `executes`, 233 `calls`, 38 `remote`, 37 `data`.
* **$S_3$ (всего 427 рёбер):** 169 `executes`, 190 `calls`, 30 `remote`, 38 `data`.

| Механизм | Шаги сценариев | executes | calls | remote | data | Итого рёбер (Union) | Ключевые таблицы БД |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **1. Покупка билета (`preserve` / `preserveOther`)** | $S_2$: ш. 6, 11<br>$S_3$: ш. 7, 8 | $S_2$: 94<br>$S_3$: 108/88 | $S_2$: 118<br>$S_3$: 131/111 | $S_2$: 20<br>$S_3$: 23/18 | $S_2$: 17<br>$S_3$: 20/15 | **249** ($S_2$)<br>**282** ($S_3$ ш. 7)<br>**232** ($S_3$ ш. 8) | `orders`/`orders_other`, `contacts`, `trip`/`trip2`, `config`, `station`, `train_type`, `route*`, `price_config`, `security_config`, `user` |
| **2. Внутренняя оплата (`inside-payment`)** | $S_2$: ш. 8, 13<br>$S_3$: ш. 12, 13 | 13 | 11 | 2 | 4 | **30** | `inside_money`, `inside_payment`, `orders` ($S_3$) / `orders_other` ($S_2$) |
| **3. Отмена и расчет возврата (`cancel-service`)** | $S_2$: ш. 9 (`calculate`)<br>$S_2$: ш. 10 (`cancel`) | ш.9: 17<br>ш.10: 24<br>U: 26 | ш.9: 19<br>ш.10: 29<br>U: 34 | ш.9: 2<br>ш.10: 4<br>U: 4 | ш.9: 2<br>ш.10: 4<br>U: 4 | **40** (ш. 9)<br>**61** (ш. 10)<br>**68** (Union) | `orders` (зонд), `orders_other`, `inside_money` |
| **4. Перебронирование (`rebook-service`)** | $S_2$: ш. 14 | 74 | 92 | 16 | 12 | **194** | `orders_other`, `trip2`, `route*`, `train_type`, `config`, `price_config`, `inside_money` |
| **5. Еда и RabbitMQ (`food` + `delivery`)** | $S_2$: ш. 4, 6, 11<br>$S_3$: ш. 4, 7 | ш.4: 2<br>ш.6: 8<br>U: 10 | ш.4: 1<br>ш.6: 9<br>U: 10 | ш.4: 0<br>ш.6: 2<br>U: 2 | ш.4: 2<br>ш.6: 2<br>U: 4 | **5** (ш. 4)<br>**21** (внутри preserve)<br>**26** (Всего) | `station_food_store`, `station_food_list`, `food_order`, `delivery` |

---

## 3. Детальный аудит механизмов по `annotation_rules.md`

### 3.1. Механизм 1: Покупка билета (`preserve` / `preserveOther`)

1. **Безусловная перекрёстная проверка безопасности (Правила R3, R17):**
   * В `PreserveOtherServiceImpl#checkSecurity` вызывается `ts-security-service:SecurityServiceImpl#check`.
   * В строках 111–112 `SecurityServiceImpl` **безусловно** опрашивает оба сервиса:
     * `getSecurityOrderInfoFromOrder` -> `ts-order-service:OrderController#securityInfoCheck`
     * `getSecurityOrderOtherInfoFromOrder` -> `ts-order-other-service:OrderOtherController#securityInfoCheck`
   * Поскольку пользователь `fdse_microservice` имеет заказы обоих типов в дампе БД (`db-after-warmup.sql.gz`), цикл `for (Order order : orders)` отрабатывает в обоих сервисах, вызывая `StringUtils.String2Date` и `OrderStatus.getCode()`.
   * **Статус:** вызовы обоих сервисов заказов в $S_2$ и $S_3$ — подтвержденные True Positives.
2. **Каскадная маршрутизация через `ts-basic-service` (Правила R1, R10):**
   * `preserve` вызывает `BasicController#getTravelResult`.
   * Сервис последовательно опрашивает 4 сервиса: `ts-station-service` (`station`), `ts-train-service` (`train_type`), `ts-route-service` (`route`, `route_stations`, `route_distances`) и `ts-price-service` (`price_config`).
   * По правилу **R10**: коллекции `route_stations` и `route_distances` гидрируются при Jackson-сериализации ответа контроллера и включаются в граф.
3. **Мертвый код отправки почты (Правила R1, R4):**
   * В `PreserveServiceImpl` (строки 245–261) и `PreserveOtherServiceImpl` (строки 244–260) строка `sendEmail(notifyInfo, headers)` физически закомментирована в Java-коде.
   * Вызов `getAccount` перед ней исполняется и читает `ts-user-service.user`.
   * **Статус:** `ts-notification-service` и таблица `notify_info` не вызываются (True Negative). Наш отсев корректен.
4. **Конструктор сущности и гидрация (Правило R7):**
   * `new Order()` в сервисе preserve дёргает `edu.fudan.common.entity.Order#<init>()`, который вызывает `Date2String`, `OrderStatus#getCode()` и `SeatClass#getCode()`.

---

### 3.2. Механизм 2: Оплата (`inside-payment`)

1. **Отсечение внешнего шлюза оплаты (Правило R15):**
   * В `InsidePaymentServiceImpl#pay` проверяется `if (totalExpand.compareTo(money) > 0)`.
   * Баланс пользователя в дампе — 10 361 RMB, сумма к списанию — не более 100 RMB.
   * Ветка внешней оплаты через `ts-payment-service` не выполняется. Отсечение таблиц `ts-payment-service.payment` и `money` — True Negative.
2. **Разделение таблиц `pay` и `drawBack` (Правило R10):**
   * `pay` сохраняет транзакцию: трогает **обе таблицы** — `inside_payment` и `inside_money`.
   * `drawBack` (возврат денег при отмене/перебронировании): вызывает только `addMoneyRepository.findByUserId` и `save`. Трогает **только `inside_money`**. Таблица `inside_payment` при возврате не затрагивается.

---

### 3.3. Механизм 3: Отмена заказа и расчет возврата (`cancel-service`)

1. **Разделение шагов 9 (`calculateRefund`) и 10 (`cancelTicket`):**
   * Шаг 9 (`calculate`): опрашивает сервисы заказов, находит билет в `ts-order-other-service` и локально считает 80% возврата. Не вызывает `drawbackMoney` и `ts-inside-payment-service`.
   * Шаг 10 (`cancelTicket`): находит заказ, меняет статус через `cancelFromOtherOrder` и выполняет возврат через `drawbackMoney` -> `InsidePaymentController#drawBack` (пишет в `inside_money`).
2. **Зондирующий запрос к чужому сервису (Правило R7 / риск FP):**
   * В $S_2$ метод `CancelServiceImpl#getOrderByIdFromOrder` сначала опрашивает `ts-order-service`, получая `Optional.empty()` (0 записей).
   * **Потенциальный FP:** если при 0 возвращенных строк гидрация `Order#<init>()` не должна выполняться (правило R7), то включение конструктора на шаге зондирования ошибочно (хотя на шагах обновления заказов 7 и 12 он легитимен).

---

### 3.4. Механизм 4: Перебронирование (`rebook-service`)

1. **Ветка возврата разницы (Правило R15):**
   * В $S_2$ шаг 14 меняет 1-й класс на более дешевый 2-й класс регулярного поезда.
   * `priceOld.compareTo(priceNew) > 0` = `true`.
   * Исполняется возврат разницы: `drawBackMoney` -> `InsidePaymentController#drawBack` (пишет в `inside_money`).
   * Ветка доплаты (`payDifferentMoney`) и создание `new Order()` не выполняются.
2. **Внутрисемейное обновление заказа:**
   * Оба поезда регулярные: условие `(!tripGD(oldTripId) && !tripGD(info.getTripId()))` истинно.
   * Вызывается `updateOrder` (`PUT /api/v1/orderOtherService/orderOther`). Методы `deleteOrder` и `createOrder` (смена типа поезда) отсекаются.

---

### 3.5. Механизм 5: Еда и RabbitMQ (`food` + `delivery`)

1. **Жадная загрузка коллекции блюд (Правило R10):**
   * В `StationFoodStore.java` коллекция блюд помечена `@ElementCollection(fetch = FetchType.EAGER)` с таблицей `station_food_list`.
   * При запросе магазинов по станции (шаг 4) Hibernate читает **обе таблицы**: `station_food_store` и `station_food_list`.
2. **Асинхронное ребро через брокер сообщений (Правило R13):**
   * При оформлении заказа в `FoodServiceImpl#createFoodOrder` сообщение отправляется через `RabbitSend#send`.
   * В скелете есть ребро `message_delivery` к `delivery.mq.RabbitReceive#process`.
   * По правилу **R13** оно трансформируется в `remote`. Потребитель сохраняет запись в таблицу `delivery`.
3. **Изолированный сервис `ts-food-delivery-service`:**
   * Сервис `ts-food-delivery-service` не слушает очередь RabbitMQ и не имеет активных входящих маршрутов. Активный обработчик — только `ts-delivery-service`. Любые рёбра к `ts-food-delivery-service` — ложные.

---

## 4. Источники расхождений (~60 ошибочных рёбер в S2/S3)

| № | Механизм | Правило | Характер | Описание и риск |
| :-: | :--- | :-: | :-: | :--- |
| **1** | Коллекции JDK | **R5** | Потенциальный **FN** | `OrderServiceImpl#create` и `OrderOtherServiceImpl#create` вызывают `accountOrders.contains(order)`. Внутри вызывается `Order#equals(Object)`. По правилу R5 метод, вызванный библиотекой JVM, попадает в `executes` (без `calls`). Движок его сейчас не выдаёт. |
| **2** | Пустые выборки | **R7** | Потенциальный **FP** | При зондировании `ts-order-service` из `CancelServiceImpl` возвращается 0 строк. Если генератор триггерит гидрацию `Order#<init>()` на факте запроса к таблице, это даёт ложные рёбра. |
| **3** | Коллекции JPA | **R10** | Потенциальный **FP** | В `ts-route-service` коллекции `route_stations` и `route_distances` объявлены как `@ElementCollection`. Если в отдельных сценариях они не сериализуются, обращение к таблицам может быть лишним. |
| **4** | Вызовы `ts-config` | **R1** | Подтверждено | `distributeSeat` не читает `ts-config-service`. Конфиг читается только из `getLeftTicketOfInterval` (шаг 3, просмотр рейса). В коде движка это разнесено верно. |

---

## 5. Программа действий

1. **Точечная абляция правила R5 (JDK callbacks):**
   Добавить узел `Order#equals(Object)` в `executes` для сценариев $S_2$ и $S_3$ при сохранении нового заказа. Проверить дельту IoU на платформе NSUTS.
2. **Строгая проверка правила R7 (пустые выборки):**
   Не генерировать гидрацию сущностей для зондирующих запросов `getOrderByIdFromOrder` при отсутствии записи в целевой таблице.
3. **Фиксация в каталоге фактов:**
   Внести выявленные зависимости и подтвержденные ветки в `data/runtime_and_topology_rules.json` для предотвращения регрессий при дальнейших оптимизациях.
