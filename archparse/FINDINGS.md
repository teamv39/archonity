# Памятка находок по результатам разбора пула методов archparse

**Дата:** 16.10.2026  
**Модуль:** `archparse`
**Артефакт:** `archparse/out/pool_ir.json` (32 методов, 123 веток, 1609 вызовов, 100% совпадение; таблица ниже описывает исходные 14 методов с узлами `call_site` скелета).

---

## 1. Сводка совпадений со скелетом (Проверка по п. 3.2 README)

Все 1041 вызов (`calls`), извлечённые из тел методов пула, по координатам `(file, line, col)`на 100% сопоставлены с узлами `call_site` графа-скелета (`skeleton/trainticket.json.gz`), без расхождений:

| Класс и метод | Ветки (branches) | Вызовы (calls) | Совпадение со скелетом |
|---|---:|---:|:---:|
| `CancelServiceImpl#cancelOrder` | 9 | 83 | 83/83 (100%) |
| `CancelServiceImpl#calculateRefund(String,...)` | 6 | 34 | 34/34 (100%) |
| `CancelServiceImpl#calculateRefund(Order)` | 2 | 30 | 30/30 (100%) |
| `ExecuteServiceImpl#ticketExecute` | 6 | 32 | 32/32 (100%) |
| `ExecuteServiceImpl#ticketCollect` | 6 | 36 | 36/36 (100%) |
| `InsidePaymentServiceImpl#pay` | 5 | 80 | 80/80 (100%) |
| `InsidePaymentServiceImpl#setOrderStatus` | 1 | 10 | 10/10 (100%) |
| `RebookServiceImpl#rebook` | 16 | 98 | 98/98 (100%) |
| `RebookServiceImpl#updateOrder` | 1 | 7 | 7/7 (100%) |
| `PreserveServiceImpl#preserve` | 16 | 257 | 257/257 (100%) |
| `PreserveOtherServiceImpl#preserve` | 16 | 256 | 256/256 (100%) |
| `ConsignServiceImpl#updateConsignRecord` | 2 | 44 | 44/44 (100%) |
| `OrderServiceImpl#queryOrders` | 8 | 37 | 37/37 (100%) |
| `OrderOtherServiceImpl#queryOrders` | 8 | 37 | 37/37 (100%) |
| **ИТОГО** | **102** | **1041** | **1041/1041 (100%)** |

---

## 2. Сравнение с текущими эвристиками `engine/rules.py`

### 2.1. `RebookServiceImpl#rebook`
* **Что в коде (IR):**
  - Ветка смены семейства поезда: `tripGD(oldTripId) ^ tripGD(newTripId)`.
    - Если семейство меняется (G/D $\leftrightarrow$ Regular) $\to$ вызываются `createOrder(...)` и `deleteOrder(...)`.
    - Если семейство поезда то же $\to$ вызывается приватный `updateOrder(...)`.
  - Ветка цены:
    - Если билет дороже $\to$ `payDifferentMoney(...)`.
    - Если билет дешевле (как в S2) $\to$ `drawBackMoney(...)`.
    - Если цена равна $\to$ разница не выплачивается.
  - Статус-гейт: `status == NOTPAID`, `CHANGE`, `COLLECTED` завершаются `early_exit` (нельзя перебронировать). Разрешён только `PAID` (`status == 1`).
* **Что в `rules.py` сейчас:**
  - `createOrder`, `deleteOrder`, `payDifferentMoney` безусловно исключены через `is_dead_code_method` (`"RebookServiceImpl" in method_id`).
  - **Вывод для движка:** на S2 это даёт правильный результат (перебронирование дешевле, тот же тип поезда). Перебронирование есть только в S2 и S7, смены типа поезда или доплаты в них нет, поэтому безусловный отсев сейчас безопасен. Он станет FN только при появлении таких сценариев.

### 2.2. `InsidePaymentServiceImpl#pay`
* **Что в коде (IR):**
  - Диспатч сервиса заказов: `if (info.getTripId().startsWith("G") || info.getTripId().startsWith("D"))` $\to$ запрос в `ts-order-service`, иначе $\to$ `ts-order-other-service`.
  - Ветка внешнего/внутреннего платежа: вычисляется `totalExpand.compareTo(money) > 0`.
    - Если баланс достаточен $\to$ прямой расчет, `ts-payment-service` не вызывается.
    - Если баланса не хватает $\to$ вызывается внешний `ts-payment-service` (line 110).
  - Статус-гейт: `if (order.getStatus() != OrderStatus.NOTPAID.getCode())` $\to$ ранний выход (оплатить можно только `NOTPAID`).
* **Что в `rules.py` сейчас:**
  - Диспатч G/D определяется глобальным флагом сценария `ScenarioProfile.train_mode`, а не по конкретному заказу, переданному в запросе шага.
  - Внешний платеж отсекается флагом `has_external_payment` по наличию слов `empty balance` / `external payment` в тексте сценария.

### 2.3. `ExecuteServiceImpl#ticketExecute` и `#ticketCollect`
* **Что в коде (IR):**
  - Статус-гейт исполнения: `if (order.getStatus() != OrderStatus.COLLECTED.getCode())` $\to$ `LOGGER.error`, ранний выход (`early_exit: true`).
  - Метод `executeOrder` вызывается **только** после прохождения проверки на статус `COLLECTED`.
  - В `ticketCollect`: статус-гейт `if (order.getStatus() != OrderStatus.PAID.getCode())` $\to$ ранний выход (`early_exit: true`).
* **Что в `rules.py` сейчас:**
  - Отказ в S7 отслеживается regex'ом `has_refused_cancel/rebook`, но для исполнения билета статус-проверка в `rules.py` отсутствует в явном виде.

### 2.4. Enum-константы (`OrderStatus` и `SeatClass`)
* **Что в коде (IR):**
  - Все вызовы `OrderStatus.XXX.getCode()` (линии 52, 53 в Cancel; 50, 56 в Execute; 70 в InsidePayment; 64, 67, 69, 72 в Rebook) получают атрибут `"enum_constant": {"type": "edu.fudan.common.entity.OrderStatus", "constant": "..."}`.
* **Что в `rules.py` / `graph/builder.py` сейчас:**
  - Ранее в скелете `receiver_type=None` для этих вызовов приводил к потере рёбер `calls`/`executes` на метод `getCode()`.
  - В `builder.py` существовал только частичный хардкод для конструктора `Order#<init>()`. Теперь M4 имеет полную карту всех статусных проверок для добавления рёбер R7.
