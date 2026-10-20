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

    def test_fields_sent_only_under_condition(self, catalog) -> None:
        g = [r for r in catalog.by_handler()[PRESERVE] if "client_ticket_book" in r.file][0]
        opt = {o["field"]: o["guards"] for o in g.body_opt}
        assert opt["consigneeWeight"] == opt["isWithin"] == ["$('#need-consign-or-not').is(\":checked\")"]
        assert "foodPrice" in opt and "seatType" not in opt and "assurance" not in opt
        # условие, под которым уходит весь запрос (проверка ввода в админке), поле не отделяет
        assert not [r for r in catalog.requests if r.body_opt and "/admin" in r.url]

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

    def test_sampling_in_key_only_when_given(self, tmp_path: Path) -> None:
        import hashlib

        c = LLMClient(model="m", use_server=False, cache_dir=tmp_path)
        msgs = [{"role": "user", "content": "x"}]
        raw = json.dumps({"model": "m", "prompt_version": "v1", "messages": msgs, "schema": {"type": "object"}},
                         ensure_ascii=False, sort_keys=True)
        # ключ жадного вызова — как до голосования (кеш m1-v7 и profile-v1 не сдвигается)
        assert c.key("v1", msgs, {"type": "object"}) == "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
        k1 = c.key("v1", msgs, {"type": "object"}, {"temperature": 0.7, "seed": 1})
        assert k1 != c.key("v1", msgs, {"type": "object"}) != c.key("v1", msgs, {"type": "object"}, {"seed": 2})

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


STATION_STORES = "method:ts-station-food-service:food.controller.StationFoodController#getFoodStoresOfStation(java.lang.String,org.springframework.http.HttpHeaders)"
STATION_BY_NAMES = "method:ts-station-food-service:food.controller.StationFoodController#getFoodStoresByStationNames(java.util.List)"
ORDER_PRICE = "method:ts-order-service:order.controller.OrderController#getOrderPrice(java.lang.String,org.springframework.http.HttpHeaders)"


class TestUnboundHandlers:
    """R20: обработчик, который Spring вызвать не может (`@PathVariable` не совпадает с шаблоном пути)."""

    def test_only_station_stores_handler_is_unbound(self, ix: SkeletonIndex, handlers: HandlerCatalog) -> None:
        from engine.grounding.binding import unbound_path_variables

        bad = {h.id: unbound_path_variables(ix, h) for h in handlers.handlers.values()}
        bad = {k: v for k, v in bad.items() if v}
        assert bad == {STATION_STORES: ["stationName"]}

    def test_stem_matches_list_parameter(self) -> None:
        from engine.grounding.binding import _stem

        assert _stem("stationNameList") == _stem("stationNames") == _stem("stationName") == "stationname"
        assert _stem("stationFoodStoreId") != "stationname"

    def test_rebind_to_working_handler_of_same_controller(self, ix: SkeletonIndex) -> None:
        from engine.grounding.request import StepRequest

        g = StepGrounder(ix, TARGETS, embedder=None, llm=None)
        req = StepRequest(scenario="S2", step=4, action="Browse the food stores at Suzhou station",
                          handler=STATION_STORES, http={}, params={"stationId": "suzhou"}, grounding={"source": "LLM"})
        got = g.rebind(req)
        assert got is not None and got.handler == STATION_BY_NAMES
        assert got.http == {"method": "POST", "path": "/api/v1/stationfoodservice/stationfoodstores"}
        assert got.params == {} and got.grounding["rebound"]["from"] == STATION_STORES
        # рабочий обработчик не трогаем
        assert g.rebind(StepRequest(scenario="S1", step=9, action="x", handler=ORDER_PRICE, http={})) is None


class _FakeLLM:
    """LLM-заглушка: отдаёт заданный ответ и запоминает запрос."""

    def __init__(self, resp: dict) -> None:
        self.resp = resp
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, kind, prompt_version, messages, schema, max_tokens=600):
        self.calls.append((kind, prompt_version))
        return self.resp, "sha256:fake"


