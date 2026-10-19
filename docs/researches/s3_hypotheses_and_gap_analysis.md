# Комплексный аудит сценария S3 и пул гипотез для устранения отставания скора

> **Устарело.** Пул гипотез 18.10, балл 0.936, до [ADR-006](../adr/adr-006_constructor_visibility.md). Почти весь разрыв до 1.0 сидел в конструкторах, а не в ветках и шагах, поэтому оценки вклада гипотез здесь неверны. Текущее — [roadmap.md](../roadmap.md) и [agent_lessons.md](../agent_lessons.md).

**Дата составления:** 18.10.2026  
**Контекст:** Соревнование TECHARENA 2026, трек «Семантический граф микросервисной архитектуры»  
**Базовые документы:** [roadmap.md](../roadmap.md), [AGENTS.md](../../AGENTS.md), [ADR-005](../adr/adr-005_scenario_execution_pipeline.md), [annotation_rules.md](../annotation_rules.md), [s2_s3_gap_hypotheses.md](s2_s3_gap_hypotheses.md), [next_day_hypotheses_and_todo.md](next_day_hypotheses_and_todo.md)  
**Текущий подтвержденный скор на платформе:** **0.924310** (до M4) / **0.936250** (с M4 `--executor ir --m4-unresolved-calls emit`)  
**Текущий балл сценария S3 на платформе:** **~0.905265** (наибольшее отставание среди скоростных сценариев: $S_1 = 0.934$, $S_4 = 0.931$, $S_5 = 0.932$, $S_6 = 0.937$)  
**Цель исследования:** Детальная анатомия сценария $S_3$, выявление источников ложноположительных (FP) и ложноотрицательных (FN) рёбер и формулирование пула из 14 целевых гипотез с потенциалом роста скора.

---

## 1. Анатомия сценария S3 и метрики графа

### 1.1. Описание пользовательского сценария S3

Сценарий $S_3$ представляет собой комплексный пользовательский путь работы со скоростными поездами (GaoTie/DongChe):
1. **Шаг 1:** Вход в систему с логином и паролем (`UserController#getToken`).
2. **Шаг 2:** Поиск скоростных поездов Шанхай $\rightarrow$ Сучжоу на 01.10.2026 (`TravelController#queryInfo`).
3. **Шаг 3:** Открытие подробной информации о первом найденном рейсе (`TravelController#getTripAllDetailInfo`).
4. **Шаг 4:** Просмотр списка продуктовых магазинов на станции Сучжоу (`StationFoodController#getFoodStoresOfStation`).
5. **Шаг 5:** Открытие адресной книги контактов, выбор первого контакта (`ContactsController#findContactsByAccountId`).
6. **Шаг 6:** Добавление нового контакта попутчика с удостоверением личности (`ContactsController#createNewContacts`).
7. **Шаг 7:** Бронирование билета 1-го класса на выбранный рейс для первого контакта с полным пакетом опций: станционное питание (`foodType = 2`), страховка первого типа (`assurance = 1`) и багажная квитанция 0.5 кг (`PreserveController#preserve`).
8. **Шаг 8:** Бронирование билета 2-го класса на тот же рейс для нового попутчика без питания, страховки и багажа (`PreserveController#preserve`).
9. **Шаг 9:** Обновление списка заказов (`OrderController#queryOrdersForRefresh`).
10. **Шаг 10:** Просмотр деталей первого нового заказа (`OrderController#getOrderById`).
11. **Шаг 11:** Просмотр деталей второго нового заказа (`OrderController#getOrderById`).
12. **Шаг 12:** Оплата первого заказа с внутреннего баланса (`InsidePaymentController#pay`).
13. **Шаг 13:** Оплата второго заказа с внутреннего баланса (`InsidePaymentController#pay`).
14. **Шаг 14:** Проверка стоимости перевозки багажа 0.5 кг в пределах региона (`ConsignPriceController#getPriceByWeightAndRegion`).
15. **Шаг 15:** Просмотр каталога доступных видов страхования (`AssuranceController#getAllAssuranceType`).

---

### 1.2. Распределение рёбер в предсказании Archonity для S3

Всего в сабмишне для $S_3$ генерируется **419 рёбер**:

| Категория связи | Число рёбер в $S_3$ | Доля в графе | Число рёбер в $S_1$ (для сравнения) | Дельта $S_1 - S_3$ |
|:---|---:|---:|---:|---:|
| **executes** | 167 | 39.85% | 184 | +17 |
| **calls** | 188 | 44.87% | 206 | +18 |
| **remote** | 30 | 7.16% | 36 | +6 |
| **data** | 34 | 8.12% | 39 | +5 |
| **ИТОГО** | **419** | **100.0%** | **465** | **+46** |

