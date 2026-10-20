"""Основной конвейер сборки графа зависимостей (Archonity Pipeline)."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.adapters.submission import SubmissionAdapter
from engine.decisions import DecisionLedger
from engine.evidence import EvidenceLogger
from engine.graph.builder import GraphBuilder
from engine.resolver import ScenarioGrounder
from engine.ir import MethodPoolIR
from engine.projection import project_constructors
from engine.rules import RuntimeRules, ScenarioProfile
from engine.state import ScenarioState

@dataclasses.dataclass
class ScenarioContext:
    """Тонкий контекст пассажира для M4 без доменных структур Train Ticket (OrderStatus, TrainType)."""
    user_name: str | None = None
    account_id: str | None = None
    scenario_id: str = "S?"

    def apply_step(self, *args: Any, **kwargs: Any) -> None:
        pass


def resolve_passenger_context(
    context: dict[str, Any] | None,
    db_state: Any = None,
    scenario_id: str = "S?",
) -> ScenarioContext:
    """Извлекает имя и идентификатор пассажира из README/контекста и таблицы пользователей дампа."""
    context = context or {}
    user_name = context.get("user_name", "fdse_microservice")
    account_id = "4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f"
    if db_state is not None:
        user_rows = db_state.get_table("user") if hasattr(db_state, "get_table") else []
        for u in user_rows:
            if u.get("user_name") == user_name:
                account_id = u.get("user_id", account_id)
        if user_rows and account_id == "4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f" and not any(u.get("user_id") == account_id for u in user_rows):
            account_id = user_rows[0].get("user_id", account_id)
            user_name = user_rows[0].get("user_name", user_name)
    return ScenarioContext(user_name=user_name, account_id=account_id, scenario_id=scenario_id)


@dataclasses.dataclass
class PipelineConfig:
    """Типизированная конфигурация оркестратора конвейера."""
    rules_path: str | Path | None = None
    db_dump_path: str | Path | None = None
    db_state: Any = None
    pool_ir: MethodPoolIR | None = None
    ir_path: str | Path | None = None
    entity_ir_path: str | Path | None = None
    constructors: str = "caller_only"
    collection_tables_on_read: str = "loaded"
    element_callbacks: str = "on"
    rabbitmq_delivery: str = "on"
    station_food_collection: str = "store_browse_only"
    probe_orders_data: str = "on"
    enum_member_calls: str = "on"
    trip_food_query: str = "cascade"
    route_distances_collection: str = "pruned"
    preserve_notification_lookup: str = "on"
    grounder: str = "legacy"
    m1_options: dict[str, Any] | None = None
    executor: str = "legacy"
    method_ir_dir: str | Path | None = None
    unresolved_receiver_calls: str = "mute"
    m4_success_retry: str = "on"
    m4_judge: str = "off"
    m4_judge_budget: int = 400
    security_check_scope: str = "all"
    route_stations_usage: str = "pruned"
    jackson_ctor: str = "on"
    lombok_tostring: str = "on"
    unbound_handlers: str = "rebind"
    spring_security: str = "semantic"
    m4_m3_refs: str = "off"
    module_roles: str = "skeleton"
    m4_state: str = "context"
    ref_kinds: str | None = None
    m4_conventions: str = "code"


class ArchonityPipeline:
    """Оркестратор полного цикла статического анализа и сборки графа."""

    def __init__(
        self,
        skeleton_path: str | Path,
        targets_root: str | Path,
        config: PipelineConfig | None = None,
        **kwargs: Any,
    ) -> None:
        cfg = dataclasses.replace(config) if config is not None else PipelineConfig()
        for k, v in kwargs.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        self.config = cfg

        # Виды refs (ADR-007) — как у промпта M1: M1 v8 (по умолчанию) даёт виды манифеста, v7 и legacy — прежние 12
        if self.config.ref_kinds is None:
            self.config.ref_kinds = (
                "v8"
                if self.config.grounder == "m1" and (self.config.m1_options or {}).get("prompt", "v8") == "v8"
                else "v7"
            )
        self.skeleton_path = Path(skeleton_path)
        self.targets_root = Path(targets_root)

        sk_dict = load_json(self.skeleton_path)
        self.index = SkeletonIndex(
            sk_dict,
            db_dump_path=self.config.db_dump_path,
            db_state=self.config.db_state,
            pool_ir=self.config.pool_ir,
            ir_path=self.config.ir_path,
            entity_ir_path=self.config.entity_ir_path,
        )

        self.evidence_logger = EvidenceLogger(self.index, targets_root=self.targets_root)

        self.rules = RuntimeRules(
            self.config.rules_path,
            constructors=self.config.constructors,
            collection_tables_on_read=self.config.collection_tables_on_read,
            element_callbacks=self.config.element_callbacks,
            rabbitmq_delivery=self.config.rabbitmq_delivery,
            station_food_collection=self.config.station_food_collection,
            probe_orders_data=self.config.probe_orders_data,
            enum_member_calls=self.config.enum_member_calls,
            trip_food_query=self.config.trip_food_query,
            route_distances_collection=self.config.route_distances_collection,
            route_stations_usage=self.config.route_stations_usage,
            preserve_notification_lookup=self.config.preserve_notification_lookup,
            unresolved_receiver_calls=self.config.unresolved_receiver_calls,
            m4_success_retry=self.config.m4_success_retry,
            security_check_scope=self.config.security_check_scope,
            jackson_ctor=self.config.jackson_ctor,
            lombok_tostring=self.config.lombok_tostring,
            unbound_handlers=self.config.unbound_handlers,
            spring_security=self.config.spring_security,
            m4_m3_refs=self.config.m4_m3_refs,
            module_roles=self.config.module_roles,
            m4_state=self.config.m4_state,
            ref_kinds=self.config.ref_kinds,
            m4_conventions=self.config.m4_conventions,
        )

        self.grounder_mode = self.config.grounder
        self.grounder = None
        self.m1 = None
        self.step_requests: dict[str, list[dict[str, Any]]] = {}
        if self.config.grounder == "legacy":
            self.grounder = ScenarioGrounder(self.index, self.targets_root)
        elif self.config.grounder == "m1":
            from engine.grounding.grounder import StepGrounder

            self.m1 = StepGrounder(self.index, self.targets_root, **(self.config.m1_options or {}))
        else:
            raise ValueError(f"неизвестный grounder: {self.config.grounder}")

        self.builder = GraphBuilder(self.index, self.rules)
        self.ledger = DecisionLedger()

        self.executor_mode = self.config.executor
        self.m4 = None
        if self.config.executor == "ir":
            if self.config.grounder != "m1":
                raise ValueError("executor=ir работает от StepRequest M1: нужен grounder=m1")
            from engine.executor.step import StepExecutor

            ir_dir = (
                Path(self.config.method_ir_dir)
                if self.config.method_ir_dir
                else Path(__file__).resolve().parent.parent / "data" / "ir"
            )
            judge = None
            llm = (self.config.m1_options or {}).get("llm")
            if self.config.m4_judge != "off" and llm is not None:
                # Судья M4 с кешем и бюджетом вызовов сервера (engine/executor/judge.py)
                from engine.executor.judge import Judge

                judge = Judge(
                    self.targets_root,
                    self.index.sk.get("context"),
                    llm,
                    mode=self.config.m4_judge,
                    budget=self.config.m4_judge_budget,
                )
            self.m4 = StepExecutor(self.index, self.rules, ir_dir, self.targets_root, judge=judge)
        elif self.config.executor != "legacy":
            raise ValueError(f"неизвестный executor: {self.config.executor}")

    def run_scenario(
        self,
        scenario_dict: dict[str, Any],
        scenario_state: ScenarioState | None = None,
    ) -> tuple[set[str], set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
        """Обработка одного сценария: пошаговый grounding + state tracking + graph traversal + filtering."""
        sid = scenario_dict.get("id", "S?")
        use_m4_context = (self.m4 is not None and getattr(self.rules, "m4_state", "context") == "context")
        profile = (
            ScenarioProfile.from_scenario(scenario_dict)
            if not use_m4_context
            else None
        )
        self.ledger.begin_scenario(sid)

        # Фаза 1: Инициализация состояния сценария
        if scenario_state is None:
            db_state = getattr(self.index, "db_state", None)
            context = getattr(self.index, "context", None)
            if use_m4_context:
                scenario_state = resolve_passenger_context(context, db_state=db_state, scenario_id=sid)
            else:
                scenario_state = ScenarioState.create_initial(
                    db_state=db_state.fork() if db_state else None,
                    scenario_profile=profile,
                    context=context,
                )

        step_texts = [st.get("action", "") for st in scenario_dict.get("steps") or []]
        scenario_meta = {
            "id": sid,
            "title": scenario_dict.get("title", ""),
            "description": scenario_dict.get("description", ""),
            "step_texts": step_texts,
        }

        all_methods: set[str] = set()
        all_calls: set[tuple[str, str]] = set()
        all_remote: set[tuple[str, str]] = set()
        all_data: set[tuple[str, str]] = set()

        prev_files: set[str] = set()
        session = self.m1.begin(scenario_dict) if self.m1 is not None else None
        self.step_requests[sid] = []
        if self.m4 is not None:
            self.m4.begin_scenario(sid)

        # Шаг 2: Пошаговый обход графа (Step-by-step Execution)
        for st in scenario_dict.get("steps") or []:
            self.ledger.begin_step(st.get("n"))
            step_profile = profile.for_step(st) if profile is not None else None
            step_req = None
            if session is not None:
                step_req = session.ground(st)
                # R20: обработчик, который Spring вызвать не может, — шаг через рабочий обработчик того же
                # контроллера. Замена после заземления: история шагов в промпте M1 и кеш LLM не меняются.
                if self.rules.unbound_handlers == "rebind":
                    step_req = self.m1.rebind(step_req) or step_req
                step_entries = {step_req.handler}
                self.step_requests[sid].append(step_req.to_dict())
            else:
                step_entries, prev_files = self.grounder.ground_step(
                    st,
                    step_profile,
                    prev_files=prev_files,
                )
            if not step_entries:
                # В UI-шагах нет сетевого вызова
                if not isinstance(scenario_state, ScenarioContext):
                    scenario_state.apply_step(st, scenario_dict=scenario_dict)
                continue

            if self.m4 is not None and step_req is not None:
                m, c, r, d = self.m4.run_step(step_req, scenario_state, ledger=self.ledger,
                                              scenario=scenario_dict)
                self.builder._ledger = self.ledger
                self.builder.apply_spring_security(m, c, d)
            else:
                m, c, r, d = self.builder.traverse(
                    step_entries,
                    is_admin_scenario=step_profile.is_admin,
                    scenario_meta=scenario_meta,
                    profile=step_profile,
                    scenario_state=scenario_state,
                    ledger=self.ledger,
                )
            # M5: конструктор в ответе, только если из него исполнился вызов проекта (R7, ADR-006)
            project_constructors(m, c, r, d, self.rules.constructors, self.ledger)
            all_methods |= m
            all_calls |= c
            all_remote |= r
            all_data |= d

            # Применение мутаций текущего шага к состоянию сценария
            # Шаг 3: Обновление состояния после успешного шага
            if not isinstance(scenario_state, ScenarioContext):
                if step_req is not None:
                    params = {k: v for k, v in step_req.params.items() if v is not None}
                    scenario_state.apply_step(dataclasses.replace(step_req, params=params), scenario_dict=scenario_dict)
                else:
                    scenario_state.apply_step(st, scenario_dict=scenario_dict)

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
