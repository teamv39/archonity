"""Промпты и JSON-схемы M1: вызов 1 — выбор обработчика, вызов 2 — параметры (ADR-005, M1, п. 3).

Порядок частей под кеш префикса llama.cpp: системный промпт (постоянный; у выбора — с индексом всех обработчиков) → сценарий →
история выбранных запросов (растёт) → текущий шаг и кандидаты или поля запроса.
Любая правка текста промпта или схемы — новая `PROMPT_VERSION` (иначе кеш вернёт старые ответы для старого текста,
а новые — пересчитает; версия нужна, чтобы это было явно).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from engine.grounding.docs import SKIP_PARAM_TYPES, HandlerInfo
from engine.grounding.request import OUTCOMES, REF_ENTITIES, REF_PICKS
from engine.grounding.ui_catalog import UIRequest

PROMPT_VERSION = "m1-v7"
CAND_SRC_LINES = 6

SYSTEM = """You map steps of a user scenario in the Train Ticket web application to backend REST requests.
Train Ticket is a set of Java microservices behind a gateway (/api/v1/<service>/...). A browser UI (ts-ui-dashboard) sends the requests.

Rules:
- Every scenario step sends exactly one HTTP request through the gateway. Pick the one backend handler that serves it, even when the web UI would send several requests or none for that action.
- Services come in twins for the two train kinds: high-speed trains (GaoTie/DongChe, trip numbers starting with G or D) and regular trains (the 'Other' type, e.g. K, T, Z). The twin with 'other' or '2' in its service name (ts-travel2-service, ts-order-other-service, ts-preserve-other-service) serves regular trains; the plain one serves high-speed trains. Choose the twin by the train kind of the trip or order the step works with.
- When a UI variant is sent only under a condition, check the condition against the scenario.
- Prefer a handler that the web UI calls for this kind of action (candidates show their UI page and action). Handlers without UI are mostly internal APIs that other services call; choose one only when no UI handler does what the step asks.
- Administrator steps (admin console) use admin services; passenger steps do not.
- A step that the system refuses still sends its request: pick the handler that refuses it.

