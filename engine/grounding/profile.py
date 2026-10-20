"""Профиль проекта для промпта M1 v8: Stage 0, ADR-007, решение 4.

Один вызов LLM на репозиторий. Вход — факты, которые код уже знает: начало README, `context` скелета, модули,
пары близнецов (`twin_groups`) и условия, по которым UI шлёт запрос в одну или другую сторону пары, со строками
UI-кода, где заданы сравниваемые значения. Выход — `domain_summary` и правило каждой пары: что обслуживает каждая
сторона и как выбрать сторону для шага.

Профиль строится при каждой сборке M1 тем же `LLMClient`: из кеша `cache/llm/` — тот же ответ. Правка ответа
руками ломает ключ кеша. Файл `data/project_profile.json` пишет `scripts/profile_project.py` — копия для чтения,
конвейер её не читает. Нет сервера и кеша — профиль пустой.
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.adapters.skeleton import SkeletonIndex
from engine.grounding.docs import HandlerCatalog
from engine.grounding.retrieval import _module_marker
from engine.grounding.ui_catalog import UICatalog, UIRequest

PROFILE_VERSION = "profile-v1"
MAX_TOKENS = 1600
README_CHARS = 1500
UI_LINES = 8
VALUE_LINES = 6

SYSTEM = """You describe a software project for a tool that maps steps of user scenarios to backend REST handlers.
Use only the facts given below. Answer with JSON."""

TASK = """Answer:
- analysis: first work out, from the UI conditions, the UI code and the remote calls, which property of the data splits each pair. Pairs that split the data the same way get the same split.
- domain_summary: one or two sentences: what the system does, for whom, and its main business objects.
- twins: for every pair, which part of the data each side serves and how to choose the side for a scenario step. Name that part of the data as the project names it (labels and codes shown in the UI code, values of the record's fields); do not name UI variables. When several pairs split the data the same way, describe them the same way. Keep each description under 25 words."""

_JS_WORDS = {"this", "true", "false", "null", "undefined", "var", "let", "const", "typeof", "new", "length"}
# Модель начинает описание стороны с «Base side:» — промпт выбора и так подписывает сторону
_SIDE = re.compile(r"^\s*(base|variant)\s+side\s*[:\-]\s*", re.I)


@dataclass(frozen=True)
class TwinRule:
    """Пара близнецов: базовый модуль, вариант с маркером в имени и правило выбора от профилировщика."""

    base: str
    variant: str
    marker: str
    serves: dict[str, str] = field(default_factory=dict)  # модуль -> какие данные обслуживает
    choose_by: str = ""


@dataclass(frozen=True)
class ProjectProfile:
    domain_summary: str = ""
    twins: tuple[TwinRule, ...] = ()
    key: str | None = None  # ключ кеша LLM ответа профилировщика

    def rule_for(self, module: str) -> tuple[TwinRule, str] | None:
        """Правило пары, в которой есть модуль, и второй модуль пары."""
        for t in self.twins:
            if module in (t.base, t.variant) and t.serves.get(module):
                return t, t.variant if module == t.base else t.base
        return None

    def to_dict(self) -> dict[str, Any]:
        return {"version": PROFILE_VERSION, "llm_cache_key": self.key, "domain_summary": self.domain_summary,
                "twins": [{"base": t.base, "variant": t.variant, "marker": t.marker, "serves": t.serves,
                           "choose_by": t.choose_by} for t in self.twins]}


@dataclass
class _Pair:
    base: str
    variant: str
    marker: str
    shared: list[tuple[str, str]]  # (обработчик базы, обработчик варианта)


def twin_pairs(cat: HandlerCatalog, twins: dict[str, list[str]]) -> list[_Pair]:
    """Пары модулей-близнецов из групп близнецов обработчиков; база — модуль без маркера в имени."""
    shared: dict[tuple[str, str], list[tuple[str, str]]] = collections.defaultdict(list)
    for h, others in sorted(twins.items()):
        for o in others:
            a, b = cat.handlers[h].module, cat.handlers[o].module
            if _module_marker(a, b):
                shared[(a, b)].append((h, o))
    out = []
    for (a, b), hs in sorted(shared.items()):
        out.append(_Pair(a, b, _module_marker(a, b) or "", hs))
    return out


def _readme(root: Path) -> str:
    """Начало README без картинок, HTML и блоков кода."""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = root / name
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            text = re.sub(r"```.*?```", " ", text, flags=re.S)
            lines = [ln.strip() for ln in text.splitlines()]
            lines = [ln for ln in lines if ln and not re.match(r"^(!\[|<img|<|\[!\[)", ln)]
            return "\n".join(lines)[:README_CHARS]
    return ""


def _ui_lines(pair: _Pair, cat: HandlerCatalog, ui: UICatalog) -> tuple[list[str], list[UIRequest], set[str]]:
    """Действия UI, которые шлют запрос в сторону пары: по действию — его запросы к обеим сторонам с условиями.
    Одинаковые действия в разных файлах — одной строкой. Условие, при котором действие шлёт запрос в обе стороны
    (или обе без условия), — показ всех данных; числа из таких условий возвращаются третьим элементом."""
    mods = {pair.base, pair.variant}
    by_action: dict[tuple[str, tuple[str, ...]], list[str]] = collections.defaultdict(list)
    reqs: list[UIRequest] = []
    all_values: set[str] = set()
    for nid, h in sorted(cat.handlers.items()):
        if h.module not in mods:
            continue
        for r in sorted(h.ui, key=lambda x: x.id):
            group = [r] + ui.siblings(r)
            sent = sorted({(x.verb, x.url, cat.handlers[s].module, " && ".join(x.guards))
                           for x in group for s in x.handlers if s in cat.handlers and cat.handlers[s].module in mods})
            if len({m for _, _, m, _ in sent}) < 2 and not r.guards:
                continue
            sides: dict[str, set[str]] = collections.defaultdict(set)
            for _, _, m, g in sent:
                sides[g].add(m)
            both = {g for g, ms in sides.items() if len(ms) == 2}
            for g in both:
                all_values |= set(re.findall(r"==\s*(\d+)\b", g))
            variants = tuple(f"{v} {u} -> {m}" + (f" when {g}" if g else "")
                             + (" (both sides: all of the data)" if g in both else "") for v, u, m, g in sent)
            files = by_action[(r.function, variants)]
            if Path(r.file).name not in files:
                files.append(Path(r.file).name)
            reqs.append(r)
    lines = []
    for (func, variants), files in sorted(by_action.items(), key=lambda kv: (kv[1], kv[0])):
        lines.append(f"- {', '.join(files)}, action {func} sends:\n" + "\n".join(f"    {v}" for v in variants))
    return lines[:UI_LINES], reqs, all_values


def _value_lines(root: Path, reqs: list[UIRequest], skip_values: set[str]) -> list[str]:
    """Строки UI-кода, где заданы значения из условий: присваивания переменных, которые условие сравнивает со
    строкой или числом, и пункты списков выбора (`{text: ..., value: N}`) с теми же числами. Числа из условий показа
    всех данных (`skip_values`) пропускаются."""
    out: list[str] = []
    for r in reqs:
        if not r.guards:
            continue
        cond = " ".join(r.guards)
        names = {w.split(".")[-1] for w in re.findall(r"([A-Za-z_$][\w$.]*)\s*[!=]==?\s*(?:'|\"|\d)", cond)}
        names -= _JS_WORDS
        values = set(re.findall(r"==\s*(\d+)\b", cond)) - skip_values
        try:
            src = (root / r.file).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        pats = [re.compile(rf"\b{re.escape(n)}\s*=(?!=)") for n in sorted(names)]
        pats += [re.compile(rf"\bvalue\s*:\s*{v}\b") for v in sorted(values)]
        for i, ln in enumerate(src, 1):
            if any(p.search(ln) for p in pats):
                s = f"- {Path(r.file).name}:{i}: {ln.strip()[:160]}"
                if s not in out:
                    out.append(s)
    return out[:VALUE_LINES]


def _module_calls(ix: SkeletonIndex, mods: set[str]) -> dict[str, set[str]]:
    """Удалённые вызовы между модулями из `mods` по рёбрам `remote_call` скелета."""

    def module(nid: str) -> str | None:
        return (ix.N.get(nid) or {}).get("module") or (nid.split(":")[1] if nid.count(":") >= 2 else None)

    calls: dict[str, set[str]] = collections.defaultdict(set)
    for e in ix.sk.get("edges") or []:
        if e.get("type") != "remote_call":
            continue
        a, b = module(e.get("source", "")), module(e.get("target", ""))
        if a != b and a in mods and b in mods:
            calls[a].add(b)
    return calls


def same_split(ix: SkeletonIndex, pairs: list[_Pair]) -> list[list[int]]:
    """Группы пар (номера с 1), которые делят данные одинаково: база одной пары вызывает базу другой, вариант —
    вариант, и накрест вызовов нет. Сервис работает с той же частью данных, что и сервисы, которые он вызывает."""
    calls = _module_calls(ix, {m for p in pairs for m in (p.base, p.variant)})
    parent = list(range(len(pairs)))

    def find(i: int) -> int:
        while parent[i] != i:
            i = parent[i]
        return i

    for i, a in enumerate(pairs):
        for j, b in enumerate(pairs):
            if i == j:
                continue
            straight = b.base in calls[a.base] and b.variant in calls[a.variant]
            cross = b.variant in calls[a.base] or b.base in calls[a.variant]
            if straight and not cross:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = collections.defaultdict(list)
    for i in range(len(pairs)):
        groups[find(i)].append(i + 1)
    return [g for g in groups.values() if len(g) > 1]


def profile_messages(ix: SkeletonIndex, root: Path, cat: HandlerCatalog, ui: UICatalog,
                     pairs: list[_Pair]) -> list[dict[str, str]]:
    ctx = ix.sk.get("context") or {}
    modules = sorted(n["name"] for n in ix.N.values() if n.get("kind") == "module" and n.get("name"))
    parts = [f"Project README (beginning):\n{_readme(root) or 'none'}\n"]
    if ctx:
        parts.append("Context of the scenarios (from the benchmark authors):\n"
                     + "\n".join(f"- {k}: {v}" for k, v in ctx.items()) + "\n")
    parts.append(f"Java microservices ({len(modules)}): {', '.join(modules)}\n")
    if pairs:
        parts.append("Twin services: pairs of microservices that serve the same REST API; their names differ by one "
                     "token (the marker). Each side keeps its own part of the data. A UI action sends its request to "
                     "one side or the other depending on a condition; an action that shows all of the data sends both "
                     "requests (both sides listed under the same condition or without one), and such an option is not "
                     "a part of the data itself.\n")
        for i, p in enumerate(pairs, 1):
            ex = "; ".join(f"{' '.join(cat.handlers[a].routes[0])} ~ {' '.join(cat.handlers[b].routes[0])}"
                           for a, b in p.shared[:2])
            lines, reqs, all_values = _ui_lines(p, cat, ui)
            vals = _value_lines(root, reqs, all_values)
            parts.append(f"Pair {i}: {p.base} / {p.variant} (marker '{p.marker}'; {len(p.shared)} handlers with the "
                         f"same path, e.g. {ex})\n"
                         + "UI requests:\n" + ("\n".join(lines) if lines else "- none") + "\n"
                         + "UI code with the values these conditions compare:\n" + ("\n".join(vals) if vals else "- none")
                         + "\n")
        calls = _module_calls(ix, {m for p in pairs for m in (p.base, p.variant)})
        if calls:
            parts.append("Remote calls between twin services (from the code):\n"
                         + "\n".join(f"- {a} calls {', '.join(sorted(bs))}" for a, bs in sorted(calls.items())) + "\n")
        for g in same_split(ix, pairs):
            parts.append(f"Pairs {', '.join(map(str, g))} split the data the same way: in the calls above the base side "
                         "of one pair calls the base side of another, and the variant side calls the variant side.\n")
    parts.append(TASK)
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(parts)}]


