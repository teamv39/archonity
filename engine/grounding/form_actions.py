"""Действия формы UI без запроса (R20, M1).

Шаг сценария соответствует одному действию в UI. Если это действие — элемент формы, обработчик события которого не
шлёт запроса (выбор станции в `#food-station-list` фильтрует уже загруженный ответ), шаг до бэкенда не доходит.

Каталог строится по AST tree-sitter-javascript (как `ui_catalog.py`) и HTML:

- обработчики событий: атрибуты `onchange`/`onclick`/... в HTML и привязки `$("#id").change(function…)` в JS;
- обработчик без запроса: ни он, ни функции, которые он вызывает (транзитивно, по имени), не вызывают `$.ajax`,
  `$http`, `$.get`/`$.post`, `axios`. Одноимённые функции в разных файлах объединяются: запрос хотя бы в одной —
  запрос;
- слова действия — из `id` и `name` элемента без слов виджета (`list`, `btn`, `select`…).

Шаг — действие формы, если все слова действия (не меньше двух) есть в тексте шага. Решение принимает
`StepGrounder.form_only`: вдобавок выбранный M1 обработчик не должен вызываться ни одним запросом UI.
"""
from __future__ import annotations

import collections
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import tree_sitter as ts

from engine.grounding.ui_catalog import (
    _JS, AJAX_OBJ, AJAX_POS, EVENT_METHODS, FUNC_TYPES, UI_DIR, _callee, _func_name, _line, _text, _walk, ui_files,
)

HTML_EVENTS = ("onchange", "oninput", "onclick", "ng-change", "ng-click", "v-on:change", "v-on:click", "@change",
               "@click", "(change)", "(click)")
# Слова, которые называют виджет, а не то, что он выбирает
WIDGET_WORDS = {"list", "select", "selected", "btn", "button", "input", "box", "checkbox", "radio", "div", "span",
                "form", "or", "not", "and", "the", "id"}
_TAG = re.compile(r"<([a-zA-Z][\w-]*)\b([^>]*)>", re.S)
_ATTR = re.compile(r'([\w:@()\-]+)\s*=\s*"([^"]*)"')
_CALL = re.compile(r"([A-Za-z_$][\w$]*)\s*\(")


def words(text: str) -> set[str]:
    """Слова в нижнем регистре: camelCase и разделители `-_` разбиваются, множественное число снимается."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    out = set()
    for w in re.findall(r"[a-z]+", text.lower()):
        if len(w) > 3 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


@dataclass
class FormAction:
    file: str
    line: int
    element: str
    function: str
    words: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Fn:
    file: str
    line: int
    sends: bool
    calls: set[str]


def _functions(rel: str, src: bytes) -> list[tuple[str, _Fn]]:
    root = ts.Parser(_JS).parse(src).root_node
    out = []
    for fn in _walk(root):
        if fn.type not in FUNC_TYPES:
            continue
        name = _func_name(fn)
        if not name:
            continue
        sends, calls = False, set()
        for n in _walk(fn):
            if n.type != "call_expression":
                continue
            c = _callee(n)
            if c in AJAX_OBJ or c in AJAX_POS:
                sends = True
            f = n.child_by_field_name("function")
            if f is not None and f.type == "identifier":
                calls.add(_text(f))
        out.append((name, _Fn(rel, _line(fn), sends, calls)))
    return out


def build_form_actions(targets_root: str | Path) -> list[FormAction]:
    root = Path(targets_root)
    fns: dict[str, list[_Fn]] = collections.defaultdict(list)
    html: list[tuple[str, str]] = []
    for p in ui_files(root / UI_DIR):
        rel = p.relative_to(root).as_posix()
        if p.suffix == ".js":
            for name, f in _functions(rel, p.read_bytes()):
                fns[name].append(f)
        else:
            html.append((rel, p.read_text(encoding="utf-8", errors="replace")))

    memo: dict[str, bool] = {}

    def sends(name: str, stack: tuple[str, ...] = ()) -> bool:
        if name in memo:
            return memo[name]
        if name in stack:
            return False
        r = any(f.sends or any(sends(c, stack + (name,)) for c in f.calls if c in fns) for f in fns[name])
        memo[name] = r
        return r

    out: list[FormAction] = []

    def add(file: str, line: int, element: str, function: str, label: str) -> None:
        if function not in fns or sends(function):
            return
        w = words(label) - WIDGET_WORDS
        if len(w) >= 2:
            out.append(FormAction(file, line, element, function, sorted(w)))

    for rel, text in html:
        for m in _TAG.finditer(text):
            attrs = dict(_ATTR.findall(m.group(2)))
            label = " ".join(x for x in (attrs.get("id"), attrs.get("name")) if x)
            for ev in HTML_EVENTS:
                for fn in _CALL.findall(attrs.get(ev, "")):
                    add(rel, text.count("\n", 0, m.start()) + 1, "#" + attrs.get("id", ""), fn, label)
    for name, defs in fns.items():
        meth, _, sel = name.partition(":")
        if meth in EVENT_METHODS and sel.startswith("#"):
            add(defs[0].file, defs[0].line, sel, name, sel[1:])
    return out


def match(actions: list[FormAction], text: str) -> list[FormAction]:
    """Действия формы, все слова которых есть в тексте шага."""
    w = words(text)
    return [a for a in actions if set(a.words) <= w]
