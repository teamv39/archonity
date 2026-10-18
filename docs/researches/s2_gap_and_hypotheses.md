# Анализ потерь баллов и пул гипотез для сценария S2

**Дата:** 18 октября 2026 г.  
**Контекст:** Пайплайн M4 IR-Executor (текущий скор **0.936250**, посылка `02-m4-unresolved-emit`)  
**Ориентиры:** [roadmap.md](../roadmap.md), [AGENTS.md](../../AGENTS.md), [hypothesis_generation_guidelines.md](hypothesis_generation_guidelines.md), [next_day_hypotheses_and_todo.md](next_day_hypotheses_and_todo.md)

---

## 1. Текущий статус сценария S2 и динамика балла

Сценарий **S2** на текущий момент имеет самый низкий балл среди всех 7 оцениваемых сценариев: около **0.919** (разрыв до 1.0 составляет **~0.081**; отставание от лидеров S7 = 0.951, S5 = 0.950, S4 = 0.942, S1 = 0.941 составляет от 0.022 до 0.032).

Поскольку итоговая метрика соревнования — это строгое среднее арифметическое:
$$\text{Score} = \frac{1}{7} \sum_{i=1}^{7} \text{IoU}(S_i)$$
прирост на **+0.035** в сценарии $S_2$ дает немедленный рост общего лидерборда на **+0.0050** (вход в Топ-10 турнира).

### Динамика балла $S_2$ по посылкам:
1. **0.875931** (Базовый пайплайн 17.10): М1 заземление, R5 (`Order#equals`), R7 (`project_calls`), R10 (JPA lazy collections).
2. **0.882280** (+0.006349): Контекстный отсев таблицы `station_food_list` на шаге 4 (просмотр магазинов станции без запроса позиций меню).
3. **~0.919000** (+0.037000): Исправление ошибки заземления M1 на шаге 14 (`payDifference` $\to$ `rebook`).
4. **0.936250** (Текущий общий скор, M4 IR-Executor с неразрешенными вызовами `emit`): паритет S2 с базой + вызовы `TripId#toString`.

### Состав предсказания $S_2$ в сабмишне:
Всего рёбер: **478**
* `executes`: **177**
* `calls`: **230**
* `remote`: **38**
* `data`: **33**

---

## 2. Ретроспектива: почему прошлые гипотезы по S2 оказались «мимо»

Ряд предыдущих гипотез по $S_2$ был опровергнут проверками на платформе или анализом журналов решений:

1. **Исключение RabbitMQ доставки (Правило R13):**
   * *Предположение:* Потребитель RabbitMQ (`delivery.mq.RabbitReceive#process` $\to$ `delivery`) работает асинхронно и не входит в скоуп HTTP-сценария.
   * *Итог платформы:* **Опровергнуто** (падение балла $S_2$ на **-0.015949**, посылка №1664920). Эталон организаторов включает асинхронную доставку еды.
2. **Исключение зондирующего SELECT к `orders` на шагах 9 и 10:**
   * *Предположение:* `CancelServiceImpl` делает `findById` в сервис скоростных поездов `orders`, получает 0 строк, затем идет в `orders_other`. Если пустой SELECT не учитывается, это FP.
   * *Итог платформы:* **Опровергнуто** (падение балла $S_2$ на **-0.007143**, посылка №1664934). Факт отправки SQL в БД строго учитывается организаторами независимо от числа возвращенных строк.
3. **Селекция сервиса мест при перебронировании (Гипотеза 2.2):**
   * *Предположение:* `SeatServiceImpl#distributeSeat` для поезда Z1234 может слать лишние запросы в `ts-order-service`.
   * *Итог:* Проверено по коду и журналу решений — код и так вызывает только `ts-order-other-service`. Изменений в графе не дает.
4. **Изоляция расчета возврата на шаге 9 (Гипотеза 2.4):**
   * *Предположение:* Шаг 9 (`calculateRefund`) может задевать платежный сервис.
   * *Итог:* Проверено по коду — шаг 9 изолирован и не трогает `ts-inside-payment-service`.
5. **Таблица `station_food_list` на шагах 6 и 11 (Гипотеза 2.3):**
   * *Предположение:* При оформлении заказа еды метод `createFoodOrder` подтягивает позиции станционных блюд.
   * *Итог:* В коде пишется только `food_order`, в графе $S_2$ обращений к `station_food_list` на шагах 6 и 11 ровно 0.

---

## 3. Пошаговый маржинальный анализ графа S2

Сценарий $S_2$ состоит из 14 шагов. Анализ добавления новых (маржинальных) рёбер на каждом шаге:

