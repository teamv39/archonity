"""Судья M4: локальная LLM решает условие, которое исполнитель не смог посчитать (ADR-005, «Вердикт судьи»).

Исполнитель считает `if` в трёхзначной логике; на UNKNOWN он зовёт `Judge.ask`. Судья строит промпт, берёт ответ из кеша
(`cache/llm/`) или с сервера llama.cpp и возвращает вердикт TRUE / FALSE / UNKNOWN. `None` значит «ответа нет» (режим off,
бюджет, промах кеша без сервера, ошибка сервера): исполнитель берёт правило по умолчанию.

Порядок частей промпта под кеш префикса llama.cpp: системный промпт (постоянный на прогон) → сценарий → шаг → состояние
сценария → исходник метода → путь → факты → вопрос. Любая правка текста промпта или схемы — новая `JUDGE_PROMPT_VERSION`.
Одинаковый `JudgeQuery` даёт байт-в-байт одинаковые сообщения: от этого зависит ключ кеша.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from engine.grounding.llm import LLMClient

JUDGE_PROMPT_VERSION = "m4-judge-v3"
VERDICTS = ("TRUE", "FALSE", "UNKNOWN")
MODES = ("on", "cache", "off")
MAX_METHOD_LINES = 160  # метод длиннее показываем окном вокруг условия
WINDOW_LINES = 60  # строк окна до и после условия

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        # Длина ограничена: ответ всегда укладывается в MAX_TOKENS клиента (v1 обрывался на длинном reasoning)
        "cited_line": {"type": "string", "maxLength": 200},
        "reasoning": {"type": "string", "maxLength": 400},
        "verdict": {"type": "string", "enum": list(VERDICTS)},
    },
    "required": ["cited_line", "reasoning", "verdict"],
    "additionalProperties": False,
}

SYSTEM = """You are a judge of one branching condition in the Java code of the Train Ticket microservice application.
You get one step of a user scenario, the source of one method that the step executes, and one condition in it (an if, a loop, a switch or a ternary). The analysis is static: the code is never run. Decide whether the condition is TRUE or FALSE when this step reaches this line.

Rules:
- Base the decision on the scenario text, the step text, the expected outcome, the execution path so far, the known values and the scenario state. Do not invent data that none of them gives.
- Response.status 1 means success; 0 means refusal or error.
- Trains whose number starts with G or D are high-speed trains, served by ts-order-service, ts-travel-service and ts-preserve-service. All other trains are regular, served by ts-order-other-service, ts-travel2-service and ts-preserve-other-service.
- Expected outcome 'success': the system serves the step normally, so every check passes the way it does on the normal path. Expected outcome 'refused': the system refuses the step, and the refusal happens at the specific check that the scenario talks about; every other check behaves as on the normal path.
- For a loop, TRUE means the body runs at least once, FALSE means it never runs.
- Answer UNKNOWN only when the texts and the known values really do not determine the answer.
- cited_line is the line of code from the shown method that the decision rests on, copied as it is; reasoning is one or two sentences. Fill the fields in this order: cited_line, reasoning, verdict.
"""

ENV_HEADER = "Environment of the recorded runs:"

NO_SOURCE = "(source not available)"

COND_TASK = """Condition at line {line}: {condition}

Will this condition be TRUE or FALSE when step {n} reaches this line? Answer UNKNOWN only if the texts and the known values do not determine it.
Answer with JSON: cited_line, reasoning, verdict."""

LOOP_TASK = """Loop at line {line} over: {condition}

