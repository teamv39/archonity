# Свои сценарии

Сценарии в стиле организаторов на обработчики, которых нет в S1–S7 (roadmap, П2). Нужны, чтобы проверить M1 и M4 на том, чего мы не видели.

**Это наша разметка, а не эталон организаторов.** Расхождение пайплайна с ней — вопрос, а не баг. Правка кода по расхождению — только с механизмом из кода Train Ticket, под флагом и с проверкой sha256 на S0–S7. Подгонка под эти сценарии без механизма теряет баллы на закрытых сценариях так же, как подгонка под S1–S7.

## Файлы

- `scenarios/X*.json` — сценарии в формате `hackaton/tt-challenge/scenarios/`.
- `steps.json` — ответ на каждый шаг, схема `eval/m1_steps.json` плюс два поля:
  - `outcome`: `success`, `refused` или `other` (ответ не отказ и не успех, например «доплатите разницу»);
  - `branch`: ветка исполнения с файлом и строками.

`status`: `ok` — запрос есть в активном UI; `no_ui` — в UI его нет, обработчик по коду сервиса; `disputed` — спорно, тогда `alt` тоже считается верным. При `ok` и `no_ui` поле `alt` — ловушки, которые проверили и отвергли (причина в `note`).

## Как размечено

Каждый ответ подтверждён кодом, а не догадкой:

1. Обработчик — по запросу в `ts-ui-dashboard` или маршруту контроллера и правам в `SecurityConfig` сервиса.
2. Исход — по условиям в сервисе и данным `context/db-after-warmup.sql.gz`.
3. Если шаг допускает два прочтения, меняется текст шага, а не выбирается одно из прочтений.

| ID | Тема | Новое относительно S1–S7 |
|---|---|---|
| X1 | Перебронирование с доплатой, отмена перебронированного и неоплаченного заказов | `rebook` с ответом «доплатите разницу», `RebookController#payDifference`, отказ расчёта возврата для статуса CHANGE, ветка NOTPAID в `calculate` и `cancelTicket` |
| X2 | Контакты: добавить, дубликат, изменить, удалить | отказ `createNewContacts`, `modifyContacts`, `deleteContacts` |
| X3 | Админ: станции, типы поездов, цены | `getAll*`, `modify*`, `delete*` в `AdminBasicInfoController`, отказ `addStation` |
| X4 | Неверный пароль, занятое имя, новый пустой аккаунт | отказ `getToken`, отказ `registerUser`, пустые контакты и багаж |
| X5 | Админ: пользователи и заказы | `AdminUserController` (добавить, дубликат, изменить, удалить), `AdminOrderController` (добавить, сменить статус, удалить) |
| X6 | Админ: рейсы, маршруты, конфиги | правка рейса G9998 проходит, G1234 отказывает (станции не на маршруте), отказ `addTravel` (нет типа поезда), удаление рейса и маршрута, конфиги |
| X7 | Админ: контакты | близнец X2 через `AdminBasicInfoController`: добавить, дубликат, изменить, удалить |
| X8 | Багаж и страховка после покупки | `updateConsign` по трём веткам (вставка при пустом id, пересчёт цены при новом весе), `findByOrderId` пусто и найдено, `findByConsignee`, цена вне региона, страховки нет |

## Проверка M1

```bash
python -m engine.grounding.grounder eval/own/scenarios/*.json --eval eval/own/steps.json --embed-model
```

Ответы LLM и векторы шагов X1–X8 лежат в `cache/` с 21.10: проверка M1 и прогон всего пайплайна идут без GPU и сервера LLM.

Замер 21.10: RTX 5070 Ti 16 ГБ, сервер с `-ncmoe 7 -dev Vulkan1` (раздел «Видеокарта 16 ГБ» в [run_on_a100.md](../../docs/run_on_a100.md)). Ответов на эти сценарии в кеше тогда не было; векторы шагов считал эмбеддер на CUDA отдельным прогоном до прогона с LLM.

