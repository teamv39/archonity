# S3: трасса слепой разметки

Сценарий: семейная поездка на D1345, два заказа, новый контакт, еда, страховка, груз 0.5 кг, оплата обоих заказов.

Ответ: `eval/blind/S3.json`: 170 `executes`, 195 `calls`, 30 `remote`, 35 `data`. Формат проверен `evaluate_golden.py`: принято 423 ребра, отклонённых нет.

Пути к исходникам ниже даны от `hackaton/tt-challenge/targets/trainticket/`. Состояние БД взято из `context/db-after-warmup.sql.gz`. Пассажир: `fdse_microservice`, id `4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f`.

Пометки:
- **[Д]** — допущение: по данным не выводится, решено по тексту шага.
- **[Г]** — гипотеза разметки: правило не подтверждено эталоном.

## Сквозные решения

| Что | Решение | Откуда |
| --- | --- | --- |
| `JWTFilter#doFilterInternal` | `executes` на каждом запросе, без `calls` | R5 |
| `JWTUtil.*` | не выводим | R9 |
| Конструкторы сущностей, созданные Hibernate | только `order.entity.Order#<init>()`, `other.entity.Order#<init>()`: в них есть вызовы проекта (`Date2String`, `getCode`). Пустые или с одним `UUID` (`Trip`, `TripId`, `Station`, `TrainType`, `Route`, `PriceConfig`, `Config`, `SecurityConfig`, `Contacts`, `User`, `ConsignPrice`, `Money`, `Assurance`, `StationFoodStore`, `Delivery`) не выводим | R7 (`project_calls`) |
| Конструкторы через `new` из проекта | `executes` + `calls` от вызывающего метода | R7, последний абзац |
| Объекты, созданные Jackson | не выводим | R8 |
| Вызовы enum-констант (`SeatClass.FIRSTCLASS.getCode()`, `OrderStatus.NOTPAID.getCode()`) | разрешены вручную в `edu.fudan.common.entity.SeatClass#getCode()` / `OrderStatus#getCode()` (импорт `edu.fudan.common.entity.*`) | R7: в скелете у таких call_site нет рёбер |
| `trip.getTripId().toString()` | `edu.fudan.common.entity.TripId#toString()` → `Type#getName()` | `ts-common/.../TripId.java:41-44` |
| Конструкторы enum (`SeatClass`, `AssuranceType`, `PaymentType` …) | не выводим: класс загружен ещё при прогреве | Д: сервисы между сценариями не перезапускаются |
| Уровень логов | INFO (настроек `logging` в сервисах нет) | важно для H1–H3 |

## Шаг 1. Вход

Запрос `POST /api/v1/users/login` (`ts-ui-dashboard/static/assets/js/client_login.js:47`) → `auth.controller.UserController#getToken`.

- `TokenServiceImpl.java:65` `!StringUtils.isEmpty(verifyCode)` → false: кода нет (`context/README.md`). Remote в verification-code не уходит.
- `TokenServiceImpl.java:84` `authenticate` проходит → `loadUserByUsername` и методы `UserDetails` у `User`. Без `calls`, кроме `getToken → User#getPassword` (R6).
- `TokenServiceImpl.java:91` `orElseThrow`: пользователь найден, лямбда не вызывается (R16).
- `data`: `loadUserByUsername → auth_user`; `getToken → auth_user, user_roles` (R10).

Совпадает с S0, калибровка 1.0.

## Шаг 2. Поиск G/D Шанхай → Сучжоу на 01.10.2026

Запрос `POST /api/v1/travelservice/trips/left` (`index.js:118-119`: `train_type == 1` → только travel-service) → `TravelController#queryInfo`.