Will the loop body run at least once (TRUE) or never (FALSE) when step {n} reaches this line? Answer UNKNOWN only if the texts and the known values do not determine it.
Answer with JSON: cited_line, reasoning, verdict."""


@dataclass(frozen=True)
class JudgeQuery:
    scenario_id: str
    scenario_title: str
    scenario_description: str
    step_n: int
    step_action: str
    expected_outcome: str  # "success" | "refused"
    step_params: dict[str, Any]  # параметры запроса шага (без None)
    step_refs: dict[str, str]  # ссылки на результаты прошлых шагов, например {"order": "new_of_step_4"}
    method_id: str  # ID метода скелета
    file: str  # путь исходника относительно targets_root
    method_line: int  # строка объявления метода
    method_end: int  # последняя строка метода
    cond_line: int  # первая строка условия
    cond_end: int  # последняя строка условия (равна cond_line, если условие в одну строку)
    condition: str  # условие в синтаксисе Java (или выражение коллекции для цикла)
    kind: str  # "if" | "loop" | "switch" | "ternary"
    path: tuple[str, ...]  # пройденный путь: стек вызовов и принятые решения, готовые строки
    facts: tuple[str, ...]  # известные значения переменных условия, готовые строки
    state: tuple[str, ...]  # сводка состояния сценария, готовые строки


@dataclass(frozen=True)
class JudgeVerdict:
    verdict: str  # TRUE | FALSE | UNKNOWN
    cited_line: str
    reasoning: str
    cache_key: str
    from_cache: bool


@dataclass
class JudgeStats:
    asked: int = 0
    true: int = 0
    false: int = 0
    unknown: int = 0
    cache_hits: int = 0
    server_calls: int = 0
    skipped_off: int = 0  # режим off
    skipped_budget: int = 0  # бюджет вызовов сервера исчерпан
    misses: int = 0  # нет ответа: промах кеша без сервера, ошибка сервера, нет клиента

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def system_prompt(context: dict[str, str] | None) -> str:
    """Постоянная часть промпта; окружение прогонов из `context` скелета идёт в конце, ключи по алфавиту."""
    if not context:
        return SYSTEM
    env = "\n".join(f"- {k}: {context[k]}" for k in sorted(context))
    return f"{SYSTEM}\n{ENV_HEADER}\n{env}\n"


def _json(obj: dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str) if obj else "none"


def _lines_block(header: str, lines: tuple[str, ...]) -> str:
    return f"{header}\n" + "\n".join(lines) if lines else f"{header} none"


class Judge:
    def __init__(self, targets_root: str | Path, context: dict[str, str] | None, llm: LLMClient | None,
                 mode: str = "on", budget: int = 400) -> None:
        if mode not in MODES:
            raise ValueError(f"судья: режим {mode!r} не из {MODES}")
        self.targets_root = Path(targets_root)
        self.llm = llm
        self.mode = mode
        self.budget = budget
        self.stats = JudgeStats()
        self._system = system_prompt(context)
        self._files: dict[str, list[str] | None] = {}

    def ask(self, q: JudgeQuery) -> JudgeVerdict | None:
        """Вердикт по условию или `None`, если ответа нет и исполнитель берёт правило по умолчанию."""
        st = self.stats
        st.asked += 1
        if self.mode == "off":
            st.skipped_off += 1
            return None
        if self.llm is None:
            st.misses += 1
            return None
        messages = self.render_messages(q)
        key = self.llm.key(JUDGE_PROMPT_VERSION, messages, JUDGE_SCHEMA)
        from_cache = not self.llm.refresh and self.llm.is_cached(key)
        if not from_cache:
            if self.mode == "cache":
                st.misses += 1
                return None
            if st.server_calls >= self.budget:
                st.skipped_budget += 1
                return None
            st.server_calls += 1
        resp, key = self.llm.complete_json("judge", JUDGE_PROMPT_VERSION, messages, JUDGE_SCHEMA)
        if resp is None:
            st.misses += 1
            return None
        if from_cache:
            st.cache_hits += 1
        return self._verdict(resp, key, from_cache)

    def _verdict(self, resp: Any, key: str, from_cache: bool) -> JudgeVerdict:
        """Вердикт вне VERDICTS и ответ неверной формы — UNKNOWN."""
        resp = resp if isinstance(resp, dict) else {}
        verdict = resp.get("verdict")
        if verdict not in VERDICTS:
            verdict = "UNKNOWN"
        cited, reasoning = resp.get("cited_line"), resp.get("reasoning")
        st = self.stats
        if verdict == "TRUE":
            st.true += 1
        elif verdict == "FALSE":
            st.false += 1
        else:
            st.unknown += 1
        return JudgeVerdict(verdict=verdict, cited_line=cited if isinstance(cited, str) else "",
                            reasoning=reasoning if isinstance(reasoning, str) else "",
                            cache_key=key, from_cache=from_cache)

    def render_messages(self, q: JudgeQuery) -> list[dict[str, str]]:
        """Сообщения `system` + `user` для запроса; публично для тестов и отладки."""
        return [{"role": "system", "content": self._system}, {"role": "user", "content": self._user(q)}]

    def _user(self, q: JudgeQuery) -> str:
        scenario = f"Scenario {q.scenario_id}: {q.scenario_title}\nDescription: {q.scenario_description}"
        step = (f"Step {q.step_n}: {q.step_action}\n"
                f"Expected outcome: {q.expected_outcome}\n"
                f"Request parameters: {_json(q.step_params)}\n"
                f"References to results of earlier steps: {_json(q.step_refs)}")
        method = (f"Method: {q.method_id}\nFile: {q.file}\n"
                  f"Method source (the lines marked >> hold the {'loop' if q.kind == 'loop' else 'condition'}):\n"
                  f"{self._source(q)}")
        task = (LOOP_TASK if q.kind == "loop" else COND_TASK).format(line=q.cond_line, condition=q.condition, n=q.step_n)
        blocks = [
            scenario,
            step,
            _lines_block("Scenario state before this step:", q.state),
            method,
            _lines_block("Execution path so far:", q.path),
            _lines_block("Known values:", q.facts),
            task,
        ]
        return "\n\n".join(blocks)

    def _lines(self, file: str) -> list[str] | None:
        """Строки исходника без перевода строки; прочитанные файлы держим в памяти."""
        if file not in self._files:
            try:
                text = (self.targets_root / file).read_bytes().decode("utf-8", errors="replace")
            except OSError:
                self._files[file] = None
            else:
                lines = re.split(r"\r\n|\r|\n", text)
                if lines and lines[-1] == "":
                    lines.pop()
                self._files[file] = lines
        return self._files[file]

    def _source(self, q: JudgeQuery) -> str:
        """Исходник метода с номерами строк; `>>` — строки условия. Длинный метод — объявление и окно вокруг условия."""
        lines = self._lines(q.file)
        first, last = max(q.method_line, 1), min(q.method_end, len(lines or ()))
        if lines is None or first > last:
            return NO_SOURCE
        shown: list[int | None] = []  # номера строк; None — пропуск (`...`)
        if last - first + 1 > MAX_METHOD_LINES:
            start = max(first + 1, q.cond_line - WINDOW_LINES)
            end = min(last, q.cond_end + WINDOW_LINES)
            shown.append(first)
            if start > first + 1:
                shown.append(None)
            shown.extend(range(start, end + 1))
            if end < last:
                shown.append(None)
        else:
            shown.extend(range(first, last + 1))
        width = len(str(max(n for n in shown if n is not None)))
        out = []
        for n in shown:
            if n is None:
                out.append("...")
                continue
            mark = ">> " if q.cond_line <= n <= q.cond_end else "   "
            out.append(f"{mark}{n:>{width}} | {lines[n - 1]}")
        return "\n".join(out)
