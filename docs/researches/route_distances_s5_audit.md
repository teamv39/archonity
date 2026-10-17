# Аудит гипотезы коллекции route_distances на поиске маршрутов (S5 Шаги 2–5)

**Дата:** 18.10.2026  
**Посылка на NSUTS:** ID 1664977  
**Статус гипотезы:** Опровергнута платформой (подтверждена каноничность правила R10)  
**Решение:** Оставить дефолт `--route-distances-collection pruned` (отсекать неиспользуемую ленивую коллекцию `route_distances` при чтении маршрутов).

---

## 1. Суть гипотезы

В сценарии $S_5$ на шагах 2–5 выполняется расширенный поиск рейсов с пересадками через `ts-travel-plan-service`:
* Вызывается метод `RouteController#queryByStartAndTerminal` $\rightarrow$ `RouteServiceImpl#getRouteByStartAndEnd`.
* В коде метода:
  ```java
  for (Route route : routes) {
      if (route.getStations().contains(startId) &&
          route.getStations().contains(terminalId) &&
          route.getStations().indexOf(startId) < route.getStations().indexOf(terminalId)) {
          resultList.add(route);
      }
  }
  ```
* Метод обращается к коллекции станций `route.getStations()`, но **не обращается к дистанциям `route.getDistances()`**.
* Согласно правилу R10 (`collection_tables_on_read="loaded"`), таблица ленивой коллекции `res:table:ts-route-service.route_distances` отсекается движком, так как Hibernate не загружает её при чтении.
* **Гипотеза (TASK-08 / Гипотеза 5.1):** в графе-скелете вызов `getRouteByStartAndEnd@105:51` содержит ребро `data_access` к `route_distances`. Требовалось экспериментально проверить, ожидает ли платформа строгое соблюдение R10 (отсечение `route_distances`), или эталон организаторов был построен без фильтрации ленивых коллекций JPA.

---

## 2. Эксперимент и реализация

Реализован управляемый флаг `--route-distances-collection` (`pruned` / `included`):
* `engine/rules.py`: добавлен параметр `route_distances_collection` с режимами `("pruned", "included")`.
* `engine/graph/builder.py`: в режиме `included` для метода `getRouteByStartAndEnd` принудительно возвращается `loaded = True` для таблицы `route_distances` (абляция включения).
* `engine/pipeline.py` и `run_eval.py`: сквозная передача аргумента в CLI.

### Локальная проверка
* При `--route-distances-collection included`:
  * Калибровка $S_0$: строго **1.000000** (в $S_0$ сервис маршрутов не участвует).
  * Рёбра $S_5$: увеличились с 593 до 594 (+1 ребро `data`: `RouteServiceImpl#getRouteByStartAndEnd` $\rightarrow$ `res:table:ts-route-service.route_distances`).
  * Все остальные сценарии ($S_1$, $S_2$, $S_3$, $S_4$, $S_6$, $S_7$) не изменились ни на одно ребро.

---

## 3. Результаты на платформе NSUTS

| Метрика | Бейзлайн (ID 1664936, `pruned`) | Абляция (ID 1664977, `included`) | Дельта |
|---|---:|---:|:---:|
| $S_0$ (Калибровка) | 1.000000 | 1.000000 | 0.000000 |
| $S_1$ | 0.934 | 0.934 | 0.000 |
| $S_2$ | 0.882 | 0.882 | 0.000 |
| $S_3$ | 0.905 | 0.905 | 0.000 |
| $S_4$ | 0.931 | 0.931 | 0.000 |
| **$S_5$** | **0.932** | **0.925** | **-0.007** |
| $S_6$ | 0.937 | 0.937 | 0.000 |
| $S_7$ | 0.919 | 0.919 | 0.000 |
| **Итоговый балл** | **0.920060** | **0.919120** | **-0.000940** |

---

## 4. Выводы и директива

1. **Правило R10 полностью подтверждено на платформе:**
   Включение `route_distances` в ответ привело к падению балла сценария $S_5$ с 0.932 до 0.925 (-0.007). Это означает, что лишнее ребро `data` является явным False Positive (FP) и штрафуется организаторами.
2. **Селективная гидрация коллекций JPA валидна:**
   Платформа TechArena строго оценивает только те таблицы коллекций, к полям которых происходил реальный доступ в Java-коде. Так как `route.getDistances()` не вызывается, ребро `route_distances` в эталоне отсутствует.
3. **Фиксация правила:**
   Дефолт `--route-distances-collection pruned` является каноническим и обязательным для сохранения пикового скора.
