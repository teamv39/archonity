"""Прогресс M1 (`ScenarioSession._progress`): строка в stderr только после шагов, которым понадобился сервер LLM."""
from __future__ import annotations

from types import SimpleNamespace

from engine.grounding.grounder import ScenarioSession
from engine.grounding.llm import LLMStats
from engine.grounding.request import StepRequest

SCENARIO = {"id": "X9", "steps": [{"n": 1, "action": "a"}, {"n": 2, "action": "b"}]}


def _session(calls_per_step: dict[int, int], llm: bool = True) -> ScenarioSession:
    stats = LLMStats()

    def ground_step(sc, st, ranked, history):
        stats.calls += calls_per_step.get(st["n"], 0)
        stats.seconds += 30.0 * calls_per_step.get(st["n"], 0)
        stats.hits += 1
        return StepRequest(sc["id"], st["n"], st["action"], "h", {"method": "GET", "path": "/api/x"})

    handler = SimpleNamespace(cls="C", name="m", module="svc")
    grounder = SimpleNamespace(llm=SimpleNamespace(stats=stats) if llm else None, ground_step=ground_step,
                               cat=SimpleNamespace(handlers={"h": handler}))
    return ScenarioSession(grounder, SCENARIO, {1: None, 2: None})


def test_progress_only_for_server_steps(capsys) -> None:
    sess = _session({2: 3})
    for st in SCENARIO["steps"]:
        sess.ground(st)
    err = capsys.readouterr().err.splitlines()
    assert err == ["[m1] X9 шаг 2 из 2: вызовов LLM 3 за 90 с -> GET /api/x; всего 3 вызовов, 1.5 мин"]


def test_silent_from_cache_and_without_llm(capsys) -> None:
    for sess in (_session({}), _session({1: 1}, llm=False)):
        for st in SCENARIO["steps"]:
            sess.ground(st)
    assert capsys.readouterr().err == ""
