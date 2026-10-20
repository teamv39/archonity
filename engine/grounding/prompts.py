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
# Режимы промпта (ADR-007): v8 — общий шаблон, домен и правила близнецов из профиля проекта; v7 — до ADR-007, откат
PROMPT_MODES = ("v8", "v7")
PROMPT_VERSIONS = {"v8": "m1-v8", "v7": PROMPT_VERSION}
CAND_SRC_LINES = 6

# Режим v7: тексты до ADR-007, с доменом Train Ticket. Оставлены для отката (`--m1-prompt v7`, кеш m1-v7)
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

# Режим v8 (ADR-007): без слов домена. Домен, правила близнецов — из профиля проекта (engine/grounding/profile.py),
# окружение — из `context` скелета, модуль UI — из `find_ui_dir`
SYSTEM_V8 = """You map steps of a user scenario in a web application to backend REST requests.
{domain}The backend is a set of Java microservices behind a gateway; a browser UI ({ui}) sends the requests.{environment}

Rules:
- Every scenario step sends exactly one HTTP request through the gateway. Pick the one backend handler that serves it, even when the web UI would send several requests or none for that action.
{twins}- When a UI variant is sent only under a condition, check the condition against the scenario.
- A request that the web UI sends only in the response handler of another request is the UI's follow-up to that request. A step maps to the first request even when the scenario tells what happens after it; pick the follow-up only when the step asks for the follow-up action by itself.
- Prefer a handler that the web UI calls for this kind of action (candidates show their UI page and action). Handlers without UI are mostly internal APIs that other services call; choose one only when no UI handler does what the step asks.
{admin}- A step that the system refuses still sends its request: pick the handler that refuses it.

Enum codes used in request fields:
{enums}
"""

TWINS_V8 = """- Some services come in twins: the same API in two services, each keeping its own part of the data. First pick the handler that does what the step asks; then, if that handler has a twin (its card says so), choose the side as the card says, by the data the step works with.
"""

SELECT_TASK_V8 = """Current step {n}: {action}

Candidate handlers (closest search matches):
{candidates}

Answer with JSON: a short reasoning (one or two sentences), the label of the chosen handler (a candidate, or a handler from the index when no candidate fits), whether the system serves the step ('success') or refuses it ('refused', only if the step says so), and refs — which results of earlier steps this request uses (e.g. "trip": "first_of_step_2" for the first trip found at step 2, "order": "new_of_step_6" for the order created at step 6). Each key names the kind of what the referenced step found or created, not of what this request makes. A record that the request reads or changes comes from the step that found or created that record itself, not from the step of a record it belongs to. Leave refs empty when the request uses nothing from earlier steps."""
# Пример refs — с видами ссылок v7 (`REF_ENTITIES`): виды меняет фаза B2 ADR-007 вместе с этим примером

PARAMS_TASK_V8 = """Current step {n}: {action}
Chosen request: {verb} {path} -> {signature}

Request fields (Java type):
{fields}
{ui_hints}
Fill only the fields whose value follows from the step text or the scenario description: the options and extras the step chooses, amounts and quantities, query filters and date ranges, names, numbers and dates of new entities. Do not make up values that the text does not give, such as user names, passwords or codes: they are null. When the step does not take an option ('without ...', 'no ...', or the same choice as an earlier step that did not take it), the fields that the web UI sends only for that option keep their default, and coded fields get the enum code for none. Fields that an edit does not change are null. Use enum codes from the reference for coded fields. Use null for identifiers and for anything taken from results of earlier steps, and for everything the text does not determine."""


def enum_reference(enums: dict[str, list[str]]) -> str:
    return "\n".join(f"- {name}: {', '.join(consts)}" for name, consts in sorted(enums.items()))


def system_prompt(enums: dict[str, list[str]], index: str | None = None) -> str:
    """Индекс обработчиков нужен только вызову выбора; вызову параметров он лишний и отвлекает."""
    text = SYSTEM.format(enums=enum_reference(enums))
    return text + INDEX.format(index=index) if index else text


def has_twin_rules(profile: Any) -> bool:
    """Есть ли в профиле пара близнецов с правилом. Сами правила идут не в системный промпт, а в карточку
    кандидата-близнеца (`twin_note`): список пар в системном промпте модель брала как правило выбора сервиса
    («G/D → базовый сервис заказов») и выбирала по нему обработчик без UI."""
    return any(t.serves.get(t.base) and t.serves.get(t.variant) and t.choose_by for t in getattr(profile, "twins", ()))


def system_prompt_v8(enums: dict[str, list[str]], profile: Any, ui_dir: str | None, environment: str | None,
                     admin: bool, index: str | None = None) -> str:
    """Системный промпт v8: домен из профиля, окружение из `context` скелета, правило админки — если в проекте
    есть модули админки."""
    summary = (getattr(profile, "domain_summary", "") or "").strip()
    text = SYSTEM_V8.format(
        domain=f"The application: {summary}\n" if summary else "",
        ui=ui_dir or "web UI",
        environment=f"\nEnvironment: {environment.strip()}" if environment else "",
        twins=TWINS_V8 if has_twin_rules(profile) else "",
        admin="- Administrator steps (admin console) use admin services; other users' steps do not.\n" if admin else "",
        enums=enum_reference(enums),
    )
    return text + INDEX.format(index=index) if index else text


