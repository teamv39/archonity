"""Паритет M4 и legacy: без перехваченных методов M4 обязан дать выдачу legacy ребро в ребро (ADR-005).

Пайплайн с grounder="m1" в режиме только из кеша (cache/llm, cache/emb), без GPU и сервера. M4 с only,
которому не соответствует ни один метод, раскрывает всё через legacy-ветку builder.traverse.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.adapters.skeleton import load_json
from engine.executor.executor import M4Options
from engine.grounding.llm import LLMClient
from engine.pipeline import ArchonityPipeline

ROOT = Path(__file__).resolve().parent.parent
SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"
TARGETS_ROOT = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"
SCENARIO_FILES = sorted((ROOT / "hackaton" / "tt-challenge" / "scenarios").glob("S*.json"))
EDGE_SETS = ("executes", "calls", "remote", "data")


def build_pipeline(executor: str, m4_options: M4Options | None = None) -> ArchonityPipeline:
    return ArchonityPipeline(
        skeleton_path=SKELETON_PATH,
        targets_root=TARGETS_ROOT,
        grounder="m1",
        m1_options={"embedder": "qwen3-4b", "llm": LLMClient(use_server=False)},
        executor=executor,
        m4_options=m4_options,
    )


@pytest.fixture(scope="module")
def legacy_pipeline() -> ArchonityPipeline:
    return build_pipeline("legacy")


@pytest.fixture(scope="module")
def m4_pipeline() -> ArchonityPipeline:
    # only: подстрока, которой нет ни в одном ID, поэтому M4 не перехватывает ни одного метода
    return build_pipeline("m4", M4Options(only="\x00nothing\x00", judge="off"))


def test_scenario_files_found() -> None:
    assert [p.stem for p in SCENARIO_FILES] == [f"S{i}" for i in range(8)]


@pytest.mark.parametrize("path", SCENARIO_FILES, ids=lambda p: p.stem)
def test_m4_without_intercepted_methods_equals_legacy(
    legacy_pipeline: ArchonityPipeline, m4_pipeline: ArchonityPipeline, path: Path
) -> None:
    scenario = load_json(path)
    sid = scenario["id"]

    legacy = legacy_pipeline.run_scenario(scenario)
    m4 = m4_pipeline.run_scenario(scenario)

    assert legacy[0], f"{sid}: пустая выдача legacy, сравнение бессмысленно"
    assert legacy_pipeline.step_requests[sid] == m4_pipeline.step_requests[sid], f"{sid}: M1 дал разные StepRequest"
    for name, a, b in zip(EDGE_SETS, legacy, m4):
        assert a == b, f"{sid}: {name} разошлись; только legacy: {sorted(a - b)[:5]}, только M4: {sorted(b - a)[:5]}"
    assert legacy_pipeline.ledger.final_edges(sid) == m4_pipeline.ledger.final_edges(sid), (
        f"{sid}: финальные рёбра журнала разошлись"
    )


def test_m4_requires_m1_grounder() -> None:
    with pytest.raises(ValueError, match="--grounder m1"):
        ArchonityPipeline(skeleton_path=SKELETON_PATH, targets_root=TARGETS_ROOT, grounder="legacy", executor="m4")


def test_unknown_executor_rejected() -> None:
    with pytest.raises(ValueError, match="неизвестный executor"):
        ArchonityPipeline(skeleton_path=SKELETON_PATH, targets_root=TARGETS_ROOT, executor="bogus")
