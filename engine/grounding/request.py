"""StepRequest — выход M1, контракт ADR-005."""
from __future__ import annotations

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
    grounding: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