# Слова домена Train Ticket, которых нет в шаблонах v8 (ADR-007, критерий 4)
DOMAIN_WORDS = ("train", "trip", "gaotie", "dongche", "seat", "assurance", "consign", "passenger", "ts-ui-dashboard")


class TestProjectProfile:
    """ADR-007: промпт v8 без домена, профиль проекта, режим отката v7."""

    def test_v8_templates_have_no_domain_words(self) -> None:
        for t in (P.SYSTEM_V8, P.TWINS_V8, P.SELECT_TASK_V8, P.PARAMS_TASK_V8, P.KINDS_V8):
            low = t.lower()
            assert not [w for w in DOMAIN_WORDS if w in low]

    def test_v7_mode_keeps_old_prompt(self, ix: SkeletonIndex) -> None:
        g = StepGrounder(ix, TARGETS, embedder=None, llm=None, prompt="v7")
        assert g.version == P.PROMPT_VERSION == "m1-v7"
        assert g.system_params.startswith("You map steps of a user scenario in the Train Ticket web application")

    def test_v7_embedder_query_text_unchanged(self) -> None:
        from engine.grounding.embedder import QUERY_TASK_V7, SPECS

        # ключи векторов кеша v7 — от этого текста
        assert SPECS["qwen3-4b"].query_fmt.format(q="Log in", task=QUERY_TASK_V7) == (
            "Instruct: Given a user action in a train ticket booking web app, retrieve the REST endpoint handler that "
            "implements it\nQuery: Log in")

    def test_find_ui_dir(self, ix: SkeletonIndex) -> None:
        from engine.grounding.ui_catalog import find_ui_dir

        assert find_ui_dir(TARGETS, ix) == "ts-ui-dashboard"

    def test_twin_pairs_split_the_same_way(self, ix: SkeletonIndex, handlers: HandlerCatalog) -> None:
        from engine.grounding.profile import same_split, twin_pairs

        pairs = twin_pairs(handlers, twin_groups(handlers))
        assert [(p.base, p.variant, p.marker) for p in pairs] == [
            ("ts-order-service", "ts-order-other-service", "other"),
            ("ts-preserve-service", "ts-preserve-other-service", "other"),
            ("ts-travel-service", "ts-travel2-service", "2"),
        ]
        # preserve -> order, travel и preserve-other -> order-other, travel2 (remote_call скелета)
        assert same_split(ix, pairs) == [[1, 2, 3]]

    def test_profile_input_has_ui_conditions(self, ix: SkeletonIndex, catalog, handlers: HandlerCatalog) -> None:
        from engine.grounding.profile import profile_messages, twin_pairs

        msgs = profile_messages(ix, TARGETS, handlers, catalog, twin_pairs(handlers, twin_groups(handlers)))
        text = msgs[1]["content"]
        assert "!(tripType == 'G' || tripType == 'D')" in text
        assert "var tripType = orderTicketInfo.tripId.charAt(0);" in text
        assert "{text: 'Other', value: 2}" in text and "{text: 'All', value: 0}" not in text
        assert "(both sides: all of the data)" in text

    def test_v8_prompt_from_profile(self, ix: SkeletonIndex) -> None:
        resp = {"analysis": "x", "domain_summary": "A shop.", "twins": {
            "pair_1": {"ts-order-service": "Base side: kind A orders", "ts-order-other-service": "kind B orders",
                       "choose_by": "By kind."}}}
        llm = _FakeLLM(resp)
        g = StepGrounder(ix, TARGETS, embedder=None, llm=llm, prompt="v8")
        assert llm.calls == [("profile", "profile-v1")] and g.version == "m1-v8"
        assert "The application: A shop." in g.system_select
        assert "Some services come in twins" in g.system_select
        # правило пары и что хранит сторона — только в карточке кандидата
        assert "By kind." not in g.system_select and "kind A orders" not in g.system_select
        assert "Train Ticket" not in g.system_params and "/api/v1/<service>/**" in g.system_params
        assert P.twin_note(g.profile, "ts-order-other-service") == (
            "twin of ts-order-service; this variant side: kind B orders; choose the side by: By kind.")
        # у пары без правила профилировщика строки нет
        assert P.twin_note(g.profile, "ts-travel2-service") is None

    def test_followup_note_from_server_answers(self, ix: SkeletonIndex, handlers: HandlerCatalog) -> None:
        rebook = next(h for h in handlers.handlers if "RebookController#rebook(" in h)
        assert handlers.answers(rebook)[2] == ["Please pay the different money!"]
        card = StepGrounder(ix, TARGETS, embedder=None, prompt="v8")._candidate(rebook)
        assert "only after POST /api/v1/rebookservice/rebook answers status 2" in card
        assert "follow-up" not in StepGrounder(ix, TARGETS, embedder=None)._candidate(rebook)

    def test_answer_guards_from_ir(self, ix: SkeletonIndex, catalog) -> None:
        from engine.grounding.grounder import ROOT

        cat = HandlerCatalog(ix, TARGETS, catalog, ROOT / "data" / "ir")
        rebook = next(h for h in cat.handlers if "RebookController#rebook(" in h)
        assert cat.answer_guards(rebook)[2] == [
            "!(priceOld.compareTo(priceNew) > 0) && !(priceOld.compareTo(priceNew) == 0)"]
        assert HandlerCatalog(ix, TARGETS, catalog).answer_guards(rebook) == {}  # без IR — пусто
        card = StepGrounder(ix, TARGETS, embedder=None, prompt="v8")._candidate(rebook)
        assert "its code returns it when !(priceOld.compareTo(priceNew) > 0)" in card

    def test_service_calls_in_card(self, ix: SkeletonIndex, handlers: HandlerCatalog) -> None:
        rebook = next(h for h in handlers.handlers if "RebookController#rebook(" in h)
        diff = next(h for h in handlers.handlers if "RebookController#payDifference(" in h)
        assert "drawBackMoney" in handlers.service_calls(rebook)
        assert "payDifferentMoney" in handlers.service_calls(diff) and "drawBackMoney" not in handlers.service_calls(diff)
        assert "its service code calls: checkTime, drawBackMoney" in StepGrounder(ix, TARGETS, embedder=None,
                                                                                 prompt="v8")._candidate(rebook)

    def test_v8_ref_kinds_from_manifest(self, ix: SkeletonIndex) -> None:
        g = StepGrounder(ix, TARGETS, embedder=None, prompt="v8")
        assert {"trainType", "trip", "consignRecord", "contacts", "priceConfig"} <= set(g.ref_kinds)
        assert "train" not in g.ref_kinds and "consign" not in g.ref_kinds
        # пример refs — два вида, на которые чаще всего ссылаются поля запросов
        assert g.example_kinds == ("order", "trip")
        assert "- consignRecord: ConsignRecord (ts-consign-service)" in g.system_select
        assert "Record kinds" not in g.system_params
        props = P.select_schema(list(g.by_label), 3, g.ref_kinds)["properties"]["refs"]["properties"]
        assert set(props) == set(g.ref_kinds)
        # v8: refs — массив пар {kind, ref}: порядок видов свободный (грамматика схемы держит порядок свойств объекта)
        pairs = P.select_schema(list(g.by_label), 3, g.ref_kinds, ref_pairs=True)["properties"]["refs"]
        assert pairs["type"] == "array" and pairs["items"]["properties"]["kind"]["enum"] == list(g.ref_kinds)
        sel = {"refs": [{"kind": "trip", "ref": "first_of_step_2"}, {"kind": "contacts", "ref": "new_of_step_3"},
                        {"kind": "trip", "ref": "new_of_step_1"}]}
        assert P.refs_of(sel) == {"trip": "first_of_step_2", "contacts": "new_of_step_3"}
        assert P.refs_of({"refs": {"trip": "first_of_step_2", "order": None}}) == {"trip": "first_of_step_2"}
        # v7 — прежние виды
        assert StepGrounder(ix, TARGETS, embedder=None).ref_kinds == P.REF_ENTITIES

    def test_bm25_without_domain_synonyms(self) -> None:
        from engine.grounding.text import query_toks

        assert "consign" in query_toks("luggage")
        assert "consign" not in query_toks("luggage", None)
