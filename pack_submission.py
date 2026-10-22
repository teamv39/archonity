"""Утилита упаковки решения в submission.zip для тестирующей системы хакатона (NSUTS).

Формат — hackaton/sample/README.md: zip-архив с кодом и обязательным submission.json в корне.

В корне архива: submission.json, evidence.json, RUN.md с командами воспроизведения и report.html — отчёт прогона (scripts/report.py). В code/ — всё, чтобы из этого
каталога получить тот же submission.json и прогнать новые сценарии (docs/run_on_a100.md): код (run_eval.py, engine/,
archparse/ и rust/ — источник data/ и Rust-движок, ADR-008), артефакты M2 (data/), кеши M1 (cache/), зависимости (pyproject.toml, uv.lock,
requirements.txt), манифест моделей и скрипты запуска.

Гарантирует:
1. Переводы строк в текстовых файлах — Unix LF, как в индексе git.
2. POSIX-атрибуты: файлы 0o644, скрипты *.sh и gradlew 0o755, каталоги 0o755, create_system = 3 (Unix).
3. Только перечисленное ниже: без node_modules, __pycache__, rust/target, hackaton/ и моделей. Нет файла из списка — ошибка.
4. Исходники Rust (rust/**/*.rs, Cargo.toml, Cargo.lock, README) в архиве: надбавку за Rust дают за исходный код, а
   scripts/run_final.sh собирает бинарники оттуда (`cargo build --release --locked`).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
SUBMISSION_JSON = OUTPUT_DIR / "submission.json"
EVIDENCE_JSON = OUTPUT_DIR / "evidence.json"
ZIP_OUT = OUTPUT_DIR / "submission.zip"

# Файлы кода, данных, зависимостей и запуска (пути от корня репозитория; в архиве — под code/)
CODE_FILES = (
    "run_eval.py",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
    "models/manifest.json",
    "facts/configs_topology.json",  # имя шлюза для evidence.json (engine/evidence.py)
    "docs/run_on_a100.md",
    "data/entity_ir.json",
    "data/ui_catalog.json",
    "scripts/run_final.sh",
    "scripts/fetch_models.py",
    "scripts/start_llm.sh",
    "scripts/start_llm.ps1",
    "scripts/verify_llm_cache.py",
    "scripts/report.py",
    "archparse/README.md",
    "archparse/build.gradle",
    "archparse/settings.gradle",
    "archparse/gradlew",
    "archparse/gradlew.bat",
    "archparse/gradle/wrapper/gradle-wrapper.jar",
    "archparse/gradle/wrapper/gradle-wrapper.properties",
)

# Каталоги целиком: (каталог, шаблон rglob)
CODE_TREES = (
    ("engine", "*.py"),
    ("data/ir", "*.json"),  # IR тел методов (M2, archparse/README.md)
    ("cache/llm", "*.json"),  # ответы LLM: S1–S7 без GPU (ADR-005, «Кеш LLM»)
    ("cache/emb/qwen3-4b", "*"),  # векторы эмбеддера
    ("archparse/src", "*.java"),
)

# Rust-движок: исходники и манифесты, без rust/target
RUST_SUFFIXES = {".rs", ".toml", ".lock", ".md"}

TEXT_SUFFIXES = {".py", ".json", ".md", ".txt", ".toml", ".lock", ".sh", ".ps1", ".bat", ".gradle", ".properties",
                 ".java", ".rs", ""}
EXECUTABLE = {"scripts/run_final.sh", "scripts/start_llm.sh", "archparse/gradlew"}

BUILD_CMD = "cd rust && cargo build --release --locked && cd .."
RUN_CMD = "python run_eval.py --engine rust --parse-sources -o output/submission.json"
PYTHON_CMD = "python run_eval.py -o output/submission.json"


def code_files() -> list[str]:
    """Пути файлов кода от корня репозитория, по алфавиту."""
    files = set(CODE_FILES)
    for top, pattern in CODE_TREES:
        found = [p for p in (ROOT / top).rglob(pattern) if p.is_file() and "__pycache__" not in p.parts]
        if not found:
            raise FileNotFoundError(f"В {ROOT / top} нет файлов {pattern}")
        files.update(p.relative_to(ROOT).as_posix() for p in found)
    rust = [p for p in (ROOT / "rust").rglob("*") if p.is_file() and "target" not in p.relative_to(ROOT / "rust").parts
            and p.suffix in RUST_SUFFIXES]
    if not any(p.name == "Cargo.lock" for p in rust) or not any(p.suffix == ".rs" for p in rust):
        raise FileNotFoundError(f"В {ROOT / 'rust'} нет Cargo.lock или исходников .rs")
    files.update(p.relative_to(ROOT).as_posix() for p in rust)
    missing = [f for f in files if not (ROOT / f).is_file()]
    if missing:
        raise FileNotFoundError(f"Нет файлов для архива: {', '.join(sorted(missing))}")
    return sorted(files)


def run_md(run_cmd: str) -> str:
    return f"""# Воспроизведение

Код — в каталоге `code/`, команды — оттуда. Пакет организаторов (скелет, исходники, сценарии) ожидается в
`code/hackaton/tt-challenge/`, другие пути задают флаги `run_eval.py` `--skeleton`, `--targets`, `--scenarios`.

