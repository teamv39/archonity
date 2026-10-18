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
   Генератор пишет прямо в `data/pool_ir.json`. Это единственный артефакт IR: движок, тесты и скрипты читают только его, копировать ничего не нужно. Старый `archparse/out/pool_ir.json` больше нигде не читается, его можно удалить.
3. **Проверка геометрии (100% совпадение со скелетом):**
   ```powershell
   $env:PYTHONUTF8=1; python scripts/verify_pool_ir.py
   ```
4. **Проверка калибровки S0:**
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

Каждое решение по ребру (включение, отсев, удаление) пишет сам `GraphBuilder` в журнал `engine/decisions.py`. `run_eval.py` сохраняет журнал в `output/decisions.json` (evidence v2, ADR-005): для каждого ребра сценария — попало ли оно в ответ, на каких шагах, источник решения (`source_type`) и правило (`rule`), плюс все решения по шагам. Правило — это ID из `branch_rules.json` с предикатом (`BR_TRIP_GD_DISPATCH@b53:else`), R7/R15-R17, строка `rules.py` (`rules.py:508`) или имя правила движка.

Сводка и списки риска по сценариям:
```powershell
$env:PYTHONUTF8=1; python scripts/decision_log.py --scenarios S2 S3
```
- Список риска A — рёбра ответа, включённые только достижимостью скелета: условия на них движок не проверял. Пометка `[IR]` — метод уже в пуле, но ни одно правило не решило его ветки.
- Список риска B — рёбра, отсеянные эвристиками `rules.py`, со строкой сработавшего правила.

Скрипт не пересчитывает обход сам и на каждом прогоне проверяет, что журнал совпадает с ответом сценария.

## 6. Git, .gitattributes и сгенерированные JSON

Файл `data/pool_ir.json` содержит десятки тысяч строк сгенерированного AST IR.
В `.gitattributes` для них настроены атрибуты:
```gitattributes
data/pool_ir.json linguist-generated=true -diff
```
- `linguist-generated=true` скрывает файл из диффа Pull Request на GitHub.
- `-diff` отключает построчный расчет в локальном `git diff` и `git diff --stat` (файл отображается как бинарный, без десятков тысяч строк).
- **Правило для агента:** при показе пользователю `git diff --stat` перед запросом аппрува фокусироваться на коде и документации, не перегружая отчет сгенерированными артефактами.

## 7. Особенности PowerShell под Windows: экранирование и Heredoc

### Проблема
1. Bash-синтаксис heredoc (`<< 'EOF'`) в PowerShell не поддерживается и приводит к ошибке:
   ```text
   Missing file specification after redirection operator.
   ```
2. Обратная кавычка (`` ` ``) в PowerShell является символом экранирования. Если передавать текст с обратными кавычками (например, markdown-код `` `user1 == null` ``) внутри двойных кавычек CLI-аргумента:
   ```powershell
   gh pr create --body "branch `user1 == null`"
   ```
   PowerShell пытается интерпретировать это как escape-последовательность и падает:
   ```text
   The Unicode escape sequence is not valid. A valid sequence is u{...}
   ```

### Правило
- Для длинных описаний (например, тело PR) использовать передачу через файл: `--body-file path/to/file.md` или выводить текст пользователю в сообщении чата.
- Если передаются строковые аргументы с markdown в PowerShell, использовать одинарные кавычки (`'...'`), отключающие интерполяцию.

## 8. Тонкости JavaParser и скелета проекта (archparse)

### Расчет колонок вызовов: байты UTF-8 vs символы Java (UTF-16)
- В скелете (`skeleton/trainticket.json.gz`) поле `col` у каждого `call_site` — это **1-based смещение в байтах UTF-8** от начала строки, а не количество символов.
- Если в строке исходника перед вызовом есть не-ASCII символы (кириллица или китайские иероглифы в комментариях/строках), метод JavaParser `getName().getBegin().column` возвращает номер символа (char), который меньше байтового смещения. Из-за этого геометрическое сопоставление вызовов в `verify_pool_ir.py` не находит вызов (0% совпадений).
- **Правило:** при извлечении вызовов Java-парсер обязан пересчитывать символьное смещение строки в байтовую длину в кодировке UTF-8.

### Неразрешённые типы параметров в скелете (?TypeName)
- В скелете параметры некоторых методов имеют признак `unresolved: True` и префикс `?` в дескрипторе (например, `?HttpHeaders` в ID `method:ts-user-service:user.service.impl.UserServiceImpl#saveUser(user.dto.UserDto,?HttpHeaders)`).
- Если попытаться восстановить ID метода автоматически из AST JavaParser, получится `HttpHeaders` (без знака вопроса), и ID не совпадет со скелетом (что нарушает строгое правило «концы рёбер — ID методов из скелета дословно»).
- **Правило:** `TargetMethod` всегда принимает и сохраняет строковый `methodId` из скелета строго дословно, а типы аргументов для поиска метода в AST задаются отдельно простыми именами.

## 9. Исполнитель M4 и судья

M4 (`engine/executor/`, ADR-005) включается флагом и требует M1:
```powershell
$env:PYTHONUTF8=1; python run_eval.py --grounder m1 --executor m4
```

| Флаг | Что делает |
|---|---|
| `--judge on` (по умолчанию) | ответы судьи из кеша `cache/llm/`, на промахе — сервер |
| `--judge cache` | только кеш; промах — плечо по исходу шага |
| `--judge off` | без судьи |
| `--judge-budget N` | не больше N вызовов сервера за прогон (по умолчанию 400) |
| `--m4-only SUBSTR` | M4 исполняет только методы с подстрокой в ID, остальные — legacy (поиск регрессий) |
| `--m4-legacy-rules` | абляция: эвристики `rules.py` поверх решений IR |
| `--m4-no-runtime-type-edges` | абляция R2: вызов по фактическому типу без рёбер |
| `--no-signal-arm continue\|then` | плечо, если у неизвестного условия нет сигнала исхода |

Сервер для судьи и M1: `powershell -File scripts/start_llm.ps1` (модель на `D:\models`). Сервер поднимается примерно за 10 с, одно условие занимает около 3 с; весь прогон S0–S7 без кеша — около 3 минут. После прогона сервер остановить: он занимает GPU, а эмбеддер с ним в 16 ГБ не помещается.

Без GPU прогон воспроизводится из кеша: `--judge cache --no-server` даёт тот же `submission.json` байт в байт. Новые ответы судьи (`cache/llm/*.json`) коммитятся вместе с кодом.

Тесты M4: `tests/test_m4_executor.py` (модели и решения на S0–S7), `tests/test_judge.py`, `tests/test_m4_parity.py`, `tests/test_builder_interceptor.py`.