def twin_note(profile: Any, module: str) -> str | None:
    """Строка карточки кандидата-близнеца (v8): что обслуживает этот модуль и его близнец, по профилю."""
    got = profile.rule_for(module) if profile is not None else None
    if got is None:
        return None
    t, other = got
    side = "base" if module == t.base else "variant"
    return f"twin of {other}; this {side} side: {t.serves[module].rstrip('.')}; choose the side by: {t.choose_by}"


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


RESPONSE_OF = "in the response handler of "
# Проверка кода статуса в обработчике ответа UI: `result["status"] == 2`, `res.status === 2`
STATUS_TEST = re.compile(r"""\w+(?:\[["']status["']\]|\.status)\s*===?\s*(-?\d+)""")


def followup_notes(ui: list[tuple[UIRequest, list[UIRequest]]], answers: Any) -> list[str]:
    """Режим v8: запрос, который UI шлёт из обработчика ответа другого запроса по коду статуса, — и что этот код
    значит в исходнике первого запроса. `answers(verb, url)` → {код: сообщения} (`HandlerCatalog.answers`)."""
    notes: list[str] = []
    for r, sib in ui:
        for x in [r] + sib:
            first = next((g[len(RESPONSE_OF):] for g in x.guards if g.startswith(RESPONSE_OF)), None)
            if not first or " " not in first:
                continue
            got = answers(*first.split(" ", 1))

            def statuses(neg: bool) -> str:
                codes = [int(m.group(1)) for g in x.guards if g.startswith("!(") == neg
                         for m in [STATUS_TEST.search(g)] if m]
                return ", ".join(f"status {c} (" + "; ".join(f"'{m}'" for m in got[c][:3]) + ")"
                                 for c in dict.fromkeys(codes) if got.get(c))

            when, unless = statuses(False), statuses(True)
            if not when:
                continue
            note = (f"follow-up: the UI sends {x.verb} {x.url} by itself, not on a user action: only after {first} "
                    f"answers {when}" + (f", not when it answers {unless}" if unless else "")
                    + f". Otherwise the user's action ends with {first}.")
            if note not in notes:
                notes.append(note)
    return notes


def candidate_block(label: str, h: HandlerInfo, ui: list[tuple[UIRequest, list[UIRequest]]],
                    train_kind: str | None = None, twin: str | None = None, notes: list[str] | None = None,
                    calls: list[str] | None = None) -> str:
    """`train_kind` — строка близнеца v7; `twin`, `notes` (`followup_notes`) и `calls` (`HandlerCatalog.service_calls`)
    — v8."""
    lines = [f"{label}: " + "; ".join(f"{v} {p}" for v, p in h.routes)]
    lines.append(f"    handler {h.signature} in {h.module}")
    if twin:
        lines.append(f"    {twin}")
    elif train_kind:
        lines.append(f"    serves {train_kind} only; its twin serves the other kind")
    if h.body_fields:
        lines.append("    body: " + ", ".join(f["name"] for f in h.body_fields))
    if calls:
        lines.append("    its service code calls: " + ", ".join(calls))
    for r, sib in ui[:2]:
        lines.append("    " + _ui_line(r, sib))
    if not ui:
        lines.append("    UI: none (the web UI never calls it)")
    lines += [f"    {x}" for x in notes or []]
    src = [ln for ln in h.source.splitlines()[1:] if ln not in ("}", "{")][:CAND_SRC_LINES]
    if src:
        lines.append("    code: " + " ".join(src))
    return "\n".join(lines)


def train_kind(module: str) -> str:
    """Режим v7: какие поезда обслуживает модуль из пары близнецов: `other` или цифра в имени — обычные."""
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
                ui: UIRequest | None, template: str = PARAMS_TASK, optional: bool = False) -> str:
    """`optional` (режим v8) — ещё и поля, которые UI шлёт только под условием, сгруппированные по условию."""
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
        groups: dict[str, list[str]] = {}
        for o in ui.body_opt if optional else []:
            if any(o["field"] == f for f, _, _ in fields):
                groups.setdefault(" && ".join(o["guards"]), []).append(o["field"])
        if groups:
            hints += ("Fields the web UI sends only under a condition; when it does not hold, the request leaves them out "
                      "and they keep their Java default (0 for numbers, false for booleans, null otherwise):\n") + "\n".join(
                f"  {', '.join(fs)} when {g}" for g, fs in list(groups.items())[:8]) + "\n"
    return template.format(n=n, action=action, verb=verb, path=path, signature=h.signature, fields=flines,
                           ui_hints=hints)