| Шаг | Действие | Новых рёбер | Всего накопительно | Категории новых рёбер |
|:---:|:---|:---:|:---:|:---|
| 1 | Логин `auth.controller.UserController#getToken` | 21 | 21 | calls: 5, data: 3, executes: 13 |
| 2 | Поиск `travel2.controller.Travel2Controller#queryInfo` | 121 | 142 | calls: 56, data: 7, executes: 50, remote: 8 |
| 3 | Детали `travel2.controller.Travel2Controller#getTripAllDetailInfo` | 58 | 200 | calls: 28, data: 5, executes: 20, remote: 5 |
| 4 | Магазины `food.controller.StationFoodController#getFoodStoresOfStation` | 4 | 204 | calls: 1, data: 1, executes: 2 |
| 5 | Контакты `contacts.controller.ContactsController#findContactsByAccountId` | 4 | 208 | calls: 1, data: 1, executes: 2 |
| 6 | Покупка `preserveOther.controller.PreserveOtherController#preserve` | **134** | 342 | calls: 68, data: 8, executes: 46, remote: 12 |
| 7 | Обновление заказов `orderOther.controller.OrderOtherController#queryOrdersForRefresh` | 6 | 348 | calls: 2, data: 1, executes: 3 |
| 8 | Оплата `inside_payment.controller.InsidePaymentController#pay` | 23 | 371 | calls: 8, data: 4, executes: 9, remote: 2 |
| 9 | Расчет возврата `cancel.controller.CancelController#calculate` | 24 | 395 | calls: 12, data: 1, executes: 9, remote: 2 |
| 10 | Отмена заказа `cancel.controller.CancelController#cancelTicket` | 28 | 423 | calls: 15, data: 2, executes: 9, remote: 2 |
| 11 | Вторая покупка `PreserveOtherController#preserve` | **0** | 423 | Полный дубликат шага 6 |
| 12 | Второе обновление заказов | **0** | 423 | Полный дубликат шага 7 |
| 13 | Вторая оплата | **0** | 423 | Полный дубликат шага 8 |
| 14 | Перебронирование `rebook.controller.RebookController#rebook` | **55** | **478** | calls: 34, executes: 14, remote: 7 |

**Главный вывод:** 
После исключения дублирующихся шагов (11, 12, 13) львиную долю уникальной бизнес-логики и потенциальных расхождений в $S_2$ генерируют всего **3 механизма**:
1. **Шаг 6 (и 11):** Покупка билета на обычный поезд (`preserveOther`).
2. **Шаги 9 и 10:** Расчет возврата и отмена (`cancel`).
3. **Шаг 14:** Успешное перебронирование со снижением цены (`rebook`).

---

## 4. Пул новых изолированных гипотез по сценарию S2

### Гипотеза S2.1 (P0): Мертвый код уведомлений в `PreserveOtherServiceImpl` (Шаги 6 и 11)

**Статус: Опровергнута платформой (Посылка 18.10.2026 11:05: скор 0.936250 → 0.929710).**

* **Построчный анализ Java-кода:**
  В конце метода `PreserveOtherServiceImpl#preserve` (строки 244–261):
  ```java
  // 8.send notification
  User getUser = getAccount(order.getAccountId().toString(), httpHeaders);

  NotifyInfo notifyInfo = new NotifyInfo();
  notifyInfo.setDate(new Date().toString());
  notifyInfo.setEmail(getUser.getEmail());
  notifyInfo.setStartPlace(order.getFrom());
  notifyInfo.setEndPlace(order.getTo());
  notifyInfo.setUsername(getUser.getUserName());
  notifyInfo.setSeatNumber(order.getSeatNumber());
  notifyInfo.setOrderNumber(order.getId().toString());
  notifyInfo.setPrice(order.getPrice());
  notifyInfo.setSeatClass(SeatClass.getNameByCode(order.getSeatClass()));
  notifyInfo.setStartTime(order.getTravelTime().toString());

  // TODO: change to async message serivce
  // sendEmail(notifyInfo, httpHeaders);
  ```
  Метод `sendEmail` физически закомментирован. Однако перед ним стоит реальный REST-вызов хелпера `getAccount`, который опрашивает сервис пользователей.
* **Результат проверки на платформе (абляция `--preserve-notification-lookup other_only`):**
  * Общий скор: **0.936250 → 0.929710 (-0.006540)**.
  * $S_2$: **0.919 → 0.894 (-0.025000)**.
  * $S_5$: **0.942 → 0.921 (-0.021000)**.
  * Сценарии $S_1, S_3, S_4, S_6, S_7$ не изменились.
* **Критический архитектурный вывод:**
  Организаторы **НЕ применяют оптимизацию мертвого кода (DCE)** поверх исходников. Разметка эталона получена на основе физического выполнения инструкций Java-рантайма: все строки вплоть до закомментированного `sendEmail` физически исполняются JVM при вызове `preserve`, и порождаемые ими рёбра (`getAccount`, чтение `user`, конструктор `NotifyInfo`, `SeatClass#getNameByCode`) **являются истинными (True Positives) в эталоне $S_2$ и $S_5$**.
