# Комплексный аудит сценария S4 и пул гипотез для устранения отставания скора

> **Устарело.** Пул гипотез 18.10, балл 0.936, до [ADR-006](../adr/adr-006_constructor_visibility.md). Почти весь разрыв до 1.0 сидел в конструкторах, а не в ветках и шагах, поэтому оценки вклада гипотез здесь неверны. Текущее — [roadmap.md](../roadmap.md) и [agent_lessons.md](../agent_lessons.md).

**Дата составления:** 18.10.2026  
**Контекст:** Соревнование TECHARENA 2026, трек «Семантический граф микросервисной архитектуры»  
**Базовые документы:** [roadmap.md](../roadmap.md), [AGENTS.md](../../AGENTS.md), [ADR-005](../adr/adr-005_scenario_execution_pipeline.md), [annotation_rules.md](../annotation_rules.md), [next_day_hypotheses_and_todo.md](next_day_hypotheses_and_todo.md), [m4_executor.md](m4_executor.md), [m4_score_gap_and_judge.md](m4_score_gap_and_judge.md)  
**Текущий подтвержденный скор на платформе:** **0.936250** (M4 `--executor ir --m4-unresolved-calls emit`, Топ-10)  
**Текущий балл сценария S4 на платформе:** **~0.938** (прирост с 0.931118 после внедрения M4; для сравнения: $S_6 \approx 0.950$, $S_7 = 0.951$, $S_5 = 0.942$, $S_1 = 0.941$)  
**Цель исследования:** Детальная анатомия сценария $S_4$ (новый пользователь с нулевым балансом: регистрация, заказ со страховкой и поездной едой, внешняя оплата, расчет возврата и отмена), выявление источников ложноположительных (FP) и ложноотрицательных (FN) рёбер и формулирование пула из 12 целевых гипотез с потенциалом роста скора до 0.950+.

---

## 1. Анатомия сценария S4 и метрики графа

### 1.1. Описание пользовательского сценария S4

Сценарий $S_4$ представляет собой путь нового пользователя с пустым начальным состоянием:
1. **Шаг 1:** Регистрация нового пассажирского аккаунта (`UserController#registerUser`).
2. **Шаг 2:** Вход в систему с новым логином и паролем (`UserController#getToken`).
3. **Шаг 3:** Добавление контакта (себя) в пустую адресную книгу (`ContactsController#createNewContacts`).
4. **Шаг 4:** Поиск скоростных поездов Шанхай $\rightarrow$ Сучжоу на 01.10.2026 (`TravelController#queryInfo`).
5. **Шаг 5:** Открытие подробной информации о первом найденном рейсе (`TravelController#getTripAllDetailInfo`).
6. **Шаг 6:** Просмотр меню питания, предлагаемого в этом рейсе (`FoodController#getAllFood`).
7. **Шаг 7:** Бронирование билета 1-го класса для нового контакта с питанием в поезде (`foodType = 1`), страховкой первого типа (`assurance = 1`), без багажа (`PreserveController#preserve`).
8. **Шаг 8:** Обновление списка заказов пользователя (`OrderController#queryOrdersForRefresh`).
9. **Шаг 9:** Открытие нового созданного заказа (`OrderController#getOrderById`).
10. **Шаг 10:** Проверка цены заказа (`OrderController#getOrderPrice`).
11. **Шаг 11:** Оплата заказа: внутренний баланс пуст (0 RMB), оплата через внешний платежный канал (`InsidePaymentController#pay`).
12. **Шаг 12:** Запрос расчета суммы возврата при отмене билета (`CancelController#calculate`).
13. **Шаг 13:** Отмена оплаченного заказа с возвратом денег на внутренний баланс пользователя (`CancelController#cancelTicket`).
14. **Шаг 14:** Обновление списка заказов с фильтрацией по статусу «Cancel» (`OrderController#queryOrdersForRefresh`, `state = 4`).

---

### 1.2. Распределение рёбер в предсказании Archonity для S4

Всего в сабмишне Archonity для $S_4$ генерируется **497 рёбер**:

