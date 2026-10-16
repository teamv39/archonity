"""Сквозные интеграционные тесты (E2E) пайплайна и проверка метрики IoU."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from engine.adapters.skeleton import load_json
from engine.pipeline import ArchonityPipeline

ROOT = Path(__file__).resolve().parent.parent
SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"
TARGETS_ROOT = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"
GOLD_S0_PATH = ROOT / "hackaton" / "tt-challenge" / "gold" / "S0.json"
EVAL_SCRIPT = ROOT / "hackaton" / "tt-challenge" / "platform" / "evaluate_golden.py"


@pytest.fixture(scope="module")
def pipeline() -> ArchonityPipeline:
    return ArchonityPipeline(
        skeleton_path=SKELETON_PATH,
        targets_root=TARGETS_ROOT,
    )


class TestPipelineE2E:
    """Сквозное тестирование конвейера на всех 8 сценариях."""

    def test_s0_perfect_score(self, pipeline: ArchonityPipeline, tmp_path: Path) -> None:
        """Регрессионный тест: скор калибровочного сценария S0 обязан быть ровно 1.0000."""
        s0_dict = load_json(ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S0.json")
        out_sub = tmp_path / "submission.json"

        pipeline.run_all([ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S0.json"], output_path=out_sub)
        assert out_sub.is_file()

        # Запуск официального evaluate_golden.py
        cmd = [sys.executable, str(EVAL_SCRIPT), str(GOLD_S0_PATH), str(out_sub), "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0, f"evaluate_golden error: {res.stderr}"

        eval_data = json.loads(res.stdout)
        score = eval_data.get("score", 0.0)
        assert score == pytest.approx(1.0, abs=1e-4), f"S0 score degraded: {score}"

        # Детальная проверка всех 4 типов связей
        s0_res = eval_data["scenarios"]["S0"]["sets"]
        assert s0_res["executes"]["iou"] == pytest.approx(1.0, abs=1e-4)
        assert s0_res["calls"]["iou"] == pytest.approx(1.0, abs=1e-4)
        assert s0_res["remote"]["iou"] == pytest.approx(1.0, abs=1e-4)
        assert s0_res["data"]["iou"] == pytest.approx(1.0, abs=1e-4)

    def test_all_scenarios_format_and_zero_rejections(
        self,
        pipeline: ArchonityPipeline,
        tmp_path: Path,
    ) -> None:
        """Проверка валидации формата и отсутствия отклоненных ребер на всех сценариях S0..S7."""
        scenario_files = sorted((ROOT / "hackaton" / "tt-challenge" / "scenarios").glob("*.json"))
        assert len(scenario_files) == 8

        out_sub = tmp_path / "submission.json"
        adapter = pipeline.run_all(scenario_files, output_path=out_sub)
        assert out_sub.is_file()

        cmd = [sys.executable, str(EVAL_SCRIPT), str(GOLD_S0_PATH), str(out_sub), "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode in (0, 3)

        eval_data = json.loads(res.stdout)
        scenarios = eval_data.get("scenarios", {})

        for sid, sdata in scenarios.items():
            rejected_count = sum(sdata.get("rejected", {}).values())
            assert rejected_count == 0, f"Scenario {sid} has rejected edges: {sdata.get('rejected')}"
            assert sdata.get("accepted", 0) > 0, f"Scenario {sid} has 0 accepted edges"

    def test_executes_completeness_invariant(self, pipeline: ArchonityPipeline) -> None:
        """Инвариант полноты: каждый метод, участвующий в calls, remote или data, обязан быть в executes."""
        scenario_files = sorted((ROOT / "hackaton" / "tt-challenge" / "scenarios").glob("*.json"))
        for sp in scenario_files:
            s_dict = load_json(sp)
            sid = s_dict["id"]
            methods, calls, remote, data = pipeline.run_scenario(s_dict)
            touched = {a for a, _ in calls | remote | data} | {b for _, b in calls | remote}
            missing = touched - methods
            assert not missing, f"Scenario {sid} has methods in edges missing from executes: {missing}"

    def test_no_intra_service_remote_calls(self, pipeline: ArchonityPipeline) -> None:
        """Инвариант remote: межсервисные вызовы допустимы ТОЛЬКО между разными сервисами."""
        scenario_files = sorted((ROOT / "hackaton" / "tt-challenge" / "scenarios").glob("*.json"))
        for sp in scenario_files:
            s_dict = load_json(sp)
            sid = s_dict["id"]
            _, _, remote, _ = pipeline.run_scenario(s_dict)
            for s, t in remote:
                mod_s = s.split(":")[1]
                mod_t = t.split(":")[1]
                assert mod_s != mod_t, f"Scenario {sid} has intra-service remote: {s} -> {t}"

    def test_artifacts_generation_and_integrity(
        self,
        pipeline: ArchonityPipeline,
        tmp_path: Path,
    ) -> None:
        """Проверка корректной генерации submission.json, canonical_graph.json и evidence.json."""
        scenario_files = sorted((ROOT / "hackaton" / "tt-challenge" / "scenarios").glob("*.json"))
        sub_file = tmp_path / "submission.json"
        cg_file = tmp_path / "canonical_graph.json"
        ev_file = tmp_path / "evidence.json"

        adapter = pipeline.run_all(scenario_files, output_path=sub_file)
        adapter.save_canonical_graph(cg_file)
        adapter.save_evidence_log(ev_file)

        assert sub_file.is_file() and sub_file.stat().st_size > 0
        assert cg_file.is_file() and cg_file.stat().st_size > 0
        assert ev_file.is_file() and ev_file.stat().st_size > 0

        # Валидация JSON
        sub_data = json.loads(sub_file.read_text(encoding="utf-8"))
        assert len(sub_data.get("scenarios", {})) == 8

        cg_data = json.loads(cg_file.read_text(encoding="utf-8"))
        assert len(cg_data.get("nodes", [])) > 20
        assert len(cg_data.get("edges", [])) > 50

        ev_data = json.loads(ev_file.read_text(encoding="utf-8"))
        assert len(ev_data) > 50
        # В evidence.json не должно быть фантомных маршрутов к ts-common
        assert not any("ts-common" in k for k in ev_data)

    def test_canonical_graph_structural_integrity(
        self,
        pipeline: ArchonityPipeline,
        tmp_path: Path,
    ) -> None:
        """Проверка структурной целостности графа: отсутствие висячих рёбер, терминальные стоки БД, 100% покрытие evidence."""
        scenario_files = sorted((ROOT / "hackaton" / "tt-challenge" / "scenarios").glob("*.json"))
        sub_file = tmp_path / "submission.json"
        cg_file = tmp_path / "canonical_graph.json"

        adapter = pipeline.run_all(scenario_files, output_path=sub_file)
        adapter.save_canonical_graph(cg_file)

        cg_data = json.loads(cg_file.read_text(encoding="utf-8"))
        nodes = cg_data.get("nodes", [])
        edges = cg_data.get("edges", [])

        node_map = {n["id"]: n for n in nodes}
        assert len(node_map) == len(nodes), "Duplicate node IDs detected in canonical graph"

        for edge in edges:
            src = edge["source"]
            tgt = edge["target"]
            rel = edge.get("relation_type") or edge.get("type")

            # 1. Отсутствие висячих рёбер
            assert src in node_map, f"Dangling edge: source '{src}' not in nodes"
            assert tgt in node_map, f"Dangling edge: target '{tgt}' not in nodes"

            # 2. База данных — строгий терминальный сток (0 исходящих рёбер)
            src_node = node_map[src]
            assert not src_node.get("isTerminalSink", False), f"Terminal sink node {src} has outgoing edge to {tgt}"
            assert src_node.get("type") != "database", f"Database node {src} has outgoing edge to {tgt}"

            # 3. Отсутствие петель на самом себе для межсервисных вызовов
            if rel == "REST_HTTP":
                assert src != tgt, f"Self-loop remote HTTP call detected: {src} -> {tgt}"

            # 4. 100% покрытие evidence_details с реальными сниппетами
            assert "evidence_details" in edge, f"Edge {src} -> {tgt} is missing evidence_details"
            details = edge["evidence_details"]
            assert details.get("file_path"), f"Edge {src} -> {tgt} is missing file_path"
            assert details.get("code_snippet"), f"Edge {src} -> {tgt} is missing code_snippet"

    def test_determinism_invariant(
        self,
        pipeline: ArchonityPipeline,
        tmp_path: Path,
    ) -> None:
        """Инвариант детерминизма: повторные запуски конвейера дают побитово идентичный результат."""
        scenario_files = sorted((ROOT / "hackaton" / "tt-challenge" / "scenarios").glob("*.json"))
        sub1 = tmp_path / "sub1.json"
        sub2 = tmp_path / "sub2.json"

        pipeline.run_all(scenario_files, output_path=sub1)
        pipeline.run_all(scenario_files, output_path=sub2)

        data1 = json.loads(sub1.read_text(encoding="utf-8"))
        data2 = json.loads(sub2.read_text(encoding="utf-8"))

        assert data1 == data2, "Non-deterministic submission generation detected across consecutive runs"