---

### 1.3. Пошаговый маргинальный анализ вклада шагов в объединенный граф $S_3$

В соответствии с регламентом соревнования и правилом R20, итоговый граф сценария формируется как **теоретико-множественное объединение (Union)** графов исполнения всех шагов: $G(S) = \bigcup_{i=1}^{N} G(Step_i)$.

| Шаг | Входной обработчик | Всего рёбер шага | Уникальных для сценария | Маргинально новых в Union | Ключевая особенность шага |
|:---:|:---|---:|---:|---:|:---|
| **1** | `UserController#getToken` | 21 | 21 | 21 | Аутентификация JWT, совпадает с калибровкой S0 |
| **2** | `TravelController#queryInfo` | 115 | 59 | 115 | Поиск рейсов, опрос станций, маршрутов, цен, мест |
| **3** | `TravelController#getTripAllDetailInfo` | 117 | 0 | 61 | Детали рейса и остаток мест (`ts-seat-service`) |
| **4** | `StationFoodController#getFoodStoresOfStation` | 4 | 4 | 4 | Просмотр магазинов; `station_food_list` отсечен (R10) |
| **5** | `ContactsController#findContactsByAccountId` | 4 | 4 | 4 | Чтение списка контактов пользователя |
| **6** | `ContactsController#createNewContacts` | 4 | 4 | 4 | Добавление контакта попутчика (`contactsRepository.save`) |
| **7** | `PreserveController#preserve` (Заказ 1) | 281 | 45 | 164 | Билет 1 класса + еда + страховка + багаж + RabbitMQ |
| **8** | `PreserveController#preserve` (Заказ 2) | 231 | 0 | **0** | **Полная маскировка шагом 7! 0 новых рёбер** |
| **9** | `OrderController#queryOrdersForRefresh` | 22 | 15 | 15 | Чтение заказов пользователя из `ts-order-service` |
| **10** | `OrderController#getOrderById` (Заказ 1) | 11 | 0 | 4 | Чтение заказа; дублируется вызовом из шага 12 |
| **11** | `OrderController#getOrderById` (Заказ 2) | 11 | 0 | **0** | Полная маскировка шагами 10 и 13 |
| **12** | `InsidePaymentController#pay` (Заказ 1) | 30 | 0 | 19 | Оплата 1-го заказа: списание, смена статуса на `PAID` |
| **13** | `InsidePaymentController#pay` (Заказ 2) | 30 | 0 | **0** | Полная маскировка шагом 12 |
| **14** | `ConsignPriceController#getPriceByWeightAndRegion` | 4 | 0 | **0** | **Полная маскировка шагом 7! 0 новых рёбер** |
| **15** | `AssuranceController#getAllAssuranceType` | 9 | 8 | 8 | Итерация по enum `AssuranceType` (подтверждено на платформе) |

---

## 2. Ключевые архитектурные выводы из анализа шагов

1. **Эффект маскировки (Masking Effect):**
   - Шаги 8 (второе бронирование), 11 (просмотр второго заказа), 13 (оплата второго заказа) и 14 (расчет тарифа багажа) дают **ровно 0 новых рёбер** в объединенный граф.
   - Если в шаге 8 организаторы ожидали специфические вызовы для билета 2-го класса (например, раскладка мест эконом-класса, иные ветки валидации), или если в шаге 14 логика регионального флага активирует иные пути, в текущем объединении эти различия полностью скрыты.
2. **Асимметрия скора скоростных сценариев:**
   - Сценарии $S_1$ (0.934), $S_4$ (0.931), $S_6$ (0.937) достигают высоких баллов.
   - Сценарий $S_3$ (0.905) отстает на **~0.030 IoU**. При размере графа 419 рёбер это соответствует примерно **20–25 ошибочным рёбрам** (суммарно FP + FN).
