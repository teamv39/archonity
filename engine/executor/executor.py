"""M4: исполнитель шага сценария по IR тел методов (ADR-005, M4).

Шаг исполняется внутри обхода `GraphBuilder.traverse`: исполнитель — перехватчик (`MethodInterceptor`), он берёт себе
методы с IR, остальные раскрывает legacy (скелет, rules.py, guard'ы pool_ir). Без перехваченных методов выдача
совпадает с legacy ребро в ребро.
"""
from __future__ import annotations

import collections
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.adapters.skeleton import SkeletonIndex
from engine.decisions import DecisionLedger
from engine.executor import facts as fx
from engine.executor import library
from engine.executor.interp import Decision, Frame, StepRun, cs_pos, short, unknown_of
from engine.executor.judge import Judge, JudgeQuery, JudgeVerdict
from engine.executor.program import FieldInfo, Program, expr_kind, walk
from engine.executor.refs import RefResolver
from engine.executor.values import Obj, Unknown, simple_name
from engine.graph.builder import GraphBuilder
from engine.grounding.request import StepRequest
from engine.rules import ScenarioProfile
from engine.state import ScenarioState, StepMutationResult

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_IR_DIR = ROOT / "data" / "ir"
BEAN_FIELD_TYPES = frozenset({"RestTemplate", "AuthenticationManager", "RabbitTemplate", "AmqpTemplate",
                              "JavaMailSender", "DiscoveryClient", "PasswordEncoder", "ObjectMapper",
                              "MongoTemplate", "JdbcTemplate", "Executor", "TaskExecutor"})
INJECT_ANNOTATIONS = frozenset({"Autowired", "Resource", "Inject"})


@dataclass
class M4Options:
    judge: str = "on"  # on — кеш, на промахе сервер; cache — только кеш; off — без судьи
    judge_budget: int = 400  # вызовов сервера на прогон; попадания в кеш бесплатны
    only: str | None = None  # подстрока ID: M4 исполняет только такие методы, остальные раскрывает legacy
    legacy_rules: bool = False  # абляция: rules.py поверх решений IR
    no_signal_arm: str = "continue"  # плечо без сигнала исхода: continue — без раннего выхода, then — всегда then
    ir_dir: Path = DEFAULT_IR_DIR


