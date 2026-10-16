# archparse — скоуп и контракт IR

Статус: рабочий план на 16.10, пишется перед кодом по требованию [ADR-005](../docs/adr/adr-005_scenario_execution_pipeline.md) ("Точные поля фиксируются в archparse/README.md до начала реализации M4"). Отвечает только за **M2: разбор тел методов**. Не трогает M1 (заземление шагов), M3 (состояние), M4 (исполнитель) — это Миша/Денис.

## 0. Контекст: от чего отталкиваемся

Сейчас `engine/` (Денис) даёт **0.879** на платформе. Это не академический closure, а обход скелета (`engine/graph/builder.py`) с ручными правилами отсева (`engine/rules.py`): флаги сценария (`ScenarioProfile.train_mode`, `has_food`, `has_assurance`, `has_refused_cancel`...) вычисляются regex'ом по тексту сценария и дальше вручную выключают целые методы/рёбра по подстроке в ID (`"CancelServiceImpl" in method_id and "cancelFromOrder" in method_id`).

Список special cases разрастается в неявный интерпретатор, и эти правила угадывают ветвление по имени метода, а не по реальному `if` в коде. **archparse не переписывает движок — он даёт ему проверенную по исходнику замену для самых хрупких мест этого списка.**

### 0.1. Конкретный баг, который это доказывает

Прочитал `CancelServiceImpl.java` и `ExecuteServiceImpl.java` целиком (из `hackaton.zip`, не из скелета). Оба метода `cancelOrder` и `ticketExecute`/`ticketCollect` сначала **всегда** зондируют `ts-order-service` (`getOrderByIdFromOrder`), и только если `status != 1` (заказ не найден) — идут в `getOrderByIdFromOrderOther`:

```java
// CancelServiceImpl.cancelOrder, строки 46-141
Response<Order> orderResult = getOrderByIdFromOrder(orderId, headers);   // всегда исполняется
if (orderResult.getStatus() == 1) {
    ... // ветка high-speed
} else {
    Response<Order> orderOtherResult = getOrderByIdFromOrderOther(orderId, headers); // для Other-заказа — сюда
    ...
}
```

Для сценария с обычным (`Other`) поездом негативный пробный запрос в `ts-order-service` **реально выполняется** — это `executes` + `calls` + `remote` + SQL-`data` на пустой результат. Но `engine/rules.py` сейчас для `train_mode == "regular_only"` помечает `getOrderByIdFromOrder(` как мёртвый код безусловно (`rules.py`, блок `elif profile.train_mode == "regular_only": ... "getOrderByIdFromOrder(" in method_id: return True`) — то же самое для `ExecuteServiceImpl`. Это, скорее всего, срезает реально исполнившийся пробный запрос в S2/S7 (там, где присутствует cancel/execute для обычного поезда) — минус в `executes`/`calls`/`remote`/`data` одновременно, то есть по всем четырём категориям сразу.

Поведение кода прочитано, но что именно лежит в скрытом эталоне, мы не знаем. Поэтому это гипотеза для проверки одной сдачей на платформе: убрать `getOrderByIdFromOrder(` из исключений для `regular_only` в `rules.py` (а также соответствующие правила для `remote` и `data` на `ts-order-service`) и сравнить балл. Это правка нашего кода, к исходникам Train Ticket и эталону она отношения не имеет.

Дальше — то, ради чего нужен парсер: такие несоответствия между реальным `if` и ручным правилом будут попадаться и дальше, и вручную перечитывать все 42 модуля в оставшиеся дни — не вариант.

## 1. Что НЕ делаем сегодня (границы)

- Не парсим все 1538 методов и не строим общий CFG проекта. Только пул ниже.
- Не делаем символическое выполнение, не резолвим типы через полный classpath/Spring DI — PoC на `StaticJavaParser` без `SymbolSolver` (как сейчас в `Main.java`), резолвинг enum/receiver делаем точечно (см. 3.3).
- Не трогаем M1 (grounding), M3 (state), M4 (executor) и их контракты из ADR-005 целиком — только даём им данные под пул методов из этой заметки.
- Не интегрируем вывод в `engine/` сегодня. Результат дня — валидный JSON + список находок текстом, который Денис/Миша руками сверяют с `rules.py`. Автоматическая интеграция — отдельная, завтрашняя задача, после утверждения формата.
- Не трогаем зеркальные классы (`ts-preserve-other-service`, `ts-travel2-service`, `other.entity.Order`...) до валидации формата на основном классе — добавляем их на день 2 копированием той же логики.

