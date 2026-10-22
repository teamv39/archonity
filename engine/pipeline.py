"""Конвейер Archonity (ADR-005): M1 заземляет шаг, M4 исполняет его по IR, затем правило Spring Security и
проекция M5. Рёбра шагов объединяются в ответ сценария."""
from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Any

from engine import attention
from engine.adapters.skeleton import SkeletonIndex, default_db_dump, load_json
from engine.adapters.submission import SubmissionAdapter
from engine.artifacts import DEFAULT_ARTIFACTS_DIR, check_artifacts
from engine.decisions import DecisionLedger
from engine.evidence import EvidenceLogger
from engine.executor.step import StepExecutor
from engine.grounding.grounder import StepGrounder
from engine.manifest import camel_to_snake
from engine.projection import project_constructors
from engine.rules import RuntimeRules
from engine.spring_security import apply_spring_security

LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass
class ScenarioContext:
    """Пассажир сценария для M4 до шага входа: имя и ID учётной записи. После входа M4 берёт ID из ответа шага
    входа, как UI (`StepExecutor._logged_in_user`)."""
    user_name: str | None = None
    account_id: str | None = None
    scenario_id: str = "S?"


def resolve_passenger_context(index: SkeletonIndex, scenario_id: str = "S?") -> ScenarioContext:
    """Пассажир из контекста задачи («pre-registered user <имя>»); ID — поле `@Id` сущности Spring Security
    (`implements UserDetails`) в строке её таблицы дампа, где есть это имя. Нет пассажира в контексте —
    предупреждение: имя при входе неизвестно, если сценарий не регистрирует своего."""
    user_name = index.context.get("user_name")
    if not user_name:
        LOGGER.warning("контекст задачи не называет пассажира (pre-registered user): имя при входе неизвестно")
        return ScenarioContext(scenario_id=scenario_id)
    return ScenarioContext(user_name=user_name, account_id=_principal_id(index, user_name), scenario_id=scenario_id)


def _principal_id(index: SkeletonIndex, user_name: str) -> str | None:
    """ID пользователя `user_name` по таблице сущности `UserDetails` (та же сущность, что у правила Spring Security)."""
    for _, n in sorted(index.type_nodes.items()):
        if "UserDetails" not in (n.get("implements_raw") or []):
            continue
        ent = index.entities.entities.get(n.get("fqn", ""))
        if ent is None or not ent.table or not ent.id_field:
            continue
        col = camel_to_snake(ent.id_field)
        for row in index.db_state.get_table(ent.table):
            if user_name in row.values() and row.get(col) is not None:
                return row[col]
    return None


