"""Чтение сценария (engine/scenario.py) и пути --scenarios (run_eval.resolve_scenario_paths): форма файла не стоит ответа."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.scenario import load_scenario
from run_eval import resolve_scenario_paths

ROOT = Path(__file__).resolve().parent.parent
S0 = ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S0.json"


@pytest.mark.skipif(not S0.is_file(), reason="нет пакета задачи")
def test_s0_unchanged() -> None:
    assert load_scenario(S0) == json.loads(S0.read_text(encoding="utf-8"))


@pytest.mark.parametrize("raw", [
    "﻿" + json.dumps({"id": "A", "steps": [{"n": 1, "action": "x"}]}),
    json.dumps({"id": "A", "steps": [{"n": 1, "action": "x"}]}).replace(" ", "\r\n"),
])
def test_bom_and_crlf(tmp_path: Path, raw: str) -> None:
    p = tmp_path / "a.json"
    p.write_bytes(raw.encode("utf-8"))
    assert load_scenario(p)["steps"] == [{"n": 1, "action": "x"}]


def test_utf16_and_missing_fields(tmp_path: Path) -> None:
    p = tmp_path / "Z7.json"
    p.write_bytes(json.dumps({"steps": [{"n": "2"}, "Open the list", {"n": 3.0, "action": None}, {"n": "x", "action": 5}]})
                  .encode("utf-16"))
    sc = load_scenario(p)
    assert sc["id"] == "Z7"
    assert sc["steps"] == [{"n": 2, "action": ""}, {"n": 2, "action": "Open the list"}, {"n": 3, "action": ""},
                           {"n": 4, "action": "5"}]


@pytest.mark.parametrize("obj", [{"id": "E"}, {"id": "E", "steps": None}, {"id": "E", "steps": []}])
def test_no_steps(tmp_path: Path, obj: dict) -> None:
    p = tmp_path / "e.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    assert load_scenario(p)["steps"] == []


def test_not_an_object(tmp_path: Path) -> None:
    p = tmp_path / "l.json"
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_scenario(p)


def test_paths_dir_and_missing(tmp_path: Path) -> None:
    for n in ("b.json", "a.json", "c.txt"):
        (tmp_path / n).write_text("{}", encoding="utf-8")
    missing: list[str] = []
    got = resolve_scenario_paths([str(tmp_path), str(tmp_path / "nope.json")], missing)
    assert [p.name for p in got] == ["a.json", "b.json"] and missing == [str(tmp_path / "nope.json")]