3. **Уже проверенные на платформе факты по $S_3$ (не подлежат ревизии):**
   - **R13 (RabbitMQ к delivery):** доставка станционной еды через очередь RabbitMQ в шаге 7 **обязательна**. Абляция снизила скор на **-0.00925** ([r13_rabbitmq_delivery_audit.md](r13_rabbitmq_delivery_audit.md)).
   - **R10 (station_food_list в шаге 4):** исключение таблицы коллекции блюд на шаге 4 **подтверждено** и дало прирост **+0.006194** к $S_3$ ([station_food_list_step4_audit.md](station_food_list_step4_audit.md)).
   - **Геттеры AssuranceType в шаге 15:** вызовы `getIndex()`, `getName()`, `getPrice()` на элементах enum **обязательны**. Отсечение снизило скор на **-0.007** ([assurance_enum_calls_audit.md](assurance_enum_calls_audit.md)).
   - **R7 (Hibernate entity constructor hydration):** конструкторы без проектных вызовов (`Assurance#<init>`, `Route#<init>`, `StationFoodStore#<init>`) являются мертвым кодом и снижают скор при включении ([r7_score_drop.md](r7_score_drop.md)).

---

## 3. Пул гипотез для сценария S3

Ниже представлены 14 детально проработанных гипотез, сгруппированных по функциональным подсистемам.

---

### Группа A: Двойное бронирование и семантика 2-го класса (Шаги 7 и 8)

#### Гипотеза 3.1 (P0): Специфичные методы распределения мест 2-го класса в `ts-seat-service`
* **Построчный анализ Train Ticket:**
  * В шаге 7 оформляется билет 1-го класса: `oti.getSeatType() == SeatClass.FIRSTCLASS.getCode()` (2).
  * В шаге 8 оформляется билет 2-го класса: `oti.getSeatType() == SeatClass.SECONDCLASS.getCode()` (3).
  * В `PreserveServiceImpl.java` (строки 148–166):
    ```java
    if (oti.getSeatType() == SeatClass.FIRSTCLASS.getCode()) {
        int firstClassTotalNum = resultForTravel.getTrainType().getConfortClass();
        Ticket ticket = dipatchSeat(..., SeatClass.FIRSTCLASS.getCode(), firstClassTotalNum, ...);
        order.setSeatClass(SeatClass.FIRSTCLASS.getCode());
        order.setPrice(resultForTravel.getPrices().get("confortClass"));
    } else {
        int secondClassTotalNum = resultForTravel.getTrainType().getEconomyClass();
        Ticket ticket = dipatchSeat(..., SeatClass.SECONDCLASS.getCode(), secondClassTotalNum, ...);
        order.setSeatClass(SeatClass.SECONDCLASS.getCode());
        order.setPrice(resultForTravel.getPrices().get("economyClass"));
    }
    ```
  * В `SeatServiceImpl#distributeSeat` для скоростных поездов отправляется запрос на `/api/v1/orderservice/order/tickets`.
  * В `OrderServiceImpl#getSoldTickets`:
    `orderRepository.findByTravelDateAndTrainNumber(...)` фильтрует только по дате и номеру поезда, **но не по типу места**.
  * Проверить: не содержит ли распределитель мест `SeatServiceImpl` вспомогательных методов пересчета диапазона мест для эконом-класса (например, вагонная сетка, вызов `SeatClass.SECONDCLASS.getName()`), которые сейчас отсутствуют в skeleton-проекции.
* **Влияние на граф:** Добавление 2–4 целевых рёбер `calls`/`executes`.
* **Ожидаемый эффект:** +0.005 ... +0.008 к IoU $S_3$.
* **Метод проверки:** Проверка покрытия вызовов `SeatServiceImpl` и `SeatClass` в `pool_ir.json` и `decisions.json`.

---

#### Гипотеза 3.2 (P1): Контактная валидация попутчика при бронировании в шаге 8
* **Построчный анализ Train Ticket:**
  * На шаге 6 создается новый контакт: `ContactsController#createNewContacts`.
  * На шаге 8 билет бронируется для этого нового контакта: `PreserveServiceImpl#getContactsById(newContactId)`.
  * В методе `ContactsServiceImpl#findContactsById`:
    `contactsRepository.findById(contactsId)` возвращает сущность `Contacts`.
  * В строках 117–119 `PreserveServiceImpl.java`:
    ```java
    order.setContactsDocumentNumber(contacts.getDocumentNumber());
    order.setContactsName(contacts.getName());
    order.setDocumentType(contacts.getDocumentType());
    ```
  * Проверить: не вызывает ли валидация нового контакта вызовов к справочнику документов `DocumentType#getNameByCode(int)` (`ts-common:edu.fudan.common.entity.DocumentType`), присутствующему в скелете.
* **Влияние на граф:** 1 `executes`, 1 `calls`.
* **Ожидаемый эффект:** +0.003 ... +0.005 к IoU $S_3$.
* **Метод проверки:** Сопоставление с эталоном $S_0$ (где `DocumentType` не вызывался на контактах).

