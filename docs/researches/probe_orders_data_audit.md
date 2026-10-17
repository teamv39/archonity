# Аудит гипотезы 3: Зондирующий SELECT в S2 (Шаги 9 и 10)

## Контекст и суть гипотезы

В сценарии S2 (оформление и отмена билета на обычный поезд) на шагах 9 («Ask how much would be refunded if the order were cancelled») и 10 («Cancel the order») вызывается сервис отмены `ts-cancel-service` (`CancelController#calculate` и `CancelController#cancelTicket`).

В методах `CancelServiceImpl#calculateRefund` и `CancelServiceImpl#cancelOrder` реализована двухэтапная логика поиска заказа:
```java
Response<Order> orderResult = getOrderByIdFromOrder(orderId, headers);
if (orderResult.getStatus() == 1) {
    ... // обработка заказа скоростного поезда (ts-order-service)
} else {
    Response<Order> orderOtherResult = getOrderByIdFromOrderOther(orderId, headers);
    ... // обработка заказа обычного поезда (ts-order-other-service)
}
```

Поскольку в сценарии S2 оформлялся обычный поезд (`train_mode == "regular_only"`), заказ находится в таблице `orders_other` сервиса `ts-order-other-service`. Однако `CancelServiceImpl` безусловно отправляет первый HTTP-запрос в `ts-order-service`. Метод `OrderServiceImpl#getOrderById` выполняет SQL-запрос `orderRepository.findById(orderId)` к таблице `orders`, который возвращает 0 строк (`Optional.empty()`), после чего `CancelServiceImpl` переходит к поиску в `ts-order-other-service`.

Аналогичный механизм зондирующего вызова работает и в сценарии S5 на шагах 11 и 12 (сбор билета и посадка на обычный поезд через `ts-execute-service`).

**Гипотеза:**
Учитывается ли в эталоне организаторов ребро `data` к таблице `ts-order-service.orders`, если зондирующий SELECT вернул 0 строк (заказ не найден в сервисе скоростных поездов)? Если эталон не учитывает безрезультатные поисковые запросы, то ребро `OrderServiceImpl#getOrderById -> res:table:ts-order-service.orders` является ложноположительным (FP).

## Реализация абляции

В движок и CLI добавлен параметр `--probe-orders-data` (`on` / `off`, по умолчанию `on`):
- [engine/rules.py](file:///c:/Users/Pavel/IdeaProjects/archonity/engine/rules.py): валидация режима `PROBE_ORDERS_DATA_MODES = ("on", "off")` в `RuntimeRules`.
- [engine/graph/builder.py](file:///c:/Users/Pavel/IdeaProjects/archonity/engine/graph/builder.py): при `probe_orders_data == "off"` в сценариях с `train_mode == "regular_only"` исключается ребро `data` от `OrderServiceImpl#getOrderById` к `res:table:ts-order-service.orders`.
- [engine/pipeline.py](file:///c:/Users/Pavel/IdeaProjects/archonity/engine/pipeline.py), [run_eval.py](file:///c:/Users/Pavel/IdeaProjects/archonity/run_eval.py): проброс параметра через CLI.

## Результаты тестирования на платформе NSUTS

Тестирование проведено на платформе NSUTS для команды **Your answer** (тур Semantic Graph, посылка №1664934 от 18.10.2026 03:10:16):

| Сценарий | Зондирующий SELECT включен (Baseline) | Зондирующий SELECT выключен (Абляция) | Дельта | Заказ в сценарии |
| :--- | :--- | :--- | :--- | :--- |
| **S0** (калибровка) | 1.000000 | 1.000000 | 0.000000 | Скоростной + обычный |
| **S1** | 0.933537 | 0.933537 | 0.000000 | Скоростной |
| **S2** | 0.882280 | 0.875137 | **-0.007143** | Обычный (отмена) |
| **S3** | 0.905265 | 0.905265 | 0.000000 | Скоростной |
| **S4** | 0.931118 | 0.931118 | 0.000000 | Скоростной |
| **S5** | 0.931903 | 0.925146 | **-0.006757** | Обычный (посадка) |
| **S6** | 0.936988 | 0.936988 | 0.000000 | Скоростной |
| **S7** | 0.919311 | 0.919311 | 0.000000 | Скоростной |
| **ИТОГО** | **0.920060** | **0.918070** | **-0.001990** | — |

## Выводы

1. **Гипотеза однозначно опровергнута платформой:**
   Исключение ребра `data` при зондирующем SELECT к таблице `orders` приводит к синхронному и ощутимому падению метрики в обоих сценариях обычных поездов:
   - S2: падение на **-0.007143** (с 0.882280 до 0.875137)
   - S5: падение на **-0.006757** (с 0.931903 до 0.925146)
   - Общий скор снижается на **-0.001990** (с 0.920060 до 0.918070).
2. **Подтверждение фундаментального правила БД (ADR-005, R10):**
   Эталон организаторов строго фиксирует факт исполнения SQL-запроса к таблице БД (`data_access`), вне зависимости от того, вернул ли `SELECT` 0 строк или N строк. Если вызов репозитория был выполнен процессом сервиса — ребро `data` к опрашиваемой таблице обязано присутствовать.
3. **Решение:**
   Опция `--probe-orders-data` оставлена со значением по умолчанию `on`. Исключать зондирующие запросы к БД нельзя.
