"""StepRequest — выход M1, контракт ADR-005."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

OUTCOMES = ("success", "refused")
# Ссылка шага на результат прежнего шага: `<pick>_of_step_<n>`; виды ссылок — из манифеста сущностей (ADR-007)
REF_PICKS = ("first", "second", "new")


@dataclass
class StepRequest:
    scenario: str
    step: int
    action: str
    handler: str
    http: dict[str, str]
    params: dict[str, Any] = field(default_factory=dict)
    expected_outcome: str = "success"
    refs: dict[str, str] = field(default_factory=dict)
    ui_source: dict[str, Any] | None = None
    # Поле тела -> поле записи прежнего шага, из которого UI его берёт (каталог UI, `UIRequest.body_src`)
    body_src: dict[str, str] = field(default_factory=dict)
    # Группы полей тела, которые UI шлёт только под общим условием (каталог UI, `UIRequest.body_groups`):
    # [{"fields": [...], "on": [[поле, значение], ...]}]; `on` — литералы, которые UI ставит, только когда условие верно
    body_groups: list[dict[str, Any]] = field(default_factory=list)
    grounding: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def canon_value(v: Any) -> str | None:
    """Значение параметра шага или литерал UI в одном виде для сравнения: `2`, `2.0` и `"2"` — `"2"`, `true` — `"true"`.
    Умолчание Java (0, false, пустая строка, null) — None: Jackson даст его и тогда, когда поля в запросе нет, поэтому
    о том, слал ли UI поле, оно ничего не говорит."""
    if v is None or v is False or v == "":
        return None
    if v is True:
        return "true"
    if isinstance(v, (int, float)):
        if v == 0:
            return None
        return str(int(v)) if float(v).is_integer() else repr(float(v))
    if isinstance(v, str):
        s = v.strip()
        if s in ("true", "false"):
            return canon_value(s == "true")
        if re.fullmatch(r"-?\d+(\.\d+)?", s):
            return canon_value(float(s))
        return v
    return None


def group_sent(group: dict[str, Any], params: dict[str, Any]) -> bool:
    """Слал ли UI группу полей: в параметрах шага есть поле группы со значением не по умолчанию или литерал, который
    UI ставит только под условием группы. Ничего такого нет — условие ложно (флажок не отмечен, раздел не заполнен)."""
    fields = set(group.get("fields") or ())
    on = {(f, v) for f, v in group.get("on") or ()}
    for name, v in params.items():
        c = canon_value(v)
        if c is not None and (name in fields or (name, c) in on):
            return True
    return False
