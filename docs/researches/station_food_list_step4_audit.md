# Аудит гипотезы 2: Таблица коллекции блюд station_food_list (Шаг 4 в S2 и S3)

## Контекст и суть гипотезы

В сущности `StationFoodStore` (сервис `ts-station-food-service`) коллекция идентификаторов блюд аннотирована как жадная:
```java
@ElementCollection(targetClass = String.class, fetch = FetchType.EAGER)
@CollectionTable(name = "station_food_list", joinColumns = @JoinColumn(name = "station_food_store_id"))
private List<String> foodList;
```
В графе-скелете организаторов вызовы репозитория `StationFoodRepository` связаны рёбрами `data_access` сразу с двумя таблицами:
1. `res:table:ts-station-food-service.station_food_store`
2. `res:table:ts-station-food-service.station_food_list`

В сценариях Train Ticket работа с едой разделяется на два различных пользовательских действия:
1. **S2 и S3 (шаг 4):** Пользователь выполняет действие *«Browse the food stores at Suzhou station»*. Вызывается эндпоинт `GET /api/v1/stationfoodservice/stationfoodstores/{stationName}` (`StationFoodServiceImpl#listFoodStoresByStationName`). Пользователь просматривает список магазинов станции (названия, время работы, телефоны), сами позиции меню не запрашиваются.
2. **S1 (шаг 4) и S4 (шаг 6):** Пользователь выполняет действие *«View the food menu offered on this trip»*. Вызывается эндпоинт `FoodController#getAllFood` (`StationFoodServiceImpl#getFoodStoresByStationNames`), где пользователю возвращается полное меню поездки, включая состав блюд каждого магазина.

**Гипотеза:**
В эталоне организаторов для действия «просмотр магазинов станции» (S2 и S3, шаг 4) ребро `data` к таблице блюд `station_food_list` отсутствует (по аналогии с `user_roles` при `loadUserByUsername` в S0), являясь ложноположительным артефактом жадной аннотации ORM.

## Реализация

В `RuntimeRules` и `GraphBuilder` реализовано правило контекстной фильтрации таблицы коллекции `station_food_list`:
- [engine/rules.py](file:///c:/Users/Pavel/IdeaProjects/archonity/engine/rules.py): параметр `station_food_collection` (`step4_store_only` / `all` / `off`, по умолчанию `step4_store_only`).
- [engine/graph/builder.py](file:///c:/Users/Pavel/IdeaProjects/archonity/engine/graph/builder.py): в режиме `step4_store_only` таблица `station_food_list` отсекается только у метода `StationFoodServiceImpl#listFoodStoresByStationName` (просмотр магазинов станции без позиций меню в S2/S3). В методе `getFoodStoresByStationNames` (просмотр полного меню в S1/S4) ребро к таблице блюд сохраняется.

## Результаты тестирования на платформе NSUTS

Тестирование проведено на платформе NSUTS для команды **Your answer** (тур Semantic Graph, посылка №1664927 от 18.10.2026 03:03:24):

| Сценарий | До (Baseline 0.918270) | Глобальное исключение (all off) | Контекстное: шаг 4 S2/S3 (step4_store_only) | Дельта к Baseline |
| :--- | :--- | :--- | :--- | :--- |
| **S0** (калибровка) | 1.000000 | 1.000000 | 1.000000 | 0.000000 |
| **S1** | 0.933537 | 0.927127 (-0.0064) | 0.933537 | 0.000000 |
| **S2** | 0.875931 | 0.882280 (+0.0063) | 0.882280 | **+0.006349** |
| **S3** | 0.899071 | 0.905265 (+0.0062) | 0.905265 | **+0.006194** |
| **S4** | 0.931118 | 0.925021 (-0.0061) | 0.931118 | 0.000000 |
| **S5** | 0.931903 | 0.931903 | 0.931903 | 0.000000 |
| **S6** | 0.936988 | 0.936988 | 0.936988 | 0.000000 |
| **S7** | 0.919311 | 0.919311 | 0.919311 | 0.000000 |
| **ИТОГО** | **0.918270** | **0.918270** (взаимное гашение) | **0.920060** | **+0.001790** |

## Выводы

1. **Гипотеза полностью подтверждена платформой:**
   В сценариях S2 и S3 на шаге 4 эталон организаторов не содержит ребра `data` к таблице `station_food_list`. Его исключение дает чистый прирост:
   - S2: с 0.875931 до **0.882280** (+0.006349)
   - S3: с 0.899071 до **0.905265** (+0.006194)
2. **Семантическое разделение шагов меню и шагов магазинов:**
   В сценариях S1 и S4 просмотр меню действительно требует таблицу `station_food_list`, поэтому глобальное исключение снижало балл S1/S4. Контекстное правило по целевому методу `listFoodStoresByStationName` сохраняет высокие баллы S1/S4 и устраняет FP в проблемных S2/S3.
3. **Общий результат:**
   Общий балл решения на платформе вырос с 0.918270 до **0.920060**, команда поднялась на 20 место в общем зачете.
4. **Решение:**
   Режим `step4_store_only` зафиксирован как постоянное дефолтное поведение анализатора.
