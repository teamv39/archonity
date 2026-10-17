"""Тесты судьи M4 (engine/executor/judge.py): промпт, кеш, бюджет, режимы. Без сети и без настоящей LLM."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from engine.executor.judge import (
    JUDGE_PROMPT_VERSION,
    JUDGE_SCHEMA,
    VERDICTS,
    Judge,
    JudgeQuery,
    JudgeStats,
)
from engine.grounding.llm import LLMClient

FILE = "svc/src/Foo.java"
CONTEXT = {
    "profile": "Default Spring profile",
    "account": "Pre-registered user fdse_microservice",
    "date": "All trips are booked for 1 October 2026",
}


class FakeLLM:
    """Те же методы, что использует судья; кеш в словаре, вызовы сервера считаются."""

    def __init__(self, verdict: str | None = "TRUE", server_up: bool = True, refresh: bool = False) -> None:
        self.cache: dict[str, dict[str, Any]] = {}
        self.refresh = refresh
        self.server_up = server_up
        self.verdict = verdict
        self.server_calls = 0
        self.key_calls = 0
        self.complete_calls = 0

    def key(self, prompt_version: str, messages: list[dict[str, str]], schema: dict[str, Any]) -> str:
        self.key_calls += 1
        raw = json.dumps({"v": prompt_version, "m": messages, "s": schema}, ensure_ascii=False, sort_keys=True)
        return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def is_cached(self, key: str) -> bool:
        return key in self.cache

    def complete_json(self, kind: str, prompt_version: str, messages: list[dict[str, str]],
                      schema: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        self.complete_calls += 1
        key = self.key(prompt_version, messages, schema)
        if not self.refresh and key in self.cache:
            return self.cache[key], key
        if not self.server_up:
            return None, key
        self.server_calls += 1
        resp: dict[str, Any] = {"cited_line": "if (x)", "reasoning": "потому что"}
        if self.verdict is not None:
            resp["verdict"] = self.verdict
        self.cache[key] = resp
        return resp, key


def make_source(tmp_path: Path, n: int = 30, name: str = FILE) -> Path:
    """Файл из n строк вида `    int vK = K;` (строка K имеет текст `    int vK = K;`)."""
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(f"    int v{k} = {k};" for k in range(1, n + 1)) + "\n", encoding="utf-8")
    return p


def src_line(k: int) -> str:
    return f"    int v{k} = {k};"


def query(**over: Any) -> JudgeQuery:
    base = JudgeQuery(
        scenario_id="S1", scenario_title="Отмена заказа", scenario_description="Пользователь отменяет оплаченный заказ.",
        step_n=3, step_action="Отменить заказ", expected_outcome="success",
        step_params={"orderId": "o1"}, step_refs={"order": "new_of_step_2"},
        method_id="method:svc:a.Foo#bar(java.lang.String)", file=FILE,
        method_line=5, method_end=20, cond_line=10, cond_end=10, condition="order.getStatus() == 1", kind="if",
        path=("Foo#bar called from Ctrl#cancel", "took then at line 7"),
        facts=("order.status = PAID",), state=("order o1: PAID",),
    )
    return replace(base, **over)


def user_text(j: Judge, q: JudgeQuery) -> str:
    return j.render_messages(q)[1]["content"]


def source_lines(text: str) -> list[str]:
    """Строки блока исходника из user-сообщения: от подсказки до строки пути."""
    lines = text.split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith("Method source")) + 1
    end = next(i for i, ln in enumerate(lines) if ln == "" and i > start)
    return lines[start:end]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    make_source(tmp_path)
    return tmp_path


class TestModes:
    def test_off_never_touches_client(self, root: Path) -> None:
        llm = FakeLLM()
        j = Judge(root, CONTEXT, llm, mode="off")
        assert j.ask(query()) is None
        assert (llm.key_calls, llm.complete_calls, llm.server_calls) == (0, 0, 0)
        assert j.stats.asked == 1 and j.stats.skipped_off == 1 and j.stats.misses == 0

    def test_unknown_mode_rejected(self, root: Path) -> None:
        with pytest.raises(ValueError):
            Judge(root, CONTEXT, FakeLLM(), mode="auto")

    def test_no_client(self, root: Path) -> None:
        j = Judge(root, CONTEXT, None, mode="on")
        assert j.ask(query()) is None
        assert j.stats.asked == 1 and j.stats.misses == 1 and j.stats.server_calls == 0

    def test_cache_mode_miss_does_not_call_server(self, root: Path) -> None:
        llm = FakeLLM()
        j = Judge(root, CONTEXT, llm, mode="cache")
        assert j.ask(query()) is None
        assert llm.server_calls == 0 and llm.complete_calls == 0
        assert j.stats.misses == 1 and j.stats.server_calls == 0

    def test_cache_mode_hit_answers(self, root: Path) -> None:
        llm = FakeLLM()
        Judge(root, CONTEXT, llm, mode="on").ask(query())  # заполнили кеш
        j = Judge(root, CONTEXT, llm, mode="cache")
        v = j.ask(query())
        assert v is not None and v.verdict == "TRUE" and v.from_cache
        assert llm.server_calls == 1 and j.stats.cache_hits == 1 and j.stats.server_calls == 0

    def test_server_error_is_miss(self, root: Path) -> None:
        llm = FakeLLM(server_up=False)
        j = Judge(root, CONTEXT, llm, mode="on")
        assert j.ask(query()) is None
        assert j.stats.misses == 1 and j.stats.server_calls == 1 and j.stats.skipped_budget == 0

    def test_refresh_ignores_cache(self, root: Path) -> None:
        llm = FakeLLM()
        Judge(root, CONTEXT, llm, mode="on").ask(query())
        llm.refresh = True
        j = Judge(root, CONTEXT, llm, mode="on")
        v = j.ask(query())
        assert v is not None and not v.from_cache
        assert llm.server_calls == 2 and j.stats.cache_hits == 0 and j.stats.server_calls == 1
        # в режиме cache при refresh сервер не зовём
        j2 = Judge(root, CONTEXT, llm, mode="cache")
        assert j2.ask(query()) is None and llm.server_calls == 2 and j2.stats.misses == 1


class TestBudget:
    def test_budget_limits_server_calls_but_not_cache_hits(self, root: Path) -> None:
        llm = FakeLLM()
        j = Judge(root, CONTEXT, llm, mode="on", budget=2)
        qs = [query(step_n=n) for n in (1, 2, 3)]
        assert j.ask(qs[0]) is not None
        assert j.ask(qs[1]) is not None
        assert j.ask(qs[2]) is None  # бюджет исчерпан, промах кеша
        assert j.stats.server_calls == 2 and j.stats.skipped_budget == 1 and llm.server_calls == 2
        # попадания в кеш бесплатны и после исчерпания бюджета
        again = j.ask(qs[0])
        assert again is not None and again.from_cache
        assert j.stats.cache_hits == 1 and j.stats.server_calls == 2 and llm.server_calls == 2
        # новые промахи по-прежнему отказ
        assert j.ask(query(step_n=4)) is None
        assert j.stats.skipped_budget == 2 and j.stats.asked == 5

    def test_zero_budget(self, root: Path) -> None:
        llm = FakeLLM()
        j = Judge(root, CONTEXT, llm, mode="on", budget=0)
        assert j.ask(query()) is None
        assert llm.server_calls == 0 and j.stats.skipped_budget == 1


class TestVerdict:
    def test_counters_and_fields(self, root: Path) -> None:
        for verdict, field in (("TRUE", "true"), ("FALSE", "false"), ("UNKNOWN", "unknown")):
            j = Judge(root, CONTEXT, FakeLLM(verdict=verdict))
            v = j.ask(query())
            assert v is not None and v.verdict == verdict
            assert v.cited_line == "if (x)" and v.reasoning == "потому что" and not v.from_cache
            assert v.cache_key.startswith("sha256:")
            assert getattr(j.stats, field) == 1 and j.stats.asked == 1

    def test_verdict_outside_enum_is_unknown(self, root: Path) -> None:
        j = Judge(root, CONTEXT, FakeLLM(verdict="MAYBE"))
        v = j.ask(query())
        assert v is not None and v.verdict == "UNKNOWN"
        assert j.stats.unknown == 1 and j.stats.true == 0 and j.stats.false == 0

    def test_missing_verdict_is_unknown(self, root: Path) -> None:
        j = Judge(root, CONTEXT, FakeLLM(verdict=None))
        v = j.ask(query())
        assert v is not None and v.verdict == "UNKNOWN" and j.stats.unknown == 1

    def test_stats_to_dict(self) -> None:
        d = JudgeStats(asked=3, true=1).to_dict()
        assert d["asked"] == 3 and d["true"] == 1
        assert set(d) == {"asked", "true", "false", "unknown", "cache_hits", "server_calls", "skipped_off",
                          "skipped_budget", "misses"}

    def test_schema_field_order(self) -> None:
        assert list(JUDGE_SCHEMA["properties"]) == ["cited_line", "reasoning", "verdict"]
        assert JUDGE_SCHEMA["properties"]["verdict"]["enum"] == list(VERDICTS)
        assert JUDGE_SCHEMA["required"] == ["cited_line", "reasoning", "verdict"]


class TestRealClientCache:
    def test_miss_then_hit_through_llm_client(self, root: Path, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        llm = LLMClient(model="m", use_server=False, cache_dir=cache)
        j = Judge(root, CONTEXT, llm, mode="on")
        q = query()
        assert j.ask(q) is None  # сервера нет
        assert j.stats.misses == 1 and j.stats.server_calls == 1
        key = llm.key(JUDGE_PROMPT_VERSION, j.render_messages(q), JUDGE_SCHEMA)
        assert not llm.is_cached(key)
        cache.mkdir()
        resp = {"cited_line": "c", "reasoning": "r", "verdict": "FALSE"}
        (cache / f"{key.split(':', 1)[1]}.json").write_text(json.dumps({"response": resp}), encoding="utf-8")
        assert llm.is_cached(key)
        v = j.ask(q)
        assert v is not None and v.verdict == "FALSE" and v.from_cache and v.cache_key == key
        assert j.stats.cache_hits == 1 and j.stats.server_calls == 1


class TestSourceRendering:
    def test_marker_only_on_condition_lines(self, root: Path) -> None:
        j = Judge(root, CONTEXT, None)
        lines = source_lines(user_text(j, query(cond_line=10, cond_end=12)))
        assert [ln for ln in lines if ln.startswith(">>")] == [f">> {k} | {src_line(k)}" for k in (10, 11, 12)]
        assert len(lines) == 16  # методы 5..20
        for ln in lines:
            if not ln.startswith(">>"):
                assert ln.startswith("   ")

    def test_single_line_condition(self, root: Path) -> None:
        j = Judge(root, CONTEXT, None)
        lines = source_lines(user_text(j, query(cond_line=7, cond_end=7)))
        marked = [ln for ln in lines if ln.startswith(">>")]
        assert marked == [f">>  7 | {src_line(7)}"]  # ширина номера 2: метод 5..20

    def test_line_numbers_match_file_and_right_aligned(self, root: Path) -> None:
        j = Judge(root, CONTEXT, None)
        lines = source_lines(user_text(j, query(method_line=8, method_end=12, cond_line=11, cond_end=11)))
        assert lines == [
            f"    8 | {src_line(8)}",
            f"    9 | {src_line(9)}",
            f"   10 | {src_line(10)}",
            f">> 11 | {src_line(11)}",
            f"   12 | {src_line(12)}",
        ]

    def test_method_range_clipped_to_file(self, root: Path) -> None:
        j = Judge(root, CONTEXT, None)
        lines = source_lines(user_text(j, query(method_line=28, method_end=99, cond_line=29, cond_end=29)))
        assert [ln[3:5] for ln in lines] == ["28", "29", "30"]

    def test_tabs_kept_and_crlf_stripped(self, tmp_path: Path) -> None:
        (tmp_path / "T.java").write_bytes(b"class T {\r\n\tint a;\r\n\tint b;\r\n}\r\n")
        j = Judge(tmp_path, None, None)
        q = query(file="T.java", method_line=1, method_end=4, cond_line=2, cond_end=2)
        assert source_lines(user_text(j, q)) == ["   1 | class T {", ">> 2 | \tint a;", "   3 | \tint b;", "   4 | }"]

    def test_source_not_available(self, tmp_path: Path) -> None:
        j = Judge(tmp_path, None, None)
        text = user_text(j, query(file="no/such/File.java"))
        assert "(source not available)" in text
        assert not any(ln.startswith(">>") for ln in text.split("\n"))

    def test_non_utf8_bytes_replaced(self, tmp_path: Path) -> None:
        (tmp_path / "B.java").write_bytes(b"int a; // \xff\xfe\nint b;\n")
        j = Judge(tmp_path, None, None)
        text = user_text(j, query(file="B.java", method_line=1, method_end=2, cond_line=2, cond_end=2))
        assert "�" in text and ">> 2 | int b;" in text

    def test_file_read_once(self, tmp_path: Path) -> None:
        p = make_source(tmp_path)
        j = Judge(tmp_path, None, None)
        first = user_text(j, query())
        p.unlink()
        assert user_text(j, query()) == first and "(source not available)" not in first

    def test_long_method_window_in_middle(self, tmp_path: Path) -> None:
        make_source(tmp_path, n=400)
        j = Judge(tmp_path, None, None)
        lines = source_lines(user_text(j, query(method_line=1, method_end=400, cond_line=200, cond_end=201)))
        assert lines[0] == f"     1 | {src_line(1)}"
        assert lines[1] == "..."
        assert lines[2] == f"   140 | {src_line(140)}"
        assert lines[-2] == f"   261 | {src_line(261)}"
        assert lines[-1] == "..."
        numbers = [int(ln[3:].split("|")[0]) for ln in lines if "|" in ln]
        assert numbers == [1, *range(140, 262)]
        assert [ln for ln in lines if ln.startswith(">>")] == [f">> 200 | {src_line(200)}", f">> 201 | {src_line(201)}"]

    def test_long_method_window_near_start_has_no_gap(self, tmp_path: Path) -> None:
        make_source(tmp_path, n=400)
        j = Judge(tmp_path, None, None)
        lines = source_lines(user_text(j, query(method_line=1, method_end=400, cond_line=30, cond_end=30)))
        numbers = [int(ln[3:].split("|")[0]) for ln in lines if "|" in ln]
        assert numbers == list(range(1, 91))
        assert lines.count("...") == 1 and lines[-1] == "..."

    def test_long_method_window_near_end_has_no_trailing_dots(self, tmp_path: Path) -> None:
        make_source(tmp_path, n=400)
        j = Judge(tmp_path, None, None)
        lines = source_lines(user_text(j, query(method_line=1, method_end=400, cond_line=395, cond_end=395)))
        numbers = [int(ln[3:].split("|")[0]) for ln in lines if "|" in ln]
        assert numbers == [1, *range(335, 401)]
        assert lines[1] == "..." and lines.count("...") == 1

    def test_method_of_exactly_160_lines_shown_whole(self, tmp_path: Path) -> None:
        make_source(tmp_path, n=300)
        j = Judge(tmp_path, None, None)
        lines = source_lines(user_text(j, query(method_line=10, method_end=169, cond_line=100, cond_end=100)))
        assert len(lines) == 160 and "..." not in lines
        lines = source_lines(user_text(j, query(method_line=10, method_end=170, cond_line=100, cond_end=100)))
        assert "..." in lines


class TestPrompt:
    def test_block_order_in_user_message(self, root: Path) -> None:
        text = user_text(Judge(root, CONTEXT, None), query())
        marks = ["Scenario S1:", "Step 3:", "Scenario state before this step:", "Method: ", "Method source",
                 "Execution path so far:", "Known values:", "Condition at line 10:"]
        pos = [text.index(m) for m in marks]
        assert pos == sorted(pos)
        assert text.index(src_line(10)) > text.index("Scenario state before this step:")
        assert text.index(src_line(10)) < text.index("Known values:")
        assert text.index("order.status = PAID") < text.index("Condition at line 10:")

    def test_blocks_separated_by_blank_line(self, root: Path) -> None:
        text = user_text(Judge(root, CONTEXT, None), query())
        for mark in ("Step 3:", "Scenario state before this step:", "Method: ", "Execution path so far:",
                     "Known values:", "Condition at line 10:"):
            assert "\n\n" + mark in text

    def test_scenario_step_blocks(self, root: Path) -> None:
        text = user_text(Judge(root, CONTEXT, None), query(step_params={"b": 1, "a": "Москва"}))
        assert text.startswith("Scenario S1: Отмена заказа\nDescription: Пользователь отменяет оплаченный заказ.\n\n")
        assert "Step 3: Отменить заказ\nExpected outcome: success\n" in text
        assert 'Request parameters: {"a": "Москва", "b": 1}' in text
        assert 'References to results of earlier steps: {"order": "new_of_step_2"}' in text

    def test_state_path_facts_lines(self, root: Path) -> None:
        text = user_text(Judge(root, CONTEXT, None), query())
        assert "Scenario state before this step:\norder o1: PAID\n" in text
        assert "Execution path so far:\nFoo#bar called from Ctrl#cancel\ntook then at line 7\n" in text
        assert "Known values:\norder.status = PAID\n" in text

    def test_empty_parts_are_none(self, root: Path) -> None:
        q = query(step_params={}, step_refs={}, state=(), path=(), facts=())
        text = user_text(Judge(root, CONTEXT, None), q)
        assert "Request parameters: none" in text
        assert "References to results of earlier steps: none" in text
        assert "Scenario state before this step: none" in text
        assert "Execution path so far: none" in text
        assert "Known values: none" in text

    def test_question_if(self, root: Path) -> None:
        for kind in ("if", "ternary", "switch"):
            text = user_text(Judge(root, CONTEXT, None), query(kind=kind))
            assert "Condition at line 10: order.getStatus() == 1\n" in text
            assert "TRUE or FALSE" in text and "Loop at line" not in text
            assert text.rstrip().endswith("Answer with JSON: cited_line, reasoning, verdict.")

    def test_question_loop(self, root: Path) -> None:
        text = user_text(Judge(root, CONTEXT, None), query(kind="loop", condition="orders"))
        assert "Loop at line 10 over: orders\n" in text
        assert "at least once (TRUE) or never (FALSE)" in text and "Condition at line" not in text
        assert text.rstrip().endswith("Answer with JSON: cited_line, reasoning, verdict.")

    def test_system_has_context_sorted_at_end(self, root: Path) -> None:
        system = Judge(root, CONTEXT, None).render_messages(query())[0]
        assert system["role"] == "system"
        content = system["content"]
        header = "Environment of the recorded runs:"
        assert header in content
        tail = content[content.index(header):].splitlines()
        assert tail[1:] == [f"- {k}: {CONTEXT[k]}" for k in sorted(CONTEXT)]
        assert content.index(header) > content.index("Rules:")
        assert "G or D" in content and "ts-order-other-service" in content and "Response.status" in content

    @pytest.mark.parametrize("ctx", [None, {}])
    def test_system_without_context_has_no_environment_block(self, root: Path, ctx: dict | None) -> None:
        content = Judge(root, ctx, None).render_messages(query())[0]["content"]
        assert "Environment of the recorded runs" not in content

    def test_messages_roles(self, root: Path) -> None:
        msgs = Judge(root, CONTEXT, None).render_messages(query())
        assert [m["role"] for m in msgs] == ["system", "user"]

    def test_system_constant_across_queries(self, root: Path) -> None:
        j = Judge(root, CONTEXT, None)
        a = j.render_messages(query(step_n=1))
        b = j.render_messages(query(step_n=2, condition="x > 1", cond_line=12, cond_end=12))
        assert a[0] == b[0] and a[1] != b[1]


class TestDeterminism:
    def test_same_query_same_messages_and_key(self, root: Path) -> None:
        llm = FakeLLM()
        a, b = Judge(root, dict(CONTEXT), llm), Judge(root, dict(reversed(list(CONTEXT.items()))), llm)
        q1, q2 = query(), query()
        ma, mb = a.render_messages(q1), b.render_messages(q2)
        assert json.dumps(ma, ensure_ascii=False) == json.dumps(mb, ensure_ascii=False)
        assert llm.key(JUDGE_PROMPT_VERSION, ma, JUDGE_SCHEMA) == llm.key(JUDGE_PROMPT_VERSION, mb, JUDGE_SCHEMA)
        va, vb = a.ask(q1), b.ask(q2)
        assert va is not None and vb is not None and va.cache_key == vb.cache_key
        assert not va.from_cache and vb.from_cache

    def test_params_key_order_irrelevant(self, root: Path) -> None:
        j = Judge(root, CONTEXT, None)
        a = j.render_messages(query(step_params={"a": 1, "b": 2}))
        b = j.render_messages(query(step_params={"b": 2, "a": 1}))
        assert a == b

    def test_different_query_different_key(self, root: Path) -> None:
        llm = FakeLLM()
        j = Judge(root, CONTEXT, llm)
        k1 = j.ask(query())
        k2 = j.ask(query(facts=("order.status = CANCELLED",)))
        assert k1 is not None and k2 is not None and k1.cache_key != k2.cache_key