## 2. Пул методов на сегодня

Приоритет — по тому, что в `rules.py`/`graph/builder.py` сейчас решено текстовым угадыванием, а не чтением кода, и по количеству задетых сценариев.

| # | Класс.метод | Файл | Что решает в движке сейчас (угадывается) | Сценарии |
|---|---|---|---|---|
| 1 | `CancelServiceImpl#cancelOrder`, `#calculateRefund(String,...)`, `#calculateRefund(Order)` | `ts-cancel-service/.../cancel/service/CancelServiceImpl.java` | `train_mode`-ветка пробного запроса (баг из 0.1), статус-гейт на `NOTPAID/PAID/CHANGE` | S2, S4, S7 |
| 2 | `ExecuteServiceImpl#ticketExecute`, `#ticketCollect` | `ts-execute-service/.../execute/serivce/ExecuteServiceImpl.java` | та же пара-проба, гейт `COLLECTED` | S1, S5, S7 |
| 3 | `InsidePaymentServiceImpl#pay`, `#setOrderStatus` | `ts-inside-payment-service/.../inside_payment/service/InsidePaymentServiceImpl.java` | G/D-диспатч по `tripId` (сейчас решается флагом сценария, а не по конкретному заказу шага), ветка internal/external pay по сумме ledger | S1, S2, S4 |
| 4 | `RebookServiceImpl#rebook`, приватный `updateOrder(Order,String,HttpHeaders)` | `ts-rebook-service/.../rebook/service/RebookServiceImpl.java` | статус-гейт (`NOTPAID/CHANGE/COLLECTED`), ветка цены (дешевле/дороже/равно), ветка смены семейства поезда (`tripGD(old) xor tripGD(new)`) — сейчас `createOrder/deleteOrder/payDifferentMoney` исключены блоком безусловно | S2 |
| 5 | `PreserveServiceImpl#preserve`, `PreserveOtherServiceImpl#preserve` | `ts-preserve-service/.../preserve/service/PreserveServiceImpl.java` (и `preserveOther` аналог) | `assurance != 0`, `foodType != 0` (плюс `== 2` для station food), `consigneeName` не пуст — сейчас эти флаги вычисляются regex'ом по английскому тексту шага (`ScenarioProfile.has_assurance/has_food/has_consign`), а не по факту извлечённых из запроса значений | S1, S3 |
| 6 | `ConsignServiceImpl#updateConsignRecord` | `ts-consign-service/.../consign/service/ConsignServiceImpl.java` | пересчёт цены при смене веса — сейчас хардкод `profile.id == "S7"` в `rules.py` | S7 |
| 7 | `OrderServiceImpl#queryOrders`, `OrderOtherServiceImpl#queryOrders` | `ts-order-service/.../order/service/OrderServiceImpl.java` (+ other) | OR-флаги `enableStateQuery/...`, попадание в `String2Date` — сейчас хардкод "если в тексте шага нет 'travel date'/'bought date', вырезать ребро к `String2Date`" в `graph/builder.py` | S0 (эталон), S7 |
| 8 | `TokenServiceImpl#getToken` | `ts-auth-service/.../auth/service/impl/TokenServiceImpl.java` | ветка `!StringUtils.isEmpty(verifyCode)` — отсекает ложный `remote_call` к `ts-verification-code-service` | S0–S7 (все логины) |
| 9 | `UserServiceImpl#saveUser`, `#createDefaultAuthUser` | `ts-user-service/.../user/service/impl/UserServiceImpl.java` | ветка `user1 == null` — активация регистрации нового пользователя и удалённого вызова к `ts-auth-service` | S4 |
| 10 | `AdminOrderServiceImpl#getAllOrders`, `#deleteOrder`, `#updateOrder`, `#addOrder` | `ts-admin-order-service/.../adminorder/service/AdminOrderServiceImpl.java` | G/D-диспатч админки (`startsWith("G") || startsWith("D")`) и безусловные вызовы в оба order-сервиса | S6 |

