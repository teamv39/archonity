"""Сторож переносимости: в рабочем коде нет литералов Train Ticket (ADR-007, аудит универсальности).

Проверяются строковые литералы, а не комментарии: примеры из Train Ticket в комментариях допустимы, имена сервисов,
пакеты, пассажир и UUID в коде — нет. Разрешены только умолчания путей входа к пакету задачи
(`hackaton/tt-challenge/...`), их задаёт запуск, а не анализ.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKERS = re.compile(r"\bts-[a-z0-9]|fudan|fdse|gaotie|dongche|orders_other|trainticket|train ?ticket|4d2a46c7|"
                     r"tt-challenge", re.I)
# Умолчания путей входа к пакету задачи: hackaton/tt-challenge/{skeleton/trainticket.json.gz,targets/trainticket,...}
ENTRY_PATH = re.compile(r"^(?:tt-challenge|trainticket|trainticket\.json\.gz)$|hackaton/tt-challenge/|targets/trainticket")


def _python_literals(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docs.add(id(first.value))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def _java_literals(path: Path) -> list[str]:
    s = path.read_text(encoding="utf-8")
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"//[^\n]*", "", s)
    return re.findall(r'"(?:[^"\\n]|\.)*"', s)


def test_python_code_has_no_project_literals() -> None:
    files = sorted(ROOT.joinpath("engine").rglob("*.py")) + [ROOT / "run_eval.py"]
    bad = [f"{p.relative_to(ROOT)}:{ln}: {v[:80]!r}" for p in files for ln, v in _python_literals(p)
           if MARKERS.search(v) and not ENTRY_PATH.search(v)]
    assert not bad, "литералы Train Ticket в коде:\n" + "\n".join(bad)


def test_archparse_has_no_project_literals() -> None:
    files = sorted(ROOT.joinpath("archparse", "src", "main").rglob("*.java"))
    assert files
    bad = [f"{p.relative_to(ROOT)}: {v[:80]}" for p in files for v in _java_literals(p) if MARKERS.search(v)]
    assert not bad, "литералы Train Ticket в archparse:\n" + "\n".join(bad)


def test_guard_catches_literals(tmp_path: Path) -> None:
    p = tmp_path / "x.py"
    p.write_text('"""Пример: ts-order-service."""\nNAME = "ts-common"  # ts-common в комментарии\n', encoding="utf-8")
    hits = [v for _, v in _python_literals(p) if MARKERS.search(v)]
    assert hits == ["ts-common"]


def _rust_literals(path: Path) -> list[str]:
    s = path.read_text(encoding="utf-8")
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"//[^\n]*", "", s)
    return re.findall(r'"(?:[^"\\\n]|\\.)*"', s)


def test_archonity_parse_has_no_project_literals() -> None:
    files = sorted(ROOT.joinpath("rust", "crates", "archonity-parse", "src").rglob("*.rs"))
    assert files
    bad = [f"{p.relative_to(ROOT)}: {v[:80]}" for p in files for v in _rust_literals(p) if MARKERS.search(v)]
    assert not bad, "литералы Train Ticket в archonity-parse:\n" + "\n".join(bad)
