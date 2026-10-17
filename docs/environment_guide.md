# Руководство по окружению и частым ошибкам

В документе собраны правила запуска скриптов, сборки и частые проблемы окружения (включая работу под Windows), с которыми сталкиваются агенты и разработчики.

## 1. Запуск Python и кодировка Windows (CP1251)

### Проблема
По умолчанию в консоли Windows (cmd/PowerShell) используется кодовая страница CP1251. При выводе в `stdout` символов вне этой таблицы (включая служебные символы в логах `run_eval.py` и библиотеках) скрипт завершается с ошибкой:
```text
UnicodeEncodeError: 'charmap' codec can't encode character ...
```

### Правило
Всегда запускать Python в режиме UTF-8:
```powershell
$env:PYTHONUTF8=1; python run_eval.py
```
или для одиночных команд:
```powershell
$env:PYTHONUTF8=1; python scripts/decision_log.py --scenarios S2 S3
```

## 2. Сборка Java и модуль archparse

### Запуск Gradle под Windows
Скрипт `gradlew` является bash-скриптом. В среде Windows PowerShell или CMD запуск выполняется через `.bat`:
```powershell
cmd /c gradlew.bat test
cmd /c gradlew.bat run --args="--pool all"
```
Команды выполнять из директории `archparse/` или указывать путь к `archparse/gradlew.bat`.

### Пайплайн обновления IR (pool_ir.json)
При изменении пула методов в `TargetPool.java` строго соблюдать последовательность:

1. **Тесты парсера:**
   ```powershell
   cmd /c gradlew.bat test
   ```
2. **Генерация IR:**
   ```powershell
   cmd /c gradlew.bat run --args="--pool all"
   ```
3. **Синхронизация артефакта в data/:**
   Генератор пишет в `archparse/out/pool_ir.json`. Для воспроизводимости и работы движка без пересборки файл необходимо скопировать:
   ```powershell
   Copy-Item archparse/out/pool_ir.json data/pool_ir.json -Force
   ```
4. **Проверка геометрии (100% совпадение со скелетом):**
   ```powershell
   $env:PYTHONUTF8=1; python scripts/verify_pool_ir.py --ir data/pool_ir.json
   ```
5. **Проверка калибровки S0:**
   ```powershell
   $env:PYTHONUTF8=1; python run_eval.py
   ```
   Балл S0 обязан оставаться 1.0000.

## 3. Особенности тестов pytest

При запуске `python -m pytest -q tests`:
- Два теста производительности:
  - `test_performance_under_5_seconds` в `tests/test_contract_and_quality.py`
  - `test_state_fork_latency_under_50us` в `tests/test_state.py`
  сильно зависят от загрузки процессора и характеристик конкретной машины (на медленных CPU или под Windows могут превышать лимиты: например 5.2s вместо 5.0s, 65µs вместо 50µs).
- **Правило:** если упали только эти два теста производительности, а остальные 171+ функциональных тестов зелёные — это не считается поломкой логики и не блокирует работу.

## 4. Программный запуск пайплайна (ArchonityPipeline)

Для диагностических скриптов и обвязок пайплайн инициализируется следующим образом:
```python
from pathlib import Path
from engine.pipeline import ArchonityPipeline

ROOT = Path(__file__).resolve().parent.parent

pipeline = ArchonityPipeline(
    skeleton_path=ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz",
    targets_root=ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket",
    ir_path=ROOT / "data" / "pool_ir.json",
)

# Запуск сценария (например, S2)
methods, calls, remote, data = pipeline.run_scenario(scenario_dict)
```

## 5. Диагностика решений: журнал решений (decision_log.py)

Для оценки того, что решило судьбу каждого ребра скелета (IR-guard, эвристика rules.py или обход по умолчанию), использовать:
```powershell
$env:PYTHONUTF8=1; python scripts/decision_log.py --scenarios S2 S3
```
Скрипт формирует список риска — рёбра, отсекаемые `rules.py`, которые необходимо в первую очередь покрывать AST IR.
