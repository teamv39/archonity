import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"
TARGETS_ROOT = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"


@pytest.fixture(scope="session")
def shared_skeleton_dict() -> dict[str, Any]:
    from engine.adapters.skeleton import load_json

    return load_json(SKELETON_PATH)


@pytest.fixture(scope="session")
def shared_skeleton_index(shared_skeleton_dict: dict[str, Any]):
    from engine.adapters.skeleton import SkeletonIndex

    return SkeletonIndex(shared_skeleton_dict)


@pytest.fixture(scope="session")
def shared_pipeline():
    """Конвейер рекорда: M1 с ответами LLM и векторами только из cache/, M4 (как `run_eval.py --require-cache`)."""
    from engine.grounding.llm import LLMClient
    from engine.pipeline import ArchonityPipeline

    return ArchonityPipeline(
        skeleton_path=SKELETON_PATH,
        targets_root=TARGETS_ROOT,
        m1_options={"llm": LLMClient(use_server=False)},
    )
