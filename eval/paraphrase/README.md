# Перефразированные S0–S7

Тексты S0–S7 другими словами: тот же сценарий, те же факты, другие формулировки. Закрытые сценарии организаторов будут написаны не нашими словами, а эталона для них у нас нет. Здесь эталон есть, поэтому это единственный замер всего конвейера на незнакомом тексте с настоящими рёбрами (roadmap, П2, «Перефразированные шаги S1–S7»).

## Файлы

- `scenarios/S0.json` … `S7.json` — формат `hackaton/tt-challenge/scenarios/`, ID те же, что у оригиналов: так подходят `eval/m1_steps.json` и сравнение с рекордом. Ни один текст шага не совпадает с оригиналом дословно, переписаны и `title`, и `description`.
- `gold.json` — эталон в формате `platform/evaluate_golden.py`: S0 — `gold/S0.json` организаторов, S1–S7 — рекорд `eval/records/submission_p27_1.00000.json` (1.00000 на платформе при точности 1e-5, то есть совпадает с эталоном ребро в ребро). Без ключа `ids`: формат ID оценщик не проверяет. Проверка: рекорд против `gold.json` — 1.000.

## Как переписано

- Сохранено всё, от чего зависит выбор обработчика и параметры: города, дата, тип поезда (`GaoTie/DongChe`, `'Other'`), класс места, еда (на борту или со станции), страховка, вес багажа, статусы фильтров, даты, ожидаемый отказ, числа шагов администратора, имена `Ning Bo`, `GaoTieSix`, `G9101`.
- Заменены глаголы и обороты: Book → Reserve, Refresh the list of orders → Reload my orders, Search → Find / Look for, Open the details → Show the details, Collect the ticket → Pick up the ticket, Enter the station → Go through the station entrance, Check the price → See how much the order costs, internal account balance → internal account balance / the money on the internal account, Ask how much would be refunded → Find out how much money would come back, regular → ordinary, food → meal.
- Это стресс-тест: организаторы, скорее всего, пишут своим словарём (Book, Refresh, Collect), так что балл здесь — нижняя оценка для закрытых сценариев по формулировкам. Новых обработчиков он не проверяет, это делают `eval/own/`.

## Замер без моделей (22.10)

| | M1 BM25: top-1 | верный среди кандидатов | итог без LLM и эмбеддера |
|---|---|---|---|
| исходные S0–S7 | 61/103 | 92/103 | 0.623 |
| перефразированные | 37/103 | 62/103 | 0.477 |

BM25 не знает синонимов: Reserve не находит `preserve`, Reload — `queryOrdersForRefresh`, Find … trains — `queryInfo`. Сколько из этого закрывают векторы и LLM — вопрос прогона на GPU.

## Прогон с моделями (22.10, до #147)

RTX 5070 Ti 16 ГБ, `ARCHONITY_LLAMA_ARGS="-ncmoe 7 -dev Vulkan1"`, ветка слита с `dev` (код M4 как в `dev`). Кеша для этих текстов не было: 405 ответов LLM от сервера (1 из кеша), векторов шагов докачано 72 (в `cache/emb` было 520, стало 592). Прогон 1103 с, из них сервер LLM 1063 с, пик видеопамяти 15.8 ГБ, ошибок и шагов без ответа нет, режим M1 `full`, все 103 шага выбраны моделью.

Команды (как в предыдущей редакции):

```powershell
$env:PYTHONUTF8=1; $env:ARCHONITY_LLAMA_ARGS="-ncmoe 7 -dev Vulkan1"
python run_eval.py --scenarios "eval/paraphrase/scenarios/*.json" --no-eval -o output/paraphrase/submission.json
python hackaton/tt-challenge/platform/evaluate_golden.py eval/paraphrase/gold.json output/paraphrase/submission.json
python -m engine.grounding.grounder eval/paraphrase/scenarios/S*.json --eval eval/m1_steps.json --embed-model
```