Если за день успеваешь только половину — бери 1–4 (пять методов, три сервиса): они закрывают G/D-диспатч и status-гейты, которые размножены по cancel/execute/rebook/payment и чаще всего дают parallel FP/FN.

## 3. Контракт вывода (узкий, только для пула)

Не весь ADR-005 IR (`ir/<module>.json` с полным деревом операторов) — для пула это избыточно на день 1. Нужен укороченный срез: список веток и список вызовов с привязкой к `call_site` скелета.

### 3.1. Файл вывода

`archparse/out/pool_ir.json` — массив объектов `MethodIR`:

```json
{
  "method_id": "method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
  "file": "ts-cancel-service/src/main/java/cancel/service/CancelServiceImpl.java",
  "branches": [
    {"id": "b49",  "line": 49,  "guard": [], "kind": "if",
     "condition_text": "orderResult.getStatus() == 1",
     "early_exit": {"then": true, "else": true}, "then_calls": ["cs:51:40", "..."], "else_calls": ["..."]},
    {"id": "b52",  "line": 52,  "guard": ["b49:then"], "kind": "if",
     "condition_text": "order.getStatus() == OrderStatus.NOTPAID.getCode() || ...",
     "early_exit": {"then": true, "else": true}, "then_calls": ["..."], "else_calls": ["..."]},
    {"id": "b105", "line": 105, "guard": ["b49:else"], "kind": "if",
     "condition_text": "orderOtherResult.getStatus() == 1",
     "early_exit": {"then": true, "else": true}, "then_calls": ["..."], "else_calls": ["..."]}
  ],
  "calls": [
    {"line": 48,  "col": 39,  "callee": "getOrderByIdFromOrder", "receiver": "this", "arg_count": 2, "kind": "SAME_CLASS", "guard": []},
    {"line": 52,  "col": 58,  "callee": "getCode", "receiver": "OrderStatus.NOTPAID", "arg_count": 0, "kind": "ENUM", "enum_constant": {"type": "edu.fudan.common.entity.OrderStatus", "constant": "NOTPAID"}, "guard": ["b49:then"]},
    {"line": 83,  "col": 59,  "callee": "getNameByCode", "receiver": "SeatClass", "arg_count": 1, "kind": "OTHER", "guard": ["b49:then", "b52:then", "b59:then", "b65:then"]},
    {"line": 104, "col": 48,  "callee": "getOrderByIdFromOrderOther", "receiver": "this", "arg_count": 2, "kind": "SAME_CLASS", "guard": ["b49:else"]},
    {"line": 115, "col": 50,  "callee": "cancelFromOtherOrder", "receiver": "this", "arg_count": 2, "kind": "SAME_CLASS", "guard": ["b49:else", "b105:then", "b109:then"]}
  ],
  "unsupported": []
}
```

Пример сокращён: полный вывод по `cancelOrder` содержит 9 веток и 83 вызова. Позиции `(line, col)` взяты из реального вывода парсера. У `getNameByCode` вид `OTHER`: в скелете у него уже есть тип получателя и ребро, резолвер его не трогает.

Поля:

- `branches[].id` это `"b" + номер строки` оператора `if` (уникален в пределах метода). `guard` ветки и вызова перечисляет плечи объемлющих `if` снаружи внутрь: `"b49:else"` значит «внутри `else` ветки b49». Кроме `if`, в `guard` бывают три служебных вида: `"f392:orders"` (тело `foreach` по коллекции `orders`; исполняется, только если коллекция непуста, R17), `"t83:catch"` (плечо `catch` оператора `try` со строки 83; на штатном пути не исполняется, R15) и `"l91:orElseThrow"` (тело лямбды со строки 91, переданной в метод `orElseThrow`; исполняется, только если хост-метод её вызывает, R16). Вызов исполняется, только если выбраны все плечи из его `guard`. Для `else if` цепочка записывается как плечо `:else` предыдущего `if`.
- `branches[].condition_text` это `toString()` условия JavaParser'а, без вычисления значения. Вычислять условие — работа M4, не archparse.
- `branches[].early_exit` задаётся по плечам: `then` и `else` равны `true`, если плечо заканчивается `return`/`throw` на всех путях (в том числе внутри вложенного `if/else` или цепочки `else if`). Нужно для R15.
- `branches[].then_calls` и `else_calls` это координаты `cs:line:col` вызовов, лежащих непосредственно в плече, без вложенных `if`.
- `calls[]` содержит **каждый** `MethodCallExpr` и `ObjectCreationExpr` в теле метода, с точной позицией. Сопоставление с `call_site` скелета делает Python по `(file, line, col)` (см. 3.2). Вызовы без `call_site` в скелете (логгер, геттеры Lombok) Python отбрасывает сам.
- `calls[].kind`: `SAME_CLASS` (метод этого же класса), `ENUM` (получатель это константа известного enum, см. 3.3), `CONSTRUCTOR` (`new Foo(...)`), `OTHER` (всё остальное). Больше парсер ничего не классифицирует, remote и data берутся из скелета.
- `calls[].enum_constant` заполняется только для `kind = ENUM`. Именно этого скелету не хватает (`receiver_type=None`, см. R7 в `annotation_rules.md`).
- `unsupported` — строки вида `"line 87: while loop not modeled (R17)"` для циклов, `switch`, `try`, тернарных операторов и лямбд. Тело цикла в IR выглядит как безусловное, потребитель обязан трактовать такую строку как «здесь неизвестно».

