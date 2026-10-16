"""Утилита упаковки решения в submission.zip для тестирующей системы хакатона.

Формат согласно hackaton/sample/README.md:
ZIP-архив с кодом и обязательным файлом submission.json в корне архива.
"""
from __future__ import annotations

import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
SUBMISSION_JSON = OUTPUT_DIR / "submission.json"
EVIDENCE_JSON = OUTPUT_DIR / "evidence.json"
ZIP_OUT = OUTPUT_DIR / "submission.zip"


def pack() -> Path:
    if not SUBMISSION_JSON.is_file():
        raise FileNotFoundError(
            f"Файл {SUBMISSION_JSON} не найден. Сначала выполните: uv run python run_eval.py"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(ZIP_OUT, "w", zipfile.ZIP_DEFLATED) as z:
        # 1. Обязательный файл submission.json в корне архива
        z.write(SUBMISSION_JSON, arcname="submission.json")

        # 2. Лог улик evidence.json (для верификации жюри)
        if EVIDENCE_JSON.is_file():
            z.write(EVIDENCE_JSON, arcname="evidence.json")

        # 3. Исходный код решения
        z.write(ROOT / "run_eval.py", arcname="code/run_eval.py")
        if (ROOT / "pyproject.toml").is_file():
            z.write(ROOT / "pyproject.toml", arcname="code/pyproject.toml")

        # Пакет engine
        engine_dir = ROOT / "engine"
        for root, _, files in os.walk(engine_dir):
            for f in files:
                if f.endswith(".py"):
                    full_p = Path(root) / f
                    rel_p = full_p.relative_to(ROOT)
                    z.write(full_p, arcname=f"code/{rel_p}")

        # Данные правил
        data_dir = ROOT / "data"
        if data_dir.is_dir():
            for root, _, files in os.walk(data_dir):
                for f in files:
                    if f.endswith(".json"):
                        full_p = Path(root) / f
                        rel_p = full_p.relative_to(ROOT)
                        z.write(full_p, arcname=f"code/{rel_p}")

    print(f"Архив успешно создан: {ZIP_OUT}")
    print(f"Размер: {ZIP_OUT.stat().st_size / 1024:.1f} KB")
    return ZIP_OUT


if __name__ == "__main__":
    pack()