---

#### Гипотеза 3.3 (P1): Проверка наличия мест (`checkSeat is enough`) на шаге 8
* **Построчный анализ Train Ticket:**
  * В `PreserveServiceImpl.java` (строки 87–97) проверяется наличие мест в ответе рейса:
    ```java
    if (oti.getSeatType() == SeatClass.FIRSTCLASS.getCode()) {
        if (tripResponse.getConfortClass() == 0) return new Response<>(0, "Seat Not Enough", null);
    } else {
        if (tripResponse.getEconomyClass() == SeatClass.SECONDCLASS.getCode() && tripResponse.getConfortClass() == 0) {
            return new Response<>(0, "Seat Not Enough", null);
        }
    }
    ```
  * Логика условия во второй ветке содержит потенциальный артефакт разработчиков Train Ticket: проверка `getEconomyClass() == SeatClass.SECONDCLASS.getCode()` вместо проверки количества мест.
  * Если в БД или эмуляторе количество мест эконом-класса исчерпано, бронирование шага 8 должно было завершиться ошибкой `"Seat Not Enough"`, оборвав последующие шаги цепочки (сохранение заказа, отправка уведомления).
  * В `eval/m1_steps.json` шаг 8 помечен как успешное бронирование (`status: ok`).
* **Влияние на граф:** При обрыве шага 8 граф не меняется (так как шаг 7 уже добавил все ребра), но при моделировании M4 важно гарантировать статус ветки `True`.
* **Ожидаемый эффект:** Защита от деградации при интеграции интерпретатора M4.

---

### Группа B: Кросс-сервисный аудит безопасности (Шаги 7 и 8)

#### Гипотеза 3.4 (P0): Ложные вызовы к `ts-order-other-service` при проверке безопасности в S3
* **Построчный анализ Train Ticket:**
  * На шагах 7 и 8 `PreserveServiceImpl#preserve` вызывает `checkSecurity(accountId)`.
  * `SecurityServiceImpl#check` выполняет два безусловных удаленных вызова:
    ```java
    OrderSecurity orderResult = getSecurityOrderInfoFromOrder(new Date(), accountId, headers);
    OrderSecurity orderOtherResult = getSecurityOrderOtherInfoFromOrder(new Date(), accountId, headers);
    ```
  * Второй вызов идет в `ts-order-other-service:OrderOtherController#securityInfoCheck`.
  * В сценарии $S_3$ пассажир покупает **только скоростные поезда** (`train_mode = gaotie_only`).
  * В текущей выдаче $S_3$ блок `ts-order-other-service` порождает **16 рёбер**:
    - 4 `executes`: `OrderOtherController#securityInfoCheck`, `OrderOtherServiceImpl#checkSecurityAboutOrder`, `SecurityServiceImpl#getSecurityOrderOtherInfoFromOrder`, `other.entity.Order#<init>()`
    - 10 `calls`: `String2Date`, `OrderStatus#getCode()`, `SeatClass#getCode()`, `Date2String`, `OrderSecurity#<init>()`
    - 1 `remote`: `getSecurityOrderOtherInfoFromOrder -> OrderOtherController#securityInfoCheck`
    - 1 `data`: `OrderOtherServiceImpl#checkSecurityAboutOrder -> ts-order-other-service.orders_other`
  * **Критический риск:** Если в эталоне организаторов для чистого GaoTie-сценария ($S_3$) обращения к сервису обычных поездов считаются выходящими за контекст сценария или если в тестовом стенде таблица `orders_other` не содержала записей пользователя (0 строк $\rightarrow$ отсутствие гидрации `Order#<init>()` и цикла по заказам), то от 4 до 16 рёбер являются **ложноположительными (FP)**.
* **Потенциальный прирост:** **+0.015 ... +0.025 к IoU $S_3$** (**+0.002 ... +0.0035 к общему скору**).
* **Метод проверки:** Абляционный флаг `--security-check-scope all|target_train_only`.

---

#### Гипотеза 3.5 (P1): Гидрация сущностей `other.entity.Order` внутри `checkSecurityAboutOrder`
* **Построчный анализ Train Ticket:**
  * Внутри `OrderOtherServiceImpl#checkSecurityAboutOrder`:
    `orderOtherRepository.findByAccountId(accountId)` загружает заказы из БД.
  * Согласно правилу R7, если запрос вернул записи, отрабатывает конструктор сущности `Order#<init>()`, вызывая `Date2String`, `OrderStatus#getCode()` и `SeatClass#getCode()`.
  * В калибровочном сценарии $S_0$ заказов в `ts-order-other-service` у пользователя не было.
  * Если `orders_other` в тестовой среде $S_3$ пуста для тестового аккаунта, то:
    - `executes: other.entity.Order#<init>()` — FP (1 ребро);
    - `calls: Order#<init>() -> Date2String, getCode` — FP (3 ребра);
    - Вызовы внутри цикла `for (Order order : orders)` (`order.getStatus() == OrderStatus.NOTPAID.getCode()`) — FP (2 ребра).