### Балл

| Сценарий | S0 | S1 | S2 | S3 | S4 | S5 | S6 | S7 | среднее |
|---|---|---|---|---|---|---|---|---|---|
| перефразированные | 1.000 | 0.852 | 0.973 | 0.852 | 0.880 | 0.965 | 0.827 | 0.840 | **0.899** |

По видам рёбер (среднее по сценариям): `executes` 0.908, `calls` 0.871, `remote` 0.872, `data` 0.944. Полнота везде 1.00 (S7 `calls` — 0.99): потери только в точности, то есть ошибка M1 даёт лишнее исполнение чужого обработчика, а не пропуск. Без моделей было 0.477, с моделями 0.899; исходные тексты дают 1.0.

### M1

Точность top-1 на шаге: 92/103 = 0.893; верный обработчик среди кандидатов: 82/103. Параметры шагов: 47/47 = 1.000. Ошибок 11, они повторяют три формулировки:

| Шаг | Что выбрала модель | Верный обработчик | Шагов |
|---|---|---|---|
| «Find GaoTie/DongChe (high-speed) trains from … to …» | `TravelPlanController#getByQuickest` | `TravelController#queryInfo` | S1.2, S3.2, S4.4, S6.8, S7.2 |
| «Reload my orders» | `OrderController#findAllOrder` (S2 — `OrderOtherController`) | `queryOrdersForRefresh` | S1.7, S2.7, S2.12, S7.5 |
| «Reload my orders, showing only those bought today» | `OrderController#queryOrders` | `queryOrdersForRefresh` | S7.14 |
| «Create a new passenger account …» | `AdminUserController#addUser` | `UserController#registerUser` | S4.1 |

Для всех, кроме S7.14, верного обработчика нет среди кандидатов M1: ни BM25, ни векторы его не находят (Reload — `queryOrdersForRefresh`, Find … trains — `queryInfo`). Чинить надо поиск кандидатов, а не выбор LLM. Совпадает с шагом «Reload my orders on high-speed GaoTie/DongChe trains» из замера 21.10 (`docs/run_on_a100.md`).

### Проверки

- Выдача S0–S7 оригиналов прежняя: `python run_eval.py --require-cache` даёт sha256 `94463c41a72c244fc548cbb52d009cff7c65f44ad5e682b7176a156cb66a5a08`.
- В `cache/` добавлены 405 файлов `cache/llm/*.json` (читаются, поле `key` на месте) и обновлён `cache/emb/qwen3-4b/vectors.npz` (592 вектора, NaN нет). Повтор M1 на перефразировках идёт целиком из кеша: grounder сообщил «кеш 406, вызовов 0».

## Повтор на `dev` после #133 и #147 (22.10)