def profile_schema(pairs: list[_Pair]) -> dict[str, Any]:
    props = {}
    for i, p in enumerate(pairs, 1):
        keys = [p.base, p.variant, "choose_by"]
        props[f"pair_{i}"] = {
            "type": "object",
            "properties": {p.base: {"type": "string", "maxLength": 300}, p.variant: {"type": "string", "maxLength": 300},
                           "choose_by": {"type": "string", "maxLength": 300}},
            "required": keys, "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": {
            "analysis": {"type": "string", "maxLength": 1200},
            "domain_summary": {"type": "string", "maxLength": 400},
            "twins": {"type": "object", "properties": props, "required": list(props), "additionalProperties": False},
        },
        "required": ["analysis", "domain_summary", "twins"],
        "additionalProperties": False,
    }


def build_profile(ix: SkeletonIndex, targets_root: str | Path, cat: HandlerCatalog, ui: UICatalog,
                  twins: dict[str, list[str]], llm: Any) -> ProjectProfile:
    """Профиль из ответа LLM (кеш или сервер); без ответа — пустой профиль с парами близнецов без правил."""
    root = Path(targets_root)
    pairs = twin_pairs(cat, twins)
    empty = ProjectProfile(twins=tuple(TwinRule(p.base, p.variant, p.marker) for p in pairs))
    if llm is None:
        return empty
    msgs = profile_messages(ix, root, cat, ui, pairs)
    resp, key = llm.complete_json("profile", PROFILE_VERSION, msgs, profile_schema(pairs), max_tokens=MAX_TOKENS)
    if not isinstance(resp, dict):
        return ProjectProfile(twins=empty.twins, key=key)
    got = resp.get("twins") or {}
    rules = []
    for i, p in enumerate(pairs, 1):
        g = got.get(f"pair_{i}") or {}
        rules.append(TwinRule(p.base, p.variant, p.marker,
                              {m: _SIDE.sub("", str(g.get(m) or "")).strip() for m in (p.base, p.variant)},
                              str(g.get("choose_by") or "").strip()))
    return ProjectProfile(str(resp.get("domain_summary") or "").strip(), tuple(rules), key)