* **Потенциальный прирост:** Ликвидация 6 FP-рёбер в $S_3$ (+0.010 к IoU).
* **Метод проверки:** Тестовый прогон с проверкой размера выборки `orders_other` из контекста сценария.

---

### Группа C: Расчет тарифа и параметров багажа (Шаги 7 и 14)

#### Гипотеза 3.6 (P0): Ветка региональности `isWithinRegion` на шаге 14
* **Построчный анализ Train Ticket:**
  * Шаг 14: *«Check what a 0.5 kg consignment within the region costs»*.
  * Входной URL: `/consignprice/0.5/true`.
  * В `ConsignPriceServiceImpl#getPriceByWeightAndRegion(double weight, boolean isWithinRegion)`:
    ```java
    ConsignPrice priceConfig = repository.findByIndex(0);
    double price = 0;
    double initialPrice = priceConfig.getInitialPrice();
    if (weight <= priceConfig.getInitialWeight()) {
        price = initialPrice;
    } else {
        double extraWeight = weight - priceConfig.getInitialWeight();
        if (isWithinRegion) {
            price = initialPrice + extraWeight * priceConfig.getWithinPrice();
        } else {
            price = initialPrice + extraWeight * priceConfig.getBeyondPrice();
        }
    }
    return new Response<>(1, success, price);
    ```
  * Из дампа БД (`InitData.java`): `initialWeight = 1.0 kg`, `initialPrice = 8.0 RMB`.
  * Так как вес багажа равен 0.5 кг ($0.5 \le 1.0$), условие `weight <= initialWeight` истинно: возвращается `initialPrice`.
  * Ветка `else` (содержащая `isWithinRegion`) при динамическом исполнении **физически не выполняется**.
  * Проверить: не генерирует ли статический анализатор организаторов рёбра для ветки `isWithinRegion` (например, вызовы `getWithinPrice` или `getBeyondPrice`), если парсер организаторов использует грубый обход без вычисления константных условий.
* **Влияние на граф:** В Train Ticket `ConsignPrice` использует Lombok `@Data`, поэтому геттеры не входят в скелет. Влияние на граф возможно только через регистрацию в `branch_rules.json`.
* **Ожидаемый эффект:** Подтверждение корректности отсечения ветки `else` в M4.

---

#### Гипотеза 3.7 (P1): Консистентность параметров багажа между шагом 7 и шагом 14
* **Построчный анализ Train Ticket:**
  * На шаге 7 пассажир оформляет багаж 0.5 кг: `oti.getConsigneeWeight() == 0.5`.
  * При этом в шаге 7 флаг региональности `oti.isWithin()` по умолчанию равен `false`.
  * `ConsignServiceImpl#insertConsignRecord` шлет запрос:
    `/consignprice/0.5/false`.
  * На шаге 14 пассажир явно проверяет перевозку *«within the region»*:
    `/consignprice/0.5/true`.
  * Оба запроса дают одинаковый ответ (8.0 RMB) из-за непревышения базового веса 1.0 кг.
  * Шаг 14 дает 0 новых рёбер, поскольку метод `ConsignPriceServiceImpl#getPriceByWeightAndRegion` и таблица `consign_price` уже были активированы на шаге 7.
  * **Риск:** Если шаг 7 по какой-либо причине не должен был вызывать `ts-consign-price-service` (например, если расчет цены багажа кэшируется на клиенте), то на шаге 7 возникают лишние рёбра. Однако код `ConsignServiceImpl.java` (строка 68) доказывает прямой HTTP-вызов.
* **Вывод:** Шаг 14 полностью дублирует подграф шага 7; расхождений с кодовой базой нет.

---

### Группа D: Раздельная оплата двух заказов (Шаги 12 и 13)