Тот же прогон на `dev` с синонимами глаголов в BM25 (#147, `VERB_SYN_EXTRA`). RTX 5070 Ti 16 ГБ, `ARCHONITY_LLAMA_ARGS="-ncmoe 7 -dev Vulkan1"`. Синонимы поменяли кандидатов M1, поэтому часть ключей кеша новая: 270 ответов LLM от сервера, 112 из кеша; векторов шагов промахов нет (`cache/emb` не менялся). Прогон 756 с (сервер LLM 735 с), пик видеопамяти 15.6 ГБ, ошибок и шагов без ответа нет.

| Сценарий | S0 | S1 | S2 | S3 | S4 | S5 | S6 | S7 | среднее |
|---|---|---|---|---|---|---|---|---|---|
| до #147 | 1.000 | 0.852 | 0.973 | 0.852 | 0.880 | 0.965 | 0.827 | 0.840 | 0.899 |
| после #147 | 1.000 | 1.000 | 1.000 | 1.000 | 0.987 | 0.965 | 0.963 | 1.000 | **0.989** |

Виды рёбер (среднее): `executes` 0.992, `calls` 0.994, `remote` 0.988, `data` 0.983.

M1: top-1 102/103 = 0.990 (было 92/103), верный среди кандидатов 97/103 (было 82/103), параметры 47/47. Единственная ошибка M1 — S4.1 «Create a new passenger account …»: `AdminUserController#addUser` вместо `UserController#registerUser`, верного нет среди кандидатов. Она даёт все лишние рёбра S4: 3 `executes` и 2 `calls` в `admin-user-service` и один `remote` из `AdminUserServiceImpl#addUser` в `UserController#registerUser`; пропусков в S4 нет.

Остаток S5 и S6 не от M1: шаги выбраны верно, параметры 47/47. По рёбрам против эталона:

- S5 (0.965): только лишние рёбра, полнота 1.00. Исполнитель заходит в `ConsignController#insertConsign`, `ConsignPriceController#getPriceByWeightAndRegion` и `PreserveOtherServiceImpl#createConsign` (с их `data` в `consign_record` и `consign_price`), а эталон их не содержит. Результат совпал с прогоном до #147, то есть от синонимов не зависит.
- S6 (0.963): только пропуски, точность 1.00. Нет `OrderController#modifyOrder` → `OrderServiceImpl#modifyOrder` (и `data` в `orders`), `InsidePaymentServiceImpl#setOrderStatus` с `remote` в заказ, `data` из `pay` в `inside_money` и `inside_payment`.

Причину S5 и S6 не разбирали: нужно смотреть `decisions.json` по этим шагам (кандидаты в roadmap, не в этот PR).

### Проверки

- Выдача S0–S7 оригиналов прежняя: `python run_eval.py --require-cache` — sha256 `94463c41a72c244fc548cbb52d009cff7c65f44ad5e682b7176a156cb66a5a08`.
- Добавлены 270 файлов `cache/llm/*.json`, все читаются. Повтор M1 на перефразировках идёт из кеша: «кеш 382, вызовов 0».

## S6.13: правило «созданная запись, а не элемент списка» в промпте M1 (22.10, отвергнуто)

Остаток S6 (0.963) — шаг 13 «Pay for the order with the internal account balance»: M1 дал `order: first_of_step_12` (список после «Reload my orders»), а нужен заказ, забронированный шагом 11. Первый в списке — старый заказ пассажира из дампа, `pay` идёт не по тому пути: нет `modifyOrder`, `setOrderStatus` с их `remote` и `data`. Цена шага +0.037 к S6 (`scripts/m1_error_cost.py`). В M4 правило «первый в списке — новый» не ставили: порядок списка заказов нигде не задан (`client_order_list.js` не сортирует, `findByAccountId` без `ORDER BY`).

Попробовали правило в абзаце `refs` у `SELECT_TASK_V8` (ветка `feature/150-m1-new-over-list-ref`), без слов домена:

> When the step names a record without a position ("the ...", "this ...") and an earlier step created a record of that kind, use new_of_step_N of the step that created it, even if a later step listed records of that kind: a list can hold older records, and its order is not defined. Use first_of_step_N or second_of_step_N only when the step names a position, or when no earlier step created the record.

Условие приёма: `run_eval.py --require-cache` после пересборки кеша даёт sha256 рекорда `94463c41…5a08`, ничья голосов S2.14 цела. **Не выполнено, правку откатили (revert).**

| Проверка | Результат |
|---|---|
| Цель, перефразированный S6 с новым текстом (51 вызов, 145 с) | шаг 13 исправлен: `order: first_of_step_11`, это созданный шагом 11 заказ (`first` у шага-создателя M4 берёт сохранённую сущность). Но S6.6 «Create … trip G9101» перевернулся: `TravelController#createTrip` вместо `AdminTravelController#addTravel` (голоса были 2:4, стали 3:2). S6 0.946 вместо 0.963 |
| Ворота: S0–S7 оригиналов с пересборкой `select` (319 вызовов сервера, 894 с) | sha256 `048f6e98…`, S0–S7 **0.948** вместо 1.000 |

Что перевернулось в S0–S7 при одном добавленном предложении:

- **S2.14**: `rebook` → `payDifference`, голоса 3:3, решал жадный ответ. S2 0.758 (+110/−16 рёбер).
- **S6.8**: `queryInfo` → `TravelPlanController#getByQuickest`, голоса 4:2 → 1:3. S6 0.827 (+91 ребро).
- S7.12: ссылка `consignRecord: first_of_step_11` → `order: new_of_step_4`, S7 0.999 (+1 `calls`).
- `refs` изменились в 23 шагах из 103 (в 21 из них обработчик прежний), почти везде на равноценные: `first_of_step_N` ↔ `new_of_step_N` у шага, который создал запись, лишний или пропавший `user`. Цель в воротах достигнута (S6.13: `order: new_of_step_11`), но выбор обработчика на шагах с разделёнными голосами (в рекорде S2.10 3:1, S2.14 3:3, S6.8 4:2) любая правка текста `select` переигрывает заново.

Вывод для следующей итерации: правка промпта M1 проверяется рекордом, пока эти три шага держатся на разделённых голосах, а они держатся. Прежде чем возвращаться к S6.13, нужно сделать S2.14 (`rebook` против `payDifference`) и S6.8 (`queryInfo` против `getByQuickest`) однозначными по карточкам, а не по ничьей; тогда то же правило можно проверить ещё раз. Те же шаги на закрытых сценариях при живом LLM решаются так же жребием.

### Что пробовали после отката и что вошло

**Стабилизация S2.14 карточкой (не вошла).** Карточка follow-up `payDifference` печатает условие возврата `status 2` из IR как есть: `!(priceOld.compareTo(priceNew) > 0) && !(priceOld.compareTo(priceNew) == 0)`. Модель читала его как «новая не дороже» и выбирала `payDifference` на шаге «the cheaper ticket». Читаемая запись условий (`a.compareTo(b) > 0` → `a > b`, снятие отрицаний: `priceOld < priceNew`) перевела S2.14 из голосов 3:3 в 3:1 за `rebook`, затронуты 31 вызов (карточки бронирования и перебронирования), 98 шагов из 101 без изменений. Но жадный ответ S2.14 потерял ссылку `trip: first_of_step_2`, и S2 разошёлся с рекордом на +93 ребра (S2 0.804, sha256 `fa5e9dda…`): `rebook` без нового рейса M4 исполняет по неизвестным веткам. Ответ рекорда в кеше — одна конкретная выборка; любой другой ответ на тот же шаг, даже верный по смыслу и по обработчику, рекорд меняет. Вывод: пока рекорд держится на записанных ответах, карточки и промпт M1 нельзя править без перезаписи S2.14; патч в репозиторий не вошёл.

**Правило в M4 вместо промпта (вошло, по умолчанию off).** R22 ([annotation_rules.md](../../docs/annotation_rules.md)): ссылка `first`/`second_of_step_N` без слова позиции в тексте шага и запись этого вида, созданная раньше, чем читался список N, — это созданная запись. Замеры на готовых ответах M1 из кеша (флаг `--ref-unpositioned on`, M1 не вызывается):

| | off | on |
|---|---|---|
| S0–S7 оригиналов, sha256 | `94463c41…5a08` | `94463c41…5a08` (одна замена, S7.12, рёбра те же) |
| перефразированные S0–S7 | 0.994 | **0.998** (S6 0.963 → 1.000; остаток S4 0.987 — S4.1, шаг без ответа в кеше после #150) |
| X1–X12 | — | замена одна: X10.8; X10 0.900 → 1.000 по оракулу |

Правило есть в обоих движках: Rust — `StepCore::prefer_created` (`archonity-m4`), выдачи с ним совпадают с Python байт в байт на S0–S7, X1–X12 и перефразировках (`tests/test_ref_unpositioned.py`). Умолчание пока off.
