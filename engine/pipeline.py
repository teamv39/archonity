"""Основной конвейер сборки графа зависимостей (Archonity Pipeline)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.adapters.submission import SubmissionAdapter
from engine.evidence import EvidenceLogger
from engine.graph.builder import GraphBuilder
from engine.resolver import ScenarioGrounder
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
    ) -> None:
        self.skeleton_path = Path(skeleton_path)
        self.targets_root = Path(targets_root)

        # 1. Загрузка скелета и инициализация DB State (M0)
        sk_dict = load_json(self.skeleton_path)
        self.index = SkeletonIndex(sk_dict, db_dump_path=db_dump_path)

        # 2. Логгер доказательств (Evidence Log)
        self.evidence_logger = EvidenceLogger(self.index, targets_root=self.targets_root)

        # 3. Загрузка правил
        self.rules = RuntimeRules(rules_path)

        # 4. Инициализация резолвера шагов
        self.grounder = ScenarioGrounder(self.index, self.targets_root)

        # 5. Инициализация графового строителя
        self.builder = GraphBuilder(self.index, self.rules)

    def run_scenario(
        self,
        scenario_dict: dict[str, Any],
        scenario_state: ScenarioState | None = None,
    ) -> tuple[set[str], set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
        """Обработка одного сценария: пошаговый grounding + state tracking + graph traversal + filtering."""
        sid = scenario_dict.get("id", "S?")
        profile = ScenarioProfile.from_scenario(scenario_dict)

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

        # Шаг 2: Пошаговый обход графа (Step-by-step Execution)
        for st in scenario_dict.get("steps") or []:
            step_profile = profile.for_step(st)
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
            )
            all_methods |= m
            all_calls |= c
            all_remote |= r
            all_data |= d

            # Применение мутаций текущего шага к состоянию сценария
            scenario_state.apply_step(st, scenario_dict=scenario_dict)

        # Гарантия правила R19: каждый метод из связей calls/remote/data входит в executes
        all_methods |= {s for s, _ in all_calls | all_remote | all_data} | {t for _, t in all_calls | all_remote}

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