#### Гипотеза 3.8 (P1): Мутация баланса счета и отсутствие внешней оплаты на шаге 13
* **Построчный анализ Train Ticket:**
  * На шаге 12 оплачивается Заказ 1 (~100 RMB), на шаге 13 — Заказ 2 (~50 RMB).
  * Метод `InsidePaymentServiceImpl#pay` суммирует все предыдущие платежи пользователя из таблицы `inside_payment` и сравнивает с пополнениями из `inside_money`:
    ```java
    List<Payment> payments = paymentRepository.findByUserId(userId);
    List<Money> addMonies = addMoneyRepository.findByUserId(userId);
    ...
    if (totalExpand.compareTo(money) > 0) { ... } // Внешняя оплата через ts-payment-service
    else {
        setOrderStatus(info.getTripId(), info.getOrderId(), headers);
        payment.setType(PaymentType.P);
        paymentRepository.save(payment);
    }
    ```
  * Из дампа БД: стартовый баланс `fdse_microservice` равен 10 000 RMB.
  * После оплаты Заказа 1 остаток превышает 9 800 RMB. Оплата Заказа 2 гарантированно идет по внутренней ветке (`PaymentType.P`).
  * Проверить: не порождает ли движок на шагах 12 или 13 ложных обращений к `ts-payment-service` или таблице `payment`.
  * По журналу `decisions.json`: вызов к `PaymentController#pay` в $S_3$ успешно **отсечен** правилом `BR_EXTERNAL_PAYMENT` (rules.py:481).
* **Вывод:** Ветвление оплаты в $S_3$ рассчитывается на 100% корректно.

---

#### Гипотеза 3.9 (P2): Литеральное задание статуса в `setOrderStatus` против Enum-вызовов
* **Построчный анализ Train Ticket:**
  * Внутри `InsidePaymentServiceImpl#pay` (строка 67) статус проверяется через enum:
    `if (order.getStatus() != OrderStatus.NOTPAID.getCode())` $\rightarrow$ ребро `calls` к `OrderStatus#getCode()`.
  * Однако внутри метода `InsidePaymentServiceImpl#setOrderStatus`:
    ```java
    Response setOrderStatus(String tripId, String orderId, HttpHeaders headers) {
        int orderStatus = 1; // Захардкоженный int-литерал, без вызова OrderStatus.PAID.getCode()!
        ...
        restTemplate.exchange(order_service_url + "/api/v1/orderservice/order/status/" + orderId + "/" + orderStatus, ...);
    }
    ```
  * Разработчики Train Ticket использовали примитивный литерал `1` вместо `OrderStatus.PAID.getCode()`.
  * Если статический анализатор связывал `setOrderStatus` с `OrderStatus#getCode()` по семантике назначения статуса, это формирует ложный `calls`.
  * Текущий парсер Archonity корректно видит литерал и не создает лишнего ребра от `setOrderStatus`.

---

### Группа E: Просмотр деталей заказов (Шаги 10 и 11)

#### Гипотеза 3.10 (P1): Соответствие шагов «Open order» реальным HTTP-запросам фронтенда
* **Построчный анализ Train Ticket:**
  * Шаг 10: *«Open the first new order»*.
  * Шаг 11: *«Open the second new order»*.
  * В эталоне M1 (`m1_steps.json`) оба шага заземлены на `OrderController#getOrderById`.
  * В JS-клиенте Train Ticket (`client_order_list.js`):
    - Все атрибуты заказа (ID, рейс, цена, места, статус) уже получены на шаге 9 вызовом `OrderController#queryOrdersForRefresh` и отрендерены в Vue-таблице `myOrderList`.
    - Нажатие на строку заказа в UI **не выполняет сетевого запроса** к бэкенду.
  * Однако на шагах 12 и 13 метод `InsidePaymentServiceImpl#pay` бэкенда сам выполняет GET к `OrderController#getOrderById` перед проведением транзакции.
  * **Следствие для графа:** Независимо от того, является ли действие «Open order» клиентским UI-событием (no HTTP) или отдельным запросом через шлюз, ребро `OrderController#getOrderById` и доступ к таблице `orders` присутствуют в итоговом графе через шаги оплаты 12 и 13.
* **Вывод:** Заземление шагов 10 и 11 не искажает Union-граф сценария.

---

### Группа F: Каталог страховок и станции питания (Шаги 4 и 15)

