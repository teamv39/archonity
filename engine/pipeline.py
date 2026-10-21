"""Конвейер Archonity (ADR-005): M1 заземляет шаг, M4 исполняет его по IR, затем правило Spring Security и
проекция M5. Рёбра шагов объединяются в ответ сценария."""
from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Any

from engine.adapters.skeleton import SkeletonIndex, default_db_dump, load_json
from engine.adapters.submission import SubmissionAdapter
from engine.decisions import DecisionLedger
from engine.evidence import EvidenceLogger
from engine.executor.step import StepExecutor
from engine.grounding.grounder import StepGrounder
from engine.projection import project_constructors
from engine.rules import RuntimeRules
from engine.spring_security import apply_spring_security

ROOT = Path(__file__).resolve().parent.parent
LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass
class ScenarioContext:
    """Пассажир сценария для M4: имя из контекста задачи. ID учётной записи M4 берёт из ответа шага входа, как UI
    (`StepExecutor._logged_in_user`)."""
    user_name: str | None = None
    scenario_id: str = "S?"


def resolve_passenger_context(context: dict[str, Any] | None, scenario_id: str = "S?") -> ScenarioContext:
    """Пассажир из контекста задачи («pre-registered user <имя>»). Нет его — предупреждение: имя при входе неизвестно,
    если сценарий не регистрирует своего."""
    user_name = (context or {}).get("user_name")
    if not user_name:
        LOGGER.warning("контекст задачи не называет пассажира (pre-registered user): имя при входе неизвестно")
    return ScenarioContext(user_name=user_name, scenario_id=scenario_id)


@dataclasses.dataclass
class PipelineConfig:
    """Конфигурация конвейера: входные артефакты, режимы правил M4/M5 и опции M1."""
    db_dump_path: str | Path | None = None
    db_state: Any = None
    entity_ir_path: str | Path | None = None
    method_ir_dir: str | Path | None = None
    rules: RuntimeRules = dataclasses.field(default_factory=RuntimeRules)
    m1_options: dict[str, Any] | None = None


class ArchonityPipeline:
    """Оркестратор: заземление и исполнение шагов, сборка ответа по сценариям."""

    def __init__(
        self,
        skeleton_path: str | Path,
        targets_root: str | Path,
        config: PipelineConfig | None = None,
        **kwargs: Any,
    ) -> None:
        """`kwargs` — поля `PipelineConfig` и режимы `RuntimeRules` (constructors=..., unbound_handlers=...)."""
        cfg = dataclasses.replace(config) if config is not None else PipelineConfig()
        rule_names = {f.name for f in dataclasses.fields(RuntimeRules)}
        cfg_names = {f.name for f in dataclasses.fields(PipelineConfig)}
        unknown = sorted(set(kwargs) - rule_names - cfg_names)
        if unknown:
            raise TypeError(f"ArchonityPipeline: неизвестные параметры {unknown}")
        cfg = dataclasses.replace(cfg, **{k: v for k, v in kwargs.items() if k in cfg_names})
        cfg.rules = dataclasses.replace(cfg.rules, **{k: v for k, v in kwargs.items() if k in rule_names})
        self.config = cfg
        self.rules = cfg.rules

        self.skeleton_path = Path(skeleton_path)
        self.targets_root = Path(targets_root)
        self.index = SkeletonIndex(
            load_json(self.skeleton_path),
            db_dump_path=cfg.db_dump_path or (default_db_dump(self.skeleton_path) if cfg.db_state is None else None),
            db_state=cfg.db_state,
            entity_ir_path=cfg.entity_ir_path,
        )
        self.evidence_logger = EvidenceLogger(self.index, targets_root=self.targets_root)
        self.ledger = DecisionLedger()
        self.step_requests: dict[str, list[dict[str, Any]]] = {}

        self.m1 = StepGrounder(self.index, self.targets_root, **(cfg.m1_options or {}))
        ir_dir = Path(cfg.method_ir_dir) if cfg.method_ir_dir else ROOT / "data" / "ir"
        self.m4 = StepExecutor(self.index, self.rules, ir_dir, self.targets_root)

    def run_scenario(
        self, scenario_dict: dict[str, Any],
    ) -> tuple[set[str], set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
        """Сценарий шаг за шагом: заземление M1, исполнение M4, правило Spring Security, проекция M5."""
        sid = scenario_dict.get("id", "S?")
        self.ledger.begin_scenario(sid)
        passenger = resolve_passenger_context(self.index.context, scenario_id=sid)

        all_methods: set[str] = set()
        all_calls: set[tuple[str, str]] = set()
        all_remote: set[tuple[str, str]] = set()
        all_data: set[tuple[str, str]] = set()

        session = self.m1.begin(scenario_dict)
        self.step_requests[sid] = []
        self.m4.begin_scenario(sid)

        for st in scenario_dict.get("steps") or []:
            self.ledger.begin_step(st.get("n"))
            step_req = session.ground(st)
            # R20: обработчик, который Spring вызвать не может, — шаг через рабочий обработчик того же
            # контроллера. Замена после заземления: история шагов в промпте M1 и кеш LLM не меняются.
            if self.rules.unbound_handlers == "rebind":
                step_req = self.m1.rebind(step_req) or step_req
            self.step_requests[sid].append(step_req.to_dict())

            m, c, r, d = self.m4.run_step(step_req, passenger, ledger=self.ledger)
            apply_spring_security(self.index, m, c, d, self.ledger)
            # M5: конструктор в ответе, только если из него исполнился вызов проекта (R7, ADR-006)
            project_constructors(m, c, r, d, self.rules.constructors, self.ledger)
            all_methods |= m
            all_calls |= c
            all_remote |= r
            all_data |= d

        r19 = {s for s, _ in all_calls | all_remote | all_data} | {t for _, t in all_calls | all_remote}
        self.ledger.begin_step(None)
        for m in sorted(r19 - all_methods):
            self.ledger.execute(m, "DEFAULT_RULE", "R19")
        all_methods |= r19

        return all_methods, all_calls, all_remote, all_data

    def run_all(
        self,
        scenario_paths: list[str | Path],
        output_path: str | Path,
    ) -> SubmissionAdapter:
        """Прогон по списку сценариев и экспорт submission.json."""
        adapter = SubmissionAdapter(
            project=self.index.project,
            evidence_logger=self.evidence_logger,
        )

        for sp in sorted(scenario_paths, key=lambda p: str(p)):
            s_dict = load_json(sp)
            sid = s_dict["id"]
            methods, calls, remote, data = self.run_scenario(s_dict)
            adapter.add_scenario_edges(
                scenario_id=sid,
                methods=methods,
                calls=calls,
                remote=remote,
                data=data,
            )

        adapter.save(output_path)
        return adapter
