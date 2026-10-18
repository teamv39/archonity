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
1. Заземление шагов $S_0 \dots S_7$ через M1 (`engine/grounding`, `--grounder m1` по умолчанию): ответы LLM и векторы эмбеддера берутся из `cache/`, сервер LLM не нужен. Старый `ScenarioGrounder` — `--grounder legacy`.
2. Обход графа скелета и фильтрацию веток через `GraphBuilder` и `RuntimeRules`.
3. Сохранение `output/submission.json`, `output/evidence.json`, `output/decisions.json`.
4. Синхронизацию данных с графовым визуализатором (`visualizer/public/data/`).
5. Автоматический запуск официального валидатора `evaluate_golden.py`.

**Сдача с исполнителем M4** (ADR-005; по умолчанию пока legacy): ответы судьи берутся из `cache/llm/`, сервер LLM не нужен:
```bash
uv run python run_eval.py --grounder m1 --executor m4 --judge cache --no-server
```
Этой же командой код из архива воспроизводит `submission.json` байт в байт. Проверь в выводе `Статистика M4`: `misses: 0`, `server_calls: 0`.

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
* Упаковывает исходный код `engine/`, `run_eval.py`, `pyproject.toml`, каталог `data/` и кеши M1 (`cache/llm/`, `cache/emb/qwen3-4b/`) в папку `code/`.
* Исключает временные файлы (`__pycache__`, `.pyc`, `.git`, `.venv`).

---

### Шаг 4. Проверка содержимого архива
Верифицируй структуру созданного архива:
```bash
unzip -l output/submission.zip
```
Убедись, что:
1. В корне присутствуют `submission.json` и `evidence.json`.
2. В каталоге `code/` присутствуют `code/run_eval.py`, `code/engine/`, `code/data/pool_ir.json`, `code/data/entity_ir.json`, `code/data/ir/` (IR тел методов, 42 файла), `code/cache/llm/` и `code/cache/emb/qwen3-4b/` (кеши M1).
3. Отсутствуют сторонние мусорные файлы и размер архива составляет около 3.8 MB (из них около 3 MB — кеши M1 и судьи M4).

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
* **Статус `W` (Wrong Answer) и балл 0 в NSUTS:**
  * Убедись, что архив собран именно скриптом `pack_submission.py`: он гарантирует Unix LF (`\n`), POSIX-права (`0o644`/`0o755`) и строгий состав файлов без мусора `node_modules`.
  * Проверь, что в NSUTS загружен именно `output/submission.zip`, а не `submission.json` напрямую или архив с вложенной папкой `output/submission.json`. В корне архива обязан лежать `submission.json`.
* **Файлы не попали в архив:**
  Проверь список `DATA_RULE_FILES` в `pack_submission.py` при добавлении новых json-файлов правил в `data/`.