#### Гипотеза 3.11 (P1): Конструктор `Assurance#<init>` в шаге 7
* **Построчный анализ Train Ticket:**
  * На шаге 7 вызывается `AssuranceController#modifyAssurance` $\rightarrow$ `AssuranceServiceImpl#create(1, orderId)`.
  * В коде сервиса:
    `Assurance assurance = new Assurance(UUID.randomUUID().toString(), orderId, at);`
    `assuranceRepository.save(assurance);`
  * В отличие от загрузки через Hibernate, этот конструктор вызван проектным оператором `new`.
  * Конструктор `Assurance#<init>(String, String, AssuranceType)` присутствует в узлах скелета и в `submission.json` ($S_3$):
    - `executes: Assurance#<init>(java.lang.String,java.lang.String,assurance.entity.AssuranceType)`
    - `calls: AssuranceServiceImpl#create -> Assurance#<init>`
  * При этом конструктор без параметров `Assurance#<init>()` (для Hibernate) отсечен по правилу R7 (`R7:mode_excludes_ctor`).
* **Вывод:** Проектный конструктор учтен, reflection-конструктор исключен — строго по правилам R7.

---

#### Гипотеза 3.12 (P2): Отсутствие каскада `ts-station-food-service` при бронировании питания
* **Построчный анализ Train Ticket:**
  * На шаге 4 пассажир смотрит магазины на станции Сучжоу (`StationFoodController#getFoodStoresOfStation`), читая `station_food_store`. Таблица `station_food_list` отсечена по R10 (+0.006194).
  * На шаге 7 пассажир заказывает станционную еду (`foodType = 2`, `stationName = "Su Zhou"`, `storeName = ...`).
  * Метод `FoodServiceImpl#createFoodOrder` (`ts-food-service`) сохраняет заказ в `ts-food-service.food_order` и отправляет сообщение в RabbitMQ.
  * `createFoodOrder` **не делает никаких HTTP-запросов** к `ts-station-food-service` и не обращается к таблицам магазинов станции.
  * Проверить: не генерирует ли движок ложных повторных обращений к `station_food_store` на шаге 7.
  * По `decisions.json`: на шаге 7 обращений к `ts-station-food-service` нет.

---

### Группа G: Модель данных и JPA-коллекции

#### Гипотеза 3.13 (P1): Таблицы ленивых коллекций маршрута (`route_stations`, `route_distances`)
* **Построчный анализ Train Ticket:**
  * На шагах 2, 3 и 7 вызывается `RouteServiceImpl#getRouteById`.
  * В сущности `Route`:
    `route_stations` и `route_distances` — ленивые `@ElementCollection`.
  * В `BasicServiceImpl#queryForTravel`:
    `TravelResult result = new TravelResult(); result.setRoute(route);` — метод возвращает маршрут в DTO, не итерируясь по станциям внутри метода.
  * Однако в `PreserveServiceImpl#preserve` (строка 147):
    `List<String> stationList = resultForTravel.getRoute().getStations();`
    `dipatchSeat(..., stationList, ...);`
  * Коллекция `stations` физически используется при распределении мест!
  * Согласно правилу R10, таблица `route_stations` должна быть включена в `data`, если обращение произошло внутри проектного кадра, имеющего этот `data_access`.
  * Проверить: в `decisions.json` для $S_3$ обе таблицы (`route_stations` и `route_distances`) отсечены правилом `R10:lazy_not_loaded(lines 82)` от метода `RouteServiceImpl#getRouteById`.
  * **Потенциальный риск:** Если в эталоне организаторов обращение к `getStations()` в вызывающем сервисе признается основанием для включения `route_stations` в `data`, то в $S_3$ мы имеем **1 ложноотрицательное ребро (FN)**.
* **Потенциальный прирост:** **+0.003 ... +0.005 к IoU $S_3$**.
* **Метод проверки:** Тестовое включение `route_stations` при явном вызове `getStations()`.

---

#### Гипотеза 3.14 (P2): Колбэк равенства заказов `Order#equals` при повторном сохранении в шаге 8
* **Построчный анализ Train Ticket:**
  * В шаге 7 метод `OrderServiceImpl#create` выполняет:
    `accountOrders.contains(createOrder)` $\rightarrow$ вызывает `Order#equals` (правило R5, подтверждено платформой).
  * В шаге 8 оформляется второй заказ: `createOrder` вызывается снова.
  * К моменту шага 8 в БД уже сохранен Заказ 1. Число заказов пользователя увеличилось на 1.
  * `Order#equals` исполняется как на шаге 7, так и на шаге 8.
  * Поскольку в сабмишне учитывается множество вершин на сценарий, ребро `executes: Order#equals` уже включено шагом 7.
* **Вывод:** Повторный вызов `Order#equals` не меняет топологию Union-графа.

---

## 4. Сводная таблица гипотез и приоритизация проверки