Зависимости (Python 3.11+):

    pip install -r requirements.txt        # или: uv sync --locked

Анализ кода и построение ответа — Rust (`rust/`, ADR-008, ADR-009): Rust 1.99.1 из `rust/rust-toolchain.toml` и
компилятор C (`cc`/`gcc`) для tree-sitter, зависимости с crates.io. На Python — только M1 (сопоставление шагов
с обработчиками через локальные модели) и кеш ответов моделей.

`submission.json` этого архива (S0–S7) из кешей `cache/`, без GPU и сервера LLM: сборка Rust, затем прогон.
`archonity-parse` строит IR тел методов из исходников, `archonity-exec` исполняет шаги и пишет выдачу:

    {BUILD_CMD}
    {run_cmd}

Если `archonity-exec` нет или он упал, тот же прогон идёт на Python-исполнителе: выдача та же байт в байт, сбой —
в рамке и `ATTENTION.txt`. Целиком на Python, без Rust: `{PYTHON_CMD}`.

Новые сценарии на Linux с A100 40 ГБ — одна команда, она докачивает модели по `models/manifest.json` (версии и sha256)
и поднимает `llama-server` сама:

    scripts/run_final.sh <файлы сценариев>

Подробно — `docs/run_on_a100.md`.

`report.html` рядом — отчёт этого прогона: качество по эталону, шаги, обработчики и рёбра с правилом и местом
в коде. Пересобрать по любому прогону: `python scripts/report.py output/`. Ресурсы прогона (время этапов, пик памяти
и видеопамяти, вызовы LLM) — `output/resources.json` после запуска и раздел «Ресурсы» в отчёте.
"""


def _add_file(zf: zipfile.ZipFile, arcname: str, data: bytes, mode: int = 0o644) -> None:
    zinfo = zipfile.ZipInfo(arcname)
    zinfo.create_system = 3  # Unix
    zinfo.external_attr = (0o100000 | mode) << 16
    zinfo.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(zinfo, data)


def _add_dir(zf: zipfile.ZipFile, arcname: str) -> None:
    zinfo = zipfile.ZipInfo(arcname.rstrip("/") + "/")
    zinfo.create_system = 3  # Unix
    zinfo.external_attr = 0o40755 << 16  # drwxr-xr-x
    zf.writestr(zinfo, b"")


def _read(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return data


def report_html(run_dir: Path = OUTPUT_DIR) -> str | None:
    """Отчёт прогона (scripts/report.py) для корня архива: ссылки на код — в code/hackaton/, куда организаторы
    кладут свой пакет. Нет файлов прогона рядом с выдачей — отчёта нет."""
    if not all((run_dir / f).is_file() for f in ("decisions.json", "step_requests.json")):
        print(f"Отчёт не добавлен: в {run_dir} нет decisions.json или step_requests.json")
        return None
    sys.path.insert(0, str(ROOT / "scripts"))
    import report

    args = report.parse_args([str(run_dir), "-o", "report.html",
                              "--targets", "code/hackaton/tt-challenge/targets/trainticket"])
    return report.render(run_dir, args)


def pack(zip_out: Path = ZIP_OUT, run_cmd: str | None = None, run_dir: Path = OUTPUT_DIR,
         submission: Path | None = None) -> Path:
    """Архив сдачи из прогона в run_dir (по умолчанию output/). run_cmd — команда, которой получен submission.json
    (в RUN.md архива); submission — другая выдача вместо run_dir/submission.json (зонды scripts/probe_cells.py)."""
    submission, evidence = submission or run_dir / SUBMISSION_JSON.name, run_dir / EVIDENCE_JSON.name
    if not submission.is_file():
        raise FileNotFoundError(
            f"Файл {submission} не найден. Сначала выполните: {BUILD_CMD} && {RUN_CMD}"
        )
    files = code_files()
    dirs = sorted({"code"} | {f"code/{p}" for f in files for p in PurePosixPath(f).parents if str(p) != "."})

    zip_out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_out, "w") as z:
        _add_file(z, "submission.json", _read(submission))
        if evidence.is_file():
            _add_file(z, "evidence.json", _read(evidence))
        _add_file(z, "RUN.md", run_md(run_cmd or RUN_CMD).encode("utf-8"))
        if page := report_html(run_dir):
            _add_file(z, "report.html", page.encode("utf-8"))
        for d in dirs:
            _add_dir(z, d)
        for f in files:
            _add_file(z, f"code/{f}", _read(ROOT / f), 0o755 if f in EXECUTABLE else 0o644)

    file_count = len(zipfile.ZipFile(zip_out).infolist())
    size_kb = zip_out.stat().st_size / 1024
    print(f"Архив успешно создан: {zip_out}")
    print(f"Всего записей: {file_count}, Размер: {size_kb:.1f} KB")
    return zip_out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Упаковка output/submission.json и кода в архив сдачи")
    ap.add_argument("--out", type=Path, default=ZIP_OUT, help="Путь архива (по умолчанию output/submission.zip)")
    ap.add_argument("--cmd", default=None, help=f"Команда, которой получен submission.json (по умолчанию {RUN_CMD})")
    a = ap.parse_args()
    pack(a.out, a.cmd)