Enum codes used in request fields:
{enums}
"""

INDEX = """
Handler index. Each step lists candidate handlers: the closest search matches, with details. Search can miss: when no candidate does what the step asks, pick the right handler from this index, which lists every handler (label: route -> Class#method; "ui" marks handlers that the web UI calls).
{index}
"""

SELECT_TASK = """Current step {n}: {action}

Candidate handlers (closest search matches):
{candidates}

Answer with JSON: a short reasoning (one or two sentences), the label of the chosen handler (a candidate, or a handler from the index when no candidate fits), whether the system serves the step ('success') or refuses it ('refused', only if the step says so), and refs — which results of earlier steps this request uses (e.g. "trip": "first_of_step_2" for the first trip found at step 2, "order": "new_of_step_6" for the order created at step 6). Leave refs empty when the request uses nothing from earlier steps."""

PARAMS_TASK = """Current step {n}: {action}
Chosen request: {verb} {path} -> {signature}

Request fields (Java type):
{fields}
{ui_hints}
Fill only the fields whose value follows from the step text or the scenario description: seat class, food, assurance, consignment weight and consignee, query filters and date ranges, names, numbers and dates of new entities. Use enum codes from the reference for coded fields. Use null for identifiers and for anything taken from results of earlier steps, and for everything the text does not determine."""


def enum_reference(enums: dict[str, list[str]]) -> str:
    return "\n".join(f"- {name}: {', '.join(consts)}" for name, consts in sorted(enums.items()))


def system_prompt(enums: dict[str, list[str]], index: str | None = None) -> str:
    """Индекс обработчиков нужен только вызову выбора; вызову параметров он лишний и отвлекает."""
    text = SYSTEM.format(enums=enum_reference(enums))
    return text + INDEX.format(index=index) if index else text


def handler_labels(handlers: dict[str, HandlerInfo]) -> dict[str, str]:
    """Постоянные метки H1..Hn в порядке ID: одни и те же в индексе, в карточках кандидатов и в схеме ответа."""
    return {hid: f"H{i + 1}" for i, hid in enumerate(sorted(handlers))}


def handler_index(handlers: dict[str, HandlerInfo], labels: dict[str, str]) -> str:
    """Все обработчики, по строке на каждый: кандидаты поиска — подсказка, а не граница выбора."""
    return "\n".join(
        f"{labels[hid]}: " + "; ".join(f"{v} {p}" for v, p in h.routes) + f" -> {h.cls}#{h.name}"
        + (" (ui)" if h.ui else "")
        for hid, h in sorted(handlers.items()))


def scenario_block(sc: dict[str, Any]) -> str:
    steps = "\n".join(f"{s['n']}. {s['action']}" for s in sc.get("steps") or [])
    return (f"Scenario {sc.get('id')}: {sc.get('title', '')}\n"
            f"Description: {sc.get('description', '')}\n"
            f"Steps:\n{steps}\n")


def history_block(history: list[str]) -> str:
    if not history:
        return "Requests of earlier steps: none yet.\n"
    return "Requests of earlier steps:\n" + "\n".join(history) + "\n"


def history_line(n: int, verb: str, path: str, h: HandlerInfo, outcome: str) -> str:
    return f"step {n}: {verb} {path} -> {h.cls}#{h.name} [{h.module}] ({outcome})"


def _ui_line(r: UIRequest, siblings: list[UIRequest]) -> str:
    page = ", ".join(Path(p).stem for p in r.pages) or Path(r.file).stem
    s = f"UI: page {page}, action {r.function}"
    if r.labels:
        s += " [" + ", ".join(f'"{x}"' for x in r.labels[:3]) + "]"
    if r.guards:
        s += "; sent only when: " + " && ".join(r.guards)
    others = [x for x in siblings if x.url != r.url]
    if others:
        s += "; the same UI action also sends: " + ", ".join(
            f"{x.verb} {x.url}" + (f" (when {' && '.join(x.guards)})" if x.guards else "") for x in others[:3])
    return s


def candidate_block(label: str, h: HandlerInfo, ui: list[tuple[UIRequest, list[UIRequest]]],
                    train_kind: str | None = None) -> str:
    lines = [f"{label}: " + "; ".join(f"{v} {p}" for v, p in h.routes)]
    lines.append(f"    handler {h.signature} in {h.module}")
    if train_kind:
        lines.append(f"    serves {train_kind} only; its twin serves the other kind")
    if h.body_fields:
        lines.append("    body: " + ", ".join(f["name"] for f in h.body_fields))
    for r, sib in ui[:2]:
        lines.append("    " + _ui_line(r, sib))
    if not ui:
        lines.append("    UI: none (the web UI never calls it)")
    src = [ln for ln in h.source.splitlines()[1:] if ln not in ("}", "{")][:CAND_SRC_LINES]
    if src:
        lines.append("    code: " + " ".join(src))
    return "\n".join(lines)


def train_kind(module: str) -> str:
    """Какие поезда обслуживает модуль из пары близнецов: `other` или цифра в имени — обычные."""
    core = module.removeprefix("ts-").removesuffix("-service")
    if re.search(r"other|\d", core):
        return "regular trains (the 'Other' type, not G/D)"
    return "high-speed trains (GaoTie/DongChe, G/D)"


def select_schema(labels: list[str], step: int) -> dict[str, Any]:
    ref_values = [f"{p}_of_step_{i}" for i in range(1, step) for p in REF_PICKS]
    ref_props = {e: {"type": "string", "enum": ref_values} for e in REF_ENTITIES} if ref_values else {}
    return {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string", "maxLength": 400},
            "handler": {"type": "string", "enum": labels},
            "expected_outcome": {"type": "string", "enum": list(OUTCOMES)},
            "refs": {"type": "object", "properties": ref_props, "additionalProperties": False},
        },
        "required": ["reasoning", "handler", "expected_outcome", "refs"],
        "additionalProperties": False,
    }


JSON_TYPES = {
    "int": "integer", "Integer": "integer", "long": "integer", "Long": "integer", "short": "integer",
    "double": "number", "Double": "number", "float": "number", "Float": "number", "BigDecimal": "number",
    "boolean": "boolean", "Boolean": "boolean",
}


def request_fields(h: HandlerInfo) -> list[tuple[str, str, str]]:
    """Поля, которые может заполнить LLM: (имя, источник, Java-тип). Заголовки и служебные параметры не берём."""
    out = [(f["name"], "body", f["type"]) for f in h.body_fields]
    names = {n for n, _, _ in out}
    for p in h.params:
        if p["source"] in ("path", "query") and p["type_raw"] not in SKIP_PARAM_TYPES and p["name"] not in names:
            out.append((p["name"], p["source"], p["type_raw"]))
    return out


def needs_params(h: HandlerInfo) -> bool:
    """Вызов 2 нужен, если у запроса есть тело или query-параметры; path-переменные берутся из refs."""
    return any(src in ("body", "query") for _, src, _ in request_fields(h))


def params_schema(fields: list[tuple[str, str, str]]) -> dict[str, Any]:
    props = {}
    for name, _, jt in fields:
        t = JSON_TYPES.get(jt.split("<")[0], "string")
        props[name] = {"type": [t, "null"]}
    return {"type": "object", "properties": props, "required": [n for n, _, _ in fields], "additionalProperties": False}


def params_task(n: int, action: str, verb: str, path: str, h: HandlerInfo, fields: list[tuple[str, str, str]],
                ui: UIRequest | None) -> str:
    flines = "\n".join(f"  {name} ({src}): {jt}" for name, src, jt in fields)
    hints = ""
    if ui is not None:
        consts = {k: v for k, v in ui.body_consts.items() if any(k == f for f, _, _ in fields)}
        if consts:
            hints += "Values the web UI always sends: " + ", ".join(f"{k}={v!r}" for k, v in consts.items()) + "\n"
        cond = [c for c in ui.body_cond if any(c["field"] == f for f, _, _ in fields)]
        if cond:
            hints += "Values the web UI sends under conditions:\n" + "\n".join(
                f"  {c['field']}={c['value']!r} when {' && '.join(c['guards']) or 'always'}" for c in cond[:12]) + "\n"
    return PARAMS_TASK.format(n=n, action=action, verb=verb, path=path, signature=h.signature, fields=flines,
                              ui_hints=hints)
