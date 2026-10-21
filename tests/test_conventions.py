"""Соглашения проекта в M4 из кода (feature/102): ответ-обёртка, строки шага по миру БД, поля тела из шаблона UI."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.executor import envelope
from engine.executor.envelope import Envelope
from engine.executor.interpreter import arm_fails
from engine.executor.step import StepExecutor, _is_failure, _payload
from engine.executor.values import Obj, Wrapper
from engine.grounding.ui_catalog import _FileParser, _HtmlScan, _template_sources, build_catalog

ROOT = Path(__file__).resolve().parent.parent
TT = ROOT / "hackaton" / "tt-challenge"
TARGETS = TT / "targets" / "trainticket"
PAY = "method:ts-inside-payment-service:inside_payment.controller.InsidePaymentController#pay"
REBOOK = "method:ts-rebook-service:rebook.controller.RebookController#rebook"

# Чужое соглашение: в коде M4 нет ни Response, ни status, ни 1
RESULT = Envelope(name="Result", status="code", success=0, data="payload")


@pytest.fixture(scope="module")
def ix() -> SkeletonIndex:
    return SkeletonIndex(load_json(TT / "skeleton" / "trainticket.json.gz"))


@pytest.fixture(scope="module")
def ir() -> dict:
    out: dict = {}
    for p in sorted((ROOT / "data" / "ir").glob("*.json")):
        out.update(json.loads(p.read_text(encoding="utf-8"))["methods"])
    return out


class TestEnvelope:
    def test_failure_arm_by_convention(self) -> None:
        def ret(cls: str, code: int) -> list[dict]:
            return [{"op": "return", "expr": {"new": f"{cls}<>", "args": [{"lit": code, "type": "int"}]}}]

        set_code = [
            {"op": "expr", "expr": {"call": "c", "callee": "setCode", "recv": {"name": "r", "ref": "local"},
                                    "args": [{"lit": 3, "type": "int"}]}},
            {"op": "return", "expr": {"name": "r", "ref": "local"}},
        ]
        assert arm_fails(ret("Result", 1), RESULT) and arm_fails(set_code, RESULT)
        assert not arm_fails(ret("Result", 0), RESULT) and not arm_fails([], RESULT)
        # Без соглашения отказ — только throw и null
        assert not arm_fails(ret("Response", 0), None)
        assert arm_fails([{"op": "throw", "expr": {}}], None)
        assert arm_fails([{"op": "return", "expr": {"lit": None, "type": "null"}}], None)

    def test_failure_and_payload_of_response(self) -> None:
        bad = Wrapper(Obj("x.Result", {"code": 2, "payload": "p"}, open=False))
        good = Wrapper(Obj("x.Result", {"code": 0, "payload": "p"}, open=False))
        assert _is_failure(bad, RESULT) and not _is_failure(good, RESULT) and not _is_failure(bad, None)
        assert _payload(good, RESULT) == "p"

    def test_derived_from_train_ticket(self, ix: SkeletonIndex, ir: dict) -> None:
        # Класс — из `return new X(<код>, "<сообщение>")`, поля — из скелета, успех — из проверок UI
        tt = envelope.Envelope(name="Response", status="status", success=1, data="data")
        assert envelope.derive(ix, ir, TARGETS) == tt
        # Без UI значение успеха дают сравнения get<Статус>() сервисов
        assert envelope.derive(ix, ir, None) == tt


class TestWorldString:
    def _ex(self, rows: dict[str, list[dict]]) -> SimpleNamespace:
        world = SimpleNamespace(table_of={"x.Station": "station", "x.Delivery": "delivery", "x.Trip": "trip"},
                                collections_of={}, rows=lambda t: rows.get(t, []))
        return SimpleNamespace(it=SimpleNamespace(world=world))

    def test_text_value_to_stored_value(self) -> None:
        ex = self._ex({"station": [{"name": "shanghai"}, {"name": "ningbo"}],
                       "trip": [{"start": "shanghai"}], "delivery": [{"station_name": "Shang Hai"}]})
        # «Ning Bo» хранится как «ningbo»; у «Shanghai» два вида, берётся тот, что в большем числе колонок
        assert StepExecutor._world_string(ex, "Shanghai,Suzhou,Ning Bo") == "shanghai,Suzhou,ningbo"

    def test_tie_keeps_text(self) -> None:
        ex = self._ex({"station": [{"name": "ningbo"}], "delivery": [{"station_name": "Ning Bo"}]})
        assert StepExecutor._world_string(ex, "NING BO") == "NING BO"


class TestBodySources:
    def test_template_argument_through_component_state(self) -> None:
        js = """
        new Vue({ methods: {
            payMyOrder(num, orderId, tripId) { this.orderId = orderId; this.tripId = tripId; var that = this;
                $('#m').modal({ onConfirm: function () {
                    var info = new Object(); info.orderId = that.orderId; info.tripId = that.tripId;
                    $.ajax({ type: "post", url: "/api/v1/pay", data: JSON.stringify(info) });
                }});
            }
        }});
        """
        rec = next(_FileParser("t.js", js.encode("utf-8")).requests())
        assert rec["body_src"] == {"orderId": ["payMyOrder", 1], "tripId": ["payMyOrder", 2]}
        sc = _HtmlScan()
        sc.feed('<button v-on:click="payMyOrder(index, item.id, item.trainNumber)">Pay</button>')
        assert _template_sources(rec["body_src"], sc.call_args) == {"orderId": "id", "tripId": "trainNumber"}

    def test_disagreeing_call_sites_give_nothing(self) -> None:
        assert _template_sources({"tripId": ["f", 0]}, {"f": [["item.trainNumber"], ["row.tripId"]]}) == {}

    def test_train_ticket_pay_and_rebook(self, ix: SkeletonIndex) -> None:
        cat = build_catalog(TARGETS, ix)
        by = {h.split("(")[0]: r for r in cat.requests for h in r.handlers}
        assert by[PAY].body_src["tripId"] == "trainNumber"
        assert by[REBOOK].body_src["oldTripId"] == "trainNumber"
