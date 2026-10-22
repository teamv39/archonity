# Каталог правил разметки эталона

Как из исполнения сценария получаются рёбра ответа. Документ нужен модулю атрибуции (M5 в [ADR-005](adr/adr-005_scenario_execution_pipeline.md)) и всем, кто разбирает расхождения с эталоном.

Источники: [README](../hackaton/tt-challenge/README.md) и [REFERENCE](../hackaton/tt-challenge/REFERENCE.md) организаторов, скелет `skeleton/trainticket.json.gz`, открытый эталон `gold/S0.json`.

## Статусы

- **README** — прямо сказано организаторами.
- **S0** — подтверждено открытым эталоном.
- **Гипотеза** — вывод из семантики кода или одного примера. Держим под флагом и проверяем абляцией на платформе.

Каждое правило в коде включается отдельным флагом, чтобы его можно было выключить и сравнить балл.
Ветвления решает исполнитель M4 по IR тел методов (ADR-005). Прежний декларативный каталог веток legacy-контура (`data/branch_rules.json`) удалён 21.10.


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
- Как это находит код (`engine/spring_security.py`, с 19.10): вход — исполненный метод, в котором стоит call_site `authenticate` с `receiver_type` `AuthenticationManager`; `loadUserByUsername` — у типа того же модуля с `implements UserDetailsService`, его `data` — таблицы `data_access` скелета без ленивых коллекций (R10 отсекает `user_roles`); методы `UserDetails` — у типа с `implements UserDetails`, только те, что вызывает `DaoAuthenticationProvider` (без `getUsername`: его исполняет `createToken`, и это ребро даёт M4); фильтры — `doFilterInternal` подклассов `OncePerRequestFilter`; ребро `calls` от входа — по R6. Имён методов и таблиц Train Ticket в правиле нет. Прежнее правило по именам (`getToken`/`authenticate`/`login`, `createToken`, подстрока `user` в таблице) давало ту же выдачу и удалено 21.10.
- Подтверждено платформой 17.10.2026 (0.91827 против 0.91709): рукописный `equals` сущности, который вызывает библиотека коллекций. `OrderServiceImpl#create` и `OrderOtherServiceImpl#create` проверяют `accountOrders.contains(order)`, `ArrayList` вызывает `order.equals(элемент)` обычным вызовом, не через отражение. Исполняется, только если у владельца уже есть заказы: S1, S2, S3, S5, S6, S7, но не S4 (новый пользователь). `equals` вызывает только геттеры Lombok, так что это одно ребро `executes`. Факты — archparse (`element_callbacks` в `entity_ir.json`), режим `RuntimeRules(element_callbacks=...)` или `run_eval.py --element-callbacks on|off`.

Другие механизмы, которые вызывает фреймворк, разобраны 17.10 (блок 8 плана archparse) и новых рёбер не дают: слушатели RabbitMQ уже идут по R13, `MyCallable#call` (пул потоков travel-service) и `@Async` не исполняются на путях сценариев, `@ExceptionHandler` — только при ошибке входа, колбэков JPA (`@PrePersist`, `@PostLoad`) и `Comparable` в проекте нет.

- Подтверждено платформой 19.10 (посылки 11–12, +0.0015): **Lombok-`toString` при логировании.** `BasicServiceImpl` пишет `LOGGER.info("...{}", result)`, SLF4J форматирует аргумент через `toString()`. У `TravelResult` он сгенерирован Lombok (`@Data`) и берёт поля через геттеры, если они есть; `isStatus()` написан руками и исполняется — `executes` во всех семи сценариях, `calls` нет. Правило: аргумент `info`/`warn`/`error` у поля типа SLF4J `Logger` по шаблону с `{}`; класс с `@Data`/`@ToString`/`@Value` — исполняются рукописные геттеры его собственных полей, вложенные объекты, списки и словари обходятся так же; рукописный `toString` исполняется сам. `debug`/`trace` не форматируются: своих настроек логирования в сервисах нет, уровень по умолчанию Spring Boot — INFO. Режим — `RuntimeRules(lombok_tostring=...)` или `run_eval.py --lombok-tostring on|off`, код — `Interpreter.log_format` ([разбор](researches/code_record_drift.md)).

### R6. Совпадение имени у ближайшего проектного кадра

Статус: S0, один пример.

В эталоне есть `TokenServiceImpl#getToken → User#getPassword`, хотя `getToken` вызывает только `dto.getPassword()` у Lombok-DTO, а `User#getPassword` дёргает Spring Security внутри `authenticate`. Ребер `getToken → User#getAuthorities` и `getToken → User#isEnabled` нет.

