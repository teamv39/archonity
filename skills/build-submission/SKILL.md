---
name: build-submission
description: >-
  Пошаговое руководство и регламент сборки, валидации и упаковки официального архива submission.zip
  для отправки решения на платформу TechArena 2026 (NSUTS). Используй этот навык при необходимости
  сгенерировать submission.json, проверить калибровку на открытом эталоне S0 и упаковать архив.
---

# Сборка и валидация архива submission.zip

Этот навык описывает полный регламент подготовки официального архива `output/submission.zip` для бенчмарка Train Ticket (TechArena 2026).

---

## 1. Требования к архиву по регламенту

Согласно спецификации организаторов ([case_description.md](../../docs/case_description.md)):
1. **Структура архива:**
   * `submission.json` — строго в корне архива (подграфы исполнения для $S_0 \dots S_7$).
   * `evidence.json` — журнал обоснований принятых решений (v2 / `decisions.json`).
   * `code/` — исходный код пайплайна и используемые факты/модели, позволяющие воспроизвести генерацию офлайн без GPU.
2. **Лимиты:** размер архива не более 20 MB (наш типовой размер: ~180–200 KB).
3. **Строгая воспроизводимость:** автономный запуск без доступа в сеть и без внешних API (Strict Local-First).

---

## 2. Предварительные требования и окружение

Перед запуском убедись, что окружение настроено согласно [environment_guide.md](../../docs/environment_guide.md):

* **Python:** версия $\ge 3.10$ с пакетным менеджером `uv`.
* **Кодировка UTF-8:**
  * Windows PowerShell: `$env:PYTHONUTF8=1; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8`
  * Linux / macOS: `export PYTHONUTF8=1`
* **Наличие артефактов организаторов:**
  * Скелет: `hackaton/tt-challenge/skeleton/trainticket.json.gz`
  * Дамп БД: `hackaton/tt-challenge/context/db-after-warmup.sql.gz`
  * Открытый эталон: `hackaton/tt-challenge/gold/S0.json`
* **Факты и IR-модели:**
  * `data/runtime_and_topology_rules.json`
  * `data/pool_ir.json` (IR тел методов)
  * `data/entity_ir.json` (структуры сущностей и конструкторы R7)

---

## 3. Пошаговая процедура сборки

### Шаг 1. Прогон автоматических тестов
Убедись, что все модульные тесты ядра проходят без ошибок:
```bash
uv run --with pytest pytest
```
*Критерий успешности:* все тесты (50+) должны быть зелеными (`passed`), 0 `failed`.

---

### Шаг 2. Генерация графов исполнения и калибровка
Запусти основной раннер пайплайна:
```bash
uv run python run_eval.py
```
Команда выполняет:
1. Резолвинг точек входа для сценариев $S_0 \dots S_7$ через `ScenarioGrounder`.
2. Обход графа скелета и фильтрацию веток через `GraphBuilder` и `RuntimeRules`.
3. Сохранение `output/submission.json`, `output/evidence.json`, `output/decisions.json`.
4. Синхронизацию данных с графовым визуализатором (`visualizer/public/data/`).
5. Автоматический запуск официального валидатора `evaluate_golden.py`.

*Критерии валидации в выводе консоли:*
* **Калибровка $S_0$:** итоговый балл обязан быть строго **`1.0000`** (65 из 65 рёбер: 34 `executes`, 24 `calls`, 0 `remote`, 7 `data`).
* **Скрытые сценарии $S_1 \dots S_7$:** статус `format_only`, отклонено рёбер: строго **`0`**.

---

### Шаг 3. Упаковка в архив submission.zip
Сформируй финальный zip-архив скриптом упаковщика:
```bash
uv run python pack_submission.py
```
Скрипт автоматически:
* Кладёт `output/submission.json` и `output/evidence.json` в корень архива.
* Упаковывает исходный код `engine/`, `run_eval.py`, `pyproject.toml` и каталог `data/` в папку `code/`.
* Исключает временные файлы (`__pycache__`, `.pyc`, `.git`, `.venv`).

---

### Шаг 4. Проверка содержимого архива
Верифицируй структуру созданного архива:
```bash
unzip -l output/submission.zip
```
Убедись, что:
1. В корне присутствуют `submission.json` и `evidence.json`.
2. В каталоге `code/` присутствуют `code/run_eval.py`, `code/engine/`, `code/data/pool_ir.json`, `code/data/entity_ir.json`.
3. Отсутствуют сторонние мусорные файлы и размер архива составляет ~150–250 KB.

---

## 4. Быстрая сборка одной строкой

Для быстрой пересборки при частых итерациях:
```bash
uv run python run_eval.py && uv run python pack_submission.py
```

---

## 5. Типовые проблемы и их устранение

* **`UnicodeEncodeError` / `charmap codec can't encode characters` (Windows):**
  Установи переменную окружения `$env:PYTHONUTF8=1` перед вызовом скриптов.
* **Балл на $S_0$ меньше 1.0000:**
  Проверь `git diff engine/rules.py engine/resolver.py` — возможно, новое правило фильтрации случайно задело вызовы калибровочного сценария $S_0$.
* **Отклоненные рёбра (`отклонено > 0`) на $S_1 \dots S_7$:**
  В граф попали идентификаторы методов или таблиц, отсутствующие в `nodes` скелета. Запусти валидацию против `SkeletonIndex`.
* **Файлы не попали в архив:**
  Проверь список `INCLUDE_FILES` в `pack_submission.py` при добавлении новых модулей или json-файлов в `data/`.
