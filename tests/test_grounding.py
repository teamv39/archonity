"""Тесты M1 (engine/grounding): каталог UI, кандидаты, промпты, кеш LLM, фолбэк без моделей."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.grounding import prompts as P
from engine.grounding.docs import HandlerCatalog
from engine.grounding.grounder import StepGrounder, enum_codes
from engine.grounding.llm import LLMClient
from engine.grounding.retrieval import Ranked, rrf, twin_groups
from engine.grounding.ui_catalog import _FileParser, build_catalog, match_handlers

ROOT = Path(__file__).resolve().parent.parent
TT = ROOT / "hackaton" / "tt-challenge"
TARGETS = TT / "targets" / "trainticket"

PRESERVE = "method:ts-preserve-service:preserve.controller.PreserveController#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)"
PRESERVE_OTHER = "method:ts-preserve-other-service:preserveOther.controller.PreserveOtherController#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)"
ORDER_REFRESH = "method:ts-order-service:order.controller.OrderController#queryOrdersForRefresh(order.entity.OrderInfo,org.springframework.http.HttpHeaders)"
OTHER_REFRESH = "method:ts-order-other-service:other.controller.OrderOtherController#queryOrdersForRefresh(other.entity.QueryInfo,org.springframework.http.HttpHeaders)"
CANCEL = "method:ts-cancel-service:cancel.controller.CancelController#cancelTicket(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)"


@pytest.fixture(scope="module")
def ix() -> SkeletonIndex:
    return SkeletonIndex(load_json(TT / "skeleton" / "trainticket.json.gz"))


@pytest.fixture(scope="module")
def catalog(ix: SkeletonIndex):
    return build_catalog(TARGETS, ix)


@pytest.fixture(scope="module")
def handlers(ix: SkeletonIndex, catalog) -> HandlerCatalog:
    return HandlerCatalog(ix, TARGETS, catalog)


def _parse(js: str) -> list[dict]:
    return list(_FileParser("t.js", js.encode("utf-8")).requests())


class TestJsParser:
    def test_concat_url_and_verb(self) -> None:
        recs = _parse('function cancelOrder(orderId) { $.ajax({type: "get", url: "/api/v1/cancelservice/cancel/" '
                      '+ orderId + "/" + sessionStorage.getItem("client_id")}); }')
        assert recs[0]["verb"] == "GET"
        assert recs[0]["variants"] == [("/api/v1/cancelservice/cancel/{orderId}/{client_id}", [])]
        assert recs[0]["function"] == "cancelOrder"

    def test_url_variable_with_branches(self) -> None:
        recs = _parse('function book() { var path; if (t == "G") { path = "/a/x"; } else { path = "/a/y"; } '
                      '$.ajax({type: "post", url: path, data: JSON.stringify(info)}); }')
        assert recs[0]["variants"] == [("/a/x", ['t == "G"']), ("/a/y", ['!(t == "G")'])]

    def test_helper_param_resolved_per_call_site(self) -> None:
        recs = _parse('var v = new Vue({methods: {'
                      'refresh() { var q = new Object(); q.enableStateQuery = false; q.loginId = id;'
                      ' var d = JSON.stringify(q); this.send("/api/one", d); this.send("/api/two", d); },'
                      'send(path, data) { $.ajax({type: "post", url: path, data: data}); }}});')
        urls = sorted(u for r in recs for u, _ in r["variants"])
        assert urls == ["/api/one", "/api/two"]
        assert all(r["function"] == "refresh" for r in recs)
        assert all(r["body_consts"] == {"enableStateQuery": False} for r in recs)
        assert all(set(r["body_fields"]) == {"enableStateQuery", "loginId"} for r in recs)

    def test_guarded_literal_is_not_constant(self) -> None:
        recs = _parse('function f() { var o = new Object(); if (c) { o.food = 1; } else { o.food = 0; } o.w = 2;'
                      ' $.ajax({type: "post", url: "/x/y", data: JSON.stringify(o)}); }')
        assert recs[0]["body_consts"] == {"w": 2}
        assert {(c["field"], c["value"]) for c in recs[0]["body_cond"]} == {("food", 1), ("food", 0)}

    def test_angular_http_and_event_binding_name(self) -> None:
        recs = _parse('$("#go_btn").click(function () { $http({method: "put", url: "/api/v1/x/y"}); });')
        assert recs[0]["verb"] == "PUT"
        assert recs[0]["function"] == "click:#go_btn"


class TestMatchHandlers:
    H = [("a", "GET", ["api", "v1", "s", "order", "{id}"]), ("b", "GET", ["api", "v1", "s", "order", "admin"]),
         ("c", None, ["api", "v1", "s", "list"])]

    def test_placeholder_prefers_variable(self) -> None:
        assert match_handlers("GET", "/api/v1/s/order/{orderId}", self.H) == ["a"]

    def test_literal_and_any_verb(self) -> None:
        assert match_handlers("GET", "/api/v1/s/order/admin", self.H) == ["b"]
        assert match_handlers("POST", "/api/v1/s/list", self.H) == ["c"]
        assert match_handlers("POST", "/api/v1/s/order/1", self.H) == []


class TestCatalog:
    def test_preserve_variants_with_condition(self, catalog) -> None:
        by = catalog.by_handler()
        g = [r for r in by[PRESERVE] if "client_ticket_book" in r.file][0]
        o = [r for r in by[PRESERVE_OTHER] if "client_ticket_book" in r.file][0]
        assert g.group == o.group
        assert g.guards[-1] == "tripType == 'G' || tripType == 'D'"
        assert o.guards[-1] == "!(tripType == 'G' || tripType == 'D')"
        assert "client_ticket_book.html" in " ".join(g.pages)

    def test_request_in_response_handler_is_marked(self, catalog) -> None:
        diff = [r for r in catalog.requests if r.url == "/api/v1/rebookservice/rebook/difference"
                and r.file.endswith("client_order_list.js")][0]
        assert diff.guards[0] == "in the response handler of POST /api/v1/rebookservice/rebook"
        assert 'result["status"] == 2' in diff.guards

    def test_order_list_refresh_sends_two_requests(self, catalog) -> None:
        reqs = [r for r in catalog.requests if r.file.endswith("client_order_list.js") and r.function == "queryMyOrderList"]
        assert {h for r in reqs for h in r.handlers} == {ORDER_REFRESH, OTHER_REFRESH}
        assert all(r.body_consts.get("enableStateQuery") is False for r in reqs)

    def test_cancel_template(self, catalog) -> None:
        r = catalog.by_handler()[CANCEL][0]
        assert r.url == "/api/v1/cancelservice/cancel/{orderId}/{client_id}"


class TestRetrieval:
    def test_twins(self, handlers: HandlerCatalog) -> None:
        tw = twin_groups(handlers)
        assert PRESERVE_OTHER in tw[PRESERVE]
        assert OTHER_REFRESH in tw[ORDER_REFRESH]

    def test_rrf_and_candidates_with_twins(self) -> None:
        fused = [h for _, h in rrf([["a", "b", "c"], ["b", "a", "d"]])]
        assert fused[:2] == ["a", "b"] and set(fused) == {"a", "b", "c", "d"}
        r = Ranked(["x"], [], ["x", "y", "z"])
        assert r.candidates(2, {"x": ["x2"]}) == ["x", "x2", "y"]

    def test_handler_doc_has_dto_fields_and_ui(self, handlers: HandlerCatalog) -> None:
        h = handlers.handlers[PRESERVE]
        assert {"seatType", "assurance", "foodType"} <= {f["name"] for f in h.body_fields}
        text = handlers.render(PRESERVE, "code_ui")
        assert "POST /api/v1/preserveservice/preserve" in text and "client_ticket_book" in text
        assert "client_ticket_book" not in handlers.render(PRESERVE, "code")


class TestPrompts:
    def test_params_schema_nullable_typed(self, handlers: HandlerCatalog) -> None:
        fields = P.request_fields(handlers.handlers[PRESERVE])
        sch = P.params_schema(fields)
        assert sch["properties"]["seatType"] == {"type": ["integer", "null"]}
        assert sch["properties"]["tripId"] == {"type": ["string", "null"]}
        assert P.needs_params(handlers.handlers[PRESERVE])
        assert not P.needs_params(handlers.handlers[CANCEL])

    def test_handler_index_lists_every_handler(self, handlers: HandlerCatalog) -> None:
        labels = P.handler_labels(handlers.handlers)
        lines = P.handler_index(handlers.handlers, labels).splitlines()
        assert len(lines) == len(handlers.handlers) == len(set(labels.values()))
        cancel = next(ln for ln in lines if ln.startswith(labels[CANCEL] + ":"))
        assert cancel.endswith("-> CancelController#cancelTicket (ui)")
        assert P.select_schema(list(labels.values()), 1)["properties"]["handler"]["enum"][0] == "H1"

    def test_select_schema_refs(self) -> None:
        s1 = P.select_schema(["C1", "C2"], 1)
        assert s1["properties"]["refs"]["properties"] == {}
        s3 = P.select_schema(["C1"], 3)
        assert "new_of_step_2" in s3["properties"]["refs"]["properties"]["order"]["enum"]
        assert "first_of_step_3" not in s3["properties"]["refs"]["properties"]["order"]["enum"]

    def test_enum_codes_from_source(self, ix: SkeletonIndex) -> None:
        enums = enum_codes(ix, TARGETS)
        assert "FIRSTCLASS=2 (FirstClassSeat)" in enums["SeatClass"]
        assert any(v.startswith("PAID=1") for v in enums["OrderStatus"])


class TestLLMCache:
    def test_key_depends_on_model_version_and_input(self, tmp_path: Path) -> None:
        c = LLMClient(model="m", use_server=False, cache_dir=tmp_path)
        msgs = [{"role": "user", "content": "x"}]
        k = c.key("v1", msgs, {"type": "object"})
        assert k.startswith("sha256:")
        assert k != c.key("v2", msgs, {"type": "object"})
        assert k != LLMClient(model="m2", use_server=False, cache_dir=tmp_path).key("v1", msgs, {"type": "object"})

    def test_cache_hit_without_server(self, tmp_path: Path) -> None:
        c = LLMClient(model="m", use_server=False, cache_dir=tmp_path)
        msgs = [{"role": "user", "content": "x"}]
        resp, key = c.complete_json("select", "v1", msgs, {"type": "object"})
        assert resp is None and c.stats.misses == 1
        (tmp_path / f"{key.split(':', 1)[1]}.json").write_text(json.dumps({"response": {"candidate": "C1"}}),
                                                               encoding="utf-8")
        resp, _ = c.complete_json("select", "v1", msgs, {"type": "object"})
        assert resp == {"candidate": "C1"} and c.stats.hits == 1


class TestGrounderFallback:
    def test_no_models_gives_valid_requests(self, ix: SkeletonIndex) -> None:
        g = StepGrounder(ix, TARGETS, embedder=None, llm=None)
        sc = load_json(TT / "scenarios" / "S7.json")
        reqs = g.ground_scenario(sc)
        assert len(reqs) == len(sc["steps"])
        assert all(r.handler in ix.N and r.grounding["source"] == "RETRIEVAL" for r in reqs)
        assert reqs[0].handler.endswith("UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)")
        assert reqs[8].expected_outcome == "refused"  # «the system refuses»
        assert reqs[0].expected_outcome == "success"
