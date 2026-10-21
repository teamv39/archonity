"""Утилита упаковки решения в submission.zip для тестирующей системы хакатона (NSUTS).

Формат согласно hackaton/sample/README.md:
ZIP-архив с кодом и обязательным файлом submission.json в корне архива.
Гарантирует:
1. submission.json и evidence.json строго в корне архива.
2. Исключительно Unix LF (\\n) переводы строк.
3. POSIX-атрибуты файлов (0o644) и каталогов (0o755) с create_system = 3 (Unix).
4. Строгое исключение мусорных файлов (node_modules, train-ticket, кэши).
"""
from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
SUBMISSION_JSON = OUTPUT_DIR / "submission.json"
EVIDENCE_JSON = OUTPUT_DIR / "evidence.json"
ZIP_OUT = OUTPUT_DIR / "submission.zip"

# Канонический список файлов правил и IR из data/
DATA_RULE_FILES = (
    "entity_ir.json",
    "ui_catalog.json",
)


def _add_file_to_zip(zf: zipfile.ZipFile, src_path: Path, arcname: str, normalize_lf: bool = False) -> None:
    data = src_path.read_bytes()
    if normalize_lf:
        data = data.replace(b"\r\n", b"\n")
    clean_arc = arcname.replace("\\", "/")
    zinfo = zipfile.ZipInfo(clean_arc)
    zinfo.create_system = 3  # Unix
    zinfo.external_attr = 0o100644 << 16  # -rw-r--r--
    zinfo.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(zinfo, data)


def _add_dir_to_zip(zf: zipfile.ZipFile, arcname: str) -> None:
    clean_arc = arcname.replace("\\", "/").rstrip("/") + "/"
    zinfo = zipfile.ZipInfo(clean_arc)
    zinfo.create_system = 3  # Unix
    zinfo.external_attr = 0o40755 << 16  # drwxr-xr-x
    zf.writestr(zinfo, b"")


def pack(zip_out: Path = ZIP_OUT, run_cmd: str | None = None) -> Path:
    """Архив сдачи. run_cmd — команда, которой получен submission.json (кладётся в RUN.md архива)."""
    if not SUBMISSION_JSON.is_file():
        raise FileNotFoundError(
            f"Файл {SUBMISSION_JSON} не найден. Сначала выполните: uv run python run_eval.py"
        )

    zip_out.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_out, "w") as z:
        # 1. Обязательный файл submission.json в корне архива (строго Unix LF)
        _add_file_to_zip(z, SUBMISSION_JSON, "submission.json", normalize_lf=True)

        # 2. Лог улик evidence.json (для верификации жюри, строго Unix LF)
        if EVIDENCE_JSON.is_file():
            _add_file_to_zip(z, EVIDENCE_JSON, "evidence.json", normalize_lf=True)

        # 3. README архива
        readme_path = ROOT / "README.md"
        if readme_path.is_file():
            _add_file_to_zip(z, readme_path, "README.md", normalize_lf=True)
        if run_cmd:
            zinfo = zipfile.ZipInfo("RUN.md")
            zinfo.create_system = 3
            zinfo.external_attr = 0o100644 << 16
            zinfo.compress_type = zipfile.ZIP_DEFLATED
            run_md = f"# Воспроизведение\n\nИз каталога code/:\n\n    {run_cmd}\n"
            z.writestr(zinfo, run_md.encode("utf-8"))

        # 4. Каталоги кода
        _add_dir_to_zip(z, "code")
        _add_dir_to_zip(z, "code/engine")
        _add_dir_to_zip(z, "code/engine/adapters")
        _add_dir_to_zip(z, "code/engine/executor")
        _add_dir_to_zip(z, "code/engine/grounding")
        _add_dir_to_zip(z, "code/data")

        # 5. Исходный код решения
        _add_file_to_zip(z, ROOT / "run_eval.py", "code/run_eval.py", normalize_lf=True)
        # Проверка кеша LLM без GPU (README, «Проверка без кеша»)
        _add_dir_to_zip(z, "code/scripts")
        _add_file_to_zip(z, ROOT / "scripts" / "verify_llm_cache.py", "code/scripts/verify_llm_cache.py",
                         normalize_lf=True)
        pyproj = ROOT / "pyproject.toml"
        if pyproj.is_file():
            _add_file_to_zip(z, pyproj, "code/pyproject.toml", normalize_lf=True)

        # Пакет engine (только .py файлы, без кэшей)
        engine_dir = ROOT / "engine"
        for p in sorted(engine_dir.rglob("*.py")):
            if "__pycache__" not in p.parts:
                rel_p = p.relative_to(ROOT)
                _add_file_to_zip(z, p, f"code/{rel_p}", normalize_lf=True)

        # Данные правил (строго канонический список data/*.json без мусора)
        data_dir = ROOT / "data"
        if data_dir.is_dir():
            for fname in DATA_RULE_FILES:
                fp = data_dir / fname
                if fp.is_file():
                    _add_file_to_zip(z, fp, f"code/data/{fname}", normalize_lf=True)
            # IR тел методов (M2, archparse/README.md, раздел 3.6): data/ir/<module>.json
            _add_dir_to_zip(z, "code/data/ir")
            for fp in sorted((data_dir / "ir").glob("*.json")):
                _add_file_to_zip(z, fp, f"code/data/ir/{fp.name}", normalize_lf=True)

        # Кеши M1 (ответы LLM и векторы эмбеддера): прогон без GPU (ADR-005, «Кеш LLM»)
        _add_dir_to_zip(z, "code/cache")
        _add_dir_to_zip(z, "code/cache/emb")
        for cache_dir in (ROOT / "cache" / "llm", ROOT / "cache" / "emb" / "qwen3-4b"):
            if cache_dir.is_dir():
                _add_dir_to_zip(z, f"code/{cache_dir.relative_to(ROOT).as_posix()}")
                for full_p in sorted(cache_dir.iterdir()):
                    if full_p.is_file():
                        _add_file_to_zip(
                            z,
                            full_p,
                            f"code/{full_p.relative_to(ROOT).as_posix()}",
                            normalize_lf=full_p.suffix in (".json", ".txt", ".md"),
                        )

    file_count = len(zipfile.ZipFile(zip_out).infolist())
    size_kb = zip_out.stat().st_size / 1024
    print(f"Архив успешно создан: {zip_out}")
    print(f"Всего записей: {file_count}, Размер: {size_kb:.1f} KB")
    return zip_out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Упаковка output/submission.json и кода в архив сдачи")
    ap.add_argument("--out", type=Path, default=ZIP_OUT, help="Путь архива (по умолчанию output/submission.zip)")
    ap.add_argument("--cmd", default=None, help="Команда, которой получен submission.json (в RUN.md архива)")
    a = ap.parse_args()
    pack(a.out, a.cmd)

