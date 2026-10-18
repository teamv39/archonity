# Исправление отсева распределения мест в сценарии S7 (SeatController#create)

**Дата:** 18.10.2026  
**Сценарий:** S7 («After collecting the ticket: refused cancellation and rebooking, changing the consignee, orders filtered by dates»)  
**Компонент:** `engine/rules.py` (`ScenarioProfile`, `RuntimeRules.is_dead_code_method`, `RuntimeRules.is_dead_code_edge`)  
**Статус:** Исправлено и верифицировано  

---

## 1. Проблема

В сценарии $S_7$ пассажир выполняет следующие действия:
1. Шаг 4: Бронирует билет первого класса на скоростной поезд Shanghai -> Suzhou (`PreserveController#preserve`).
2. Шаги 5–7: Оплачивает и собирает билет (статус `COLLECTED = 2`).
3. Шаги 8–10: Пытается запросить возврат, отменить и перебронировать собранный билет — система закономерно отказывает (`has_refused_rebook = True`).

В `engine/rules.py` присутствовало глобальное правило:
```python
if profile.has_refused_rebook:
    if "SeatController#create" in method_id:
        return True
```
и в `is_dead_code_edge`:
```python
if "SeatController#create" in target or "SeatController#create" in source:
    return True
```

### Последствия:
Поскольку флаг `has_refused_rebook` был активен на уровне сценария, метод `SeatController#create` признавался мёртвым кодом **для всего сценария целиком**, включая штатный шаг 4 бронирования билета. В результате в $S_7$ были полностью отсечены вызовы распределения мест (`SeatController#create`, `SeatServiceImpl#distributeSeat`, `getLeftTicketOfInterval`, `getDirectProportion`, `isContained`, вызовы к `ts-order-service` и `ts-config-service`). Это создавало 10 ложноотрицательных рёбер (FN) в $S_7$.

---

## 2. Решение

1. В `ScenarioProfile` добавлено свойство `has_preserve`:
   - Определяет, происходит ли в сценарии бронирование билета (`book ... seat` / `preserve`).
   - Для $S_1 \dots S_7$ `has_preserve = True`; для $S_0$ `has_preserve = False`.
2. В `is_dead_code_method`:
   - `SeatController#create` признаётся мёртвым кодом при `has_refused_rebook` **только если в сценарии нет бронирования билета** (`not getattr(profile, "has_preserve", False)`).
3. В `is_dead_code_edge`:
   - Вызов `SeatController#create` блокируется **только если источником вызова является `RebookServiceImpl`**:
     ```python
     if "RebookServiceImpl" in source and "SeatController#create" in target:
         return True
     ```
   - Вызов `PreserveServiceImpl#dipatchSeat -> SeatController#create` на шаге 4 остаётся активным.

---

## 3. Результаты верификации

- **Калибровка $S_0$:** строго **1.000000** (65/65 золотых рёбер).
- **Валидация формата $S_1 \dots S_7$:** **0 отклонённых рёбер**.
- **Число рёбер в $S_7$:** увеличилось с 407 до **417** (+10 истинных рёбер цепочки распределения мест).
- **Все остальные сценарии ($S_1 \dots S_6$):** геометрия графов осталась строго неизменной.
- **Тесты pytest:** **328 из 328 пройдены** (100% green).
