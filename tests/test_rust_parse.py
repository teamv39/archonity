"""Разбор исходников на Rust (ADR-009): `archonity-parse` воспроизводит `data/ir/*.json` и `data/entity_ir.json` байт в байт.
Пропускается без собранного бинарника (`cd rust && cargo build --release --locked`) или без пакета задачи в `hackaton/`."""
from __future__ import annotations

import filecmp
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "rust" / "target" / "release" / "archonity-parse"
TARGETS = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"
SKELETON = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"
pytestmark = pytest.mark.skipif(not (BIN.is_file() and TARGETS.is_dir() and SKELETON.is_file()),
                                reason="нет archonity-parse или пакета задачи")


def _parse(mode: str, out: Path) -> None:
    res = subprocess.run([str(BIN), "--mode", mode, "--targets-dir", str(TARGETS), "--skeleton", str(SKELETON),
                          "-o", str(out)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr[-2000:]


def test_ir_matches_committed(tmp_path: Path) -> None:
    _parse("bodies", tmp_path / "ir")
    expected = sorted(p.name for p in (ROOT / "data" / "ir").glob("*.json"))
    assert sorted(p.name for p in (tmp_path / "ir").glob("*.json")) == expected
    diff = [n for n in expected if not filecmp.cmp(tmp_path / "ir" / n, ROOT / "data" / "ir" / n, shallow=False)]
    assert not diff, f"IR отличается от data/ir: {diff}"


def test_entity_ir_matches_committed(tmp_path: Path) -> None:
    _parse("entities", tmp_path / "entity_ir.json")
    assert filecmp.cmp(tmp_path / "entity_ir.json", ROOT / "data" / "entity_ir.json", shallow=False)


def test_mode_all_writes_both(tmp_path: Path) -> None:
    _parse("all", tmp_path)
    assert filecmp.cmp(tmp_path / "entity_ir.json", ROOT / "data" / "entity_ir.json", shallow=False)
    assert len(list((tmp_path / "ir").glob("*.json"))) == len(list((ROOT / "data" / "ir").glob("*.json")))
