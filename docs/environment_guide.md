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
Без ключей `run_eval.py` даёт выдачу кода — конфигурацию рекорда ([AGENTS.md](../AGENTS.md), «Выдача кода и рекорд»). Других исполнителей нет: legacy-контур удалён 21.10.

## 2. Сборка Java и модуль archparse

### JDK и Gradle под Windows
Нужен JDK 17+ (на машине Миши — `%USERPROFILE%\.jdks\openjdk-24.0.1`, системный `java` в PATH — Java 8, им Gradle не запустить). Wrapper при первом запуске качает Gradle 9.0 и зависимости (javaparser, jackson) в `%USERPROFILE%\.gradle`. Скрипт `gradlew` — bash, под Windows запускать `.bat` из `archparse/`:
```powershell
$env:JAVA_HOME = "$env:USERPROFILE\.jdks\openjdk-24.0.1"
.\gradlew.bat test
```

### Пересборка IR (data/ir, data/entity_ir.json)
Пути — обязательные аргументы (`--targets-dir`, `--skeleton`), умолчаний под Train Ticket нет. В `--args` пути с пробелами не передаются: путь к репозиторию содержит пробел (`xakaton huawei`), поэтому пути — относительные от `archparse/`:
```powershell
$T = "../hackaton/tt-challenge/targets/trainticket"; $K = "../hackaton/tt-challenge/skeleton/trainticket.json.gz"
.\gradlew.bat -q run "--args=--mode bodies --targets-dir $T --skeleton $K -o ../data/ir"
.\gradlew.bat -q run "--args=--mode entities --targets-dir $T --skeleton $K -o ../data/entity_ir.json"
```
После пересборки: `git diff --stat data/` (21.10 код archparse воспроизводил закоммиченные артефакты байт в байт), затем `run_eval.py` — sha256 рекорда.

### Привязка артефактов к проекту

Конвейер сверяет IR и `entity_ir.json` со скелетом при старте, до M1 и M4 (`engine/artifacts.py`). Если от 5% ID методов IR нет в `nodes`, вызовов репозиториев без call_site или сущностей без типа в скелете, либо IR пуст, либо `entity_ir.json` не загрузился, прогон останавливается: `ArtifactMismatch` с командой пересборки (в `run_eval.py` — сообщение в stderr и код выхода 1). Доля меньше предела — предупреждение в логе (скелет и артефакты соседних коммитов). Сверка идёт по ID, а не по телам методов.

Кеш каталога UI `data/ui_catalog.json` пересобирать вручную не нужно: в нём отпечаток (проект и коммит скелета, обработчики, содержимое файлов UI), и при несовпадении каталог строится заново чистым Python. Кеш другого проекта прогон не перезаписывает (каталог живёт только в этом прогоне); принудительная пересборка с записью — `build_catalog(..., force_rebuild=True)`. Закоммиченный кеш Train Ticket после правки скелета или UI пакета обновляется так же (`tests/test_artifacts.py` проверяет, что отпечаток в нём актуален).

Другой проект — своя папка артефактов (`ir/`, `entity_ir.json`, `ui_catalog.json`), `data/` не трогается. Папка `ui_catalog.json` создаётся сама при первом прогоне, IR и `entity_ir.json` строит archparse:
```powershell
$T = "../путь/к/targets"; $K = "../путь/к/skeleton.json.gz"; $A = "../artifacts/мой-проект"
.\gradlew.bat -q run "--args=--mode bodies --targets-dir $T --skeleton $K -o $A/ir"
.\gradlew.bat -q run "--args=--mode entities --targets-dir $T --skeleton $K -o $A/entity_ir.json"
```
затем из корня репозитория:
```powershell
$env:PYTHONUTF8=1; python run_eval.py --skeleton <skeleton> --targets <targets> --scenarios <сценарии> --artifacts-dir artifacts/мой-проект
```
Ошибка `ArtifactMismatch` на умолчании (`data/`) сама подсказывает такую папку: `artifacts/<проект скелета>`. Из кода — `PipelineConfig(artifacts_dir=...)`; `method_ir_dir` и `entity_ir_path` переопределяют отдельные пути.

## 3. Особенности тестов pytest