| Категория связи | Число рёбер в $S_4$ | Доля в графе | Число рёбер в $S_1$ (для сравнения) | Дельта $S_4 - S_1$ |
|:---|---:|---:|---:|---:|
| **executes** | 194 | 39.03% | 184 | +10 |
| **calls** | 224 | 45.07% | 206 | +18 |
| **remote** | 38 | 7.65% | 36 | +2 |
| **data** | 41 | 8.25% | 39 | +2 |
| **ИТОГО** | **497** | **100.0%** | **465** | **+32** |

---

### 1.3. Пошаговый маргинальный анализ вклада шагов в объединенный граф $S_4$

В соответствии с регламентом соревнования и правилом R20, итоговый граф сценария формируется как **теоретико-множественное объединение (Union)** графов исполнения всех шагов: $G(S) = \bigcup_{i=1}^{N} G(Step_i)$.

| Шаг | Входной обработчик | Всего рёбер шага | Уникальных для сценария | Маргинально новых в Union | Ключевая особенность шага |
|:---:|:---|---:|---:|---:|:---|
| **1** | `UserController#registerUser` | 20 | 18 | 20 | Регистрация: запись в `user`, REST к `auth`, запись в `auth_user` и `user_roles` |
| **2** | `UserController#getToken` | 21 | 19 | 19 | Аутентификация JWT: проверка пароля, чтение `auth_user` и `user_roles` |
| **3** | `ContactsController#createNewContacts` | 4 | 4 | 4 | Добавление контакта пассажира в пустую адресную книгу (`contacts`) |
| **4** | `TravelController#queryInfo` | 121 | 61 | 121 | Поиск скоростных поездов, опрос станций, маршрутов, цен, мест |
| **5** | `TravelController#getTripAllDetailInfo` | 121 | 0 | 61 | Детали рейса и остаток мест (`ts-seat-service`), частичная маскировка шагом 4 |
| **6** | `FoodController#getAllFood` | 42 | 31 | 31 | Поездное меню + каскад станций (подтверждено на платформе) |
| **7** | `PreserveController#preserve` | 261 | 131 | 140 | Билет 1 класса + еда в поезде + страховка 1 + RabbitMQ (без багажа) |
| **8** | `OrderController#queryOrdersForRefresh` | 22 | 1 | 15 | Обновление списка заказов пользователя без фильтров дат/статуса |
| **9** | `OrderController#getOrderById` | 11 | 0 | 4 | Чтение заказа; маскируется шагами 8 и 12 |
| **10** | `OrderController#getOrderPrice` | 11 | 4 | 4 | Чтение цены заказа из `orderRepository.findById` (без полного DTO) |
| **11** | `InsidePaymentController#pay` | 37 | 26 | 26 | Внешняя оплата: `PaymentType.O`, вызов `ts-payment-service`, запись `payment` |
| **12** | `CancelController#calculate` | 27 | 6 | 15 | Расчет 80% возврата: чтение заказа PAID, вызов `calculateRefund(order)` |
| **13** | `CancelController#cancelTicket` | 64 | 34 | 34 | Отмена: смена статуса на CANCEL, `drawbackMoney` на баланс (`inside_money`) |
| **14** | `OrderController#queryOrdersForRefresh` | 25 | 3 | 3 | Фильтрация по статусу CANCEL: цикл заказов, вызовы `String2Date` |

---

## 2. Ключевые архитектурные выводы из анализа шагов S4

1. **Уникальные функциональные подсистемы S4:**
   - Сценарий $S_4$ — единственный пользовательский сценарий, где задействован полный цикл регистрации и первичной авторизации (`ts-user-service` $\rightarrow$ `ts-auth-service`), порождающий 28 уникальных рёбер.
   - Сценарий $S_4$ — единственный сценарий с **внешней оплатой** (`ts-payment-service`), активируемой из-за нулевого баланса нового аккаунта.
   - Сценарий $S_4$ — единственный сценарий с отменой билета, где возврат уходит на внутренний баланс (`drawbackMoney` $\rightarrow$ `inside_money`).
