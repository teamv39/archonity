"""Интерпретатор IR тел методов для одного шага сценария (ADR-005, M4).

Шаг — один путь: в каждом условии исполняется одно плечо. Условие считается по значениям (параметры шага,
состояние, результаты вызовов) в трёхзначной логике; неизвестное разрешают шаблоны по умолчанию, судья и, в конце,
ожидаемый исход шага (`engine/executor/defaults.py`).

Вызов проектного метода — рекурсивный вход; RestTemplate — переход в обработчик другого сервиса (R3, R12);
отправка в очередь — вход в потребителя (R13); репозиторий — события SQL и чтение состояния (`repo.py`);
остальное — модели библиотеки (`library.py`). Рёбра пишутся в общий контекст обхода и журнал решений;
методы без IR уходят в стек legacy-раскрытия.
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from engine.executor import facts, library, repo
from engine.executor.defaults import default_leaf, leaf_rules, outcome_arm
from engine.executor.program import PRIMITIVE_DEFAULTS, expr_kind, match_template, walk
from engine.executor.values import (
    MISSING, NONNULL, Coll, Iter, Lambda, Obj, Opt, Sym, TypeRef, Unknown, and_, binop, is_unknown, not_, or_,
    resolve, simple_name, truth, unop,
)

if TYPE_CHECKING:
    from engine.executor.executor import M4Executor
    from engine.graph.builder import TraversalContext
    from engine.grounding.request import StepRequest

MAX_DEPTH = 40
MAX_ITER = 20
MAX_METHOD_RUNS = 100
NUMERIC = frozenset({"int", "long", "short", "byte", "double", "float", "Integer", "Long", "Short", "Byte", "Double",
                     "Float", "BigDecimal", "Number"})
COLLECTIONS = frozenset({"List", "ArrayList", "LinkedList", "Set", "HashSet", "TreeSet", "LinkedHashSet", "Collection",
                         "Iterable", "Queue", "Deque"})
CS_POS = re.compile(r"@(\d+):(\d+)$")
MUTATORS = frozenset({"add", "addAll", "put", "putAll", "remove", "removeAll", "retainAll", "clear", "append",
                      "insert", "push", "offer", "poll", "pop", "sort"})


class ReturnSignal(Exception):
    def __init__(self, value: Any) -> None:
        self.value = value


class ThrowSignal(Exception):
    def __init__(self, value: Any, line: int = 0) -> None:
        self.value = value
        self.line = line


class BreakSignal(Exception):
    def __init__(self, label: str | None = None) -> None:
        self.label = label


class ContinueSignal(Exception):
    def __init__(self, label: str | None = None) -> None:
        self.label = label


@dataclass
class Decision:
    """Решение по условию: какое плечо и почему."""

    bid: str
    arm: str
    line: int
    source_type: str  # IR_BRANCH, STATE, DEFAULT_RULE, LLM_JUDGE
    label: str  # IR, STATE, D1…D4, NO_EFFECT, JUDGE, OUTCOME, LOOP, R16
    text: str = ""
    detail: str = ""
    facts: tuple[str, ...] = ()

    def tag(self) -> str:
        return f"{self.label}@{self.bid}:{self.arm}"


@dataclass
class Frame:
    method_id: str
    unit: str
    this: Any
    env: dict[str, Any]
    depth: int
    caller: Frame | None = None
    call_line: int = 0
    active: list[Decision] = field(default_factory=list)  # плечи, внутри которых сейчас исполнение
    history: list[Decision] = field(default_factory=list)  # все решения в кадре по порядку
    line: int = 0

    def reason(self) -> tuple[str, str]:
        """Источник и правило для ребра из текущего места: решения плеч, внутри которых стоит вызов."""
        if not self.active:
            return "SKELETON", "M4"
        return self.active[-1].source_type, ";".join(d.tag() for d in self.active)


def cs_pos(cs: str | None) -> tuple[int, int]:
    m = CS_POS.search(cs or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def unknown_of(origin: str, type_str: str | None, src: str, *, success_defaults: bool = True) -> Unknown:
    """Неизвестное значение по типу. Для результатов вызовов — значения по умолчанию успешного пути (D2, D4)."""
    s = simple_name(type_str)
    from_call = success_defaults and src in ("remote", "call", "repo")
    if s in ("boolean", "Boolean"):
        return Unknown(origin, "bool", src=src, type=type_str)
    if s in NUMERIC:
        return Unknown(origin, "number", src=src, type=type_str)
    if s in ("String", "char", "Character"):
        return Unknown(origin, "string", NONNULL if from_call else MISSING, src=src, type=type_str,
                       rule="D2" if from_call else None)
    if s in COLLECTIONS or (type_str or "").endswith("[]"):
        return Unknown(origin, "collection", NONNULL if from_call else MISSING, src=src, type=type_str,
                       rule="D2" if from_call else None)
    if s == "Optional":
        return Unknown(origin, "optional", NONNULL if from_call else MISSING, src=src, type=type_str,
                       rule="D2" if from_call else None)
    if s == "void":
        return Unknown(origin, "void", src=src, type=type_str)
    return Unknown(origin, "object", NONNULL if from_call else MISSING, src=src, type=type_str,
                   rule="D2" if from_call else None)


def short(method_id: str) -> str:
    """`method:svc:pkg.Class#name(...)` -> `Class#name`."""
    tail = method_id.split(":", 2)[-1]
    cls, _, rest = tail.partition("#")
    return f"{cls.rsplit('.', 1)[-1]}#{rest.split('(', 1)[0]}"


class StepRun:
    """Исполнение одного шага: перехватчик обхода `GraphBuilder.traverse`."""

    def __init__(self, ex: M4Executor, step_req: StepRequest, state: Any, profile: Any,
                 scenario_meta: dict[str, Any]) -> None:
        self.ex = ex
        self.program = ex.program
        self.index = ex.index
        self.step = step_req
        self.state = state
        self.profile = profile
        self.meta = scenario_meta
        self.ctx: TraversalContext | None = None
        self.expected = step_req.expected_outcome or "success"
        self.runs: collections.Counter[str] = collections.Counter()
        self.silent = 0
        self.taint = False

    # --- MethodInterceptor -----------------------------------------------------------------------------------------

    def wants(self, method_id: str) -> bool:
        return self.ex.wants(method_id)

    def run(self, method_id: str, unit: str, ctx: TraversalContext, entry: bool) -> None:
        self.ctx = ctx
        if entry and method_id == self.step.handler:
            args = self.ex.refs.bind_entry(self, method_id, self.step)
            via = None
        else:
            # Метод достигнут legacy-раскрытием: аргументы неизвестны
            args = [unknown_of(f"argument {p.name} of {short(method_id)} (caller without IR)", p.type, "call",
                               success_defaults=False)
                    for p in self.program.params_by_method.get(method_id, [])]
            via = ctx.reached_via.get(method_id, (None, None, None))[2]
        this = self.receiver_for(method_id, None, None)
        try:
            self.invoke(method_id, unit, args, this=this, caller=None, via=via, already_marked=True)
        except ThrowSignal:
            pass  # исключение дошло до DispatcherServlet: шаг закончился ошибкой, выполненное остаётся (R15)

    # --- события ---------------------------------------------------------------------------------------------------

    def emit(self, relation: str, frame: Frame, target: str, *, line: int = 0, col: int = 0,
             extra: tuple[str, str] | None = None) -> bool:
        """Ребро из метода кадра. extra — (источник, правило), уточняющее решение плеч (R3, R10)."""
        if self.silent:
            return False
        src = frame.method_id
        st, rule = frame.reason()
        if extra is not None:
            st = extra[0] if st == "SKELETON" else st
            rule = extra[1] if rule == "M4" else f"{rule};{extra[1]}"
        if self.ex.options.legacy_rules and self._legacy_dead(relation, src, target):
            return False
        edges = {"calls": self.ctx.edges_calls, "remote": self.ctx.edges_remote, "data": self.ctx.edges_data}[relation]
        edges.add((src, target))
        if self.ctx.ledger is not None:
            detail: dict[str, Any] = {}
            if line:
                detail = {"line": line, "col": col}
            self.ctx.ledger.include(relation, src, target, st, rule, **detail)
        self.ex.count_edge(st)
        return True

    def prune(self, relation: str, src: str, target: str, source_type: str, rule: str, **detail: Any) -> None:
        if self.silent or self.ctx.ledger is None:
            return
        self.ctx.ledger.prune(relation, src, target, source_type, rule, **detail)

    def _legacy_dead(self, relation: str, src: str, target: str) -> bool:
        """Абляция --m4-legacy-rules: отсев rules.py поверх решений IR."""
        rules = self.ex.builder.rules
        admin = bool(getattr(self.profile, "is_admin", False))
        dead = rules.is_dead_code_edge(src, relation, target, profile=self.profile, is_admin_scenario=admin)
        if relation in ("calls", "remote"):
            dead = dead or rules.is_dead_code_method(target, profile=self.profile, is_admin_scenario=admin)
        if dead:
            self.prune(relation, src, target, "DEFAULT_RULE", "m4_legacy_rules")
        return dead

    def mark(self, method_id: str, unit: str, reason: tuple[str, str], via: str | None) -> None:
        if self.silent:
            return
        self.ctx.seen_methods.add((method_id, unit))
        self.ctx.reached_via.setdefault(method_id, (reason[0], reason[1], via))

    # --- вызов метода ----------------------------------------------------------------------------------------------

    def invoke(self, method_id: str, unit: str, args: list[Any], *, this: Any, caller: Frame | None,
               via: str | None, call_line: int = 0, reason: tuple[str, str] | None = None,
               already_marked: bool = False) -> Any:
        reason = reason or (caller.reason() if caller else ("SKELETON", "ENTRY"))
        if not self.ex.wants(method_id):
            # Метод без IR (или исключён --m4-only): раскрывает legacy
            if not self.silent:
                self.ctx.reached_via.setdefault(method_id, (reason[0], reason[1], via))
                if (method_id, unit) not in self.ctx.seen_methods:
                    self.ctx.stack.append((method_id, unit))
            return self.unknown_return(method_id, "not executed by M4")
        if not already_marked:
            self.mark(method_id, unit, reason, via)
        depth = caller.depth + 1 if caller else 0
        if depth > MAX_DEPTH or self.runs[method_id] >= MAX_METHOD_RUNS:
            self.ex.count(f"limit:{'depth' if depth > MAX_DEPTH else 'runs'}:{short(method_id)}")
            return self.unknown_return(method_id, "execution limit")
        self.runs[method_id] += 1
        ir = self.program.ir(method_id) or {}
        env: dict[str, Any] = {}
        for i, p in enumerate(ir.get("params") or []):
            env[p["name"]] = args[i] if i < len(args) else unknown_of(f"argument {p['name']}", p.get("type"), "call",
                                                                      success_defaults=False)
        frame = Frame(method_id, unit, this, env, depth, caller, call_line)
        try:
            self.exec_block(ir.get("body") or [], frame)
        except ReturnSignal as r:
            return r.value
        return None

    def unknown_return(self, method_id: str, why: str) -> Unknown:
        n = self.index.N.get(method_id, {})
        return unknown_of(f"result of {short(method_id)} ({why})", n.get("return") or n.get("return_raw"), "call")

    def receiver_for(self, target: str, recv: Any, frame: Frame | None) -> Any:
        """`this` вызываемого метода: объект-получатель, а для бинов Spring — их экземпляр."""
        if self.program.is_static(target):
            return None
        owner = self.program.owner_of(target)
        if recv is None:
            # Неявный this: метод того же объекта (или суперкласса)
            if frame is not None and frame.this is not None:
                return frame.this
            return self.ex.singleton(owner)
        if isinstance(recv, Obj) and recv.src == "bean":
            return self.ex.singleton(owner) if self.program.is_bean_type(owner) else recv
        if is_unknown(recv) and self.program.is_bean_type(owner):
            return self.ex.singleton(owner)
        return recv

    # --- операторы -------------------------------------------------------------------------------------------------

    def exec_block(self, stmts: list[dict[str, Any]], frame: Frame) -> None:
        for st in stmts:
            self.exec_stmt(st, frame)

    def exec_stmt(self, st: dict[str, Any], frame: Frame) -> None:
        op = st.get("op")
        frame.line = st.get("line", frame.line)
        if op == "expr":
            self.eval(st.get("expr"), frame)
        elif op == "assign":
            self.exec_assign(st, frame)
        elif op == "if":
            self.exec_if(st, frame)
        elif op == "return":
            raise ReturnSignal(self.eval(st["expr"], frame) if st.get("expr") is not None else None)
        elif op == "throw":
            raise ThrowSignal(self.eval(st.get("expr"), frame), st.get("line", 0))
        elif op == "foreach":
            self.exec_foreach(st, frame)
        elif op in ("while", "do", "for"):
            self.exec_loop(st, frame)
        elif op == "try":
            self.exec_try(st, frame)
        elif op == "switch":
            self.exec_switch(st, frame)
        elif op == "block":
            try:
                self.exec_block(st.get("body") or [], frame)
            except BreakSignal as b:
                if b.label is None or b.label != st.get("label"):
                    raise
        elif op == "break":
            raise BreakSignal(st.get("label"))
        elif op == "continue":
            raise ContinueSignal(st.get("label"))
        # unsupported и прочее — пропуск

    def exec_assign(self, st: dict[str, Any], frame: Frame) -> None:
        target = st.get("target") or {}
        if "expr" in st and st["expr"] is not None:
            value = self.eval(st["expr"], frame)
        elif st.get("decl"):
            value = PRIMITIVE_DEFAULTS.get(st["decl"], None)
        else:
            return
        operator = st.get("operator") or "="
        if operator != "=":
            value = binop(operator[:-1], self.eval(target, frame), value)
        self.assign_to(target, value, frame)

    def assign_to(self, target: dict[str, Any], value: Any, frame: Frame) -> None:
        k = expr_kind(target)
        if k == "name":
            if target.get("ref") == "field" and isinstance(frame.this, Obj):
                frame.this.fields[target["name"]] = value
            else:
                frame.env[target["name"]] = value
        elif k == "field":
            obj = self.eval(target.get("of"), frame)
            if isinstance(obj, Obj):
                obj.fields[target["field"]] = value
        elif k == "index":
            coll = self.eval(target.get("of"), frame)
            idx = self.eval(target.get("index"), frame)
            if isinstance(coll, Coll) and coll.items is not None and isinstance(idx, int) and 0 <= idx < len(coll.items):
                coll.items[idx] = value

    def exec_if(self, st: dict[str, Any], frame: Frame) -> None:
        then, els = st.get("then") or [], st.get("else") or []
        v, tainted = self.eval_cond(st.get("cond"), frame)
        take, d = self.decide(frame, v, tainted, bid=st.get("id") or f"b{st.get('line', 0)}", line=st.get("line", 0),
                              kind="if", cond=st.get("cond"), then=then, els=els)
        arm = then if take else els
        self.prune_arm(frame, els if take else then, d)
        frame.active.append(d)
        try:
            self.exec_block(arm, frame)
        finally:
            frame.active.pop()
        if d.label == "NO_EFFECT":
            self.havoc(frame, then + els, d)

    def exec_foreach(self, st: dict[str, Any], frame: Frame) -> None:
        coll = self.eval(st.get("iter"), frame)
        items, d = self.loop_items(frame, coll, st)
        if d is not None and d.arm == "skip":
            self.prune_arm(frame, st.get("body") or [], d)
            return
        if d is not None:
            frame.active.append(d)
        try:
            for item in items[:MAX_ITER]:
                frame.env[st.get("var", "_")] = item
                try:
                    self.exec_block(st.get("body") or [], frame)
                except ContinueSignal:
                    continue
                except BreakSignal as b:
                    if b.label is None:
                        break
                    raise
        finally:
            if d is not None:
                frame.active.pop()
        if d is not None and d.label == "NO_EFFECT":
            self.havoc(frame, st.get("body") or [], d)

    def loop_items(self, frame: Frame, coll: Any, st: dict[str, Any]) -> tuple[list[Any], Decision | None]:
        """Элементы цикла foreach: известные — все (до MAX_ITER); иначе один неизвестный, если тело исполняется."""
        bid = st.get("id") or f"f{st.get('line', 0)}"
        line = st.get("line", 0)
        if isinstance(coll, Coll) and coll.items is not None:
            src = "STATE" if coll.src == "state" else "IR_BRANCH"
            d = Decision(bid, "body" if coll.items else "skip", line, src, "STATE" if src == "STATE" else "IR",
                         self.cond_text(frame, st))
            self.record(frame, d)
            return list(coll.items), d
        if isinstance(coll, Obj) and isinstance(coll.fields.get("__map__"), dict):
            items = list(coll.fields["__map__"].values())
            return items, None
        nonempty = coll.nonempty if isinstance(coll, Coll) else (
            coll.child("nonempty", lambda: Unknown(f"{coll.origin} is not empty", "bool", src=coll.src,
                                                   default=True if coll.default is NONNULL else MISSING,
                                                   rule="D4" if coll.default is NONNULL else None))
            if isinstance(coll, Unknown) else MISSING)
        if nonempty is MISSING:
            nonempty = Unknown(f"collection at line {line} is not empty", "bool", src="library")
        elem_type = st.get("var_type")
        take, d = self.decide(frame, nonempty, isinstance(coll, Coll) and coll.src == "state", bid=bid, line=line,
                              kind="loop", cond=st.get("iter"), then=st.get("body") or [], els=[])
        if not take:
            return [], d
        origin = coll.origin if isinstance(coll, (Coll, Unknown)) else "collection"
        return [unknown_of(f"element of {origin}", elem_type, "loop", success_defaults=False)], d

    def exec_loop(self, st: dict[str, Any], frame: Frame) -> None:
        op = st.get("op")
        if op == "for":
            self.exec_block(st.get("init") or [], frame)
        bid = st.get("id") or f"{op[0]}{st.get('line', 0)}"
        decided: Decision | None = None
        first = True
        for _ in range(MAX_ITER):
            if not (op == "do" and first):
                cond = st.get("cond")
                if cond is not None:
                    v, tainted = self.eval_cond(cond, frame)
                    if truth(v) is None or first:
                        take, d = self.decide(frame, v, tainted, bid=bid, line=st.get("line", 0), kind="loop",
                                              cond=cond, then=st.get("body") or [], els=[])
                        if truth(v) is None:
                            decided = d
                        if not take:
                            if first:
                                self.prune_arm(frame, st.get("body") or [], d)
                            break
                    elif not truth(v):
                        break
            first = False
            if decided is not None:
                frame.active.append(decided)
            try:
                self.exec_block(st.get("body") or [], frame)
            except ContinueSignal:
                pass
            except BreakSignal as b:
                if b.label is None:
                    break
                raise
            finally:
                if decided is not None:
                    frame.active.pop()
            if decided is not None:
                break  # условие неизвестно: тело исполнено один раз
            for u in st.get("update") or []:
                self.eval(u, frame)

    def exec_try(self, st: dict[str, Any], frame: Frame) -> None:
        try:
            self.exec_block(st.get("resources") or [], frame)
            self.exec_block(st.get("body") or [], frame)
        except ThrowSignal as t:
            handler = self.match_catch(st.get("catches") or [], t.value)
            if handler is None:
                raise
            frame.env[handler.get("var") or "_"] = t.value
            d = Decision(st.get("id") or f"t{st.get('line', 0)}", "catch", st.get("line", 0), "IR_BRANCH", "R15",
                         f"exception at line {t.line}")
            self.record(frame, d)
            frame.active.append(d)
            try:
                self.exec_block(handler.get("body") or [], frame)
            finally:
                frame.active.pop()
        finally:
            if st.get("finally"):
                self.exec_block(st["finally"], frame)

    @staticmethod
    def match_catch(catches: list[dict[str, Any]], exc: Any) -> dict[str, Any] | None:
        etype = simple_name(exc.type) if isinstance(exc, Obj) else ""
        for c in catches:
            for t in c.get("types") or []:
                s = simple_name(t)
                if s in ("Exception", "Throwable", "RuntimeException") or not etype or s == etype:
                    return c
        return None

    def exec_switch(self, st: dict[str, Any], frame: Frame) -> None:
        sel = self.eval(st.get("selector"), frame)
        cases = st.get("cases") or []
        start = None
        if not is_unknown(sel):
            for i, c in enumerate(cases):
                for lab in c.get("labels") or []:
                    lv = self.eval(lab, frame)
                    if lv == sel or (isinstance(lv, Obj) and lv is sel):
                        start = i
                        break
                if start is not None:
                    break
        if start is None:
            start = next((i for i, c in enumerate(cases) if not c.get("labels")), None)
        if start is None:
            return
        try:
            for c in cases[start:]:
                self.exec_block(c.get("body") or [], frame)
        except BreakSignal as b:
            if b.label is not None:
                raise

    # --- решения ---------------------------------------------------------------------------------------------------

    def eval_cond(self, cond: Any, frame: Frame) -> tuple[Any, bool]:
        saved = self.taint
        self.taint = False
        try:
            v = self.eval(cond, frame)
            return v, self.taint
        finally:
            self.taint = saved or self.taint

    def decide(self, frame: Frame, v: Any, tainted: bool, *, bid: str, line: int, kind: str, cond: Any,
               then: list[dict[str, Any]], els: list[dict[str, Any]]) -> tuple[bool, Decision]:
        """Плечо условия: значение, шаблоны по умолчанию, судья, исход шага."""
        arms = ("body", "skip") if kind == "loop" else ("then", "else")
        text = self.cond_text(frame, {"line": line, "cond": cond})

        def made(take: bool, source_type: str, label: str, detail: str = "",
                 fl: tuple[str, ...] = ()) -> tuple[bool, Decision]:
            d = Decision(bid, arms[0] if take else arms[1], line, source_type, label, text, detail, fl)
            self.record(frame, d)
            return take, d

        t = truth(v)
        if t is not None:
            return made(t, "STATE" if tainted else "IR_BRANCH", "STATE" if tainted else "IR")
        if self.silent:
            return made(True, "DEFAULT_RULE", "SILENT")
        if self.edge_free(then) and self.edge_free(els):
            # Плечи без рёбер и выходов: выбор не меняет рёбра; изменённые переменные станут неизвестными (havoc)
            take = True if kind == "loop" else outcome_arm(then, els, self.expected,
                                                           self.ex.options.no_signal_arm)[0] == "then"
            return made(take, "DEFAULT_RULE", "NO_EFFECT")
        fact_lines = facts.condition_facts(self, frame, cond, v)
        if self.expected == "success":
            used: list[Unknown] = []
            r = truth(resolve(v, default_leaf, used))
            if r is not None:
                return made(r, "DEFAULT_RULE", leaf_rules(used))
        verdict = self.ex.ask_judge(self, frame, v, kind=kind, line=line, cond=cond, text=text, facts=fact_lines)
        if verdict is not None and verdict.verdict in ("TRUE", "FALSE"):
            return made(verdict.verdict == "TRUE", "LLM_JUDGE", "JUDGE", verdict.reasoning, fact_lines)
        if kind == "loop":
            return made(True, "DEFAULT_RULE", "LOOP", "", fact_lines)
        arm, why = outcome_arm(then, els, self.expected, self.ex.options.no_signal_arm)
        return made(arm == "then", "DEFAULT_RULE", "OUTCOME", why, fact_lines)

    def record(self, frame: Frame, d: Decision) -> None:
        if self.silent:
            return
        frame.history.append(d)
        self.ex.count_decision(self, frame, d)

    def edge_free(self, stmts: list[dict[str, Any]]) -> bool:
        """В плече нет вызовов с рёбрами скелета (или целью IR) и нет выхода из метода или цикла."""
        for n in walk(stmts):
            if n.get("op") in ("return", "throw", "break", "continue"):
                return False
            cs = n.get("call")
            if isinstance(cs, str) and (n.get("target") or self.has_targets(cs)):
                return False
        return True

    def havoc(self, frame: Frame, stmts: list[dict[str, Any]], d: Decision) -> None:
        """После решения NO_EFFECT значения, которые меняют плечи, неизвестны: от них не решаются следующие условия."""
        names: set[str] = set()
        for n in walk(stmts):
            target = n.get("target") if (n.get("op") == "assign" or "assign" in n) else None
            if "un" in n and n.get("un") in ("++pre", "--pre", "post++", "post--"):
                target = n.get("e")
            if "callee" in n and (n["callee"] in MUTATORS or n["callee"].startswith("set")):
                target = n.get("recv")
            if isinstance(target, dict) and expr_kind(target) == "name" and target.get("ref") in ("local", "param"):
                names.add(target["name"])
        for name in sorted(names):
            if name not in frame.env:
                continue
            old = frame.env[name]
            if isinstance(old, Coll):
                kind = "collection"
            elif isinstance(old, bool):
                kind = "bool"
            elif isinstance(old, (int, float)):
                kind = "number"
            elif isinstance(old, str):
                kind = "string"
            else:
                kind = getattr(old, "kind", "object")
            frame.env[name] = Unknown(f"{name} after the condition at line {d.line} ({d.text[:70]})", kind,
                                      src="library", type=old.type if isinstance(old, Obj) else None)

    def has_targets(self, cs: str | None) -> bool:
        p = self.program
        return any(p.edges(cs, t) for t in ("calls", "runtime_dispatch", "remote_call", "message_delivery",
                                             "data_access"))

    def prune_arm(self, frame: Frame, stmts: list[dict[str, Any]], d: Decision) -> None:
        """Журнал: рёбра скелета из невзятого плеча — отсеяны этим решением."""
        if self.silent or self.ctx.ledger is None or not stmts:
            return
        tag = ";".join([x.tag() for x in frame.active] + [d.tag().rsplit(":", 1)[0] + ":" + d.arm])
        for n in walk(stmts):
            cs = n.get("call")
            if not isinstance(cs, str) or not cs.startswith("call:"):
                continue
            line, col = cs_pos(cs)
            for etype, rel in (("runtime_dispatch", "calls"), ("calls", "calls"), ("remote_call", "remote"),
                               ("message_delivery", "remote"), ("data_access", "data")):
                for t in self.program.edges(cs, etype):
                    if rel == "calls" and self.program.is_abstract(t):
                        continue
                    self.ctx.ledger.prune(rel, frame.method_id, t, d.source_type, tag, line=line, col=col)

    def cond_text(self, frame: Frame, st: dict[str, Any]) -> str:
        """Текст условия из исходника: строки от оператора до последнего вызова в условии."""
        ir = self.program.ir(frame.method_id) or {}
        line = st.get("line", 0)
        end = line
        for n in walk(st.get("cond")):
            for key in ("call",):
                cs = n.get(key)
                if isinstance(cs, str):
                    end = max(end, cs_pos(cs)[0])
            if "line" in n and isinstance(n["line"], int):
                end = max(end, n["line"])
        lines = self.ex.source_lines(ir.get("file", ""), line, min(end, line + 6))
        return " ".join(s.strip() for s in lines).strip()

    # --- выражения -------------------------------------------------------------------------------------------------

    def eval(self, node: Any, frame: Frame) -> Any:
        if node is None:
            return None
        k = expr_kind(node)
        fn = getattr(self, f"_e_{k}", None)
        if fn is None:
            return Unknown(f"unparsed expression at line {frame.line}", "object")
        return fn(node, frame)

    def _e_raw(self, node: Any, frame: Frame) -> Any:
        return Unknown(f"expression {str(node)[:40]}", "object")

    def _e_text(self, node: dict[str, Any], frame: Frame) -> Any:
        return Unknown(f"unparsed expression at line {frame.line}", "object")

    def _e_lit(self, node: dict[str, Any], frame: Frame) -> Any:
        v, t = node.get("lit"), node.get("type")
        if t == "null":
            return None
        if t in ("int", "long") and not isinstance(v, bool):
            return int(v)
        if t in ("double", "float"):
            return float(v)
        if t == "boolean":
            return bool(v)
        return v

    def _e_name(self, node: dict[str, Any], frame: Frame) -> Any:
        name, ref = node.get("name", ""), node.get("ref")
        if ref in ("local", "param"):
            if name in frame.env:
                return frame.env[name]
            return Unknown(f"variable {name}", "object", src="library")
        if ref == "field":
            if name in frame.env:  # поле, затенённое в лямбде, не встречается; на всякий случай
                return frame.env[name]
            if isinstance(frame.this, (Obj, Unknown)):
                return self.read_field(frame.this, name, frame)
            return self.static_field(self.program.owner_of(frame.method_id), name)
        if ref == "type":
            return TypeRef(name, simple_name(name))
        return frame.env.get(name, Unknown(f"name {name}", "object"))

    def _e_this(self, node: dict[str, Any], frame: Frame) -> Any:
        return frame.this

    def _e_super(self, node: dict[str, Any], frame: Frame) -> Any:
        return frame.this

    def _e_class(self, node: dict[str, Any], frame: Frame) -> Any:
        return Obj("java.lang.Class", {"name": node.get("class")}, src="library")

    def _e_field(self, node: dict[str, Any], frame: Frame) -> Any:
        of = self.eval(node.get("of"), frame)
        name = node.get("field", "")
        if isinstance(of, TypeRef):
            if name.lower() in ("logger", "log"):
                return Obj("org.slf4j.Logger", src="bean")
            if of.simple == "HttpHeaders" and name.isupper():
                return "-".join(w.capitalize() for w in name.split("_"))  # AUTHORIZATION -> "Authorization"
            if name.isupper():
                return name  # константа библиотечного enum: HttpMethod.GET -> "GET"
            return Unknown(f"static field {of.simple}.{name}", "object", src="field")
        if isinstance(of, (Obj, Unknown)):
            return self.read_field(of, name, frame)
        if isinstance(of, Coll) and name == "length":
            return len(of.items) if of.items is not None else Unknown(f"length of {of.origin}", "number")
        return Unknown(f"field {name}", "object")

    def _e_enum(self, node: dict[str, Any], frame: Frame) -> Any:
        return self.ex.enum_value(node["enum"], node.get("constant", ""), node.get("args") or [], self)

    def _e_const(self, node: dict[str, Any], frame: Frame) -> Any:
        return self.eval(node.get("value"), frame)

    def _e_bin(self, node: dict[str, Any], frame: Frame) -> Any:
        op = node.get("bin")
        a = self.eval(node.get("l"), frame)
        if op == "&&":
            return and_(a, lambda: self.eval(node.get("r"), frame))
        if op == "||":
            return or_(a, lambda: self.eval(node.get("r"), frame))
        b = self.eval(node.get("r"), frame)
        if isinstance(a, Obj) and isinstance(b, Obj) and op in ("==", "!="):
            return (a is b) if op == "==" else (a is not b)
        return binop(op, library.unbox(a), library.unbox(b))

    def _e_un(self, node: dict[str, Any], frame: Frame) -> Any:
        op = node.get("un", "")
        e = node.get("e")
        if op in ("++pre", "--pre", "post++", "post--"):
            old = self.eval(e, frame)
            new = binop("+" if "++" in op else "-", old, 1)
            self.assign_to(e, new, frame)
            return new if op.endswith("pre") else old
        return unop(op, self.eval(e, frame))

    def _e_assign(self, node: dict[str, Any], frame: Frame) -> Any:
        value = self.eval(node.get("expr"), frame)
        op = node.get("assign") or "="
        target = node.get("target") or {}
        if op != "=":
            value = binop(op[:-1], self.eval(target, frame), value)
        self.assign_to(target, value, frame)
        return value

    def _e_tern(self, node: dict[str, Any], frame: Frame) -> Any:
        c, _ = self.eval_cond(node.get("tern"), frame)
        t = truth(c)
        if t is True:
            return self.eval(node.get("then"), frame)
        if t is False:
            return self.eval(node.get("else"), frame)
        a = self.eval(node.get("then"), frame)
        b = self.eval(node.get("else"), frame)
        return a if (not is_unknown(a) and a == b) else Unknown(f"conditional value at line {frame.line}", "object")

    def _e_cast(self, node: dict[str, Any], frame: Frame) -> Any:
        v = self.eval(node.get("e"), frame)
        t = simple_name(node.get("cast"))
        if t in ("int", "long", "short", "byte") and isinstance(v, float):
            return int(v)
        if t in ("double", "float") and isinstance(v, int) and not isinstance(v, bool):
            return float(v)
        return v

    def _e_instanceof(self, node: dict[str, Any], frame: Frame) -> Any:
        v = self.eval(node.get("e"), frame)
        t = simple_name(node.get("instanceof"))
        if isinstance(v, Obj):
            return v.simple == t
        if v is None:
            return False
        return Sym("instanceof", (v, t)) if is_unknown(v) else True

    def _e_index(self, node: dict[str, Any], frame: Frame) -> Any:
        coll = self.eval(node.get("of"), frame)
        i = self.eval(node.get("index"), frame)
        if isinstance(coll, Coll) and coll.items is not None and isinstance(i, int) and 0 <= i < len(coll.items):
            return coll.items[i]
        return Unknown(f"element of {getattr(coll, 'origin', 'array')}", "object")

    def _e_new_array(self, node: dict[str, Any], frame: Frame) -> Any:
        init = node.get("init")
        if isinstance(init, list):
            return Coll([self.eval(x, frame) for x in init], src="new")
        return Coll([], src="new")

    def _e_lambda(self, node: dict[str, Any], frame: Frame) -> Any:
        return Lambda(node.get("lambda") or {}, frame.env, frame.this, frame.method_id)

    def _e_method_ref(self, node: dict[str, Any], frame: Frame) -> Any:
        cs = node.get("call")
        targets = tuple(self.program.edges(cs, "runtime_dispatch") or self.program.edges(cs, "calls"))
        return Lambda({"method_ref": node.get("method_ref"), "call": cs}, frame.env, frame.this, frame.method_id,
                      targets)

    def _e_new(self, node: dict[str, Any], frame: Frame) -> Any:
        tname = node.get("new", "")
        fqn = node.get("fqn") or self.program.resolve_simple(tname.split("<", 1)[0],
                                                             self.program.module_of(frame.method_id))
        args = [self.eval(a, frame) for a in node.get("args") or []]
        lib = library.construct(self, fqn, args, frame)
        if lib is not None:
            return lib
        cs = node.get("call")
        targets = [node["target"]] if node.get("target") else self.program.edges(cs, "calls")
        obj = Obj(fqn, src="new", origin=f"new {simple_name(fqn)} at line {frame.line}")
        if node.get("anon"):
            obj.fields["__anon__"] = node["anon"]
        line, col = cs_pos(cs)
        ctors = [t for t in targets if t.split("#", 1)[-1].startswith("<init>")]
        for x in ctors:
            if self.emit("calls", frame, x, line=line, col=col) or self.silent:
                self.invoke(x, frame.unit, args, this=obj, caller=frame, via=f"calls|{frame.method_id}|{x}",
                            call_line=line)
        if not ctors and args:
            # Конструктор без узла скелета (Lombok @AllArgsConstructor): аргументы по полям в порядке объявления
            fields = self.program.instance_fields(self.program.type_node(fqn, self.program.module_of(frame.method_id)))
            if len(fields) == len(args):
                obj.fields.update({f.name: a for f, a in zip(fields, args)})
        return obj

    def _e_call(self, node: dict[str, Any], frame: Frame) -> Any:
        cs = node.get("call")
        recv_node = node.get("recv")
        recv = self.eval(recv_node, frame) if recv_node is not None else None
        args = [self.eval(a, frame) for a in node.get("args") or []]
        line, col = cs_pos(cs)
        p = self.program
        if isinstance(cs, str):
            tables = p.edges(cs, "data_access")
            rc = self.ex.repo_call_at(frame.method_id, line, col)
            if tables or rc is not None:
                return repo.call(self, frame, node, recv, args, rc, tables, line, col)
            remote = p.edges(cs, "remote_call")
            if remote:
                return self.remote_call(frame, node, recv, args, remote, line, col)
            mq = p.edges(cs, "message_delivery")
            if mq:
                return self.mq_call(frame, mq, line, col)
            targets = [node["target"]] if node.get("target") else (
                p.edges(cs, "runtime_dispatch") or p.edges(cs, "calls"))
            if targets:
                return self.project_call(frame, node, targets, recv, args, line, col)
        return library.call(self, frame, node, recv, args)

    # --- вызовы ----------------------------------------------------------------------------------------------------

    def dispatch(self, targets: list[str], recv: Any, frame: Frame) -> list[str]:
        """Реализации для вызова (R2): runtime_dispatch, иначе CHA с выбором по типу получателя."""
        p = self.program
        obj = recv if recv is not None else frame.this
        rtype = obj.type if isinstance(obj, Obj) and obj.src != "bean" else None
        out: list[str] = []
        for t in targets:
            cands = p.implementations(t) if p.is_abstract(t) else [t] + p.implementations(t)
            if rtype:
                exact = [c for c in cands if p.owner_fqn(c) == rtype]
                if exact:
                    cands = exact
                elif not p.is_abstract(t):
                    cands = [t]
            elif not p.is_abstract(t):
                cands = [t]
            out.extend(c for c in cands if c not in out)
        return out

    def project_call(self, frame: Frame, node: dict[str, Any], targets: list[str], recv: Any, args: list[Any],
                     line: int, col: int) -> Any:
        result: Any = MISSING
        for x in self.dispatch(targets, recv, frame):
            if self.cross_unit(frame, x):
                continue
            if not self.emit("calls", frame, x, line=line, col=col) and not self.silent:
                continue
            this = self.receiver_for(x, recv, frame)
            v = self.invoke(x, frame.unit, args, this=this, caller=frame, via=f"calls|{frame.method_id}|{x}",
                            call_line=line)
            if result is MISSING:
                result = v
        if result is MISSING:
            return unknown_of(f"result of {node.get('callee')}() at line {line}", None, "call")
        return result

    def cross_unit(self, frame: Frame, target: str) -> bool:
        mod = self.index.module.get(target, "")
        if frame.unit in self.index.units.get(mod, ()):
            return False
        self.prune("calls", frame.method_id, target, "SKELETON", "cross_unit", unit=frame.unit)
        return True

    def call_lambda(self, lam: Lambda, args: list[Any], frame: Frame, host: str) -> Any:
        """Исполнение лямбды или ссылки на метод хостом библиотеки (R16)."""
        if lam.targets:
            line, col = cs_pos(lam.node.get("call"))
            result: Any = None
            for x in lam.targets:
                if self.emit("calls", frame, x, line=line, col=col):
                    result = self.invoke(x, frame.unit, args, this=self.receiver_for(x, args[0] if args else None,
                                                                                    frame),
                                         caller=frame, via=f"calls|{frame.method_id}|{x}", call_line=line)
            return result
        if "method_ref" in lam.node:
            return library.call_method_ref(self, lam, args)
        body = lam.node.get("body") or []
        env = dict(lam.env)
        for i, pname in enumerate(lam.node.get("params") or []):
            name = pname.get("name") if isinstance(pname, dict) else pname
            env[name] = args[i] if i < len(args) else Unknown(f"lambda parameter {name}", "object")
        lf = Frame(lam.method_id, frame.unit, lam.this, env, frame.depth + 1, frame, lam.node.get("line", 0))
        lf.active = list(frame.active) + [Decision(f"l{lam.node.get('line', 0)}", host, lam.node.get("line", 0),
                                                   "IR_BRANCH", "R16")]
        try:
            self.exec_block(body, lf)
        except ReturnSignal as r:
            return r.value
        return None

    def remote_call(self, frame: Frame, node: dict[str, Any], recv: Any, args: list[Any], targets: list[str],
                    line: int, col: int) -> Any:
        """RestTemplate: выбор обработчика по URL (R3) и переход в него (R12)."""
        callee = node.get("callee", "")
        url = args[0] if args else None
        verb = library.http_verb(callee, args)
        body, headers = library.request_parts(callee, args)
        segs, query = library.url_segments(url)
        chosen, rule = self.choose_remote(targets, segs, verb)
        result: Any = MISSING
        for t in chosen:
            if not self.emit("remote", frame, t, line=line, col=col, extra=("SKELETON", rule) if rule else None):
                continue
            hargs = self.bind_handler_args(t, segs, query, verb, body, headers)
            try:
                hv = self.invoke(t, self.index.unit_of(t), hargs, this=self.ex.singleton(self.program.owner_of(t)),
                                 caller=frame, via=f"remote|{frame.method_id}|{t}", call_line=line)
            except ThrowSignal:
                raise ThrowSignal(Obj("org.springframework.web.client.HttpServerErrorException", src="new"), line)
            if result is MISSING:
                result = hv
        if result is MISSING or len(chosen) > 1:
            body_v: Any = unknown_of(f"response of {verb or ''} {library.url_text(url)} (remote)", None, "remote")
        else:
            body_v = result.fields.get("body") if isinstance(result, Obj) and result.simple in (
                "ResponseEntity", "HttpEntity") else result
        if callee in ("getForObject", "postForObject"):
            return body_v
        if callee in ("put", "delete"):
            return None
        return Obj("org.springframework.http.ResponseEntity", {"body": body_v}, src="remote")

    def choose_remote(self, targets: list[str], segs: list[Any], verb: str | None) -> tuple[list[str], str | None]:
        if len(targets) == 1:
            return targets, None
        tpl = self.program.handler_templates
        hits: list[str] = []
        for lenient in (False, True):
            hits = [t for t in targets
                    if any((v is None or verb is None or v == verb) and match_template(segs, s, lenient) is not None
                           for v, s in tpl.get(t, []))]
            if hits:
                break
        if len(hits) == 1:
            return hits, "R3:url"
        self.ex.count("r3_unresolved")
        return (hits or targets), "R3:unresolved"

    def bind_handler_args(self, handler: str, segs: list[Any], query: dict[str, Any], verb: str | None, body: Any,
                          headers: Any) -> list[Any]:
        """Аргументы обработчика другого сервиса: тело, path-переменные, query, заголовки."""
        from engine.executor.program import ann_value

        pvars: dict[str, Any] = {}
        for v, s in self.program.handler_templates.get(handler, []):
            if v is None or verb is None or v == verb:
                m = match_template(segs, s, lenient=True)
                if m is not None:
                    pvars = m
                    break
        out: list[Any] = []
        for p in self.program.params_by_method.get(handler, []):
            ann = p.annotations
            name = ann_value(ann.get("PathVariable") or ann.get("RequestParam") or "") or p.name
            if "RequestBody" in ann:
                out.append(body if body is not None else unknown_of(f"request body of {short(handler)}", p.type,
                                                                    "remote", success_defaults=False))
            elif "PathVariable" in ann and name in pvars:
                out.append(pvars[name] if pvars[name] is not None else unknown_of(
                    f"path variable {name}", p.type, "remote", success_defaults=False))
            elif "RequestParam" in ann and name in query:
                out.append(query[name])
            elif "RequestHeader" in ann or simple_name(p.type) == "HttpHeaders":
                out.append(headers if headers is not None else Obj("org.springframework.http.HttpHeaders",
                                                                   src="library"))
            else:
                out.append(unknown_of(f"parameter {p.name} of {short(handler)}", p.type, "remote",
                                      success_defaults=False))
        return out

    def mq_call(self, frame: Frame, targets: list[str], line: int, col: int) -> Any:
        """Отправка в очередь: потребитель исполняется (R13), ребро remote от метода с отправкой."""
        for t in targets:
            if not self.emit("remote", frame, t, line=line, col=col):
                continue
            msg = Unknown(f"message sent at line {line} of {short(frame.method_id)}", "string", src="remote")
            try:
                self.invoke(t, self.index.unit_of(t), [msg], this=self.ex.singleton(self.program.owner_of(t)),
                            caller=frame, via=f"remote|{frame.method_id}|{t}", call_line=line)
            except ThrowSignal:
                pass
        return None

    # --- поля ------------------------------------------------------------------------------------------------------

    def read_field(self, obj: Any, name: str, frame: Frame | None = None) -> Any:
        if isinstance(obj, Unknown):
            return obj.child(f".{name}", lambda: self.unknown_field(obj, name))
        if not isinstance(obj, Obj):
            return Unknown(f"field {name}", "object")
        if obj.src == "state":
            self.taint = True
        if name in obj.fields:
            return obj.fields[name]
        v = self.missing_field(obj, name)
        obj.fields[name] = v
        return v

    def missing_field(self, obj: Obj, name: str) -> Any:
        p = self.program
        tn = p.type_node(obj.type)
        fi = p.field_info(tn, name)
        ftype = fi.type if fi else None
        if obj.src == "bean":
            return self.ex.bean_field(fi, name)
        if obj.src == "request":
            return unknown_of(f"{obj.simple}.{name} of the step request (not set by the step)", ftype, "request")
        if obj.src == "state":
            return unknown_of(f"{obj.simple}.{name} (not in the database row)", ftype, "state",
                              success_defaults=False)
        if obj.src in ("remote", "unknown"):
            return unknown_of(f"{obj.simple}.{name} of {obj.origin or 'remote object'}", ftype, "remote")
        if ftype is None:
            return None
        return PRIMITIVE_DEFAULTS.get(ftype, None)

    def unknown_field(self, parent: Unknown, name: str) -> Unknown:
        """Поле неизвестного объекта: статус ответа — D1, вложенные объекты результата вызова — D2."""
        ptype = simple_name(parent.type)
        from_call = parent.src in ("remote", "call", "repo")
        if name == "status" and (ptype in ("Response", "") and from_call):
            return Unknown(f"status of {parent.origin}", "status", 1, src=parent.src, type="java.lang.Integer",
                           rule="D1")
        if name in ("data", "body") and from_call:
            return Unknown(f"{name} of {parent.origin}", "object", NONNULL, src=parent.src, rule="D2")
        p = self.program
        fi = p.field_info(p.type_node(parent.type or ""), name) if parent.type else None
        return unknown_of(f"{name} of {parent.origin}", fi.type if fi else None, parent.src,
                          success_defaults=from_call)

    def static_field(self, owner_type_node: str, name: str) -> Any:
        if name.lower() in ("logger", "log"):
            return Obj("org.slf4j.Logger", src="bean")
        fi = self.program.field_info(owner_type_node, name)
        if fi is not None and fi.init_literal is not None:
            return library.literal(fi.init_literal, fi.type)
        return Unknown(f"static field {name}", "object", src="field")


__all__ = ["StepRun", "Frame", "Decision", "ReturnSignal", "ThrowSignal", "unknown_of", "short", "cs_pos",
           "MAX_ITER", "Iter", "Opt"]
