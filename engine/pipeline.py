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
from engine.rules import RuntimeRules, ScenarioProfile
from engine.state import ScenarioState


class ArchonityPipeline:
    """Оркестратор полного цикла статического анализа и сборки графа."""

    def __init__(
        self,
        skeleton_path: str | Path,
        targets_root: str | Path,
        rules_path: str | Path | None = None,
        db_dump_path: str | Path | None = None,
        pool_ir: MethodPoolIR | None = None,
        ir_path: str | Path | None = None,
        entity_ir_path: str | Path | None = None,
        entity_constructors_on_load: str = "project_calls",
        collection_tables_on_read: str = "loaded",
        grounder: str = "legacy",
        m1_options: dict[str, Any] | None = None,
    ) -> None:
        self.skeleton_path = Path(skeleton_path)
        self.targets_root = Path(targets_root)

        # 1. Загрузка скелета, инициализация DB State (M0) и AST IR (M2)
        sk_dict = load_json(self.skeleton_path)
        self.index = SkeletonIndex(
            sk_dict,
            db_dump_path=db_dump_path,
            pool_ir=pool_ir,
            ir_path=ir_path,
            entity_ir_path=entity_ir_path,
        )

        # 2. Логгер доказательств (Evidence Log)
        self.evidence_logger = EvidenceLogger(self.index, targets_root=self.targets_root)

        # 3. Загрузка правил
        self.rules = RuntimeRules(
            rules_path,
            entity_constructors_on_load=entity_constructors_on_load,
            collection_tables_on_read=collection_tables_on_read,
        )

        # 4. Инициализация резолвера шагов: legacy (resolver.py) или M1 (engine/grounding, ADR-005)
        self.grounder_mode = grounder
        self.grounder = ScenarioGrounder(self.index, self.targets_root)
        self.m1 = None
        self.step_requests: dict[str, list[dict[str, Any]]] = {}
        if grounder == "m1":
            from engine.grounding.grounder import StepGrounder

            self.m1 = StepGrounder(self.index, self.targets_root, **(m1_options or {}))
        elif grounder != "legacy":
            raise ValueError(f"неизвестный grounder: {grounder}")

        # 5. Инициализация графового строителя
        self.builder = GraphBuilder(self.index, self.rules)

        # 6. Журнал решений по рёбрам (evidence.json v2): пишет сам builder
        self.ledger = DecisionLedger()

    def run_scenario(
        self,
        scenario_dict: dict[str, Any],
        scenario_state: ScenarioState | None = None,
    ) -> tuple[set[str], set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
        """Обработка одного сценария: пошаговый grounding + state tracking + graph traversal + filtering."""
        sid = scenario_dict.get("id", "S?")
        profile = ScenarioProfile.from_scenario(scenario_dict)
        self.ledger.begin_scenario(sid)

        # Шаг 1: Инициализация изолированного состояния сценария (M3)
        if scenario_state is None:
            db_state = getattr(self.index, "db_state", None)
            scenario_state = ScenarioState.create_initial(
                db_state=db_state.fork() if db_state else None,
                scenario_profile=profile,
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

        # Шаг 2: Пошаговый обход графа (Step-by-step Execution)
        for st in scenario_dict.get("steps") or []:
            self.ledger.begin_step(st.get("n"))
            step_profile = profile.for_step(st)
            step_req = None
            if session is not None:
                step_req = session.ground(st)
                self.step_requests[sid].append(step_req.to_dict())
                step_entries = {step_req.handler}
            else:
                step_entries, prev_files = self.grounder.ground_step(
                    st,
                    step_profile,
                    prev_files=prev_files,
                )
            if not step_entries:
                # Клиентский UI-шаг без обращения к бэкенду
                scenario_state.apply_step(st, scenario_dict=scenario_dict)
                continue

            m, c, r, d = self.builder.traverse(
                step_entries,
                is_admin_scenario=step_profile.is_admin,
                scenario_meta=scenario_meta,
                profile=step_profile,
                scenario_state=scenario_state,
                ledger=self.ledger,
            )
            all_methods |= m
            all_calls |= c
            all_remote |= r
            all_data |= d

            # Применение мутаций текущего шага к состоянию сценария
            if step_req is not None:
                # M3 читает params через .get(k, default): пустые значения не передаём, чтобы сработал default
                params = {k: v for k, v in step_req.params.items() if v is not None}
                scenario_state.apply_step(dataclasses.replace(step_req, params=params), scenario_dict=scenario_dict)
            else:
                scenario_state.apply_step(st, scenario_dict=scenario_dict)

        # Гарантия правила R19: каждый метод из связей calls/remote/data входит в executes
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