2. **Асимметрия скора:**
   - Текущий балл $S_4$ составляет **~0.938** при размере графа 497 рёбер. Разрыв до уровня лидеров ($S_6 \approx 0.950$, $S_7 = 0.951$) составляет **~0.012–0.015 IoU**, что соответствует примерно **15–20 ошибочным рёбрам** (суммарно FP + FN).
3. **Уже проверенные на платформе факты по $S_4$ (не подлежат ревизии):**
   - **R13 (RabbitMQ к delivery):** доставка через брокер сообщений RabbitMQ на шаге 7 **обязательна**. Абляция снизила скор $S_4$ на **-0.015075** ([r13_rabbitmq_delivery_audit.md](r13_rabbitmq_delivery_audit.md)).
   - **R10 (station_food_list в шаге 6):** при запросе полного меню рейса (`getAllFood`) таблица `station_food_list` **обязательна**. Глобальное отсечение снижало $S_4$ на **-0.0061** ([station_food_list_step4_audit.md](station_food_list_step4_audit.md)).
   - **Каскад getAllFood к ts-station-food-service в шаге 6:** подтвержден платформой (посылка 1664975, [trip_food_query_audit.md](trip_food_query_audit.md)).
   - **R10 (route_distances):** таблица расстояний маршрута исключена при поиске скоростных поездов (посылка 1664977, [route_distances_s5_audit.md](route_distances_s5_audit.md)).
   - **R7 (Hibernate entity constructor hydration):** конструкторы без проектных вызовов (`User#<init>`, `Route#<init>`) отсекаются по правилу R7 ([r7_score_drop.md](r7_score_drop.md)).

---

## 3. Пул гипотез для сценария S4

Ниже представлены 12 детально проработанных гипотез, сгруппированных по функциональным подсистемам.

---

### Группа A: Проверка безопасности и кросс-сервисный опрос (Шаг 7)

#### Гипотеза 4.1 (P0): Ложные вызовы к `ts-order-other-service` при проверке безопасности в S4
* **Построчный анализ Train Ticket:**
  * На шаге 7 `PreserveServiceImpl#preserve` вызывает `checkSecurity(accountId)`.
  * В `SecurityServiceImpl#check`:
    ```java
    OrderSecurity orderResult = getSecurityOrderInfoFromOrder(new Date(), accountId, headers);
    OrderSecurity orderOtherResult = getSecurityOrderOtherInfoFromOrder(new Date(), accountId, headers);
    ```
  * Второй вызов уходит в `ts-order-other-service:OrderOtherController#securityInfoCheck`.
  * В сценарии $S_4$ пассажир покупает билет на **скоростной поезд** GaoTie (`tripGD`), а сам пользователь — **новый** (у него вообще нет истории заказов).
  * В текущей выдаче $S_4$ блок `ts-order-other-service` формирует **7 рёбер**:
    - `remote`: `SecurityServiceImpl#getSecurityOrderOtherInfoFromOrder -> OrderOtherController#securityInfoCheck`
    - `executes`: `OrderOtherController#securityInfoCheck`
    - `executes`: `OrderOtherServiceImpl#checkSecurityAboutOrder`
    - `calls`: `OrderOtherController#securityInfoCheck -> StringUtils#String2Date`
    - `calls`: `OrderOtherController#securityInfoCheck -> OrderOtherServiceImpl#checkSecurityAboutOrder`
    - `calls`: `OrderOtherServiceImpl#checkSecurityAboutOrder -> OrderSecurity#<init>()`
    - `data`: `OrderOtherServiceImpl#checkSecurityAboutOrder -> ts-order-other-service.orders_other`
  * **Критический риск:** Если в эталоне организаторов для скоростных сценариев вызовы к сервису обычных поездов считаются шумом, не относящимся к сценарию, то все 7 рёбер являются **ложноположительными (FP)**.
* **Влияние на граф:** Ликвидация 7 FP рёбер.
* **Потенциальный прирост:** **+0.010 ... +0.014 к IoU $S_4$** (**+0.0014 ... +0.0020 к общему скору**).
* **Метод проверки:** Абляционный флаг `--security-check-scope all|target_train_only`.