### 3.2. Как привязывать вызов к `call_site` скелета — НЕ собирай строковый ID сам

Скелет (`skeleton/trainticket.json.gz`) хранит у каждого `call_site`-узла явные поля `file`, `line`, `col` (`col` — 1-based позиция начала имени вызываемого метода, **в байтах UTF-8**: если до вызова в строке есть кириллица или иероглифы, колонка JavaParser'а, считающая символы, не совпадёт; парсер пересчитывает её сам). Твоя задача — выдать `(file, line, col)` вызова из JavaParser (`MethodCallExpr.getName().getBegin()` даёt именно это, 1-based). Не пытайся реконструировать строку вида `call:method:...@line:col` вручную — формат ID скелета могут менять, а `(file,line,col)` — это просто геометрия исходника, которая не меняется. Сопоставление по этим трём полям сделает Python-сторона (`engine/adapters/skeleton.py` уже индексирует `call_site` по `method`, легко добавить индекс по `(file,line,col)`).

Проверка на сегодня: после первого прогона на `CancelServiceImpl` и `InsidePaymentServiceImpl` — вручную (или маленьким скриптом) свериться, что для **каждого** вызова из `calls[]` в скелете находится `call_site` с тем же `(file,line,col)`. Если не находится — проверить, что колонка считается от той же точки (имя файла в скелете может быть с префиксом `targets/trainticket/` или без — сверить один раз руками).

### 3.3. Резолюция enum-констант (R7, явно поручено M2 в ADR-005 и annotation_rules.md)

В этом пуле enum-типов всего два: `edu.fudan.common.entity.OrderStatus` и `edu.fudan.common.entity.SeatClass` (оба в `ts-common`). Не нужен общий symbol resolver — достаточно:

1. Жёстко завести список известных enum FQN (`OrderStatus`, `SeatClass`) и их констант (видно из `edu/fudan/common/entity/OrderStatus.java`, `SeatClass.java` — там же лежат `getCode()`/`getNameByCode()`).
2. В `MethodCallExpr` проверять: `scope` — это `FieldAccessExpr` или `NameExpr`, чьё имя совпадает с одной из известных констант (`NOTPAID`, `PAID`, `CHANGE`, `COLLECTED`, `CANCEL`, `USED`, `FIRSTCLASS`, `SECONDCLASS`...), и статический импорт/квалификатор указывает на один из двух типов.
3. Если да — `enum_constant: {type, constant}`, `callee` — имя метода (`getCode`, `getNameByCode`). Python-сторона сама построит целевой `method_id` (`method:ts-common:edu.fudan.common.entity.OrderStatus#getCode()`)

Это закрывает R7 не только для `Order#<init>()` (где это уже захардкожено в `graph/builder.py._add_order_constructor_calls`), а для **всех** `== OrderStatus.XXX.getCode()` проверок в пуле — то есть status-гейтов в Cancel/Execute/Rebook, которые сейчас не дают `calls`/`executes` ребро на сам `getCode()` вообще.

### 3.4. Два прохода

Скелет уже знает, какие вызовы удалённые (`remote_call`), какие идут в БД (`data_access`) и кто кого вызывает. Поэтому первый проход не классифицирует вызовы заново, а собирает только то, чего в скелете нет.

1. **Проход 1, индекс.** По всем файлам пула и `ts-common`: поля класса и их типы, локальные переменные и их типы, enum-типы с константами, сигнатуры методов. Результат: карта «класс, имя, тип», нужная, чтобы во втором проходе понять, что `restTemplate` это `RestTemplate`, а `OrderStatus.PAID` это константа enum.
2. **Проход 2, структура.** По методам пула: цепочки `if/else if/else` и `switch`, каждый вызов с позицией `(file, line, col)`, вид вызова (проектный, enum, прочее), `early_exit`. Тип получателя берётся из карты прохода 1 без полного `SymbolSolver`: код Train Ticket простой, поля и локальные переменные объявлены явно.

## 4. Задачи на сегодня (по порядку)

1. **(10 мин, не archparse)** Поправить `rules.py`: убрать баг из 0.1 (`getOrderByIdFromOrder(`/`executeOrder(`-пробник не должен быть в списке исключений для `regular_only`). Прогнать `run_eval.py` на S0, убедиться, что ничего не сломалось (в S0 это не задействовано — login/contacts/orders/consign, cancel/execute не участвуют, так что тест только на регрессию, не на улучшение S0).
2. **Файловый список пула.** Зафиксировать 7 файлов из таблицы раздела 2 (плюс `OrderStatus.java`, `SeatClass.java` для списка констант) как единственный вход `Main.java` на сегодня — не `Files.walk` по всему репозиторию, а явный список путей. Это разводит "весь archparse" (будущее) от "пул дня 1" и защищает от хрупких файлов в остальных 394.
3. **Написать парсер заново** (старый PoC с `@PostMapping`/`Endpoint` удалён). Два прохода, см. раздел 3.4. Второй проход: по каждому методу из пула — обойти тело, собрать `IfStmt` (включая `else if` как цепочку, не как вложенность) и все `MethodCallExpr`/`ObjectCreationExpr` с позициями. `ReturnStmt`/`ThrowStmt` внутри блока → `early_exit=true` для этого блока.
4. **Enum-резолюция** по правилам раздела 3.3 — отдельный маленький модуль/класс, не вклеивать в основной visitor.
5. **Сериализация** в `archparse/out/pool_ir.json` по схеме раздела 3.1.
6. **Проверка сопоставления** по разделу 3.2 на `CancelServiceImpl` и `InsidePaymentServiceImpl` — вручную или мини-скриптом на Python, сверяя с `skeleton/trainticket.json.gz`.
7. **Текстовая памятка находок** — отдельно от JSON, просто список: для каждого метода из пула — "что нашёл, совпадает/не совпадает с текущим `rules.py`". По аналогии с пунктом 0.1. Это даёт score уже сегодня через ручные правки `rules.py`, не дожидаясь, пока Python-сторона научится читать `pool_ir.json`.
8. Если время останется — то же самое для `PreserveOtherServiceImpl`/`other.entity.Order` (зеркальные классы), но не раньше, чем формат проверен на основных классах.

## 5. Что дальше (не сегодня, чтобы не размывать фокус)

- Подключение `pool_ir.json` к `engine/graph/builder.py`/`rules.py` как источник условий вместо части `ScenarioProfile`-флагов — отдельная задача, зависит от того, появятся ли у M1 конкретные параметры шага (`assurance`, `foodType`, `tripId`...) — сейчас `engine/resolver.py` даёт только ID обработчика, не значения полей запроса. Без этого даже идеальный `pool_ir.json` не даст движку автоматически вычислить ветку — п. 7 выше (текстовая памятка) существует именно потому, что автоматическая интеграция не успеет сегодня.
- Расширение пула на `TokenServiceImpl.getToken` (verifyCode-гейт), `UserServiceImpl.saveUser/createDefaultAuthUser` (S4), `AdminOrderServiceImpl.getAllOrders` (S6) — после того, как формат пройдёт обкатку на первой пятёрке.
- Полный IR по ADR-005 (`ir/<module>.json`, все операторы, lambda-блоки, try/catch) — после хакатона или если Day 1 пул даст заметный прирост и останется время.