При запуске `python -m pytest -q tests` (около 20 секунд):
- Тесты производительности `test_fork_latency_under_100us` (`tests/test_db.py`), `test_fork_throughput_1000_operations` (`tests/test_db_stress.py`) и `test_performance_under_5_seconds` (`tests/test_contract_and_quality.py`) зависят от загрузки процессора и иногда падают на этой машине.
- `test_pack_submission_creates_valid_archive` падает в worktree без `output/submission.json`.
- **Правило:** если упали только они, а остальные зелёные — это не поломка логики (раздел 9, «Тесты»).

## 4. Программный запуск пайплайна (ArchonityPipeline)

Для диагностических скриптов и обвязок пайплайн инициализируется так же, как в `run_eval.py`:
```python
from pathlib import Path
from engine.grounding.llm import LLMClient
from engine.pipeline import ArchonityPipeline

ROOT = Path(__file__).resolve().parent.parent

pipeline = ArchonityPipeline(
    skeleton_path=ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz",
    targets_root=ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket",
    m1_options={"llm": LLMClient(use_server=False)},  # ответы LLM только из cache/llm
)

# Запуск сценария (например, S2)
methods, calls, remote, data = pipeline.run_scenario(scenario_dict)
```

Умолчания `RuntimeRules` — конфигурация рекорда; режимы правил передаются ключами (`constructors="all"`), неизвестный ключ — `TypeError`. Без `llm` M1 берёт первый кандидат поиска: это не выдача кода. Дамп БД ищется рядом со скелетом (`<пакет>/context/db-after-warmup.sql.gz`), другой — `db_dump_path=...`. Для диагностики выдачи кода проще обёртка над `run_eval.py` ([agent_lessons.md](agent_lessons.md), раздел 4).

## 5. Диагностика решений: журнал решений

Каждое решение по ребру (включение, отсев, удаление) пишут M4, правило Spring Security и проекция M5 в журнал `engine/decisions.py`. `run_eval.py` сохраняет его в `decisions.json` рядом с выдачей (evidence v2, ADR-005): для каждого ребра сценария — попало ли оно в ответ, на каких шагах, источник решения (`source_type`) и правило (`rule`), плюс все решения по шагам. Классы рёбер по журналу — `scripts/probe_edge_classes.py` ([agent_lessons.md](agent_lessons.md), раздел 4). Прежний `scripts/decision_log.py` (списки риска legacy-обхода) удалён вместе с legacy.

## 6. Git, .gitattributes и сгенерированные JSON

Файлы `data/ir/*.json` и `data/entity_ir.json` — десятки тысяч строк сгенерированного AST IR, `cache/**` — ответы LLM и векторы.
В `.gitattributes` для них настроены атрибуты:
```gitattributes
data/ir/*.json linguist-generated=true -diff
cache/** linguist-generated=true -diff -merge
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
- Если в строке исходника перед вызовом есть не-ASCII символы (кириллица или китайские иероглифы в комментариях/строках), метод JavaParser `getName().getBegin().column` возвращает номер символа (char), который меньше байтового смещения. Из-за этого вызов не сопоставляется с call_site скелета по `file + line + col` (так 0% совпадений давал прежний пул IR).
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

- `run_eval.py -o <папка>/x.json` кладёт **все** артефакты прогона рядом с `x.json`: `decisions.json`, `m4_unknowns.json`, `evidence.json`, `step_requests.json`, `m1_report.json` (режим M1: сколько ответов LLM из кеша, от сервера, без ответа; README, «Проверка без кеша»). Без `-o` — в `output/`. Каждый прогон ещё синхронизирует `visualizer/public/data`.
- Для экспериментов писать в отдельную папку (scratchpad), чтобы не затереть `output/` и не перепутать прогоны.
- Чужую посылку воспроизводить так: `git archive <sha> | tar -x -C <папка>`, туда скопировать `hackaton/`, запустить команду из её отчёта и сверить `sha256` у `submission.json`.
- В Python под Windows пути вида `/c/Users/...` не работают внутри строк кода. Передавать путь аргументом (Git Bash сам переведёт) или через `cygpath -w`.

### Тесты

Кроме двух тестов производительности из раздела 3, на этой машине стабильно падают `test_fork_throughput_1000_operations` (`tests/test_db_stress.py`) и `test_pack_submission_creates_valid_archive`. Падали и до правок M4 (проверено 19.10). Признак поломки — новые падения сверх этих. Называйте их в чатах "известные" (famous) тесты. Тесты-селебрити, тесты-звёзды.
