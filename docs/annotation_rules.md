# Каталог правил разметки эталона

Как из исполнения сценария получаются рёбра ответа. Документ нужен модулю атрибуции (M5 в [ADR-005](adr/adr-005_scenario_execution_pipeline.md)) и всем, кто разбирает расхождения с эталоном.

Источники: [README](../hackaton/tt-challenge/README.md) и [REFERENCE](../hackaton/tt-challenge/REFERENCE.md) организаторов, скелет `skeleton/trainticket.json.gz`, открытый эталон `gold/S0.json`.

## Статусы

- **README** — прямо сказано организаторами.
- **S0** — подтверждено открытым эталоном.
- **Гипотеза** — вывод из семантики кода или одного примера. Держим под флагом и проверяем абляцией на платформе.

Каждое правило в коде включается отдельным флагом, чтобы его можно было выключить и сравнить балл.
Правила ветвления AST IR тел методов вынесены в декларативный файл [data/branch_rules.json](../data/branch_rules.json) и применяются через `engine/branch_rules.py` с поддержкой отключения любого правила для абляций.


## Как устроен эталон (рабочая модель)

Эталон похож на трассу исполнения, спроецированную на узлы скелета:

- `executes` — каждый метод проекта, который выполнился хотя бы раз и есть среди узлов `method`.
- `calls` — пара «ближайший проектный кадр стека → вызванный проектный метод», но только если между ними нет библиотеки (исключение — R6).
- `data` — SQL к таблице, приписанный методу, в котором стоит вызов репозитория.
- `remote` — переход запроса или сообщения в другой сервис.

Отсюда большинство правил ниже. Модель — наша реконструкция, а не слова организаторов.

## Правила

### R1. Схлопывание call_site

Статус: README, S0.

В скелете `calls`, `runtime_dispatch`, `remote_call`, `data_access` идут от вершины `call_site` (`call:method:...@строка:колонка`). В ответе источник — метод из поля `method` этой вершины.

- Вызовы внутри лямбды принадлежат объемлющему методу: `new UserOperationException(...)` внутри `orElseThrow(() -> ...)` в `TokenServiceImpl#getToken` имеет `method` = `getToken`.
- Методы анонимных классов — отдельные узлы (`JWTUtil$1#getUsername()`), их вызовы к объемлющему методу не относятся.
- Несколько call_site одного метода к одной цели дают одно ребро.
- Колонка call_site — 1-based позиция начала имени вызываемого метода. По `file + line + col` наш парсер сопоставляет свои вызовы с узлами скелета.

### R2. Полиморфизм внутри сервиса

Статус: S0.

`calls` скелета часто ведёт к методу интерфейса, а `runtime_dispatch` того же call_site — к реализации. В ответ идёт реализация.

```text
call:method:ts-auth-service:auth.controller.UserController#getToken(...)@45:44
  calls            -> auth.service.TokenService#getToken(...)          (интерфейс, в ответ не идёт)
  runtime_dispatch -> auth.service.impl.TokenServiceImpl#getToken(...) (в ответ)
```

- В Train Ticket у каждого call_site не больше одной цели `runtime_dispatch`. Если целей нет, а цель абстрактна — ищем реализации по `overrides` (CHA); если реализаций несколько, выбор делает исполнитель по типу объекта.
- Абстрактный метод без проектной реализации (репозитории Spring Data: `UserRepository#findByUsername`) не попадает ни в `calls`, ни в `executes`. Его call_site нужен только для `data`.

### R3. Неоднозначный remote_call

Статус: Гипотеза.

У 16 call_site `remote_call` ведёт к нескольким обработчикам. Пример:

```text
call:method:ts-inside-payment-service:inside_payment.service.InsidePaymentServiceImpl#pay(...)@59:74
  -> ts-order-service:order.controller.OrderController#getOrderById(...)
  -> ts-order-other-service:other.controller.OrderOtherController#getOrderById(...)
```

Выбор — по ветке, в которой стоит вызов, и вычисленному URL (обычно тип поезда по префиксу `tripId`: G/D — скоростные, `ts-order-service` и `ts-travel-service`; остальные — `ts-order-other-service` и `ts-travel2-service`). Другие случаи: `ts-admin-travel-service` → travel / travel2, `ts-food-service` → `TrainFoodController#home()` / `getTrainFoodOfTrip`. Брать все цели нельзя: лишнее ребро стоит столько же, сколько пропущенное.

### R4. Сгенерированные методы

Статус: README, S0.

Методы Lombok (`@Data`, `@AllArgsConstructor`, `@Builder`) и неявные конструкторы не являются узлами — их никогда не выводим, даже если в коде есть вызов (`dto.getPassword()` у `BasicAuthDto`, `user.getUserId()` у `User`).

Явно написанные методы того же класса — узлы. `OrderInfo` помечен `@Data`, но `getLoginId()`, `getState()`, `isEnableStateQuery()` написаны руками и в эталоне есть. Проверка всегда одна: есть ли ID в `nodes`.