- **[Д]** `startPlace="shanghai"`, `endPlace="suzhou"`. UI по умолчанию подставляет `'Shang Hai'`/`'Su Zhou'` (`index.js:4-5`), но `TripInfo#getStartPlace` только переводит в нижний регистр (`TripInfo.java:37`), а станции в БД — `shanghai`, `suzhou`. Шаг говорит о «первом найденном рейсе», значит, поиск что-то находит.
- **[Д]** `departureTime="2026-10-01 00:00:00"`, как в UI (`index.js:109`). Ветки это не меняет, см. ниже про seat.
- `TravelController.java:115-117`: поля не пустые → `queryByBatch`.
- `TravelServiceImpl.java:214` `findAll` → 6 рейсов (`trip`).
- `TravelServiceImpl.java:325` `afterToday("2026-10-01 …")`: часы 15.09.2026 → true.
- Цикл по 6 рейсам (`:332-341`): `new travel.entity.Travel()`, `TripId#toString`.
- Remote → `BasicController#queryForTravels`.
  - `BasicServiceImpl.java:186` станции `shanghai`, `suzhou` есть → `StationController#queryForIdBatch` (`station`).
  - `:206` типы GaoTieOne/DongCheOne/GaoTieTwo есть → `TrainController#retrieveByName(List)` (`train_type`).
  - `:229` маршруты → `RouteController#queryByIds` (`route`). Коллекции маршрута не грузятся в методе, ребра к `route_stations`/`route_distances` нет (R10).
  - `:250-256` фильтр маршрутов. Остаётся **только D1345** (маршрут `f3d4d4ef`: shanghai(0) → suzhou(1)). G1234/G1236: suzhou раньше shanghai. G1235/G9998: нет suzhou. G1237: маршрут suzhou → shanghai.
  - `:272` цены → `PriceController#query(List)` (`price_config`, найдено `f3d4d4ef:DongCheOne`).
  - `:309` один `new TravelResult()`.
  - **[Г] H1**: `:319` `LOGGER.info("…result map: {}", trMap)` → Lombok-`TravelResult.toString()` вызывает рукописный `TravelResult#isStatus()` (Lombok по умолчанию берёт геттеры). Поставлен только `executes`: ближайший проектный кадр — `queryForTravels`, call_site с именем `isStatus` у него нет.
- `TravelServiceImpl.java:367` один элемент → `setResponse` → два `getRestTicketNumber` (FIRSTCLASS, SECONDCLASS) → remote `SeatController#getLeftTicketOfInterval`.
  - `SeatServiceImpl.java:138` `D1345` начинается с `D` → `OrderController#getTicketListByDateAndTripId` (не order-other).
  - `OrderServiceImpl.java:55` `findByTravelDateAndTrainNumber("2026-10-01 00:00:00","D1345")`: `travel_date` — varchar, в БД `2026-10-01` → пусто → ветка `:68` (`Response(0)`). При дате `2026-10-01` (шаги 3, 7, 8) находится 6 заказов → `Ticket#<init>(int,…)`, `LeftTicketInfo#<init>()`, явный `leftTicketInfo.toString()` (`:65`). Итоговое множество рёбер от формата даты в этом шаге не зависит.
  - `SeatServiceImpl.java:174` `leftTicketInfo` здесь `null`, на шагах 3/7/8 непуст. `:190` `getDirectProportion` → `ConfigController#retrieve` (`config`).
  - `:192` маршрут [shanghai, suzhou] совпадает с запросом, ветка «do nothing».
  - **[Г] H2**: `SeatServiceImpl.java:151` `LOGGER.info("…{}", re3)` → `ResponseEntity.toString` → Lombok-`Response.toString` → `LeftTicketInfo#toString()` (на шагах 3/7/8, где данные не `null`). Ребро `getLeftTicketOfInterval → LeftTicketInfo#toString` поставлено по R6: у метода есть call_site `toString` (`:137`).

## Шаг 3. Детали первого рейса

У UI нет отдельного запроса деталей (`client_ticket_book.js` при загрузке шлёт только контакты, страховки и еду). Обработчик выбран по коду: **[Д]** `POST /api/v1/travelservice/trip_detail` → `TravelController#getTripAllDetailInfo`, `tripId=D1345`, `from=shanghai`, `to=suzhou`, `travelDate=2026-10-01` (дата страницы бронирования без времени, `index.js:233`).

Тот же путь вызывает preserve на шагах 7–8 (`PreserveServiceImpl.java:78`), поэтому выбор почти не влияет на рёбра.

- `TravelServiceImpl.java:299` `findByTripId(new TripId("D1345"))` → найден (`:300` false). `TripId(String)`: `switch` по `D` (`TripId.java:21-36`), проектных вызовов нет.
- `:308` `getTickets` → `afterToday` true → `new Travel()` → remote `BasicController#queryForTravel`.
  - **[Г] H3**: `BasicController.java:38` `info.toString()` → Lombok `Travel` → Lombok `Trip` → `TripId#toString()`. Ребро `BasicController#queryForTravel → TripId#toString` поставлено по R6 (имя call_site `toString`).
  - `BasicServiceImpl.java:49-51` обе станции есть (`StationController#queryForStationId` ×2, `station`).
  - `:62` тип поезда есть (`TrainController#retrieveByName(String)`, `train_type`).
  - `:74` маршрут есть (`RouteController#queryById`, только `route` — R10).
  - `:85-87` shanghai < suzhou → дальше. `:98` цена (`PriceController#query(String,String)`, `price_config`).
  - `:119` лог `result` → H1 (то же `isStatus`).
- `TravelServiceImpl.java:403` статус 1 → `conveterObject` → `setResponse` (как в шаге 2, но seat получает заказы).
- `:309` `tripResponse != null` → второй `findByTripId` (`:316`).