Объяснение, которое сходится со всеми случаями S0: ребро `A → M` ставится, если M вызван (в том числе через библиотеку), ближайший проектный кадр — A, и у A есть call_site с именем M. У `getToken` есть call_site `getPassword` и `getUsername`; `User#getUsername` внутри `authenticate` не вызывается, поэтому ребра нет. Для конструкторов (`<init>`) правило не срабатывает: рёбер в конструктор нет вовсе, вход в него трассировщик не записывает (R7).

На практике правило важно для мест, где проектный метод передаёт управление библиотеке, которая вызывает проектные же колбэки (`authenticate`, компараторы, `stream().map(...)` с ссылкой на метод).

### R7. Видимость конструкторов

Статус: S0, платформа (17.10, посылки 9 и 10 от 18.10), [ADR-006](adr/adr-006_constructor_visibility.md).

Конструктор попадает в ответ, только если из него исполнился вызов метода проекта. Рёбер `calls` **в** конструктор нет никогда, рёбра **из** него есть. Способ создания объекта (`new` из кода проекта, Hibernate, Jackson) не важен.

```text
executes: ts-order-service:order.entity.Order#<init>()
calls:    Order#<init>() -> edu.fudan.common.util.StringUtils#Date2String(java.util.Date)
calls:    Order#<init>() -> edu.fudan.common.entity.OrderStatus#getCode()
calls:    Order#<init>() -> edu.fudan.common.entity.SeatClass#getCode()
```

Объяснение — гипотеза о трассировщике ([разбор](researches/constructor_project_calls_rule.md)): агент организаторов перехватывает методы, но не конструкторы. Конструктор виден только как ближайший проектный кадр стека, из которого вызван перехваченный метод.

- Рёбер `queryOrders → Order#<init>()` (загрузка Hibernate) и `preserve → Order#<init>()` (`new Order()`) нет: вход в конструктор не записывается.
- `Contacts#<init>()` (пустой) в S0 нет, хотя контакты грузятся: из него ничего не вызвано. По той же причине нет `Ticket#<init>(…)`, `Route#<init>()` и других конструкторов, тело которых только присваивает поля.
- Вызов проекта — вызов метода из `nodes` скелета. Не считаются библиотеки (`new Date()`, `UUID.randomUUID()`), Lombok и, по гипотезе, вызовы других конструкторов (`this(...)`, `new` проектного типа внутри конструктора). На путях S1–S7 вложенных конструкторов нет.
- Вызовы через enum-константу (`OrderStatus.PAID.getCode()`) в скелете отсутствуют: у call_site нет `receiver_type` и рёбер. Их разрешают наш парсер (M2) и M4.

Проверено на платформе:

- 17.10: 55 конструкторов Hibernate без проектных вызовов (`Route`, `Station`, `Trip`, `Config`, `PriceConfig`, `StationFoodStore`, `TrainFood`, `Money`, `user.entity.User`, `Assurance`) опустили балл с 0.8927 до 0.8842 ([r7_score_drop.md](researches/r7_score_drop.md));
- 18.10, посылка 9: без 29 конструкторов через `new`, из которых не вызван метод проекта, — 0.93625 → 0.98759;
- 18.10, посылка 10: вдобавок без 8 рёбер `calls` в конструктор — 0.98908. Предсказано до посылки.

Прежняя формулировка «конструкторы, вызванные проектным кодом через `new`, — обычные вызовы проекта» неверна. Она держалась на обращении фразы REFERENCE («не включайте конструкторы, вызванные библиотекой лишь через отражение»), а не на данных.

Hibernate создаёт экземпляр и исполняет конструктор в таких случаях (факты archparse, `data/entity_ir.json`; решение — `engine/entities.py`). Попадёт ли конструктор в ответ, решает правило выше:

- чтение (`find*`, своё `@Query`), если запрос вернул строки. Строки пользователя (таблица с `account_id`/`user_id`, не ключом) — по модели состояния и дампу; справочники — непустой дамп;
- чтение, после которого успешный путь ждёт пустой результат (проверка «уже существует» перед созданием: `AssuranceServiceImpl#create`, `UserServiceImpl#saveUser`), конструктор не вызывает;
- `delete*`: Spring Data сначала загружает строку;
- `save` сущности с заданным id: Spring Data делает `merge`, Hibernate загружает строку и создаёт управляемую копию конструктором. Без id — `persist`, конструктор не вызывается;
- `exists*`, `count*`, `@Modifying @Query` экземпляров не создают.

Jackson создаёт тело запроса (`@RequestBody`) конструктором без аргументов — и на входе шага, и в принимающем сервисе межсервисного вызова. Рукописный конструктор исполняется, в ответ его пропускает правило выше. Подтверждено посылкой 17 (19.10, 0.99457): `RebookInfo()` вызывает `StringUtils.Date2String`, поэтому в S2 и S7 есть `executes RebookInfo#<init>()` и `calls RebookInfo#<init>() → Date2String`. Значения конструктора в тело не идут: какие поля пришли в JSON, неизвестно. Режим — `RuntimeRules(jackson_ctor=...)` или `run_eval.py --jackson-ctor on|off`, код — `Interpreter.jackson_new`.

