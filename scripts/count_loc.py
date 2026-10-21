#!/usr/bin/env python3
"""scripts/count_loc.py — подсчёт строк кода в репозитории Archonity.

Поддерживает разбивку по языкам, подсистемам (engine, archparse, visualizer,
tests и др.), а также подсчёт чистых строк кода, комментариев и пустых строк.
Игнорирует внешние артефакты (hackaton/, cache/, node_modules/, .venv/).
"""

from __future__ import annotations

import argparse
import collections
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LANGUAGE_MAP: Dict[str, str] = {
    "py": "Python",
    "java": "Java",
    "ts": "TypeScript",
    "tsx": "TypeScript (React)",
    "css": "CSS",
    "html": "HTML",
    "sh": "Shell",
    "ps1": "PowerShell",
    "gradle": "Gradle",
    "toml": "TOML",
    "md": "Markdown",
    "json": "JSON",
}

CODE_LANGS = {
    "Python",
    "Java",
    "TypeScript",
    "TypeScript (React)",
    "CSS",
    "HTML",
    "Shell",
    "PowerShell",
    "Gradle",
    "TOML",
}

DEFAULT_IGNORED_DIRS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".gradle",
    "hackaton",
    "output",
    "cache",
}


def get_git_files(repo_root: Path) -> Optional[List[Path]]:
    """Получает список отслеживаемых git файлов, если доступен git."""
    try:
        res = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return [repo_root / line for line in res.stdout.splitlines() if line.strip()]
    except Exception:
        return None


def get_disk_files(repo_root: Path) -> List[Path]:
    """Рекурсивно сканирует файлы на диске, пропуская игнорируемые директории."""
    matched: List[Path] = []
    for p in repo_root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(repo_root)
        if any(part in DEFAULT_IGNORED_DIRS for part in rel.parts):
            continue
        matched.append(p)
    return matched


def classify_subsystem(rel_path: Path) -> str:
    """Определяет модуль / подсистему проекта."""
    parts = rel_path.parts
    if not parts:
        return "root"
    top = parts[0]
    if top in ("engine", "archparse", "visualizer", "tests", "scripts", "eval", "docs"):
        return top
    if rel_path.suffix in (".py", ".sh", ".ps1"):
        return "root scripts"
    if rel_path.suffix == ".md":
        return "docs (root)"
    return "other"


def count_lines_in_file(path: Path) -> Tuple[int, int, int, int]:
    """Возвращает (total, code, blank, comment)."""
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0, 0, 0, 0

    lines = content.splitlines()
    total = len(lines)
    blank = 0
    comment = 0
    code = 0

    ext = path.suffix.lstrip(".").lower()
    in_block_comment = False

    for line in lines:
        s = line.strip()
        if not s:
            blank += 1
            continue

        # Обработка блочных комментариев Java / JS / CSS
        if ext in ("java", "ts", "tsx", "css"):
            if in_block_comment:
                comment += 1
                if "*/" in s:
                    in_block_comment = False
                continue
            if s.startswith("/*"):
                comment += 1
                if "*/" not in s[2:]:
                    in_block_comment = True
                continue

        # Однострочные комментарии
        if (ext in ("py", "sh", "ps1", "toml") and s.startswith("#")) or (
            ext in ("java", "ts", "tsx", "gradle") and s.startswith("//")
        ):
            comment += 1
        else:
            code += 1

    return total, code, blank, comment


def main() -> None:
    parser = argparse.ArgumentParser(description="Подсчёт строк кода в репозитории")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Корень репозитория (по умолчанию текущая директория)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Включать JSON и Markdown данные в итоговый подсчёт кода",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Вывод результатов в формате JSON",
    )
    args = parser.parse_args()

    repo_root = args.root.resolve()
    files = get_git_files(repo_root)
    if files is None:
        files = get_disk_files(repo_root)

    lang_stats = collections.defaultdict(
        lambda: {"files": 0, "total": 0, "code": 0, "blank": 0, "comment": 0}
    )
    subsystem_stats = collections.defaultdict(
        lambda: {"code_loc": 0, "docs_loc": 0, "total_loc": 0, "files": 0}
    )

    for file_path in files:
        if not file_path.is_file():
            continue
        try:
            rel = file_path.relative_to(repo_root)
        except ValueError:
            rel = file_path

        ext = file_path.suffix.lstrip(".").lower()
        if not ext:
            continue

        lang = LANGUAGE_MAP.get(ext)
        if not lang:
            continue

        # Пропускаем огромные кэши/данные при обычном анализе кода, если это json вне исходников
        if ext == "json" and any(part in ("cache", "data", "facts", "hackaton") for part in rel.parts):
            continue

        tot, cod, blk, com = count_lines_in_file(file_path)
        lang_stats[lang]["files"] += 1
        lang_stats[lang]["total"] += tot
        lang_stats[lang]["code"] += cod
        lang_stats[lang]["blank"] += blk
        lang_stats[lang]["comment"] += com

        sub = classify_subsystem(rel)
        subsystem_stats[sub]["files"] += 1
        subsystem_stats[sub]["total_loc"] += tot
        if lang in CODE_LANGS:
            subsystem_stats[sub]["code_loc"] += tot
        elif lang == "Markdown":
            subsystem_stats[sub]["docs_loc"] += tot

    if args.json:
        out = {
            "by_language": dict(lang_stats),
            "by_subsystem": dict(subsystem_stats),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return

    # Вывод по языкам
    print("=" * 74)
    print(f"{'Язык':<22} {'Файлов':>8} {'Всего':>10} {'Код (SLOC)':>12} {'Пустые':>10} {'Коммент':>8}")
    print("=" * 74)

    total_files = 0
    total_lines = 0
    total_code = 0
    total_blank = 0
    total_comment = 0

    code_only_files = 0
    code_only_lines = 0
    code_only_code = 0

    sorted_langs = sorted(lang_stats.items(), key=lambda x: x[1]["total"], reverse=True)
    for lang, s in sorted_langs:
        is_code = lang in CODE_LANGS
        if is_code:
            code_only_files += s["files"]
            code_only_lines += s["total"]
            code_only_code += s["code"]

        total_files += s["files"]
        total_lines += s["total"]
        total_code += s["code"]
        total_blank += s["blank"]
        total_comment += s["comment"]

        print(
            f"{lang:<22} {s['files']:>8} {s['total']:>10} {s['code']:>12} {s['blank']:>10} {s['comment']:>8}"
        )

    print("-" * 74)
    print(
        f"{'ИТОГО (Код)':<22} {code_only_files:>8} {code_only_lines:>10} {code_only_code:>12}"
    )
    print(
        f"{'ИТОГО (Всего)':<22} {total_files:>8} {total_lines:>10} {total_code:>12} {total_blank:>10} {total_comment:>8}"
    )
    print("=" * 74)
    print()

    # Вывод по подсистемам
    print("=" * 56)
    print(f"{'Подсистема / Модуль':<24} {'Файлов':>8} {'Код (строк)':>12} {'Документация':>10}")
    print("=" * 56)
    for sub, s in sorted(subsystem_stats.items(), key=lambda x: x[1]["code_loc"], reverse=True):
        print(f"{sub:<24} {s['files']:>8} {s['code_loc']:>12} {s['docs_loc']:>10}")
    print("=" * 56)


if __name__ == "__main__":
    main()
