# План развития archparse

**Дата:** 17.10.2026
---

## 1. Исходные данные

Баллы на платформе (общий 0.892710):

| S1 | S2 | S3 | S4 | S5 | S6 | S7 |
|---:|---:|---:|---:|---:|---:|---:|
| 0.903 | 0.873 | 0.875 | 0.904 | 0.894 | 0.911 | 0.889 |

Что мы знаем про S2 и S3:

- Эталон есть только для S0 (логин, контакты, заказы обоих типов, консайны). Покупка, оплата, отмена и перебронирование ничем не проверены.
- В пуле парсера 34 метода. В S2 исполняется 181 метод, в пуле из них 16. В S3 из 169 в пуле 9.
- Остальные ветвления решаются «успехом по умолчанию», регэкспами по тексту сценария (`engine/rules.py`) и подстроками по `condition_text` (`engine/ir.py`).
- Метод в пул стоит добавлять только если его ветка зависит от сценария или состояния: тип поезда, опции заказа, статус заказа, пустые коллекции. Ветки вида «ошибка, ранний выход» ничего не меняют: успешный путь уже в ответе.

## 2. Блоки работ

### Блок 0. Измерение [ВЫПОЛНЕНО 17.10.2026]

- Журнал решений пишет сам `GraphBuilder` (`engine/decisions.py`), прогон сохраняет его в `output/decisions.json`. Журнал совпадает с ответом ребро в ребро, это проверяет тест.
- `scripts/decision_log.py` только читает журнал. Список риска A: рёбра ответа, включённые одной достижимостью скелета (S2: 264 ребра в 127 методах, S3: 229 в 114). Список риска B: рёбра, срезанные `rules.py`, со строкой сработавшего правила (S2: 18, S3: 8).
- Расширение пула до 52 методов выдачу не изменило: новые ветки либо «ошибка, ранний выход», либо G/D-диспатч, который уже решали правила по `train_mode`.

### Блок 1. Пул для S2 (по убыванию риска)

1. [ВЫПОЛНЕНО] Диспатч обычный или скоростной поезд: `SeatServiceImpl#distributeSeat` и `getLeftTicketOfInterval`; `TravelServiceImpl` для travel2 (`getTripAllDetailInfo`, `getTickets`, `getTicketsByBatch`, `getRouteByTripId`); `OrderOtherServiceImpl` (`create`, `getSoldTickets`, `modifyOrder`, `queryOrdersForRefresh`). Включено в `pool_ir.json` (52 метода, 1980 вызовов, 100% сопоставление со скелетом).
2. [ВЫПОЛНЕНО] Перебронирование: `RebookServiceImpl#getOrderByRebookInfo`, `getTripAllDetailInformation`, `dipatchSeat`, `drawBackMoney`, `queryTrainTypeByName`, `getRouteByRouteId`, `checkTime`; `InsidePaymentServiceImpl#drawBack`. Включено в `pool_ir.json`.
3. [ОСТАЛОСЬ НА БУДУЩЕЕ] Хелперы отмены: `CancelServiceImpl#getOrderByIdFromOrder`, `getOrderByIdFromOrderOther`, `drawbackMoney`.
4. [ОСТАЛОСЬ НА БУДУЩЕЕ] Хелперы `PreserveOtherServiceImpl`: `dipatchSeat`, `createOrder`, `getAccount`, `getContactsById`, `checkSecurity`, `createFoodOrder`.

### Блок 2. Пул для S3

- Хелперы `PreserveServiceImpl`: опции еды, страховки, консайна.
- `AssuranceServiceImpl#create`, `AssuranceType#getTypeByIndex`.
- `ConsignServiceImpl#insertConsignRecord`.
- `ConsignPriceServiceImpl#getPriceByWeightAndRegion` пропускаем: геттеры сгенерированы, ветка по весу наблюдаемые рёбра не меняет.

### Блок 3. Общие методы всех сценариев (после блоков 1 и 2)

- `BasicServiceImpl#queryForTravels` (27 веток) и `queryForTravel`.
- `FoodServiceImpl#getAllFood`, `createFoodOrder`.
- `PriceServiceImpl`, `RabbitReceive#process`.

### Блок 4. Таблица правил вместо хардкода в `evaluate_guard`

**Статус:** Выполнено.
Создан контракт и файл `data/branch_rules.json`, модуль `engine/branch_rules.py` (`BranchRulesRegistry`), эвристики перенесены из `engine/ir.py`, добавлены тесты `tests/test_branch_rules.py`. Поддерживается отключение любого правила по ID/коду (абляции), валидация контракта и привязка к evidence.

### Блок 6. Конструкторы сущностей при загрузке из БД (R7) [ВЫПОЛНЕНО 17.10.2026, ждёт проверки на платформе]

- archparse `--mode entities` пишет `data/entity_ir.json`: сущности, вызовы репозиториев, IR конструкторов (README, раздел 3.5).
- Хардкод `Order` в `builder.py` удалён, решение в `engine/entities.py`. Прирост `executes`: от 5 до 10 конструкторов на сценарий S1–S7, S0 = 1.0000. Подробности: FINDINGS, раздел 4.
- Это не расширение пула и не ветки внутри методов, а немоделируемый механизм из раздела «Где искать дальше» аудита.


### Блок 5. Резолвер (не парсер, но влияет на S2 и S3)

Проверить привязку шагов к обработчикам: S3 шаги 6, 10, 11, 14, 15 и S2 шаг 9 (сколько вернут при отмене). Ошибочная привязка даёт пачку лишних и пропущенных рёбер.

## 3. Критерии приёмки порции

- `scripts/verify_pool_ir.py`: 100% совпадения со скелетом в обе стороны.
- `./gradlew test` и `python -m pytest -q tests` проходят (кроме известных трёх тестов по времени на этой машине).
- S0 остаётся 1.0000.
- Разница выдачи с предыдущей посылкой объяснена ребро за ребром.
- Одна посылка на платформу на порцию.
- README и FINDINGS обновлены в том же коммите.

## 4. Порядок

1. Блок 0.
2. Блок 1 пункты 1 и 2 и блок 2 одной порцией.
3. Блок 5.
4. Блок 3.
5. Блок 4 после согласования контракта с автором engine.

Заранее оценить прирост балла нельзя: эталона для S2 и S3 нет.
