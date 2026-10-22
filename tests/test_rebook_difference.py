"""Перебронирование с доплатой (X1) при верном бронировании: доплата идёт по телу перебронирования, расчёт возврата —
по заказу, а не по сводке «доплатите разницу».

Свой сценарий X1 в кеше заземлён с ошибкой M1 на шагах 4 и 11 (`createNewOrder` вместо `preserve`), поэтому шаги
бронирования здесь заменены запросом бронирования из X8.4 (тот же вид шага). Дальше:
- шаг 7 `rebook` в класс дороже — «Please pay the different money!» (status 2);
- шаг 8 `payDifference` — тело то же, что у `rebook` (`var rebookPayInfoData = data` в UI): `oldTripId` из заказа;
- шаг 9 «сколько вернут за перебронированный заказ», ссылка `new_of_step_7`: ответ шага 7 — `new Order()` без ID,
  сущность — заказ, над которым работал шаг 7 (RuntimeRules.ref_idless_result) — отказ, статус CHANGE;
- шаг 13 тот же расчёт для неоплаченного заказа — ранний возврат «Refoud 0».
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from engine.grounding.request import StepRequest

ROOT = Path(__file__).resolve().parent.parent
OWN = ROOT / "eval" / "own" / "scenarios"


class _Replay:
    def __init__(self, reqs):
        self.reqs = reqs

    def ground(self, st):
        return StepRequest(**self.reqs[st["n"]])


@pytest.fixture(scope="module")
def own_requests(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("own") / "submission.json"
    res = subprocess.run([sys.executable, str(ROOT / "run_eval.py"), "--scenarios", str(OWN / "X1.json"),
                          str(OWN / "X8.json"), "--require-cache", "--no-eval", "-o", str(out)],
                         capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=300)
    if res.returncode == 2:
        pytest.skip("нет кеша LLM для X1, X8")
    assert res.returncode == 0, res.stderr[-2000:]
    return json.loads((out.parent / "step_requests.json").read_text(encoding="utf-8"))


def _outcomes(pipeline, reqs: dict, monkeypatch) -> dict[int, tuple]:
    got: dict[int, tuple] = {}
    m4 = pipeline.m4
    orig = m4.run_step  # у общей фикстуры run_step мог обернуть другой тест: перехват — на экземпляре

    def run_step(req, state, ledger=None):
        out = orig(req, state, ledger=ledger)
        v = m4.results.get(req.step)
        while hasattr(v, "body"):
            v = v.body
        fields = getattr(v, "fields", {})
        got[req.step] = (fields.get("status"), fields.get("msg"))
        return out

    monkeypatch.setattr(m4, "run_step", run_step)
    monkeypatch.setattr(pipeline.m1, "begin", lambda sc: _Replay(reqs))
    monkeypatch.setattr(pipeline, "failures", [])
    pipeline.run_scenario(json.loads((OWN / "X1.json").read_text(encoding="utf-8")))
    assert not pipeline.failures, pipeline.failures
    return got


def _booked_right(own: dict) -> dict:
    x1 = {r["step"]: r for r in own["X1"]}
    book = next(r for r in own["X8"] if r["step"] == 4)
    for n in (4, 11):
        r = copy.deepcopy(book)
        r.update(scenario="X1", step=n, action=x1[n]["action"], refs=x1[n]["refs"])
        r["params"] = {**r["params"], "seatType": 3}
        x1[n] = r
    return x1


def test_rebook_with_difference_chain(shared_pipeline, own_requests, monkeypatch) -> None:
    got = _outcomes(shared_pipeline, _booked_right(own_requests), monkeypatch)
    assert got[7][0] == 2
    assert got[8][0] == 1
    assert got[9] == (0, "Order Status Cancel Not Permitted, Refound error")
    assert got[13] == (1, "Success. Refoud 0")