---

### Группа B: Внешняя оплата и нулевой баланс (Шаг 11)

#### Гипотеза 4.2 (P0): Чистота внешней оплаты на шаге 11 (только `payment`, без `inside_money.save`)
* **Построчный анализ Train Ticket:**
  * Шаг 11: *«Pay for the order: the internal balance is empty, so the payment is completed through the external payment channel»*.
  * В `InsidePaymentServiceImpl#pay`:
    - `paymentRepository.findByUserId(userId)` возвращает пустой список.
    - `addMoneyRepository.findByUserId(userId)` возвращает пустой список.
    - `totalExpand > money` (цена билета > 0 RMB) $\rightarrow$ ветка `true`.
    - Вызывается внешний платежный сервис: `ts-payment-service:PaymentController#pay`.
    - В `PaymentServiceImpl#pay`: запись в `ts-payment-service.payment`.
    - В `InsidePaymentServiceImpl#pay`: сохраняется запись `PaymentType.O` в `inside_payment`.
    - Вызывается `setOrderStatus` $\rightarrow$ `ts-order-service:OrderController#modifyOrder` (статус 1 = PAID).
  * Таблица `inside_money` **не модифицируется** (отсутствует `addMoneyRepository.save`).
  * Проверить: не генерирует ли движок ошибочных записей мутации `inside_money` на шаге 11.
* **Влияние на граф:** Инвариант чистоты ветки (подтверждено: ребро мутации отсутствует).
* **Ожидаемый эффект:** Защита от деградации при доработках исполнителя M4.

---

#### Гипотеза 4.3 (P1): Проектный вызов конструктора `Payment#<init>()` в `ts-payment-service`
* **Построчный анализ Train Ticket:**
  * В `PaymentServiceImpl#pay` (строка 36):
    `Payment payment = new Payment();`
  * В отличие от Hibernate reflection, здесь объект создается через явный оператор `new`.
  * Согласно правилу R7, проектные вызовы конструкторов должны включаться в `executes` и `calls`.
  * В текущей выдаче $S_4$:
    - `executes: Payment#<init>()`
    - `calls: PaymentServiceImpl#pay -> Payment#<init>()`
  * Проверить наличие узла `Payment#<init>()` в скелете организаторов и корректность связывания.
* **Влияние на граф:** 2 валидных ребра (подтверждено по коду).

---

### Группа C: Отмена билета и возврат на баланс (Шаги 12–13)

#### Гипотеза 4.4 (P0): Полная цепочка возврата `drawbackMoney` на внутренний баланс на шаге 13
* **Построчный анализ Train Ticket:**
  * Шаг 13: *«Cancel the paid order (the refund goes back to the internal balance)»*.
  * В `CancelServiceImpl#cancelOrder`:
    - `orderResult = getOrderByIdFromOrder(orderId)` $\rightarrow$ заказ найден со статусом `PAID` (1).
    - `cancelFromOrder(order)` $\rightarrow$ вызов `ts-order-service:OrderController#saveOrderInfo` $\rightarrow$ `OrderServiceImpl#saveChanges` (статус CANCEL = 4, запись в `orders`).
    - `money = calculateRefund(order)` $\rightarrow$ вычисление 80% от цены билета.
    - `drawbackMoney(money, loginId)` $\rightarrow$ REST GET к `InsidePaymentController#drawBack`.
    - В `InsidePaymentServiceImpl#drawBack`:
      `Money addMoney = new Money(); addMoney.setMoney(money); addMoney.setType(MoneyType.D); addMoneyRepository.save(addMoney);` $\rightarrow$ запись в `inside_money`.
    - `getAccount(order.getAccountId())` $\rightarrow$ REST GET к `UserController#getUserByUserId` $\rightarrow$ чтение `user`.
  * Всего цепочка возврата на шаге 13 генерирует **10 рёбер**:
    - 4 `executes`: `drawbackMoney`, `InsidePaymentController#drawBack`, `InsidePaymentServiceImpl#drawBack`, `Money#<init>()`
    - 4 `calls`: вызовы внутри контроллера/сервиса
    - 1 `remote`: `CancelServiceImpl#drawbackMoney -> InsidePaymentController#drawBack`
    - 1 `data`: `InsidePaymentServiceImpl#drawBack -> ts-inside-payment-service.inside_money`
  * Проверить: не уходят ли ошибочные вызовы в `ts-order-other-service` из блока `else` в `cancelOrder`.