@dataclasses.dataclass
class PipelineConfig:
    """Конфигурация конвейера: входные артефакты, режимы правил M4/M5 и опции M1.

    `artifacts_dir` — папка артефактов проекта (`ir/`, `entity_ir.json`, `ui_catalog.json`), по умолчанию `data/`;
    `entity_ir_path` и `method_ir_dir` переопределяют отдельные пути."""
    db_dump_path: str | Path | None = None
    db_state: Any = None
    artifacts_dir: str | Path | None = None
    entity_ir_path: str | Path | None = None
    method_ir_dir: str | Path | None = None
    rules: RuntimeRules = dataclasses.field(default_factory=RuntimeRules)
    m1_options: dict[str, Any] | None = None
    # False — M4 в Python не нужен (`--engine rust`, ADR-008): исполнение делает `archonity-exec`
    build_m4: bool = True


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
        artifacts = Path(cfg.artifacts_dir) if cfg.artifacts_dir else DEFAULT_ARTIFACTS_DIR
        ir_dir = Path(cfg.method_ir_dir) if cfg.method_ir_dir else artifacts / "ir"
        self.index = SkeletonIndex(
            load_json(self.skeleton_path),
            db_dump_path=cfg.db_dump_path or (default_db_dump(self.skeleton_path) if cfg.db_state is None else None),
            db_state=cfg.db_state,
            entity_ir_path=cfg.entity_ir_path or artifacts / "entity_ir.json",
        )
        # IR и entity_ir.json построены по одному проекту: чужие факты не берём молча (ArtifactMismatch)
        check_artifacts(self.index, ir_dir, self.skeleton_path, self.targets_root, artifacts)
        self.evidence_logger = EvidenceLogger(self.index, targets_root=self.targets_root)
        self.ledger = DecisionLedger()
        self.step_requests: dict[str, list[dict[str, Any]]] = {}
        # Р2: исключение на шаге или в сценарии не роняет прогон, а пишется сюда (engine/attention.py)
        self.failures: list[dict[str, Any]] = []

        self.m1 = StepGrounder(self.index, self.targets_root, ir_dir=ir_dir, ui_cache=artifacts / "ui_catalog.json",
                               **(cfg.m1_options or {}))
        self.ir_dir = ir_dir
        self.m4 = StepExecutor(self.index, self.rules, ir_dir, self.targets_root) if cfg.build_m4 else None

    def enable_m4(self) -> None:
        """Откат `--engine rust` на Python: конвейер собран без M4, а `archonity-exec` не отработал."""
        if self.m4 is None:
            self.m4 = StepExecutor(self.index, self.rules, self.ir_dir, self.targets_root)

    def run_scenario(
        self, scenario_dict: dict[str, Any],
    ) -> tuple[set[str], set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
        """Сценарий шаг за шагом: заземление M1, исполнение M4, правило Spring Security, проекция M5."""
        sid = scenario_dict.get("id", "S?")
        self.ledger.begin_scenario(sid)
        passenger = resolve_passenger_context(self.index, scenario_id=sid)

        all_methods: set[str] = set()
        all_calls: set[tuple[str, str]] = set()
        all_remote: set[tuple[str, str]] = set()
        all_data: set[tuple[str, str]] = set()

        session = self.m1.begin(scenario_dict)
        self.step_requests[sid] = []
        self.m4.begin_scenario(sid)

        for st in scenario_dict.get("steps") or []:
            self.ledger.begin_step(st.get("n"))
            stage = "M1"
            try:
                step_req = session.ground(st)
                # R20: обработчик, который Spring вызвать не может, — шаг через рабочий обработчик того же
                # контроллера. Замена после заземления: история шагов в промпте M1 и кеш LLM не меняются.
                if self.rules.unbound_handlers == "rebind":
                    step_req = self.m1.rebind(step_req) or step_req
                self.step_requests[sid].append(step_req.to_dict())

                stage = "M4"
                m, c, r, d = self.m4.run_step(step_req, passenger, ledger=self.ledger)
                stage = "M5"
                apply_spring_security(self.index, m, c, d, self.ledger)
                # M5: конструктор в ответе, только если из него исполнился вызов проекта (R7, ADR-006)
                project_constructors(m, c, r, d, self.rules.constructors, self.ledger)
            except Exception as e:  # noqa: BLE001 — Р2: шаг со сбоем не даёт рёбер, остальные шаги идут дальше
                self._fail(sid, st.get("n"), stage, e)
                continue
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

    def ground_all(self, scenario_paths: list[str | Path]) -> dict[str, list[dict[str, Any]]]:
        """Режим `--engine rust` (ADR-008): только M1. Шаги каждого сценария до R20 (`StepRequest.to_dict`) —
        вход `archonity-exec`; исполнение, правила и запись выдачи делает он. Шаг со сбоем M1 пропускается (Р2),
        сценарий со сбоем даёт пустой список шагов, а значит пустой блок в ответе."""
        raw: dict[str, list[dict[str, Any]]] = {}
        for sp in sorted(scenario_paths, key=lambda p: str(p)):
            sid = Path(sp).stem
            try:
                s_dict = load_json(sp)
                sid = s_dict["id"]
                session = self.m1.begin(s_dict)
                raw[sid] = []
                for st in s_dict.get("steps") or []:
                    try:
                        raw[sid].append(session.ground(st).to_dict())
                    except Exception as e:  # noqa: BLE001 — Р2: шаг без заземления не даёт рёбер, остальные идут дальше
                        self._fail(sid, st.get("n"), "M1", e)
            except Exception as e:  # noqa: BLE001 — Р2: пустой блок сценария
                self._fail(sid, None, "сценарий", e)
                raw.setdefault(sid, [])
        self.step_requests = {sid: list(reqs) for sid, reqs in raw.items()}
        return raw

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

        paths = sorted(scenario_paths, key=lambda p: str(p))
        self._prepare_m1(paths)
        for sp in paths:
            sid = Path(sp).stem
            try:
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
            except Exception as e:  # noqa: BLE001 — Р2: блок сценария со сбоем пустой, остальные сценарии идут дальше
                self._fail(sid, None, "сценарий", e)
                # Пустой блок лучше отсутствующего: вид рёбер, которого нет и в эталоне, даёт 1 (README организаторов)
                adapter.scenarios.setdefault(sid, [])

        adapter.save(output_path)
        return adapter

    def _prepare_m1(self, paths: list[str | Path]) -> None:
        """Векторы шагов всех сценариев до первого вызова LLM: эмбеддер и `llama server` не бывают в памяти вместе.

        Нечитаемый сценарий пропускается, его сбой запишет цикл `run_all`. Сбой модели эмбеддера сюда не доходит:
        он отключает dense (Р2), прогон идёт на одном BM25."""
        scenarios = []
        for sp in paths:
            try:
                scenarios.append(load_json(sp))
            except Exception:  # noqa: BLE001
                continue
        try:
            self.m1.prepare(scenarios)
        except Exception as e:  # noqa: BLE001 — Р2: шаги заземлятся без заготовленных векторов
            self._fail(None, None, "векторы шагов M1", e)

    def _fail(self, sid: str | None, step: Any, stage: str, exc: Exception) -> None:
        f = attention.failure(sid, step, stage, exc)
        self.failures.append(f)
        LOGGER.error("сбой %s, шаг %s (%s): %s", sid, step, stage, f["error"], exc_info=exc)