### R5. Метод проекта, вызванный библиотекой

Статус: README, S0.

Такой метод попадает в `executes`, но ребра `calls` к нему нет: вызывающий кадр — библиотека.

- Контроллеры вызывает DispatcherServlet — входы шагов дают только `executes`.
- `JWTFilter#doFilterInternal` (`ts-common`) исполняется на запросах, ребра от фильтра к обработчику нет.
- Методы `UserDetails` у `auth.entity.User` (`getAuthorities`, `isAccountNonExpired`, `isAccountNonLocked`, `isCredentialsNonExpired`, `isEnabled`) вызывает Spring Security внутри `authenticationManager.authenticate(...)` — есть в `executes`, нет в `calls`.
- `UserDetailsServiceImpl#loadUserByUsername` вызывается из `authenticate` — `executes` и `data`, без `calls`.

### R6. Совпадение имени у ближайшего проектного кадра

Статус: S0, один пример.

В эталоне есть `TokenServiceImpl#getToken → User#getPassword`, хотя `getToken` вызывает только `dto.getPassword()` у Lombok-DTO, а `User#getPassword` дёргает Spring Security внутри `authenticate`. Ребер `getToken → User#getAuthorities` и `getToken → User#isEnabled` нет.

Объяснение, которое сходится со всеми случаями S0: ребро `A → M` ставится, если M вызван (в том числе через библиотеку), ближайший проектный кадр — A, и у A есть call_site с именем M. У `getToken` есть call_site `getPassword` и `getUsername`; `User#getUsername` внутри `authenticate` не вызывается, поэтому ребра нет. Для конструкторов (`<init>`) правило, судя по `Order#<init>()` ниже, не работает — там, видимо, сверяется ещё и тип.

На практике правило важно для мест, где проектный метод передаёт управление библиотеке, которая вызывает проектные же колбэки (`authenticate`, компараторы, `stream().map(...)` с ссылкой на метод).

### R7. Конструктор сущности при загрузке из БД

Статус: S0.

Явный конструктор сущности исполняется, когда Hibernate материализует строки результата, вместе со своими вызовами:

```text
executes: ts-order-service:order.entity.Order#<init>()
calls:    Order#<init>() -> edu.fudan.common.util.StringUtils#Date2String(java.util.Date)
calls:    Order#<init>() -> edu.fudan.common.entity.OrderStatus#getCode()
calls:    Order#<init>() -> edu.fudan.common.entity.SeatClass#getCode()
```

- Зависит от данных: конструктор сработает, только если запрос вернул хотя бы одну строку (по состоянию сценария).
- Ребра `queryOrders → Order#<init>()` нет: конструктор вызывает Hibernate.
- Вызовы через enum-константу (`OrderStatus.PAID.getCode()`) в скелете отсутствуют — у call_site нет `receiver_type` и рёбер. Их должен разрешать наш парсер (M2).
- Аналогично при создании нового заказа (`new Order()`) в коде сервисов `ts-preserve-service`, `ts-preserve-other-service` и `ts-rebook-service` конструктор `ts-common:edu.fudan.common.entity.Order#<init>()` выполняет те же вызовы `Date2String`, `OrderStatus#getCode()` и `SeatClass#getCode()`.

### R8. Отражение Jackson не учитывается

Статус: README, S0.

`OrderInfo#<init>()` и `OrderInfo#setLoginId(java.lang.String)` — узлы скелета, Jackson вызывает их при разборе тела запроса `queryOrdersForRefresh`, но в эталоне их нет. Правило: десериализация запроса и сериализация ответа методов не добавляют. Отличие от R7 — эмпирическое: конструкторы сущностей при загрузке Hibernate учитываются, вызовы Jackson — нет.

### R9. JWTUtil

Статус: S0, эмпирика.

`JWTFilter#doFilterInternal` в коде вызывает `JWTUtil.getJWTAuthentication(request)` — статический метод проекта. В эталоне S0 нет ни одного метода `JWTUtil`. Принимаем как границу разметки: не выводим `JWTUtil.*`. Флаг держим, чтобы проверить на скрытых сценариях.

### R10. Источник и таблицы для data

Статус: README, S0.

- Источник — метод, в котором стоит call_site репозитория, а не обработчик выше по стеку и не интерфейс репозитория.
- Таблицы — подмножество `data_access` этого call_site. Таблиц вне `data_access` в эталоне не бывает.
- Основная таблица сущности — когда запрос выполнился.
- Таблица коллекции (`user_roles`, `route_stations`, `route_distances`, `food_delivery_order_food_list`) — только когда коллекция реально загрузилась.
- Ленивая загрузка, которая произошла позже внутри библиотеки, приписывается ближайшему проектному кадру с call_site, у которого эта таблица есть в `data_access`.

Пример из S0. У call_site `findByUsername` в `loadUserByUsername` в `data_access` есть и `auth_user`, и `user_roles`, но в эталоне только `auth_user`. Роли — ленивая `@ElementCollection`; их загружает `User#getAuthorities()`, который Spring Security вызывает уже после возврата из `loadUserByUsername`, внутри `authenticate` у `getToken`. Поэтому `user_roles` приписан `getToken`:

```text
data: UserDetailsServiceImpl#loadUserByUsername(java.lang.String) -> res:table:ts-auth-service.auth_user
data: TokenServiceImpl#getToken(...)                             -> res:table:ts-auth-service.auth_user
data: TokenServiceImpl#getToken(...)                             -> res:table:ts-auth-service.user_roles
```

Схема в ID таблицы не всегда совпадает с сервисом: `res:table:ts-consign-mysql.consign_record`. ID копируем из `nodes`.

### R11. Запись и отложенный SQL

Статус: README; детали — Гипотеза.

`save`, `delete`, и SQL, который ORM выполняет при фиксации транзакции, приписываются методу с вызовом репозитория. Запись сущности с коллекцией трогает и таблицу коллекции. Что именно Hibernate делает при `save` существующей сущности (select + update) и при пустой коллекции — проверяем абляцией.

### R12. remote

Статус: README.

- Источник — метод с call_site RestTemplate (или отправки в очередь), цель — обработчик в другом сервисе.
- Внутри одного сервиса `remote` не бывает.
- После перехода обход продолжается в обработчике: его `executes`, `calls`, `data`, `JWTFilter` целевого сервиса.
- Клиентский запрос шага приходит через шлюз и `remote` не даёт: источника-метода нет.

### R13. RabbitMQ

Статус: README; детали — Гипотеза.

В скелете 4 ребра `message_delivery`, например `preserve.mq.RabbitSend#send(java.lang.String)@20:29 → ts-notification-service:notification.mq.RabbitReceive#process(java.lang.String)`. Потребителя, запущенного сообщением сценария, учитываем (`remote` от метода с call_site отправки, далее его тело). Фоновые потоки без связи со сценарием — нет.

### R14. Шлюз

Статус: S0.

Методы `ts-gateway-service` (`GatewayConfiguration#initGatewayRules()` и т.п.) работают при старте, на запросах не исполняются. `remote_call` от вершин `config_entry` (маршруты шлюза) в ответ не идут, они нужны только чтобы понять, в какой сервис уйдёт запрос.

### R15. Ошибки и отказы

Статус: README.

Если шаг закончился ошибкой, в ответ идёт всё, что успело выполниться до `throw` или раннего `return`. Пример — S7: отмена и перебронирование после выдачи билета отклоняются проверкой статуса заказа.

### R16. Лямбды и ссылки на методы

Статус: Гипотеза (следует из семантики Java).

Тело лямбды исполняется только когда её вызывают: `orElseThrow(() -> ...)` — только при пустом `Optional`, `stream().map(...)` и `forEach` — только при непустой коллекции. Ссылка на метод проекта (`Foo::bar`, `method_ref: true` у call_site) — тоже вызов по требованию; ребро от объемлющего метода — по R6.

### R17. Циклы по данным

Статус: S0 (косвенно).

Тело цикла по коллекции из БД исполняется, только если коллекция непуста в состоянии сценария. В S0 у пассажира есть заказы после прогрева, поэтому `Order#<init>()` есть. У нового пользователя в S4 списки пусты.

### R18. Идентификаторы

Статус: README, S0.

- Код `ts-common` имеет один ID, в каком бы сервисе он ни исполнялся.
- ID копируются из `nodes` дословно, включая артефакты резолвинга типов: `ContactsController#findContactsByAccountId(java.lang.String,?HttpHeaders)`.
- Похожие методы разных сервисов — разные вершины (`OrderServiceImpl#queryOrders` и `OrderOtherServiceImpl#queryOrders`).

### R19. Согласованность executes

Статус: README (предупреждение оценщика).

Каждый метод, который встречается в `calls`, `remote` или `data`, должен быть в `executes`.

### R20. Шаги и входы

Статус: README, S0.

Один шаг — один клиентский запрос через шлюз. Одинаковые обработчики разных шагов сливаются в множествах (в S0 6 шагов дают 5 входов: «Refresh» и «Refresh Paid» идут в один `OrderController#queryOrdersForRefresh`). Ответ — множество на весь сценарий, порядок и повторы не важны.

## Цифры для ориентира

- Скелет: 1538 методов, 8961 call_site, 33 таблицы; `calls` 1240, `runtime_dispatch` 287, `remote_call` 415 (из них 166 от call_site), `data_access` 319, `message_delivery` 4.
- Из 146 call_site RestTemplate у 144 есть `remote_call`; два без цели (`AsyncTask#sendAsyncCallToPaymentService` на внешний адрес и `PollThread#doPreserve`).
- Эталон S0: 34 `executes`, 24 `calls`, 0 `remote`, 7 `data`. Из 24 `calls` в скелете (после R1 и R2) находится 19; не хватает четырёх вызовов через enum-константы (`Order#<init>() → getCode()` в двух сервисах, R7) и `getToken → User#getPassword` (R6). Все 7 `data` есть в `data_access`.
