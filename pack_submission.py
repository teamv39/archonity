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

from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
SUBMISSION_JSON = OUTPUT_DIR / "submission.json"
EVIDENCE_JSON = OUTPUT_DIR / "evidence.json"
ZIP_OUT = OUTPUT_DIR / "submission.zip"

# Канонический список файлов правил и IR из data/
DATA_RULE_FILES = (
    "branch_rules.json",
    "demo_graph.json",
    "entity_ir.json",
    "llm_judge_dossiers_and_traps.json",
    "pool_ir.json",
    "runtime_and_topology_rules.json",
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


def pack() -> Path:
    if not SUBMISSION_JSON.is_file():
        raise FileNotFoundError(
            f"Файл {SUBMISSION_JSON} не найден. Сначала выполните: uv run python run_eval.py"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(ZIP_OUT, "w") as z:
        # 1. Обязательный файл submission.json в корне архива (строго Unix LF)
        _add_file_to_zip(z, SUBMISSION_JSON, "submission.json", normalize_lf=True)

        # 2. Лог улик evidence.json (для верификации жюри, строго Unix LF)
        if EVIDENCE_JSON.is_file():
            _add_file_to_zip(z, EVIDENCE_JSON, "evidence.json", normalize_lf=True)

        # 3. README архива
        readme_path = ROOT / "README.md"
        if readme_path.is_file():
            _add_file_to_zip(z, readme_path, "README.md", normalize_lf=True)

        # 4. Каталоги кода
        _add_dir_to_zip(z, "code")
        _add_dir_to_zip(z, "code/engine")
        _add_dir_to_zip(z, "code/engine/adapters")
        _add_dir_to_zip(z, "code/engine/graph")
        _add_dir_to_zip(z, "code/data")

        # 5. Исходный код решения
        _add_file_to_zip(z, ROOT / "run_eval.py", "code/run_eval.py", normalize_lf=True)
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
                # Данные правил (строго канонический список data/*.json без мусора)
        data_dir = ROOT / "data"
        if data_dir.is_dir():
            for fname in DATA_RULE_FILES:
                fp = data_dir / fname
                if fp.is_file():
                    _add_file_to_zip(z, fp, f"code/data/{fname}", normalize_lf=True)

        # Кеши M1 (ответы LLM и векторы эмбеддера): прогон --grounder m1 без GPU (ADR-005, «Кеш LLM»)
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

    file_count = len(zipfile.ZipFile(ZIP_OUT).infolist())
    size_kb = ZIP_OUT.stat().st_size / 1024
    print(f"Архив успешно создан: {ZIP_OUT}")
    print(f"Всего записей: {file_count}, Размер: {size_kb:.1f} KB")
    return ZIP_OUT


if __name__ == "__main__":
    pack()