| M1 | X1–X4: top-1 | среди кандидатов | X5–X8: top-1 | среди кандидатов |
|---|---|---|---|---|
| только BM25 (`--no-llm --no-embed`) | 20/41 | 36/41 | 17/42 | 34/42 |
| BM25 и векторы (`--no-llm`) | 24/41 | 41/41 | 24/42 | 40/42 |
| целиком: BM25, векторы, LLM | **39/41** | 41/41 | **39/42** | 40/42 |

Только BM25 — нижняя граница поиска, а не точность M1. В X5–X8 шесть из восьми промахов BM25 мимо кандидатов — шаги консоли администратора: в кандидаты попадают сервисные близнецы (`OrderController#findAllOrder`, `Travel2Controller#queryAll`), а не `Admin*Controller`.

Ошибки M1 целиком:

- X1.4 и X1.11 — `OrderController#createNewOrder` вместо `PreserveController#preserve`. Параметры X1–X4 7/13: шесть промахов — параметры брони (`seatType`, `assurance`, `foodType`) этих двух шагов, они ушли вместе с обработчиком.
- X5.9 «Change the status of the new order to 'Paid'» — `OrderController#modifyOrder` вместо `AdminOrderController#updateOrder`; с ним ушёл параметр `status`, параметры X5–X8 3/4.
- X6.2 «Open the list of all trips» — `TravelController#adminQueryAll` вместо `AdminTravelController#getAllTravels`, верного нет среди кандидатов.
- X8.8 «Add a luggage consignment of 5 kg…» — `ConsignController#insertConsign` вместо `updateConsign`, верного нет среди кандидатов.

Ресурсы:

- LLM: X1–X4 — 271 ответ за 638 с, X5–X8 — 274 ответа за 630 с; сервер поднимался за 17 с (файл модели уже был в кеше ОС).
- Пик видеопамяти: сервер LLM — 15 418 МиБ (часть экспертов MoE в RAM, `-ncmoe 7`), эмбеддер на CUDA — 8 124–8 250 МиБ. Векторы CPU и CUDA совпадают с косинусом 0.9998–0.9999, в кеше — векторы CUDA.

Прогон всего пайплайна (`--no-eval`: эталона своих сценариев у платформы нет):

```bash
python run_eval.py --scenarios "eval/own/scenarios/*.json" --no-eval -o output/own/submission.json
```

Из кеша: режим M1 `full`, 546 ответов LLM (271 на X1–X4, 274 на X5–X8 и профиль проекта), промахов векторов 0, `--require-cache` проходит без GPU. sha256 выдачи — оракул для правок:

| Сценарии | sha256 `submission.json` |
|---|---|
| X1–X8 (`*.json`) | `92c0affe54d29c74cf96741f626a51ff842e361f4060fc74b0988e45afe20b5b` |
| X1–X4 (`X[1-4].json`) | `561bc45c60a5ecae208dc4be5d2e3383ad0b74c55194ba7a5adfd705f7c95312` |
| X5–X8 (`X[5-8].json`) | `878d7a50c3ef771c58d62b6fda16de435c1ddaa565af3d5bd24591e4fd175c1e` |

Выдачи X1–X4 и X5–X8 из кеша совпали с прогонами с сервером LLM. 22.10 правило «сущность, названная явно» (`--ref-explicit-id`, annotation_rules.md, R21) добавило X6 10 рёбер шага 3; прежние sha256 X1–X8 и X5–X8 (`7053de3d…`, `f1a12b5e…`) даёт `--ref-explicit-id off`. 22.10 правило «получатель багажа без полей группы» (`--consign-absent-group`, annotation_rules.md) убрало из X8.4 «…without food, assurance or consignment» 4 ребра consign-ветки; прежние sha256 X1–X8 и X5–X8 (`c8742790…`, `9cd5d733…`) даёт `--consign-absent-group off`.

## Проверка M4

Исход каждого шага у M4 против поля `outcome` разметки. Прогон — сам `run_eval.py` с теми же ключами, выдача та же (sha256 выше):

```bash
python scripts/check_own_outcomes.py -o output/own-outcomes [--show all] -- --require-cache
```