class M4Executor:
    """Исполнитель шагов одного прогона: IR, судья, привязка refs к результатам прошлых шагов."""

    def __init__(
        self,
        index: SkeletonIndex,
        builder: GraphBuilder,
        targets_root: str | Path,
        options: M4Options | None = None,
        llm: Any = None,
    ) -> None:
        sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))
        self.index = index
        self.builder = builder
        self.targets_root = Path(targets_root)
        self.options = options or M4Options()
        self.program = Program(index, self.options.ir_dir)
        self.refs = RefResolver(self.program)
        mode = self.options.judge if llm is not None else "off"
        self.judge = Judge(self.targets_root, index.sk.get("context"), llm, mode=mode,
                           budget=self.options.judge_budget)
        self._repo_calls = {(c.method, c.line, c.col): c
                            for calls in index.entities.calls_by_method.values() for c in calls}
        self._singletons: dict[str, Any] = {}
        self._enums: dict[tuple[str, str], Obj] = {}
        self._sources: dict[str, list[str]] = {}
        self.scenario: dict[str, Any] = {}
        self.decisions: collections.Counter[str] = collections.Counter()
        self.counters: collections.Counter[str] = collections.Counter()
        self.branch_log: list[dict[str, Any]] = []

    # --- конвейер --------------------------------------------------------------------------------------------------

    def wants(self, method_id: str) -> bool:
        return method_id in self.program.methods and (self.options.only is None or self.options.only in method_id)

    def begin_scenario(self, scenario_dict: dict[str, Any]) -> None:
        """Новый сценарий: сброс сущностей шагов и бинов (сценарии изолированы)."""
        self.scenario = {"id": scenario_dict.get("id", "S?"), "title": scenario_dict.get("title", ""),
                         "description": scenario_dict.get("description", "")}
        self.refs.begin()
        self._singletons.clear()

    def run_step(
        self,
        step_req: StepRequest,
        *,
        profile: ScenarioProfile,
        scenario_state: ScenarioState,
        scenario_meta: dict[str, Any],
        ledger: DecisionLedger | None,
    ) -> tuple[set[str], set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
        """Исполнение шага: (executes, calls, remote, data), решения пишутся в ledger."""
        self.refs.remember_step(step_req)
        run = StepRun(self, step_req, scenario_state, profile, scenario_meta)
        return self.builder.traverse(
            [step_req.handler],
            is_admin_scenario=bool(getattr(profile, "is_admin", False)),
            scenario_meta=scenario_meta,
            profile=profile,
            scenario_state=scenario_state,
            ledger=ledger,
            interceptor=run,
        )

    def end_step(self, step_req: StepRequest, mutation: StepMutationResult | None) -> None:
        """После мутации M3: запомнить сущности, созданные шагом (для refs вида new_of_step_N)."""
        self.refs.remember_mutation(step_req.step, getattr(mutation, "affected_entities", None))

    def stats(self) -> dict[str, Any]:
        """Счётчики решений по источникам и судьи — для печати в run_eval."""
        return {
            "ir_methods": len(self.program.methods),
            "decisions": dict(sorted(self.decisions.items())),
            "judge": self.judge.stats.to_dict(),
            "counters": dict(sorted(self.counters.items())),
        }

    # --- сведения для интерпретатора -------------------------------------------------------------------------------

    def repo_call_at(self, method_id: str, line: int, col: int) -> Any:
        return self._repo_calls.get((method_id, line, col))

    def collection_table_loaded(self, method_id: str, table: str) -> tuple[bool, str] | None:
        """R10: как в legacy (`GraphBuilder._collection_table_loaded`)."""
        if getattr(self.builder.rules, "collection_tables_on_read", "loaded") == "all":
            return None
        return self.index.entities.collection_table_loaded(method_id, table)

    def singleton(self, type_node: str | None) -> Any:
        """Экземпляр бина Spring (сервис, контроллер, компонент) — один на сценарий."""
        if not type_node:
            return Unknown("receiver object", "object")
        if type_node not in self._singletons:
            fqn = self.program.N.get(type_node, {}).get("fqn", "")
            if self.program.is_bean_type(type_node):
                self._singletons[type_node] = Obj(fqn, src="bean", origin=f"bean {simple_name(fqn)}")
            else:
                self._singletons[type_node] = Unknown(f"instance of {simple_name(fqn)}", "object", type=fqn)
        return self._singletons[type_node]

    def bean_field(self, fi: FieldInfo | None, name: str) -> Any:
        """Поле бина: литерал инициализации, внедрённый бин, конфигурация."""
        if fi is None:
            if name.lower() in ("logger", "log"):
                return Obj("org.slf4j.Logger", src="bean")
            return Unknown(f"field {name}", "object", src="field")
        s = simple_name(fi.type)
        if fi.init_literal is not None:
            return library.literal(fi.init_literal, fi.type)
        if s == "Logger":
            return Obj("org.slf4j.Logger", src="bean")
        if "Value" in fi.annotations:
            return unknown_of(f"configuration value {name}", fi.type, "field", success_defaults=False)
        if set(fi.annotations) & INJECT_ANNOTATIONS or s in BEAN_FIELD_TYPES or self.program.is_project_type(fi.type):
            return Obj(fi.type, src="bean", origin=f"bean field {name}")
        return unknown_of(f"field {name}", fi.type, "field", success_defaults=False)

    def enum_value(self, fqn: str, constant: str, args: list[Any] | None, run: StepRun) -> Obj:
        """Константа enum: объект с полями из конструктора (исполняется тихо: инициализация класса, не шаг)."""
        key = (fqn, constant)
        if key in self._enums:
            return self._enums[key]
        p = self.program
        tn = p.type_node(fqn)
        consts = p.enum_constants(tn)
        obj = Obj(fqn, {"__name__": constant, "__ordinal__": consts.index(constant) if constant in consts else None},
                  src="enum", origin=f"{simple_name(fqn)}.{constant}")
        self._enums[key] = obj
        if args is None:
            args = p.enum_args.get(fqn, {}).get(constant)
        if args is None:  # на константу нет ссылки с аргументами в IR (values()): объявление enum в исходнике
            args = p.enum_source_args(tn, self.targets_root).get(constant)
        if args is None:
            return obj
        values = [_literal(a) for a in args]
        ctors = p.find_methods(tn, "<init>", len(values))
        if ctors and self.wants(ctors[0]) and run.ctx is not None:
            run.silent += 1
            try:
                run.invoke(ctors[0], p.module_of(ctors[0]), values, this=obj, caller=None, via=None)
            finally:
                run.silent -= 1
        else:
            fields = p.instance_fields(tn)
            if len(fields) == len(values):
                obj.fields.update({f.name: v for f, v in zip(fields, values)})
        return obj

    def source_lines(self, file: str, start: int, end: int) -> list[str]:
        if file not in self._sources:
            try:
                text = (self.targets_root / file).read_text(encoding="utf-8", errors="replace")
                self._sources[file] = text.splitlines()
            except OSError:
                self._sources[file] = []
        return self._sources[file][max(start - 1, 0):max(end, start)]

    # --- судья -----------------------------------------------------------------------------------------------------

    def ask_judge(self, run: StepRun, frame: Frame, v: Any, *, kind: str, line: int, cond: Any,
                  text: str, facts: tuple[str, ...] = ()) -> JudgeVerdict | None:
        ir = self.program.ir(frame.method_id) or {}
        end = line
        for n in walk(cond):
            cs = n.get("call")
            if isinstance(cs, str):
                end = max(end, cs_pos(cs)[0])
        step = run.step
        q = JudgeQuery(
            scenario_id=self.scenario.get("id", ""),
            scenario_title=self.scenario.get("title", ""),
            scenario_description=self.scenario.get("description", ""),
            step_n=int(step.step),
            step_action=step.action,
            expected_outcome=run.expected,
            step_params={k: x for k, x in (step.params or {}).items() if x is not None},
            step_refs=dict(step.refs or {}),
            method_id=frame.method_id,
            file=ir.get("file", ""),
            method_line=int(ir.get("line") or line),
            method_end=int(ir.get("end") or line),
            cond_line=line,
            cond_end=min(end, line + 6),
            condition=text or f"condition at line {line}",
            kind=kind,
            path=fx.path_lines(frame),
            facts=facts,
            state=fx.state_lines(run),
        )
        verdict = self.judge.ask(q)
        self.counters["judge_asked"] += 1
        return verdict

    def count_decision(self, run: StepRun, frame: Frame, d: Decision) -> None:
        self.decisions[d.label] += 1
        self.branch_log.append({
            "scenario": self.scenario.get("id"), "step": run.step.step, "method": frame.method_id,
            "line": d.line, "branch": d.bid, "arm": d.arm, "source_type": d.source_type, "rule": d.label,
            "condition": d.text, "detail": d.detail, "facts": list(d.facts),
        })

    def count_edge(self, source_type: str) -> None:
        self.counters[f"edges_{source_type}"] += 1

    def count(self, name: str) -> None:
        self.counters[name] += 1


def _literal(node: Any) -> Any:
    """Литерал аргумента константы enum (README archparse 3.6: только литералы)."""
    if isinstance(node, dict) and expr_kind(node) == "lit":
        v, t = node.get("lit"), node.get("type")
        if t == "null":
            return None
        if t in ("int", "long") and not isinstance(v, bool):
            return int(v)
        if t in ("double", "float"):
            return float(v)
        return v
    return Unknown("enum constant argument", "object")


__all__ = ["M4Executor", "M4Options", "short"]