* **Итоговое решение:**
  Параметр `--preserve-notification-lookup` оставлен со строгим значением по умолчанию **`on`**. DCE перед закомментированными строками не применяется. Базовый скор 0.936250 полностью сохранен.

---

### Гипотеза S2.2 (P0): Каскад вспомогательных сервисов при перебронировании внутри одного рейса (Шаг 14)

* **Построчный анализ Java-кода:**
  Шаг 14 перебронирует билет на **тот же регулярный поезд Z1234** с 1-го класса на более дешевый 2-й класс.
  Внутри `RebookServiceImpl#updateOrder` (строки 197–216):
  ```java
  Route route = getRouteByRouteId(trip.getRouteId(), httpHeaders);
  TrainType trainType = queryTrainTypeByName(trip.getTrainTypeName(), httpHeaders);
  List<String> stations = route.getStations();
  int secondClassTotalNum = trainType.getEconomyClass();
  Ticket ticket = dipatchSeat(info.getDate(), order.getTrainNumber(), ...);
  ```
  Метод последовательно выполняет:
  1. `getRouteByRouteId` $\to$ `RouteController#queryById` (`ts-route-service`).
  2. `queryTrainTypeByName` $\to$ `TrainController#retrieveByName` (`ts-train-service`).
  3. `dipatchSeat` $\to$ `SeatController#create` (`ts-seat-service`).
* **Суть проблемы:**
  При покупке билета на шаге 6 детали поезда и маршрута уже были получены через `ts-basic-service`. Если организаторы размечали перебронирование как точечную операцию изменения записи заказа и возврата денег:
  `rebook` $\to$ `getOrderByRebookInfo`, `drawBackMoney` $\to$ `InsidePaymentController#drawBack`, `updateOrder` $\to$ `OrderOtherController#saveOrderInfo`,
  то каскадный опрос сервисов маршрута, типов поездов и распределения мест может быть частично или полностью исключен из эталона (порождая до 15–20 ложных рёбер `calls`/`remote`/`executes`).
* **Фильтр универсальности (защита от оверфиттинга):**
  *Категория:* Семантика бизнес-операции M4.
  *Обоснование:* Сравнение параметров операции перебронирования: `rebookInfo.tripId == oldOrder.trainNumber`. Если рейс не меняется (in-place класс поезда), проверка на наличие мест может производиться без полного повторного построения маршрута `getRouteByRouteId`. Проверяется универсальным параметрическим флагом на совпадение рейсов.
* **Потенциальный эффект:**
  * До **+0.030 к IoU $S_2$** (**+0.0042 к общему скору**).
* **Метод проверки:**
  Абляционный флаг `--rebook-aux-services full|order_and_money_only`.

---

### Гипотеза S2.3 (P1): Недостижимые ветки `else-if` проверки статуса в `RebookServiceImpl#rebook` (Шаг 14)

* **Построчный анализ Java-кода:**
  В `RebookServiceImpl.java` (строки 62–78):
  ```java
  Order order = queryOrderResult.getData();
  int status = order.getStatus();
  if (status == OrderStatus.NOTPAID.getCode()) {
      return new Response<>(0, "You haven't paid...", null);
  } else if (status == OrderStatus.PAID.getCode()) {
      // do nothing
  } else if (status == OrderStatus.CHANGE.getCode()) {
      return new Response<>(0, "You have already changed...", null);
  } else if (status == OrderStatus.COLLECTED.getCode()) {
      return new Response<>(0, "You have already collected...", null);
  } else { ... }
  ```
  В сценарии $S_2$ заказ имеет статус `PAID` (код 1).
  По правилам семантики Java:
  1. Вычисляется `status == OrderStatus.NOTPAID.getCode()` $\to$ `false`.
  2. Вычисляется `status == OrderStatus.PAID.getCode()` $\to$ `true`.
  3. Ветви `CHANGE` и `COLLECTED` **не вычисляются и не достигаются**.
* **Суть проблемы:**
  Необходимо убедиться, что символический обход IR в M4 не добавляет вызовы `OrderStatus.CHANGE.getCode()` и `OrderStatus.COLLECTED.getCode()` как безусловные вызовы на enum-константах при анализе тела метода.
* **Фильтр универсальности (защита от оверфиттинга):**
  *Категория:* Семантика интерпретатора AST/CFG (`engine/interpreter.py`).
  *Обоснование:* Стандартная семантика оператора `if-else if-else` в языках программирования: если одно из условий цепочки доказано как истинное (`TRUE`), последующие условия и их ветви гарантированно не выполняются и не должны посещаться обходчиком.
