# Соглашения проекта в M4 из кода: алиасы полей, повтор шага, признак отказа

20.10.2026, ветка `feature/102-m4-code-derived-rules`. Разбор групп, которые остались в M4 после ADR-007 (решение 6: «не трогаем `_FIELD_ALIASES`, нормализацию строк при повторе, `_is_failure`»). Аудит — [universality_audit_after_1_0.md](universality_audit_after_1_0.md), пункты 2.2.1, 2.2.3, 2.2.4.

Итог: выдача при умолчаниях — sha256 `94463c41…5a08`, рекорд байт в байт; `--m4-conventions names` (откат) — тот же sha256.

## Ставки

Итог S1–S7 против рекорда, если правило убрать (зонды по выдаче кода, 20.10):

| Что убрано | Итог |
|---|---|
| `_FIELD_ALIASES` целиком | 0.901 |
| `oldTripId ← trainNumber` (S2.14, S7.10) | 0.941 |
| `tripId ← trainNumber` (все 8 оплат) | 0.953 |
| `from`/`to` (5 бронирований) | 0.980 |
| `date` | 0.997 |
| повтор шага целиком | 0.939 |
| ступень 1 повтора (`"Ning Bo" → "ningbo"`) | 0.997 |
| `Response` в правиле успешного пути | 0.910 |

## Что сделано (`--m4-conventions code`, по умолчанию)

**Признак отказа** — `engine/executor/envelope.py`. Класс, поле статуса, значение успеха и поле данных выводятся из кода:

- класс — тот, что чаще всего строят в `return new X(<целое>, "<строка>", …)` (IR): `Response`, 263 раза;
- поле статуса — единственное целое поле класса (`status`), поле данных — поле с типом-параметром класса (`data`);
- значение успеха — литерал, с которым UI сравнивает статус: `status == 1` в 54 местах из 56. Без UI — сравнения `getStatus() == / != <литерал>` в IR (1 — 46, 0 — 35). Одних конструкторов мало: `new Response(0, …)` больше, чем `(1, …)`.

Им пользуются правило успешного пути (`arm_fails`), повтор шага (`_is_failure`) и разрешение ссылок (`_payload`). Без соглашения отказ — только `throw` и `return null`.

**Ступень 1 повтора** — `StepExecutor._world_string`. Причина отказа S6.4 и S6.6: станцию в S6.2 сохранил сеттер проекта (`Station.setName`: без пробелов, строчными), а `queryForIdBatch` ищет `"Ning Bo"` в `HashMap` по именам из БД. Текст шага — запись значения, которое лежит в мире. Каждая часть словесной строки заменяется значением мира БД с тем же ключом (строчные буквы и цифры). Если таких значений несколько, берётся то, что встречается в большем числе колонок: в данных прогрева рядом с `shanghai` (10 колонок) есть `delivery.station_name = 'Shang Hai'` (1). Подстроки имён параметров (`station`, `place`, `from`, `to`) больше не нужны.

**`tripId`, `oldTripId`** — каталог UI, `UIRequest.body_src` → `StepRequest.body_src` → M4. UI берёт поле тела из элемента списка в шаблоне через состояние компонента:

```
client_order_list.html: v-on:click="payMyOrder(index, item.id, item.trainNumber, item.price)"
client_order_list.js:   payMyOrder(num, orderId, tripId, price) { this.tripId = tripId; … info.tripId = that.tripId
```

Каталог находит `tripId ← trainNumber` (оплата), `oldTripId ← trainNumber` (перебронирование), `targetDate ← boughtDate` (багаж), `startPlace ← from` (поиск со страницы заказов). В промпт M1 поле не идёт: каталог без него совпадает с прежним `data/ui_catalog.json`, кеш LLM цел. Контроль: без `body_src` итог 0.901.

## Маршрут и дата бронирования из текста (21.10, ветка `feature/108-params-route-from-text`)

Было: `from`, `to`, `date` в бронировании брались по таблице `_FIELD_ALIASES` (`schema.py`) из полей найденного рейса с именами Train Ticket (`startStation`, `startPlace`, `travelDate` …). В UI это многозвенная цепочка: аргумент шаблона → параметр URL → разбор URL по позиции → DOM → тело. Общий путь — M1 заполняет поля из текста («from Shanghai to Suzhou on 1 October 2026»). Мешала фраза `PARAMS_TASK_V8` «Use null for … anything taken from results of earlier steps»: маршрут бронирования модель считала результатом поиска (только в S1.6 она это правило нарушила и поля заполнила).

Сделано: конец `PARAMS_TASK_V8` — «Use null for identifiers, for values known only from results of earlier steps, and for everything the text does not determine. Places and dates are not identifiers: when the request acts on a record that an earlier step searched for or opened by places and a date the text names, fill those places and that date from the text.» По умолчанию (`--m4-conventions code`) таблицы алиасов нет, поле ищется в записях прежних шагов только под своим именем и по каталогу UI (`body_src`). Таблица осталась у режима отката `names`.

Пересборка: `history_line` в промпте выбора параметров не содержит, поэтому промахнулись только 68 вызовов `params`. Выбор обработчиков, голоса и S2.14 взяты из кеша. Сервер на GPU 16 ГБ, обычный прогон (не `--no-cache`), около 2 минут. `PROMPT_VERSION` не менялась: она входит в ключ и сбросила бы весь кеш `m1-v8`.

| Итерация | Что модель заполнила | Выдача без алиасов |
|---|---|---|
| 1: «A place or a date that the text names is filled from the text, even when the request also uses a record found at an earlier step» | маршрут и дату в 6 бронированиях из 8; кроме того `stationsName` в S6.6 сократился до `Suzhou`, `tripId` в S6.9 | S6 +5 рёбер: S6.11 («on the new trip») без маршрута, оплата уходит во внешний `PaymentController` |
| 2 (принята) | маршрут и дату во всех 8 бронированиях (S1.6, S2.6, S2.11, S3.7, S3.8, S4.7, S5.8, S6.11) | sha256 `94463c41…5a08`, рекорд |

Побочные изменения итерации 2, выдачу они не меняют: `stationName = "Suzhou"` у еды со станции (S2.6, S2.11, S3.7) — это станция из описания; `isWithin = false` при багаже в S7.4 — так шлёт UI (`isWithin=False when need-consign checked`); дата в перебронировании S7.10. Режим `names` с новыми ответами — тот же sha256. `scripts/verify_llm_cache.py`: нарушений 0, прогон запросил 687 ответов, все в кеше; 136 устаревших записей `params` (исходные и итерации 1) удалены.
