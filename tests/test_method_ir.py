"""Артефакт M2 data/ir/<module>.json (archparse/README.md, раздел 3.6) сходится со скелетом."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.adapters.skeleton import load_json

ROOT = Path(__file__).resolve().parent.parent
IR_DIR = ROOT / "data" / "ir"
SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"


@pytest.fixture(scope="module")
def skeleton() -> dict[str, Any]:
    return load_json(SKELETON_PATH)


@pytest.fixture(scope="module")
def ir() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for f in sorted(IR_DIR.glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        assert doc["schema"] == "method_ir/1"
        assert doc["module"] == f.stem
        out.update(doc["methods"])
    return out


def _nodes(x: Any) -> Iterator[dict[str, Any]]:
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from _nodes(v)
    elif isinstance(x, list):
        for v in x:
            yield from _nodes(v)


def test_every_method_with_body_present(skeleton: dict[str, Any], ir: dict[str, dict[str, Any]]) -> None:
    expected = {k for k, n in skeleton["nodes"].items() if n["kind"] == "method" and not n["abstract"]}
    assert set(ir) == expected


def test_every_call_site_once_in_its_method(skeleton: dict[str, Any], ir: dict[str, dict[str, Any]]) -> None:
    seen: Counter[str] = Counter()
    for mid, m in ir.items():
        for n in _nodes(m["body"]):
            cs = n.get("call")
            if isinstance(cs, str) and cs.startswith("call:"):
                assert skeleton["nodes"][cs]["method"] == mid
                seen[cs] += 1
    call_sites = {k for k, n in skeleton["nodes"].items() if n["kind"] == "call_site"}
    assert set(seen) == call_sites
    assert max(seen.values()) == 1


def test_no_unparsed_expressions(ir: dict[str, dict[str, Any]]) -> None:
    for mid, m in ir.items():
        assert not any("text" in n and "op" not in n for n in _nodes(m["body"])), mid