* **Влияние на граф:** 10 ключевых рёбер возврата, изоляция `order-other`.
* **Потенциальный прирост:** Защита от деградации, подтверждение точности ветвления.

---

#### Гипотеза 4.5 (P1): Изоляция зондирующего расчета возврата на шаге 12 (`calculateRefund`)
* **Построчный анализ Train Ticket:**
  * Шаг 12: *«Ask how much would be refunded if the paid order were cancelled»*.
  * Входной метод: `CancelController#calculate`.
  * `CancelServiceImpl#calculateRefund(String orderId)`:
    - Заказ читается из `ts-order-service`, статус равен `PAID`.
    - Вызывается вспомогательный метод `calculateRefund(Order order)`, вычисляющий `0.8 * price`.
    - Метод `drawbackMoney` **не вызывается**, статус заказа **не меняется**, обращений к `inside_payment` нет.
  * В текущей выдаче шаг 12 содержит только `ts-cancel-service`, `ts-common`, `ts-order-service`.
* **Влияние на граф:** Инвариант (0 FP).

---

### Группа D: Регистрация и первичная аутентификация (Шаги 1–2)

#### Гипотеза 4.6 (P1): Запись коллекции ролей `user_roles` в `ts-auth-service` на шагах 1 и 2
* **Построчный анализ Train Ticket:**
  * На шаге 1 `UserServiceImpl#createDefaultAuthUser` создает сущность `auth.entity.User` с коллекцией `roles`:
    `roles(new HashSet<>(Arrays.asList(AuthConstant.ROLE_USER)))`
  * В JPA `@ElementCollection private Set<String> roles` мапится на таблицу `ts-auth-service.user_roles`.
  * При `userRepository.save(user)` данные сохраняются в две таблицы: `auth_user` и `user_roles`.
  * На шаге 2 `TokenServiceImpl#getToken` проверяет роли: происходит обращение к `user_roles`.
  * Обе таблицы (`auth_user`, `user_roles`) включены в `data` на шагах 1 и 2.
  * Проверить: не порождает ли сохранение ролей паразитных вызовов конструкторов сущностей, отсутствующих в скелете.
* **Влияние на граф:** Инвариант точности `data`.

---

#### Гипотеза 4.7 (P2): Отсутствие конструктора `User#<init>()` при создании через Lombok `@Builder`
* **Построчный анализ Train Ticket:**
  * В `UserServiceImpl#saveUser`:
    `User user = User.builder()...build();`
  * В кодовой базе Train Ticket для `User` используется аннотация Lombok `@Builder`.
  * Конструктор по умолчанию без параметров `User#<init>()` в исходном коде не вызывается (вызывается скрытый конструктор со всеми полями).
  * При чтении `findByUserName` для нового пользователя возвращается `null` (нет строк для гидрации).
  * Согласно правилу R7, конструктор `User#<init>()` справедливо отсечен из графа S4.
* **Влияние на граф:** Инвариант чистоты (0 FP).

---

### Группа E: Фильтрация заказов по статусу отмены (Шаг 14)