Исход M4 — статус обёртки ответа обработчика шага: `success`, `failure`, `unknown` (статус не вычислен), `null`, `value` (ответ не обёртка). Шаг с неверным обработчиком M1 считается ошибкой M1. Построчно — `outcomes.json` в папке прогона.

Замер на `dev` 22.10 вечером (X1–X8, 83 шага, `c8742790…`): совпало **68**, ошибки M1 — 5, исход M4 другой — 4, исход M4 неизвестен — 6. Утром было 65 / 5 / 6 / 7. #138 и #143 (влиты) исходы из кеша не меняют (проверено до мержа на ветке #143: отличий 0) — их правки видны только при верном выборе M1, см. ниже.

Что осталось:

| Шаг | Разметка | M4 | Причина | Что делать |
|---|---|---|---|---|
| X1.4, X1.11 | success | success | M1: бронирование в `OrderController#createNewOrder` вместо `PreserveController#preserve`, голоса 3:0 | промпт M1, пересборка кеша на GPU; самая дорогая ошибка (на перефразировках S0–S7 +0.16…+0.33 балла сценария за шаг, `scripts/m1_error_cost.py`) |
| X5.9 | success | success | M1: `OrderController#modifyOrder` вместо `AdminOrderController#updateOrder` (близнец консоли администратора) | промпт M1 |
| X6.2 | success | success | M1: `TravelController#adminQueryAll` вместо `AdminTravelController#getAllTravels`, верного нет среди кандидатов | поиск M1 |
| X8.8 | success | success | M1: `insertConsign` вместо `updateConsign`, верного нет среди кандидатов | поиск M1 |
| X1.7 | other | success | каскад X1.4: заказ создан `createNewOrder` без `trainNumber` и цены, у `rebook` пустой `oldTripId`, ветки по догадке. При верном бронировании M4 даёт status 2 «Please pay the different money!» | ничего: чинится вместе с X1.4 |
| X1.9, X1.13 | refused, success | unknown | каскад X1.4/X1.11. При верном бронировании и #143 — «Cancel Not Permitted» и «Refoud 0», как в разметке (`tests/test_rebook_difference.py`) | сделано в #143 |
| X4.1 | refused | success | неверный пароль: отказ бросает библиотечный `AuthenticationManager.authenticate`, M4 его не видит | не чиним до сдачи: вход есть в каждом S1–S7, механизм был бы на `expected_outcome` M1 |
| X4.2, X4.3, X5.3, X5.4 | — | unknown | статус ответа `registerUser` не вычислен: `ResponseEntity.status(..).body(..)` не разобран (2 места в проекте). Ветка `saveUser` при этом верная — рёбра по разметке, в X5.4 `USER HAS ALREADY EXISTS` | не чиним: рёбер не меняет |
| X4.7, X8.13 | success | failure | расхождения нет: «пусто» в сервисе — статус 0 `No Content…`, ветка та же | — |

Исправлено 22.10:

| Шаг | Было | Правка |
|---|---|---|
| X6.8 | `deleteRoute` отказывал | производные запросы Spring Data со словом между глаголом и `By` (`removeRouteById`, `deleteFoodOrderByOrderId`, `removeAssuranceByOrderId`) разбираются как `PartTree` (#134). Рёбра не изменились: обе ветки `deleteRoute` дают одни рёбра |
| X7.4 (и мир X5) | дубликат через консоль администратора неизвестен | поле дубликата (ADR-007, решение 6) ищется и через remote_call: админка пересылает тело сервису с проверкой (#134) |
| X6.3 | тело из ID G9998 и маршрута первого рейса | «сущность, названная явно», R21 (#135). X6 +10 рёбер успешного пути |
| все | константы enum портились в плечах и переходили в следующие сценарии | #138: ошибка M1 в одном сценарии больше не портит соседние |
| X1.8–X1.9 (при верном бронировании) | тело доплаты без `oldTripId`; ссылка на ответ без ID | #143: тело доплаты = тело перебронирования в каталоге UI, ссылка на сводку без ID ведёт к сущности шага |