* **Потенциальный эффект:**
  * Устранение 2 FP `calls`: **+0.004 к IoU $S_2$**.

---

### Гипотеза S2.4 (P1): Вызов `saveChanges` vs `modifyOrder` при отмене заказа (Шаг 10)

* **Построчный анализ Java-кода:**
  На шаге 10 вызывается `CancelServiceImpl#cancelOrder`. Для обычного поезда выполняется:
  ```java
  Response changeOrderResult = cancelFromOtherOrder(order, headers);
  ```
  Внутри `cancelFromOtherOrder`:
  `PUT /api/v1/orderOtherService/orderOther` (`OrderOtherController#saveOrderInfo` $\to$ `OrderOtherServiceImpl#saveChanges`).
  Метод `saveChanges` перезаписывает всю запись заказа в репозитории:
  `data: OrderOtherServiceImpl#saveChanges -> res:table:ts-order-other-service.orders_other`.
* **Суть проблемы:**
  В сценарии оплаты (шаг 8) статус заказа меняется через точечный метод `modifyOrder` (GET `/orderOther/status/...`).
  При отмене (шаг 10) вызывается `saveChanges`. Это единственное появление ребра `saveChanges -> orders_other` во всем датасете.
  Необходимо перепроверить соответствие тела DTO, отправляемого в `saveOrderInfo`, чтобы гарантировать, что M4 не уходит в ветку `orderNotFound`.
* **Фильтр универсальности (защита от оверфиттинга):**
  *Категория:* Семантика REST-клиента и Spring Data.
  *Обоснование:* Анализ сигнатуры и тела PUT-запроса `cancelFromOtherOrder`. Если передан валидный объект заказа, сохранение в репозиторий выполняется штатно.
* **Потенциальный эффект:**
  * До **+0.005 к IoU $S_2$**.

---

### Гипотеза S2.5 (P2): Влияние 75 условий UNKNOWN, разрешаемых как `both` в S2

* **Анализ трассы M4:**
  В текущем прогоне M4 для $S_2$ зафиксировано 75 условий с вердиктом `both` (оба плеча исполняются):
  * **21 раз:** `SeatServiceImpl#isContained` (поиск коллизии номера места в `soldTickets`).
  * **18 раз:** `OrderServiceImpl#checkSecurityAboutOrder`.
  * **15 раз:** `OrderOtherServiceImpl#checkSecurityAboutOrder`.
  * **6 раз:** `CancelServiceImpl#getAuthorizationHeadersFrom`.
  * **5 раз:** `RebookServiceImpl#getAuthorizationHeadersFrom`.
* **Суть проблемы:**
  В `checkSecurityAboutOrder`: цикл идет по заказам пользователя `fdse_microservice` из дампа. Внутри цикла проверяются статусы и даты заказов. Выполнение обеих альтернатив (`then` и `else`) при неточных значениях может активировать альтернативные методы обработки, порождая фантомные вызовы `calls`.
* **Фильтр универсальности (защита от оверфиттинга):**
  *Категория:* Семантика состояния БД (World/State) и локальный LLM-судья.
  *Обоснование:* Подстановка фактических записей заказов пользователя `4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f` из `db-after-warmup.sql`. Так как все существующие заказы созданы до системной даты 2026-09-15, проверка на превышение лимита в последний час возвращает детерминированный `true` (безопасно).
* **Потенциальный эффект:**
  * Устранение от 5 до 12 FP рёбер: **+0.010 ... +0.018 к IoU $S_2$**.
* **Метод проверки:**
  Запуск локального LLM-судьи (`--judge cache|on`) на 75 условиях $S_2$ или детерминированное вычисление проверок безопасности по точным заказам из дампа `db-after-warmup`.

---

## 5. Рекомендуемый план проверки и очередность действий

1. **Шаг 1 (P0): Реализация и проверка Гипотезы S2.1 (Мертвый код уведомлений в PreserveOther):**
   * Добавить параметр `--preserve-notification-lookup on|off` (дефолт `on`).
   * Замерить точный граф-дифф для $S_2$ (ожидается удаление 5 рёбер: 1 remote, 1 data, 2 executes, 1 calls).
   * Проверить калибровку $S_0$ (строго 1.000000).
   * Сформировать изолированный сабмишн для платформы.
2. **Шаг 2 (P0): Исследование каскада перебронирования шага 14 (Гипотеза S2.2):**
   * Разобрать журнал решений шага 14.
   * Оценить состав рёбер `SeatController#create`, `TrainController#retrieveByName`, `RouteController#queryById`.
3. **Шаг 3 (P1): Аудит точных вызовов Enum в `rebook` (Гипотеза S2.3):**
   * Проверить, отсечены ли ветки `CHANGE` и `COLLECTED` в трассе M4.