Встраиваемые поля (`@Embedded TripId` у `Trip`) создаются вместе с сущностью по тому же правилу. Элементы `@ElementCollection` (`Food`) не учитываются: коллекции ленивые.

Режим — `RuntimeRules(constructors=...)` или `run_eval.py --ctors`, отбор делает проекция `engine/projection.py` (M5) на каждом шаге:

- `caller_only` (по умолчанию) — правило выше. Выдача M4 совпадает с посылкой 10 ребро в ребро;
- `all` — как до ADR-006: конструктор через `new` — всегда, вместе с ребром в него; при загрузке — только с вызовом проекта в теле. Выдача совпадает с рекордом 0.93625, режим для отката;
- `off` — конструкторов нет совсем, вместе с `Order` (S0 падает; только для отладки).

### R8. Отражение Jackson не учитывается

Статус: README, S0.

`OrderInfo#<init>()` и `OrderInfo#setLoginId(java.lang.String)` — узлы скелета, Jackson вызывает их при разборе тела запроса `queryOrdersForRefresh`, но в эталоне их нет. Правило: десериализация запроса и сериализация ответа методов не добавляют. `OrderInfo#<init>()` — частный случай R7: из него не вызван метод проекта, а `RebookInfo#<init>()` по той же причине в ответе есть (вызывает `Date2String`). Для сеттеров правило остаётся эмпирическим.

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

Обобщение на все ленивые коллекции подтверждено платформой 17.10.2026: 0.91709 против 0.90208, разница только в 17 рёбрах `data` ниже. Таблица ленивой коллекции идёт от метода с вызовом чтения, только если коллекция загрузилась, пока метод на стеке. Геттер сам коллекцию не грузит, грузит первое обращение к элементам. Если метод только вернул сущность или результат геттера, коллекцию загрузит сериализация ответа после возврата. Проектного кадра с этой таблицей в `data_access` на стеке тогда уже нет, и ребра нет. Как `loadUserByUsername` в S0.

- `getRouteById` возвращает `Route`: без `route_stations` и `route_distances`.
- `getRouteByStartAndEnd` вызывает `route.getStations().contains(...)`: `route_stations` есть, `route_distances` нет.
- `listTrainFoodByTripId` возвращает `tf.getFoodList()` в `return`: без `train_food_list`.
- `getToken` передаёт пользователя в `createToken`, тот кладёт роли в токен: `user_roles` есть (сходится с S0).
- `EAGER`-коллекции (`station_food_list`) грузятся тем же запросом, запись (`save`, `delete`) трогает таблицу коллекции сама: их правило не трогает.

Факты даёт archparse (`collections`, `collections_loaded` в `entity_ir.json`), решение — `engine/entities.py`. Режим: `RuntimeRules(collection_tables_on_read=...)` или `run_eval.py --collection-tables`: `loaded` (по умолчанию) или `all` — все таблицы `data_access` исполненного вызова, выдача до правила ребро в ребро.

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