#### Гипотеза 4.8 (P1): Вызовы `StringUtils.String2Date` в цикле `queryOrders` при `enableStateQuery == true`
* **Построчный анализ Train Ticket:**
  * Шаг 14: *«Refresh the list of orders filtered by the 'Cancel' status»*.
  * Входные параметры: `enableStateQuery: true`, `state: 4`.
  * В `OrderServiceImpl#queryOrders`:
    ```java
    if (qi.isEnableStateQuery() || qi.isEnableBoughtDateQuery() || qi.isEnableTravelDateQuery()) {
        ArrayList<Order> finalList = new ArrayList<>();
        for (Order tempOrder : list) {
            ...
            Date boughtDate = StringUtils.String2Date(tempOrder.getBoughtDate());
            Date travelDate = StringUtils.String2Date(tempOrder.getTravelDate());
            Date travelDateEnd = StringUtils.String2Date(qi.getTravelDateEnd());
            Date boughtDateStart = StringUtils.String2Date(qi.getBoughtDateStart());
            Date boughtDateEnd = StringUtils.String2Date(qi.getBoughtDateEnd());
            if (qi.isEnableTravelDateQuery()) { ... }
            if (qi.isEnableBoughtDateQuery()) { ... }
            if (statePassFlag && boughtDatePassFlag && travelDatePassFlag) {
                finalList.add(tempOrder);
            }
        }
    }
    ```
  * Вызовы `StringUtils.String2Date` стоят **до** условий проверки флагов дат и выполняются безусловно для каждого заказа в цикле.
  * На шаге 14 заказ в списке есть (он отменен на шаге 13), поэтому вызовы `String2Date` исполняются.
  * На шаге 8 все три флага равны `false`, поэтому блок `if` не исполняется и вызовов `String2Date` нет.
  * В текущей выдаче ребро `OrderServiceImpl#queryOrders -> StringUtils#String2Date` включено строго на шаге 14.
* **Влияние на граф:** 2 ребра (`calls`, `executes`).

---

#### Гипотеза 4.9 (P2): Недостижимость закомментированного вызова `queryForStationId` на шагах 8 и 14
* **Построчный анализ Train Ticket:**
  * В `OrderServiceImpl#queryOrdersForRefresh` (строка 200):
    `// List<String> names = queryForStationId(stationIds, headers);`
  * Вызов закомментирован разработчиками Train Ticket.
  * Любые обращения к `ts-station-service:StationController#queryForStationId` из этого контекста являются шумом.
  * В текущей выдаче $S_4$ на шагах 8 и 14 обращения к `ts-station-service` отсутствуют.
* **Влияние на граф:** Инвариант чистоты (0 FP).

---

### Группа F: Бронирование и сопутствующие опции (Шаг 7)

#### Гипотеза 4.10 (P1): Полная изоляция багажной подсистемы при бронировании без багажа
* **Построчный анализ Train Ticket:**
  * Шаг 7: *«Book a first-class seat on the trip for the new contact, with food on the train and assurance (insurance) of the first type, without consignment»*.
  * В `PreserveServiceImpl#preserve`:
    `if (null != oti.getConsigneeName() && !"".equals(oti.getConsigneeName()))`
  * Поскольку багаж не оформляется (`consigneeName == null`), ветка `createConsign` полностью отсекается.
  * Никаких обращений к `ts-consign-service`, `ts-consign-price-service`, таблицам `consign_record`, `consign_price` быть не должно.
  * В текущей выдаче $S_4$ число рёбер с `consign` равно строго 0.
* **Влияние на граф:** Инвариант чистоты (0 FP).

---

#### Гипотеза 4.11 (P1): Проектный конструктор `Assurance#<init>` при оформлении страховки
* **Построчный анализ Train Ticket:**
  * Шаг 7 включает страховку 1 типа (`assurance = 1`).
  * `AssuranceServiceImpl#create`:
    `Assurance assurance = new Assurance(UUID.randomUUID().toString(), orderId, at);`
  * Вызывается проектный конструктор с 3 параметрами: `Assurance#<init>(String, String, AssuranceType)`.
  * Reflection-конструктор без параметров `Assurance#<init>()` (для JPA) справедливо отсечен по R7.
* **Влияние на граф:** Инвариант (подтверждено: включен в `executes` и `calls`).

---