## Шаг 4. Магазины еды на станции Сучжоу

**[Д]** `GET /api/v1/stationfoodservice/stationfoodstores/suzhou` → `StationFoodController#getFoodStoresOfStation`. Альтернатива — UI-запрос `/foodservice/foods/{date}/{from}/{to}/{tripId}` (`client_ticket_book.js:194`). Но он возвращает еду поезда и магазины обеих станций, а шаг называет одну станцию и именно «food stores».

- `StationFoodServiceImpl.java:80` `findByStationName("suzhou")` → 1 магазин (`Roman Holiday`). Список еды `EAGER` (`StationFoodStore.java:38`) → `station_food_store` и `station_food_list` от этого метода (R10, последний пункт).

## Шаг 5. Контакты, первый контакт

`GET /api/v1/contactservice/contacts/account/{id}` (`client_ticket_book.js:58`) → `findContactsByAccountId` → `contacts`. У пассажира 4 контакта (в README пакета сказано «один», в дампе их 4), первый по ответу системы.

## Шаг 6. Новый контакт

`POST /api/v1/contactservice/contacts` (`client_ticket_book.js:574`) → `ContactsController#createNewContacts` → `ContactsServiceImpl#create` (не `createContacts`).

- `ContactsServiceImpl.java:65` `c != null` → false: **[Д]** новый документ, такого контакта нет.
- `:69` `save` без id → `persist`. `Contacts#equals/hashCode` не вызываются: Hibernate хранит сущности по identity.

## Шаги 7–8. Бронирование

`POST /api/v1/preserveservice/preserve` (`client_ticket_book.js:508-512`: `D` → preserveservice) → `PreserveController#preserve`.

Тело шага 7: `seatType=2` (FIRSTCLASS, `client_ticket_book.js:445-450`), `date=2026-10-01`, `assurance=1`, `foodType=2`, **[Д]** `stationName=suzhou` и `storeName=Roman Holiday` (магазин из шага 4), `consigneeName` задан, `consigneeWeight=0.5`, `isWithin=false` (`:500`).
Тело шага 8: `seatType=3`, `assurance=0`, `foodType=0`, `consigneeName` не задан, контакт из шага 6.

| Место | Шаг 7 | Шаг 8 | Основание |
| --- | --- | --- | --- |
| `PreserveServiceImpl.java:53` проверка безопасности | проходит | проходит | лимиты `2147483647` в `security_config` (`SecurityServiceImpl.java:122`) |
| `:63` контакт найден | да | да (создан в шаге 6) | |
| `:81` детали рейса | статус 1 | статус 1 | шаг 3 |
| `:87` / `:93` хватает мест | да | да | `confort_class`/`economy_class` у DongCheOne = `2147483647` |
| `:135` basic `queryForTravel` | статус 1 | статус 1 | шаг 3 |
| `:147-166` класс | FIRSTCLASS, цена `confortClass=50.0` | SECONDCLASS, цена `22.5` | расстояние 50 (`route_distances`), коэффициенты 1 / 0.45 |
| `:171` заказ создан | да | да | |
| `:178` страховка | `assurance=1` → `addAssuranceForOrder` | `0` → пропуск | |
| `:192` еда | `foodType=2` → `createFoodOrder` | `0` → пропуск | |
| `:218` груз | `consigneeName` задан → `createConsign` | `null` → пропуск | |
| `:245` `getAccount` | да | да | |
| `:261` `sendEmail` | закомментирован | закомментирован | RabbitMQ уведомлений нет |

Подробности удалённых вызовов:

- **security** (`SecurityServiceImpl#check`): оба `securityInfoCheck`. `checkDate` = `Date.toString()` → `String2Date` возвращает `new Date(0)` без исключения (`StringUtils.java:26-27`). Цикл по заказам непуст в обоих сервисах → `OrderStatus#getCode`, `String2Date`, `Order#<init>()` обоих сервисов. `data`: `orders`, `orders_other`, `security_config`.
- **seat** (`SeatServiceImpl#distributeSeat`): `:53` D → order-service. Проданные билеты есть (дата `2026-10-01`). `:103` конечная станция `suzhou` (индекс 1) не раньше начальной `shanghai` (0) → повторно место не выдаётся → `:108` `isContained`, новое место. `:66` явный `re3.getBody().toString()` → `LeftTicketInfo#toString()`. **[Г] H2**: ребро `distributeSeat → LeftTicketInfo#toString` поставлено по R6.
- **order** (`OrderServiceImpl#create`): `:89` заказы владельца есть → `:90` `contains` → `order.entity.Order#equals` (`executes`, R5). Новый → `save`.
- **assurance** (шаг 7): `AssuranceServiceImpl.java:56` `a != null` → false (заказ новый). `:59` `getTypeByIndex(1)` → `TRAFFIC_ACCIDENT` (`getIndex`). `new Assurance(…)`, `save` (`assurance`).
- **food** (шаг 7): `FoodServiceImpl.java:117` `fo != null` → false. `:125` `foodType==2` → станция и магазин. `save` (`food_order`), `new Delivery`, `object2Json`, `RabbitSend#send` → `message_delivery` → `delivery.mq.RabbitReceive#process` (R13). `RabbitReceive.java:38` JSON разобран: поля `Delivery` совпадают. `:44` id null → задаём → `save` (`delivery`).
- **consign** (шаг 7): `ConsignServiceImpl#insertConsignRecord` → `ConsignPriceController#getPriceByWeightAndRegion(0.5,false)`. `ConsignPriceServiceImpl.java:30` 0.5 ≤ 1 → начальная цена. `save` (`consign_record`).
- **user**: `UserController#getUserByUserId` → `user`.
- `SeatClass#getNameByCode` (`:257`): цикл до совпадения → `getCode`, `getName`. Ветка `:68` не исполняется.

## Шаг 9. Обновить список заказов

`POST /api/v1/orderservice/order/refresh`. UI шлёт и в order-other (`client_order_list.js:53-54`), но по R20 в эталоне только сервис типа поезда сценария (D → `ts-order-service`).

- `OrderServiceImpl.java:131` все флаги false → ветка `:185` (`getLoginId`). `getState` и `String2Date` не вызываются (в отличие от S0).
- Заказы есть → `Order#<init>()`.

## Шаги 10–11. Открыть первый и второй новый заказ

В UI запроса нет (`client_order_list.js`). По коду: **[Д]** `GET /api/v1/orderservice/order/{orderId}` → `OrderController#getOrderById` → `findById` (`orders`). Тот же обработчик вызывает inside-payment на шагах 12–13, так что выбор безопасен.

## Шаги 12–13. Оплата с внутреннего счёта

`POST /api/v1/inside_pay_service/inside_payment` (`client_order_list.js:127`) → `InsidePaymentController#pay`.

- **[Д]** `userId` = id пассажира. UI шлёт только `orderId` и `tripId` (`client_order_list.js:120-122`). При `userId=null` списки платежей и пополнений будут пусты, и оплата уйдёт в payment-service (`:99-126`). Выбор основан на тексте шага («from the internal account balance») и на строках прогрева: у этого пассажира платежи `type=P`.
- `InsidePaymentServiceImpl.java:53` D → order-service `getOrderById` (R3).
- `:68` статус 1. `:70` заказ `NOTPAID` → дальше.
- `:81-97` потрачено 1670 (8 платежей), пополнено 10361 → `:99` 1720 ≤ 10361 (и 1742.5 на шаге 13) → внутренняя ветка `:127-131`.
- `setOrderStatus` (`:335` D) → `OrderController#modifyOrder` → `findById` + `save` (`orders`).
- `data`: `pay → inside_payment` (чтение и запись), `pay → inside_money`.

## Шаг 14. Цена груза 0.5 кг в регионе

В UI запроса нет. По коду: `GET /api/v1/consignpriceservice/consignprice/0.5/true` → `getPriceByWeightAndRegion`. 0.5 ≤ 1 → начальная цена, ветка `isWithin` не исполняется. Рёбра совпадают с шагом 7.

## Шаг 15. Типы страховок

`GET /api/v1/assuranceservice/assurances/types` (`client_ticket_book.js:117`) → `getAllAssuranceTypes`. Один тип → `AssuranceType#getIndex/getName/getPrice`. Таблиц нет.

## Проверка полноты

После сборки ответ сверен со скелетом (скрипт в scratchpad сессии, в репозиторий не вошёл): все рёбра `calls`/`remote_call`/`data_access` от call_site исполненных методов, которых нет в ответе.

- Найден пропуск: рукописные геттеры `TripInfo#getStartPlace/getEndPlace`, `TripAllDetailInfo#getFrom/getTo`, `OrderTicketsInfo#getFrom/getTo` вызывают `StringUtils#String2Lower`. Шесть рёбер добавлены.
- Остальное отсеяно осознанно: `user_roles` у `loadUserByUsername`, коллекции маршрута у `getRouteById` (R10); `JWTUtil` (R9); verification-code (кода нет); лямбда `orElseThrow`; order-other и payment-service у seat и inside-payment (поезд D, путь P); `getState`/`String2Date` в `queryOrders` (нет фильтра); `ContactsController#home`, `AssuranceController#getAssuranceById` (URL ведёт к другим обработчикам).
