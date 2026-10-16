"""Основной конвейер сборки графа зависимостей (Archonity Pipeline)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.adapters.submission import SubmissionAdapter
from engine.graph.builder import GraphBuilder
from engine.resolver import ScenarioGrounder
from engine.rules import RuntimeRules


class ArchonityPipeline:
    """Оркестратор полного цикла статического анализа и сборки графа."""

    def __init__(
        self,
        skeleton_path: str | Path,
        targets_root: str | Path,
        rules_path: str | Path | None = None,
    ) -> None:
        self.skeleton_path = Path(skeleton_path)
        self.targets_root = Path(targets_root)

        # 1. Загрузка скелета
        sk_dict = load_json(self.skeleton_path)
        self.index = SkeletonIndex(sk_dict)

        # 2. Загрузка правил
        self.rules = RuntimeRules(rules_path)

        # 3. Инициализация резолвера шагов
        self.grounder = ScenarioGrounder(self.index, self.targets_root)

        # 4. Инициализация графового строителя
        self.builder = GraphBuilder(self.index, self.rules)

    def run_scenario(self, scenario_dict: dict[str, Any]) -> tuple[set[str], set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
        """Обработка одного сценария: grounding + graph traversal + filtering."""
        sid = scenario_dict.get("id", "S?")
        # Проверяем, административный ли сценарий
        text = " ".join(
            [scenario_dict.get("title", ""), scenario_dict.get("description", "")]
            + [st.get("action", "") for st in scenario_dict.get("steps") or []]
        )
        is_admin = "admin" in text.lower() or "administrator" in text.lower()

        # Шаг 1: Grounding точек входа
        entries = self.grounder.ground(scenario_dict)

        step_texts = [st.get("action", "") for st in scenario_dict.get("steps") or []]
        scenario_meta = {
            "id": sid,
            "title": scenario_dict.get("title", ""),
            "description": scenario_dict.get("description", ""),
            "step_texts": step_texts,
        }

        # Шаг 2: Обход графа с изоляцией БД и фильтрацией мертвого кода
        methods, calls, remote, data = self.builder.traverse(
            entries, is_admin_scenario=is_admin, scenario_meta=scenario_meta
        )

        return methods, calls, remote, data

    def run_all(
        self,
        scenario_paths: list[str | Path],
        output_path: str | Path,
    ) -> SubmissionAdapter:
        """Прогон по списку сценариев и экспорт submission.json."""
        adapter = SubmissionAdapter(project=self.index.project)

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
                stmts=self.index.stmts,
            )

        adapter.save(output_path)
        return adapter