| № | Гипотеза | Компонент | Тип ошибки | Ожидаемый эффект | Приоритет | Метод проверки |
|:---:|:---|:---|:---:|:---:|:---:|:---|
| **3.4** | Изоляция кросс-сервисного опроса `ts-order-other-service` при проверке безопасности | `ts-security-service` | FP (4–16 рёбер) | **+0.015 ... +0.025** | **P0 (Критический)** | Флаг `--security-check-scope gaotie_only` |
| **3.1** | Специфика распределения мест 2-го класса на шаге 8 | `ts-seat-service` | FN (2–4 ребра) | **+0.005 ... +0.008** | **P0 (Критический)** | Аудит веток `SeatServiceImpl` по `pool_ir.json` |
| **3.5** | Исключение гидрации `other.entity.Order` при пустой выборке | `ts-order-other-service` | FP (6 рёбер) | **+0.008 ... +0.012** | **P1 (Высокий)** | Проверка выборки в `checkSecurityAboutOrder` |
| **3.13** | Включение `route_stations` при явном `route.getStations()` | `ts-route-service` | FN (1 ребро) | **+0.003 ... +0.005** | **P1 (Высокий)** | Флаг `--route-stations-usage preserve` |
| **3.2** | Справочник типов документов `DocumentType` для попутчика | `ts-contacts-service` | FN (2 ребра) | **+0.003 ... +0.005** | **P1 (Высокий)** | Проверка AST call-site на шаге 6 |
| **3.6** | Верификация ветвления тарифа региональности багажа на шаге 14 | `ts-consign-price-service` | Инвариант | Защита M4 | P1 (Высокий) | Сверка с `branch_rules.json` |
| **3.3** | Проверка ветки `Seat Not Enough` на шаге 8 | `ts-preserve-service` | Инвариант | Защита M4 | P1 (Высокий) | Сверка статуса шага в M4 |
| **3.8** | Верификация списания баланса при двойной оплате (шаги 12–13) | `ts-inside-payment-service` | Инвариант | 0 FP/FN | P1 (Высокий) | Подтверждено по `decisions.json` |
| **3.10** | Соответствие UI-шагов «Open order» вызовам бэкенда | `ts-order-service` | Инвариант | 0 FP/FN | P1 (Высокий) | Закрыто шагами оплаты 12–13 |
| **3.11** | Проектный конструктор `Assurance#<init>` при создании страховки | `ts-assurance-service` | Инвариант | 0 FP/FN | P2 (Средний) | Подтверждено кодом (R7) |
| **3.7** | Соответствие параметров багажа между шагами 7 и 14 | `ts-consign-service` | Инвариант | 0 FP/FN | P2 (Средний) | Подтверждено кодом |
| **3.9** | Литерал `1` в `setOrderStatus` против Enum-вызовов | `ts-inside-payment-service` | Инвариант | 0 FP/FN | P2 (Средний) | Подтверждено AST |
| **3.12** | Изоляция каталога станционных блюд на шаге 7 | `ts-food-service` | Инвариант | 0 FP/FN | P2 (Средний) | Подтверждено `decisions.json` |
| **3.14** | Корректность исполнения `Order#equals` при двух заказах | `ts-order-service` | Инвариант | 0 FP/FN | P2 (Средний) | Подтверждено по R5 |

---

## 5. Рекомендованный план экспериментов по S3

1. **Эксперимент №1 (Гипотеза 3.4 — P0):**
   - Реализовать флаг селекции сервисов безопасности по режиму поезда:
     Если `profile.train_mode == "gaotie_only"`, отсекать переход от `SecurityServiceImpl#getSecurityOrderOtherInfoFromOrder` к `ts-order-other-service`.
   - Замерить дельту на калибровке $S_0$ (должна остаться строго **1.000000**, так как в $S_0$ режим `mixed`).
   - Провести проверочную посылку на NSUTS. Потенциал: сокращение разрыва $S_3$ с 0.905 до ~0.925.

2. **Эксперимент №2 (Гипотеза 3.1 — P0):**
   - Проверить наличие неразрешенных вызовов в цепочке `PreserveServiceImpl -> dipatchSeat -> SeatController -> SeatServiceImpl` для билетов 2-го класса (`SeatClass.SECONDCLASS`).
   - Сопоставить с новой функциональностью M4 `--m4-unresolved-calls emit`.

3. **Эксперимент №3 (Гипотеза 3.13 — P1):**
   - Проверить влияние добавления таблицы `res:table:ts-route-service.route_stations` в сценариях бронирования, где вызывается `resultForTravel.getRoute().getStations()`.