«Refresh the list of orders» без типа поезда — один вход: `queryOrdersForRefresh` сервиса заказов по типу поезда заказа, с которым работает сценарий (`ts-order-service` для G/D, `ts-order-other-service` для остальных). UI в `queryMyOrderList` шлёт оба запроса, но второго в эталоне нет: S0 и платформа 17.10, [OQ-08](open-questions.md#oq-08).

Шаг, которого в UI нет вовсе (цена заказа, запись страховки, расчёт возврата), шлёт запрос: обработчик выбирается по коду сервиса. Это видно по уникальным рёбрам таких шагов в S1, S4, S5, S7 — сценариях с баллом 1.000.

Шаг, который M1 заземлил на **обработчик, который Spring вызвать не может**, идёт через рабочий обработчик того же контроллера. Spring связывает `@PathVariable` по имени (явному или имени параметра); если имени нет среди переменных шаблона пути, ответ — ошибка до вызова контроллера, метод не исполняется. В проекте такой один: `StationFoodController#getFoodStoresOfStation` (`@PathVariable String stationName` при шаблоне `/stationfoodstores/{stationId}`). Шаг 4 в S2 и S3 («Browse the food stores at Suzhou station») в эталоне идёт через `POST /stationfoodstores` → `getFoodStoresByStationNames`: 2 `executes`, 1 `calls`, 2 `data` (`station_food_store`, `station_food_list`). Подтверждено посылкой 27 (19.10, итог 1.00000) после замера ячеек S2/S3 (посылки 21–26), [разбор](researches/reaching_1_0.md). Замена — обработчик того же класса, который Spring вызвать может и у которого есть параметр пути, query или тела с тем же корнем имени (`stationName` ↔ `stationNameList`); не один или нет — замены нет. Решение после заземления: выбор M1 и история в промпте не меняются, кеш LLM цел; в `step_requests.json` у шага `grounding.rebound`. Код — `engine/grounding/binding.py`, `StepGrounder.rebind`; режим — `RuntimeRules(unbound_handlers=...)` или `run_eval.py --unbound-handlers rebind|keep`.

Прежняя формулировка «шаг 4 — действие формы без запроса, выбор станции идёт в памяти JS» (посылки 13–20) давала верный результат для наших 4 рёбер, но не видела 5 рёбер рабочего обработчика. Удалена 19.10.

### R21. Значения тела запроса

Статус: README (`context` скелета) и Гипотеза (остальное). Подтверждено выдачей: sha256 рекорда, зонды 20.10 ([аудит](researches/universality_audit_after_1_0.md), раздел 8). Код — `StepExecutor.build_dto` (`engine/executor/step.py`), [ADR-007](adr/adr-007_project_profile.md), решение 6.

Поле тела, значения которого нет в тексте шага, ссылках и у текущего пользователя, неизвестно. Значение по смыслу получают:

- **Поле, по которому создающий метод ищет дубликат** (чтение репозитория перед `save` в том же методе, аргумент — геттер тела запроса): значение, которого нет в мире БД. Пример — `userName` при регистрации (`findByUserName`), `documentNumber` контакта.
- **Значение, записанное прежним шагом**, — полю следующего шага с тем же именем без учёта регистра: имя регистрации → `username` при входе.
- **Вход** (из обработчика достижим вызов `AuthenticationManager.authenticate`): имя — пассажир `context` («the passenger is the pre-registered user …»), если сценарий не регистрировал своего; поля, которых по `context` при входе нет («no verification code at login»), — пустая строка.
- **Текущий пользователь** — из ответа входа: поле с именем `@Id` класса `UserDetails` (`TokenDto.userId`). Его получают поля `accountId`, `userId`, `loginId` тела и пути. Список — потому что общее правило (поток UI: `sessionStorage.setItem("client_id", data.userId)` при входе → `accountId: sessionStorage.getItem("client_id")` в теле) требует источников полей, которых каталог UI пока не хранит.
- **Получатель багажа**: при весе 0 `consigneeName` и `consigneePhone` — `null`; при весе больше 0 — неизвестны. UI (`client_ticket_book.js`) шлёт имя, телефон и вес одной группой под флажком «need consign». Общее правило — поля группы под тем же условием, что и поле с нулевым значением из текста; каталог UI хранит только литералы под условием (`body_cond`), группу не видит. Без `null` при весе 0 — +15 рёбер в S2, S4–S6.

- **Сущность, названная явно.** Ссылка `first`/`second_of_step_N`, а в параметрах шага — строковый ID сущности того же вида (`tripId: G9998` при `trip: first_of_step_2`): поля тела, которых нет в параметрах (маршрут, станции), берутся у сущности с этим ID из результатов шага N, а не у первой по порядку. Текст шага называет объект, позиция в списке его не перекрывает. Нет такой сущности в результатах — ссылка как была. Найдено сверкой рёбер X6 (22.10): без правила тело «изменить рейс G9998» собиралось из ID G9998 и маршрута первого рейса, проверка станций в `AdminTravelServiceImpl#checkTravelInfo` отказывала, терялся успешный путь (`remote` в `TravelController#updateTrip`, `TravelServiceImpl#update`, `data` к `trip`, 10 рёбер). S0–S7 и `handler_sweep` не меняются. Режим — `RuntimeRules(ref_explicit_id=...)` или `run_eval.py --ref-explicit-id on|off`, код — `StepExecutor._explicit_id_refs`, Rust — `StepCore::explicit_id_refs`.

Синтетические значения, без которых выдача та же (имя и телефон контакта, строки получателя багажа при весе больше 0), убраны.

## Цифры для ориентира

- Скелет: 1538 методов, 8961 call_site, 33 таблицы; `calls` 1240, `runtime_dispatch` 287, `remote_call` 415 (из них 166 от call_site), `data_access` 319, `message_delivery` 4.
- Из 146 call_site RestTemplate у 144 есть `remote_call`; два без цели (`AsyncTask#sendAsyncCallToPaymentService` на внешний адрес и `PollThread#doPreserve`).
- Эталон S0: 34 `executes`, 24 `calls`, 0 `remote`, 7 `data`. Из 24 `calls` в скелете (после R1 и R2) находится 19; не хватает четырёх вызовов через enum-константы (`Order#<init>() → getCode()` в двух сервисах, R7) и `getToken → User#getPassword` (R6). Все 7 `data` есть в `data_access`.