#### Гипотеза 4.12 (P2): Отсутствие каскада станционной еды при покупке поездной еды на шаге 7
* **Построчный анализ Train Ticket:**
  * На шаге 7 пассажир заказывает питание в поезде (`foodType = 1`).
  * `FoodServiceImpl#createFoodOrder` заполняет `food_order`, не выполняя запросов к `ts-station-food-service` и не обращаясь к таблицам станционных блюд.
  * На шаге 7 рёбра к `station_food_store` и `station_food_list` отсутствуют.
* **Влияние на граф:** Инвариант чистоты.

---

## 4. Сводная таблица гипотез и приоритизация проверки

| № | Гипотеза | Компонент | Тип ошибки | Ожидаемый эффект | Приоритет | Метод проверки |
|:---:|:---|:---|:---:|:---:|:---:|:---|
| **4.1** | Изоляция кросс-сервисного опроса `ts-order-other-service` при `checkSecurity` | `ts-security-service` | FP (7 рёбер) | **+0.010 ... +0.014** | **P0 (Критический)** | Абляционный флаг `--security-check-scope gaotie_only` |
| **4.2** | Верификация внешней оплаты: отсутствие мутаций `inside_money` на шаге 11 | `ts-inside-payment-service` | Инвариант | Защита M4 | **P0 (Критический)** | Сверка по `decisions.json` |
| **4.4** | Согласованность цепочки `drawbackMoney` на шаге 13 | `ts-cancel-service` | Инвариант | Защита M4 | **P0 (Критический)** | Сверка по `decisions.json` |
| **4.3** | Проектный конструктор `Payment#<init>()` при внешней оплате | `ts-payment-service` | Инвариант | 0 FP/FN | P1 (Высокий) | Сверка по `pool_ir.json` |
| **4.8** | Вызовы `String2Date` в цикле фильтрации по статусу CANCEL на шаге 14 | `ts-order-service` | Инвариант | 0 FP/FN | P1 (Высокий) | Сверка Call-site в IR |
| **4.6** | Коллекция ролей `user_roles` при регистрации на шаге 1 | `ts-auth-service` | Инвариант | 0 FP/FN | P1 (Высокий) | Сверка схемы JPA |
| **4.10** | Полная изоляция багажной подсистемы на шаге 7 | `ts-preserve-service` | Инвариант | 0 FP | P1 (Высокий) | Подтверждено (0 рёбер) |
| **4.11** | Проектный конструктор `Assurance#<init>` на шаге 7 | `ts-assurance-service` | Инвариант | 0 FP/FN | P1 (Высокий) | Подтверждено по коду |
| **4.5** | Изоляция зондирующего расчета возврата на шаге 12 | `ts-cancel-service` | Инвариант | 0 FP | P2 (Средний) | Подтверждено по `decisions.json` |
| **4.7** | Отсутствие конструктора `User#<init>()` при Lombok `@Builder` | `ts-user-service` | Инвариант | 0 FP | P2 (Средний) | Подтверждено правилом R7 |
| **4.9** | Изоляция запроса цены `getOrderPrice` на шаге 10 | `ts-order-service` | Инвариант | 0 FP | P2 (Средний) | Подтверждено по коду |
| **4.12** | Отсутствие станционной еды при бронировании поездного питания на шаге 7 | `ts-food-service` | Инвариант | 0 FP | P2 (Средний) | Подтверждено (0 рёбер) |

---

## 5. План дальнейшей верификации и абляций

1. **Главная точка роста скора — Гипотеза 4.1 (P0):**
   - Провести совместную абляцию с гипотезой 3.4 сценария $S_3$: флаг `--security-check-scope all|target_train_only`.
   - В сценариях $S_3$ и $S_4$ поезда строго GaoTie (`tripGD`), а обращения к `ts-order-other-service` дают 16 рёбер в $S_3$ и 7 рёбер в $S_4$.
   - Потенциальный суммарный эффект на платформе: ликвидация до 23 ложноположительных рёбер, что может дать рост общего скора на **+0.003 ... +0.005** (с 0.93625 до 0.940+).
2. **Контроль инвариантов качества:**
   - Сохранение калибровочного скора $S_0 = 1.000000$ (все 4 типа связей 100%).
   - Регрессионный прогон набора из 331 теста (`uv run pytest tests`).
