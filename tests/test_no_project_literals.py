"""Сторож переносимости: в рабочем коде нет литералов Train Ticket (ADR-007, аудит универсальности).

Проверяются строковые литералы, а не комментарии: примеры из Train Ticket в комментариях допустимы, имена сервисов,
пакеты, пассажир и UUID в коде — нет. Разрешены только умолчания путей входа к пакету задачи
(`hackaton/tt-challenge/...`), их задаёт запуск, а не анализ.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

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
    # До 22.10 здесь было `[^"\\n]` — в raw-строке это «не кавычка, не обратная косая, не буква n»: литерал с буквой n
    # (`"Response"`, `"edu.fudan.common"`) не находился, сторож archparse был слепым (test_java_guard_catches_literals)
    return [m[1:-1] for m in re.findall(r'"(?:[^"\\\n]|\\.)*"', s)]


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


def test_java_guard_catches_literals(tmp_path: Path) -> None:
    p = tmp_path / "X.java"
    p.write_text('// "ts-order-service" в комментарии\nif (t.equals("Response") && p.startsWith("edu.fudan.common")) '
                 '{ s = "a\\"b"; }\n', encoding="utf-8")
    assert _java_literals(p) == ["Response", "edu.fudan.common", 'a\\"b']


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


# --- Имена из кода проекта (поля и классы скелета) строковыми литералами в движке
#
# Маркеры выше ловят имена сервисов и пакетов, но не имена полей DTO: правило «получатель багажа» держалось на
# `"consigneeName"`, `"consigneeWeight"` в M4 и проходило сторож. Знание о полях проекта движок берёт из артефактов
# (скелет, каталог UI, IR), а не из головы разработчика. Литерал, совпавший с именем поля или класса проекта, —
# либо общее слово (GENERIC), либо известный долг с причиной (KNOWN), иначе тест падает.

# Общие слова: ключи наших форматов (скелет, выдача, журнал), JDK и Spring, служебные строки. В проекте они тоже
# встречаются как имена полей, но движок пишет их не ради проекта (`Id` — аннотация JPA @Id и суффикс `<вид>Id`)
GENERIC = {
    "id", "ID", "Id", "name", "type", "data", "value", "index", "info", "status", "success", "message", "model", "code",
    "description", "number", "from", "admin", "repository", "OTHER", "T", "Z",
}
# Известный долг: имя из проекта в коде движка и почему оно там. Новое имя сюда — только с обоснованием в
# annotation_rules.md или ADR, лучше вывести его из артефактов
KNOWN = {
    "accountId": "поле тела, куда UI кладёт ID вошедшего пользователя (schema._USER_FIELDS; annotation_rules.md); "
                 "каталог UI пока не хранит нелитеральные значения полей",
    "userId": "то же, что accountId",
    "loginId": "то же, что accountId",
    "username": "контракт Spring Security UserDetails#getUsername, а не проекта",
    "StringUtils": "модель библиотечного org.springframework.util.StringUtils (library), не класса проекта",
    "account": "слово текста шага в VERB_OBJECT_SYN (grounding/text.py): «create … account» ищет и регистрацию; "
               "подобрано по перефразированному S4.1, как VERB_SYN_EXTRA, выключается --m1-verb-synonyms off",
}


def _project_names() -> set[str] | None:
    import gzip
    import json

    sk = next(ROOT.joinpath("hackaton", "tt-challenge", "skeleton").glob("*.json.gz"), None)
    if sk is None:
        return None
    nodes = json.load(gzip.open(sk, "rt", encoding="utf-8"))["nodes"]
    nodes = nodes.values() if isinstance(nodes, dict) else nodes
    out = set()
    for n in nodes:
        if n.get("kind") == "field" and n.get("name"):
            out.add(n["name"])
        elif n.get("kind") == "type" and n.get("fqn"):
            # У типа в скелете нет `name`, только `fqn` (до 22.10 имена классов не собирались); `X$1` — анонимный класс
            simple = n["fqn"].split(".")[-1].split("$")[-1]
            if not simple.isdigit():
                out.add(simple)
    return out


def _engine_rust_files() -> list[Path]:
    return sorted(p for p in ROOT.joinpath("rust", "crates").rglob("*.rs") if "tests" not in p.relative_to(ROOT).parts)


def _rust_code_literals(path: Path) -> list[tuple[int, str]]:
    """Литералы Rust вне комментариев и вне модуля `#[cfg(test)]` (тесты в конце файла)."""
    s = path.read_text(encoding="utf-8").split("#[cfg(test)]")[0]
    s = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), s, flags=re.S)
    out = []
    for ln, line in enumerate(s.splitlines(), 1):
        out += [(ln, v) for v in re.findall(r'"((?:[^"\\]|\\.)*)"', re.sub(r"//.*$", "", line))]
    return out


def _name_hits(names: set[str]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for p in sorted(ROOT.joinpath("engine").rglob("*.py")) + [ROOT / "run_eval.py"]:
        for ln, v in _python_literals(p):
            if v in names:
                hits.setdefault(v, []).append(f"{p.relative_to(ROOT)}:{ln}")
    for p in _engine_rust_files():
        for ln, v in _rust_code_literals(p):
            if v in names:
                hits.setdefault(v, []).append(f"{p.relative_to(ROOT)}:{ln}")
    for p in sorted(ROOT.joinpath("archparse", "src", "main").rglob("*.java")):
        for v in _java_literals(p):
            if v in names:
                hits.setdefault(v, []).append(str(p.relative_to(ROOT)))
    return hits


def test_engine_has_no_project_field_names() -> None:
    names = _project_names()
    if names is None:
        pytest.skip("нет скелета в hackaton/tt-challenge/skeleton")
    hits = _name_hits(names)
    bad = [f"{v!r}: {', '.join(w)}" for v, w in sorted(hits.items()) if v not in GENERIC and v not in KNOWN]
    assert not bad, ("имена полей и классов проекта литералами в движке — вывести из артефактов (скелет, каталог UI) "
                     "или записать в KNOWN с причиной:\n" + "\n".join(bad))
    stale = sorted(set(KNOWN) - set(hits))
    assert not stale, f"долг из KNOWN больше не встречается — убрать из списка: {stale}"


def test_field_name_guard_catches_literals(tmp_path: Path) -> None:
    p = tmp_path / "x.rs"
    p.write_text('// "consigneeName" в комментарии\nlet w = params.get("consigneeWeight");\n'
                 '#[cfg(test)]\nmod t { const X: &str = "consigneePhone"; }\n', encoding="utf-8")
    assert [v for _, v in _rust_code_literals(p)] == ["consigneeWeight"]


def test_engine_rust_has_no_project_literals() -> None:
    bad = [f"{p.relative_to(ROOT)}:{ln}: {v[:80]}" for p in _engine_rust_files() for ln, v in _rust_code_literals(p)
           if MARKERS.search(v) and not ENTRY_PATH.search(v)]
    assert not bad, "литералы Train Ticket в rust/crates:\n" + "\n".join(bad)
