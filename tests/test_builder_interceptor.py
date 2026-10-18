"""Перехватчик методов в GraphBuilder.traverse: контракт MethodInterceptor и TraversalContext (M4, ADR-005).

Тесты не зависят от M4: перехватчики здесь — тестовые заглушки.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from engine.adapters.skeleton import load_json
from engine.decisions import DecisionLedger
from engine.graph.builder import TraversalContext
from engine.pipeline import ArchonityPipeline
from engine.rules import ScenarioProfile
from engine.state import ScenarioState

ROOT = Path(__file__).resolve().parent.parent
SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"
TARGETS_ROOT = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"
SCENARIOS_DIR = ROOT / "hackaton" / "tt-challenge" / "scenarios"

# Короткая цепочка S0, шаг 2: контроллер -> сервис -> таблица contacts
CTL_FIND = "method:ts-contacts-service:contacts.controller.ContactsController#findContactsByAccountId(java.lang.String,?HttpHeaders)"
SVC_FIND = (
    "method:ts-contacts-service:contacts.service.ContactsServiceImpl#findContactsByAccountId("
    "java.lang.String,org.springframework.http.HttpHeaders)"
)
SVC_ALL = "method:ts-contacts-service:contacts.service.ContactsServiceImpl#getAllContacts(org.springframework.http.HttpHeaders)"
CONTACTS_TABLE = "res:table:ts-contacts-service.contacts"
CONTACTS_UNIT = "ts-contacts-service"
# Мёртвый код по rules.py: заглушки /welcome
HOME_CONTACTS = "method:ts-contacts-service:contacts.controller.ContactsController#home()"
HOME_ADMIN = "method:ts-admin-basic-info-service:adminbasic.controller.AdminBasicInfoController#home(org.springframework.http.HttpHeaders)"
# S0, шаг 3: refresh заказов "Other"; queryOrders — метод с отсевом по дате (_apply_framework_and_entity_lifecycle)
CTL_REFRESH = (
    "method:ts-order-other-service:other.controller.OrderOtherController#queryOrdersForRefresh("
    "other.entity.QueryInfo,org.springframework.http.HttpHeaders)"
)
SVC_REFRESH = (
    "method:ts-order-other-service:other.service.OrderOtherServiceImpl#queryOrdersForRefresh("
    "other.entity.QueryInfo,java.lang.String,org.springframework.http.HttpHeaders)"
)
QUERY_ORDERS = (
    "method:ts-order-other-service:other.service.OrderOtherServiceImpl#queryOrders("
    "other.entity.QueryInfo,java.lang.String,org.springframework.http.HttpHeaders)"
)
STRING2DATE = "method:ts-common:edu.fudan.common.util.StringUtils#String2Date(java.lang.String)"
ORDERS_OTHER_TABLE = "res:table:ts-order-other-service.orders_other"

Result = tuple[set[str], set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]


@pytest.fixture(scope="module")
def pipeline(shared_pipeline: ArchonityPipeline) -> ArchonityPipeline:
    return shared_pipeline


class Recorder:
    """Перехватчик: хочет заданные методы; каждый run записывает и отдаёт в on_run."""

    def __init__(
        self,
        wanted: set[str],
        on_run: Callable[[str, str, TraversalContext], None] | None = None,
    ) -> None:
        self.wanted = set(wanted)
        self.on_run = on_run
        self.asked: list[str] = []
        self.runs: list[tuple[str, str, bool]] = []

    def wants(self, method_id: str) -> bool:
        self.asked.append(method_id)
        return method_id in self.wanted

    def run(self, method_id: str, unit: str, ctx: TraversalContext, entry: bool) -> None:
        self.runs.append((method_id, unit, entry))
        if self.on_run is not None:
            self.on_run(method_id, unit, ctx)


class StepEnv:
    """Профиль и состояние шага S0 для прямого вызова traverse."""

    def __init__(self, pipeline: ArchonityPipeline, step_index: int) -> None:
        scenario = load_json(SCENARIOS_DIR / "S0.json")
        profile = ScenarioProfile.from_scenario(scenario)
        self.profile = profile.for_step(scenario["steps"][step_index])
        db_state = getattr(pipeline.index, "db_state", None)
        self.state = ScenarioState.create_initial(db_state=db_state.fork() if db_state else None, scenario_profile=profile)


def traverse(
    pipeline: ArchonityPipeline,
    env: StepEnv,
    entries: list[str],
    interceptor: Recorder | None = None,
    ledger: DecisionLedger | None = None,
) -> Result:
    return pipeline.builder.traverse(
        entries,
        is_admin_scenario=env.profile.is_admin,
        profile=env.profile,
        scenario_state=env.state,
        ledger=ledger,
        interceptor=interceptor,
    )


def new_ledger() -> DecisionLedger:
    ledger = DecisionLedger()
    ledger.begin_scenario("T")
    return ledger


def answer_edges(result: Result) -> set[tuple[str, str, str]]:
    methods, calls, remote, data = result
    out = {("executes", "scenario:T", m) for m in methods}
    out |= {("calls", s, t) for s, t in calls}
    out |= {("remote", s, t) for s, t in remote}
    out |= {("data", s, t) for s, t in data}
    return out


def test_fixture_methods_exist_in_skeleton(pipeline: ArchonityPipeline) -> None:
    """Страховка: если скелет изменится, тесты упадут здесь, а не загадочно ниже."""
    for m in (CTL_FIND, SVC_FIND, SVC_ALL, HOME_CONTACTS, HOME_ADMIN, CTL_REFRESH, SVC_REFRESH, QUERY_ORDERS, STRING2DATE):
        assert m in pipeline.index.N, m
        assert pipeline.rules.is_dead_code_method(m) is (m in (HOME_CONTACTS, HOME_ADMIN))


class TestNoopInterceptor:
    """Перехватчик, который ничего не хочет, не меняет ни выдачу, ни журнал."""

    @pytest.mark.parametrize("path", sorted(SCENARIOS_DIR.glob("S*.json")), ids=lambda p: p.stem)
    def test_scenario_answer_and_ledger_unchanged(self, pipeline: ArchonityPipeline, path: Path) -> None:
        scenario = load_json(path)
        sid = scenario["id"]
        orig_traverse = pipeline.builder.traverse
        noop = Recorder(set())

        def traverse_with_noop(*args: Any, **kwargs: Any) -> Result:
            return orig_traverse(*args, interceptor=noop, **kwargs)

        plain = pipeline.run_scenario(scenario)
        plain_ledger = pipeline.ledger.scenario_dict(sid)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(pipeline.builder, "traverse", traverse_with_noop)
            with_noop = pipeline.run_scenario(scenario)
        noop_ledger = pipeline.ledger.scenario_dict(sid)

        assert plain[0], f"{sid}: пустая выдача, сравнение бессмысленно"
        assert noop.asked, f"{sid}: перехватчик ни разу не опрошен"
        assert not noop.runs
        for name, a, b in zip(("executes", "calls", "remote", "data"), plain, with_noop):
            assert a == b, f"{sid}: {name} разошлись"
        assert plain_ledger == noop_ledger, f"{sid}: журнал решений разошёлся"

    def test_entry_dead_code_still_filtered(self, pipeline: ArchonityPipeline) -> None:
        env = StepEnv(pipeline, 1)
        noop = Recorder(set())
        assert traverse(pipeline, env, [HOME_CONTACTS], noop) == traverse(pipeline, env, [HOME_CONTACTS])
        assert traverse(pipeline, env, [HOME_CONTACTS], noop)[0] == set()


class TestInterceptedMethod:
    def test_intercepted_inner_method(self, pipeline: ArchonityPipeline) -> None:
        """run ровно один раз с unit и entry=False; рёбра перехватчика в выдаче, legacy-рёбра метода нет."""
        env = StepEnv(pipeline, 1)
        base = traverse(pipeline, env, [CTL_FIND])
        assert (SVC_FIND, CONTACTS_TABLE) in base[3], "в legacy у перехватываемого метода должно быть ребро data"
        helper = traverse(pipeline, env, [SVC_ALL])
        assert helper[3], "SVC_ALL должен раскрываться legacy в ребро data"

        def on_run(m: str, u: str, ctx: TraversalContext) -> None:
            ctx.edges_calls.add((m, SVC_ALL))
            ctx.reached_via.setdefault(SVC_ALL, ("IR_BRANCH", "test", f"calls|{m}|{SVC_ALL}"))
            ctx.stack.append((SVC_ALL, u))
            if ctx.ledger is not None:
                ctx.ledger.include("calls", m, SVC_ALL, "IR_BRANCH", "test")

        interceptor = Recorder({SVC_FIND}, on_run)
        ledger = new_ledger()
        result = traverse(pipeline, env, [CTL_FIND], interceptor, ledger)
        methods, calls, remote, data = result

        assert interceptor.runs == [(SVC_FIND, CONTACTS_UNIT, False)]
        # SVC_ALL положен в ctx.stack, его раскрыл legacy
        assert data == helper[3]
        assert calls == {(CTL_FIND, SVC_FIND), (SVC_FIND, SVC_ALL)} | helper[1]
        assert methods == {CTL_FIND, SVC_FIND, SVC_ALL} | helper[0]
        assert remote == set()
        # legacy-рёбер перехваченного метода нет
        assert not any(s == SVC_FIND for s, _ in data)
        assert {t for s, t in calls if s == SVC_FIND} == {SVC_ALL}
        # журнал сходится с ответом
        assert ledger.final_edges("T") == answer_edges(result)
        records = ledger.scenario_dict("T")
        call_record = records[f"calls|{SVC_FIND}|{SVC_ALL}"]
        assert (call_record["source_type"], call_record["rule"]) == ("IR_BRANCH", "test")
        # reached_via, заданный перехватчиком, попадает в журнал executes
        assert records[f"executes|scenario:T|{SVC_ALL}"]["source_type"] == "IR_BRANCH"

    def test_intercepted_entry(self, pipeline: ArchonityPipeline) -> None:
        """Перехваченная точка входа: entry=True; если перехватчик повторяет legacy, выдача совпадает с обходом без него."""
        env = StepEnv(pipeline, 1)
        base = traverse(pipeline, env, [CTL_FIND])
        seen_ctx: list[TraversalContext] = []

        def on_run(m: str, u: str, ctx: TraversalContext) -> None:
            seen_ctx.append(ctx)
            assert (m, u) in ctx.seen_methods
            ctx.edges_calls.add((m, SVC_FIND))
            ctx.stack.append((SVC_FIND, u))

        interceptor = Recorder({CTL_FIND}, on_run)
        result = traverse(pipeline, env, [CTL_FIND], interceptor)

        assert interceptor.runs == [(CTL_FIND, CONTACTS_UNIT, True)]
        assert result == base
        assert seen_ctx[0].entries == frozenset({CTL_FIND})

    def test_context_shares_traversal_objects(self, pipeline: ArchonityPipeline) -> None:
        """Контекст отдаёт профиль, состояние и журнал вызова traverse, а изменения множеств попадают в выдачу."""
        env = StepEnv(pipeline, 1)
        ledger = new_ledger()
        marker_call = (CTL_FIND, SVC_ALL)
        marker_remote = (CTL_FIND, "method:ts-test:Stub#remote()")
        marker_data = (CTL_FIND, CONTACTS_TABLE)
        captured: list[TraversalContext] = []

        def on_run(m: str, u: str, ctx: TraversalContext) -> None:
            captured.append(ctx)
            ctx.edges_calls.add(marker_call)
            ctx.edges_remote.add(marker_remote)
            ctx.edges_data.add(marker_data)

        methods, calls, remote, data = traverse(pipeline, env, [CTL_FIND], Recorder({CTL_FIND}, on_run), ledger)
        ctx = captured[0]

        assert ctx.profile is env.profile
        assert ctx.scenario_state is env.state
        assert ctx.ledger is ledger
        assert ctx.is_admin_scenario == env.profile.is_admin
        assert ctx.entries == frozenset({CTL_FIND})
        assert marker_call in calls and marker_remote in remote and marker_data in data
        # перехватчик ничего не положил в стек: legacy-раскрытия перехваченного входа не было
        assert methods == {CTL_FIND}

    def test_intercepted_dead_code_entry_not_filtered(self, pipeline: ArchonityPipeline) -> None:
        """Точку входа, которую хочет перехватчик, is_dead_code_method не отсеивает; остальные — как раньше."""
        env = StepEnv(pipeline, 1)
        base_ledger = new_ledger()
        assert traverse(pipeline, env, [HOME_CONTACTS, HOME_ADMIN], ledger=base_ledger)[0] == set()
        assert not base_ledger.scenario_dict("T")[f"executes|scenario:T|{HOME_CONTACTS}"]["included"]

        interceptor = Recorder({HOME_CONTACTS})
        ledger = new_ledger()
        methods, calls, remote, data = traverse(pipeline, env, [HOME_CONTACTS, HOME_ADMIN], interceptor, ledger)

        assert interceptor.runs == [(HOME_CONTACTS, CONTACTS_UNIT, True)]
        assert methods == {HOME_CONTACTS}
        assert not (calls or remote or data)
        records = ledger.scenario_dict("T")
        assert records[f"executes|scenario:T|{HOME_CONTACTS}"]["included"]
        assert not records[f"executes|scenario:T|{HOME_ADMIN}"]["included"]

    @pytest.mark.parametrize("wants_query_orders", [False, True])
    def test_query_orders_date_filter_left_to_interceptor(
        self, pipeline: ArchonityPipeline, wants_query_orders: bool
    ) -> None:
        """Отсев queryOrders -> String2Date по дате пропускается, если queryOrders хочет перехватчик."""
        env = StepEnv(pipeline, 2)
        assert not env.state.has_date_filter_query()

        def on_run(m: str, u: str, ctx: TraversalContext) -> None:
            ctx.edges_calls.add((QUERY_ORDERS, STRING2DATE))
            ctx.edges_data.add((QUERY_ORDERS, ORDERS_OTHER_TABLE))

        wanted = {SVC_REFRESH} | ({QUERY_ORDERS} if wants_query_orders else set())
        interceptor = Recorder(wanted, on_run)
        ledger = new_ledger()
        _, calls, _, data = traverse(pipeline, env, [CTL_REFRESH], interceptor, ledger)

        assert interceptor.runs == [(SVC_REFRESH, "ts-order-other-service", False)]
        assert (QUERY_ORDERS, ORDERS_OTHER_TABLE) in data
        if wants_query_orders:
            assert (QUERY_ORDERS, STRING2DATE) in calls
        else:
            assert (QUERY_ORDERS, STRING2DATE) not in calls
            decisions = ledger.scenario_dict("T")[f"calls|{QUERY_ORDERS}|{STRING2DATE}"]["decisions"]
            assert [(d["op"], d["source_type"], d["rule"]) for d in decisions] == [("discard", "STATE", "date_filter")]
