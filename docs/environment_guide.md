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
Без ключей `run_eval.py` даёт выдачу кода — конфигурацию рекорда ([AGENTS.md](../AGENTS.md), «Выдача кода и рекорд»). Legacy-исполнитель — только явно: `--grounder legacy --executor legacy`.

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
- Набор из 331 теста выполняется в среднем за 7–8 секунд.
- Два теста производительности:
  - `test_performance_under_5_seconds` в `tests/test_contract_and_quality.py`
  - `test_state_fork_latency_under_50us` в `tests/test_state.py`
  сильно зависят от загрузки процессора и характеристик конкретной машины (на медленных CPU или под Windows могут превышать лимиты: например 5.2s вместо 5.0s, 65µs вместо 50µs).
- **Правило:** если упали только эти два теста производительности, а остальные 329+ функциональных тестов зелёные — это не считается поломкой логики и не блокирует работу.

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

Так пайплайн собирается с умолчаниями класса: `grounder="legacy"`, `executor="legacy"`, `unresolved_receiver_calls="mute"`. Это не выдача кода. Для неё нужны `grounder="m1"` с `m1_options`, `executor="ir"`, `unresolved_receiver_calls="emit"` — как их собирает `run_eval.py`. Для диагностики выдачи кода проще обёртка над `run_eval.py` ([agent_lessons.md](agent_lessons.md), раздел 4).

## 5. Диагностика решений: журнал решений (decision_log.py)

Каждое решение по ребру (включение, отсев, удаление) пишет сам `GraphBuilder` в журнал `engine/decisions.py`. `run_eval.py` сохраняет журнал в `output/decisions.json` (evidence v2, ADR-005): для каждого ребра сценария — попало ли оно в ответ, на каких шагах, источник решения (`source_type`) и правило (`rule`), плюс все решения по шагам. Правило — это ID из `branch_rules.json` с предикатом (`BR_TRIP_GD_DISPATCH@b53:else`), R7/R15-R17, строка `rules.py` (`rules.py:508`) или имя правила движка.

Сводка и списки риска по сценариям:
```powershell
$env:PYTHONUTF8=1; python scripts/decision_log.py --scenarios S2 S3
```
- Список риска A — рёбра ответа, включённые только достижимостью скелета: условия на них движок не проверял. Пометка `[IR]` — метод уже в пуле, но ни одно правило не решило его ветки.
- Список риска B — рёбра, отсеянные эвристиками `rules.py`, со строкой сработавшего правила.

Скрипт не пересчитывает обход сам и на каждом прогоне проверяет, что журнал совпадает с ответом сценария.

**Только legacy.** `decision_log.py` собирает пайплайн без ключей исполнителя, поэтому списки риска A и B относятся к legacy-исполнителю и `rules.py`, а не к выдаче кода. Для выдачи кода — `decisions.json` прогона `run_eval.py` с ключами из раздела 1 и `scripts/probe_edge_classes.py` ([agent_lessons.md](agent_lessons.md), раздел 4).

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

## 9. Несколько агентов, ветки и выдача. И водка

Записано 19.10 по опыту сессии разбора M4.

### Общая рабочая копия

В основной папке репозитория одновременно работают несколько агентов: ветка может смениться посреди задачи, рядом появляются чужие неотслеживаемые файлы и незакоммиченные правки.

- Для своей задачи — отдельный worktree от `dev`:
  ```bash
  git worktree add -b feature/<id>-kebab ../archonity-wt origin/dev
  cp -r hackaton ../archonity-wt/
  ```
  `hackaton/` в `.gitignore`, поэтому его **копируют**, а не связывают junction: `git worktree remove` однажды удалил `hackaton/` через junction (восстанавливали из `hackaton.zip`).
- Файлы добавлять поимённо (`git add <путь>`), не `git add docs` или `git add .`: так в коммит уже попадал чужой файл.
- После мержа ветку не продолжать. Коммит, сделанный в локальную ветку после её пуша и мержа, в `dev` не попадёт (так потерялся `hypothesis_generation_guidelines.md`, возвращён в #72). Новая задача — новая ветка от свежего `origin/dev`.

### Прогон и выдача

- `run_eval.py -o <папка>/x.json` кладёт **все** артефакты прогона рядом с `x.json`: `decisions.json`, `m4_unknowns.json`, `evidence.json`, `step_requests.json`. Без `-o` — в `output/`. Каждый прогон ещё синхронизирует `visualizer/public/data`.
- Для экспериментов писать в отдельную папку (scratchpad), чтобы не затереть `output/` и не перепутать прогоны.
- Чужую посылку воспроизводить так: `git archive <sha> | tar -x -C <папка>`, туда скопировать `hackaton/`, запустить команду из её отчёта и сверить `sha256` у `submission.json`.
- В Python под Windows пути вида `/c/Users/...` не работают внутри строк кода. Передавать путь аргументом (Git Bash сам переведёт) или через `cygpath -w`.

### Тесты

Кроме двух тестов производительности из раздела 3, на этой машине стабильно падают `test_fork_throughput_1000_operations` (`tests/test_db_stress.py`) и `test_pack_submission_creates_valid_archive`. Падали и до правок M4 (проверено 19.10). Признак поломки — новые падения сверх этих. Называйте их в чатах "известные" (famous) тесты. Тесты-селебрити, тесты-звёзды.
