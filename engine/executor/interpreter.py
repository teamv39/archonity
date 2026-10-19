"""Исполнитель M4 (ADR-005): идёт по IR тел методов (`data/ir`) и пишет события исполнения.

- Условие считается по значениям в трёхзначной логике (TRUE, FALSE, UNKNOWN).
- UNKNOWN: правило успешного пути (плечо, которое кончается отказом `Response(0, ...)`/`throw`, не берём,
  если шаг не ожидает отказа), иначе исполняются оба плеча (как обход скелета).
- Вызов проектного метода — рекурсивный вход (цели из скелета: `calls`, `runtime_dispatch`, CHA; `target`
  IR для вызовов без рёбер скелета, R7). RestTemplate — вход в обработчик другого сервиса, цель выбирается
  по вычисленному URL и HTTP-методу (R3). Репозиторий — запрос к базе мира и событие SQL.
- Лямбда исполняется, только когда её вызывают (R16); `catch` — только при исключении (R15).

События: execute(method), call(caller, callee), remote(src, dst), data(method, table) — с причиной решения.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from engine.executor import library
from engine.executor.values import next_uid
from engine.executor.values import (
    UNKNOWN, Bean, Concat, EnumV, Lambda, ListV, MapV, MethodRef, Obj, OptionalV, TypeRef, Wrapper,
    concat, join, num, same_value, t_and, t_not, t_or, to_jstr, tri,
)
from engine.executor.world import (
    TypeIndex, World, derived_props, native_query_conds, optional_of,
)

LOGGER = logging.getLogger(__name__)

MAX_DEPTH = 48
MAX_LOOP = 40
MAX_INVOCATIONS = 60000


@dataclass
class Completion:
    normal: bool = True
    returns: list[Any] = field(default_factory=list)
    brk: bool = False
    cont: bool = False
    thrown: bool = False

    def union(self, o: Completion) -> Completion:
        return Completion(self.normal or o.normal, self.returns + o.returns, self.brk or o.brk,
                          self.cont or o.cont, self.thrown or o.thrown)


@dataclass
class Frame:
    method: str
    this: Any
    env: dict[str, Any]
    unit: str
    module: str
    owner: str | None
    # Последнее решение ветки на пути в этом кадре: (source_type, rule)
    why: tuple[str, str] = ("SKELETON", "ir_path")


class Sink:
    """События шага с причиной первого решения."""

    def __init__(self) -> None:
        self.methods: dict[str, tuple[str, str, str | None]] = {}
        self.calls: dict[tuple[str, str], tuple[str, str]] = {}
        self.remote: dict[tuple[str, str], tuple[str, str]] = {}
        self.data: dict[tuple[str, str], tuple[str, str]] = {}
        self.prunes: list[tuple[str, str, str, str, str]] = []
        self.unknowns: list[dict[str, Any]] = []
        self.muted = 0

    def execute(self, m: str, why: tuple[str, str], via: str | None) -> None:
        if not self.muted:
            self.methods.setdefault(m, (why[0], why[1], via))

    def edge(self, rel: str, s: str, t: str, why: tuple[str, str]) -> None:
        if self.muted:
            return
        getattr(self, rel).setdefault((s, t), why)

    def prune(self, rel: str, s: str, t: str, st: str, rule: str) -> None:
        if not self.muted:
            self.prunes.append((rel, s, t, st, rule))


class _Abort(Exception):
    pass


class Interpreter:
    """Исполнитель IR. Один на прогон; `begin_scenario` создаёт мир сценария, `run_step` — исполняет шаг."""

    def __init__(self, index: Any, rules: Any, ir_dir: Path, targets_root: Path | None, judge: Any = None) -> None:
        self.index = index
        self.rules = rules
        self.N: dict[str, dict[str, Any]] = index.N
        self.judge = judge
        sk_edges = index.sk.get("edges", [])
        self.types = TypeIndex(self.N, sk_edges, targets_root)
        self.ir: dict[str, dict[str, Any]] = {}
        for p in sorted(Path(ir_dir).glob("*.json")):
            with open(p, encoding="utf-8") as f:
                self.ir.update(json.load(f).get("methods", {}))
        # Рёбра скелета по call_site
        self.cs_calls: dict[str, set[str]] = {}
        self.cs_dispatch: dict[str, set[str]] = {}
        self.cs_remote: dict[str, set[str]] = {}
        self.cs_data: dict[str, set[str]] = {}
        self.cs_delivery: dict[str, set[str]] = {}
        bucket = {"calls": self.cs_calls, "runtime_dispatch": self.cs_dispatch, "remote_call": self.cs_remote,
                  "data_access": self.cs_data, "message_delivery": self.cs_delivery}
        for e in sk_edges:
            b = bucket.get(e["type"])
            if b is not None and e["source"].startswith("call:"):
                b.setdefault(e["source"], set()).add(e["target"])
        self.templates: dict[str, list[tuple[str | None, list[str]]]] = {}
        for nid, verb, segs in index.handlers:
            self.templates.setdefault(nid, []).append((verb, segs))
        self.params: dict[str, list[dict[str, Any]]] = {}
        for nid, n in self.N.items():
            if n.get("kind") == "parameter":
                self.params.setdefault(n["method"], []).append(n)
        for v in self.params.values():
            v.sort(key=lambda p: p.get("index", 0))
        # Вызовы репозиториев (факты archparse) по (метод, строка, колонка)
        self.repo_calls: dict[tuple[str, int, int], Any] = {}
        for m, calls in index.entities.calls_by_method.items():
            for c in calls:
                self.repo_calls[(m, c.line, c.col)] = c
        self.world: World | None = None
        self.sink = Sink()
        self.expected = "success"
        self.beans: dict[str, Obj] = {}
        self._enum_cache: dict[tuple[str, str], EnumV] = {}
        self.depth = 0
        self.invocations = 0
        self.stack: list[str] = []
        self.step: int | None = None
        # Журналы мутаций плеч, исполняемых обоими (UNKNOWN): ключ -> (объект, поле, старое значение)
        self.journal: list[dict[Any, tuple[Any, str, Any]]] = []
        self.journal_start: list[int] = []

    # --- сценарий и шаг -------------------------------------------------------

    def begin_scenario(self, db: Any) -> None:
        self.world = World(db, self.types, self.index.entities, self.enum_value)
        self.beans = {}

    def run_handler(self, handler: str, args: list[Any] | Callable[[], list[Any]], expected: str,
                    step: int | None) -> tuple[Sink, Any]:
        """Шаг: вход обработчика. `args` — список или функция, которая строит аргументы уже в sink шага
        (разбор тела запроса исполняет конструктор DTO, его события — события шага)."""
        self.sink = Sink()
        self.expected = expected or "success"
        self.step = step
        self.invocations = 0
        self.depth = 0
        self.stack = []
        self.sink.execute(handler, ("SKELETON", "ENTRY"), None)
        unit = self.index.unit_of(handler)
        try:
            if callable(args):
                args = args()
            ret = self.invoke(handler, None, args, unit, ("SKELETON", "ENTRY"))
        except _Abort:
            LOGGER.warning("M4: шаг %s прерван по бюджету вызовов", step)
            ret = UNKNOWN
        return self.sink, ret

    # --- мутации и слияние плеч ----------------------------------------------

    def set_field(self, obj: Any, name: str, val: Any) -> None:
        if self.journal and getattr(obj, "uid", -1) < self.journal_start[-1]:
            # объект, созданный внутри плеча, до плеча не существовал: его не откатываем
            key = (id(obj), name)
            top = self.journal[-1]
            if key not in top:
                top[key] = (obj, name, obj.fields.get(name, _MISSING))
        obj.fields[name] = val

    def touch_list(self, lst: ListV) -> None:
        if self.journal and lst.uid < self.journal_start[-1]:
            key = (id(lst), "#list")
            top = self.journal[-1]
            if key not in top:
                top[key] = (lst, "#list", (list(lst.items), lst.exact))

    def run_arms(self, arms: list[list[dict[str, Any]]], fr: Frame) -> Completion:
        """Исполнение нескольких плеч при неизвестном условии: мутации каждого изолированы, затем слияние."""
        results: list[tuple[Completion, dict[str, Any], dict[Any, Any]]] = []
        touched: dict[Any, tuple[Any, str, Any]] = {}
        for stmts in arms:
            j: dict[Any, tuple[Any, str, Any]] = {}
            self.journal.append(j)
            self.journal_start.append(next_uid())
            try:
                comp, env = self._arm(stmts, fr, fr.why)
            finally:
                self.journal.pop()
                self.journal_start.pop()
            new = {k: _current(o, f) for k, (o, f, _) in j.items()}
            for k, (o, f, old) in j.items():
                _restore(o, f, old)
                touched.setdefault(k, (o, f, old))
            results.append((comp, env, new))
        live = [r for r in results if r[0].normal] or results
        for k, (o, f, old) in touched.items():
            vals = [r[2].get(k, old) for r in live]
            if f == "#list":
                items: list[Any] = []
                exact = True
                for its, ex in vals:
                    exact = exact and ex
                    for x in its:
                        if all(x is not y for y in items):
                            items.append(x)
                if any(len(v[0]) != len(items) for v in vals):
                    exact = False
                self.touch_list(o)
                o.items[:] = items
                o.exact = exact
                continue
            v = vals[0]
            for x in vals[1:]:
                v = join(v, x) if v is not _MISSING and x is not _MISSING else UNKNOWN
            if v is _MISSING:
                continue
            self.set_field(o, f, v)
        self._merge_env(fr, *[(c, e) for c, e, _ in results])
        total = results[0][0]
        for c, _, _ in results[1:]:
            total = total.union(c)
        return total

    # --- enum ---------------------------------------------------------------

    def enum_value(self, type_id: str, key: Any) -> Any:
        """Константа enum по имени или порядковому номеру (значение колонки БД)."""
        consts = self.types.enum_constants(type_id)
        if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
            i = int(key)
            if not 0 <= i < len(consts):
                return UNKNOWN
            name = consts[i][0]
        else:
            name = str(key)
        return self.enum_const(type_id, name)

    def enum_const(self, type_id: str, name: str) -> Any:
        ck = (type_id, name)
        if ck in self._enum_cache:
            return self._enum_cache[ck]
        consts = self.types.enum_constants(type_id)
        idx = next((i for i, (c, _) in enumerate(consts) if c == name), None)
        ev = EnumV(self.types.fqn(type_id) or type_id, name, idx)
        self._enum_cache[ck] = ev
        if idx is not None:
            args = consts[idx][1]
            ctor = next((m for m in self.types.methods.get(type_id, ())
                         if self.N[m].get("name") == "<init>" and len(self.N[m].get("params_as_written") or []) == len(args)),
                        None)
            if ctor and ctor in self.ir:
                self.sink.muted += 1
                try:
                    self._run_body(ctor, ev, list(args), self.index.unit_of(ctor), ("SKELETON", "enum_init"))
                finally:
                    self.sink.muted -= 1
        return ev

    # --- вызов метода ---------------------------------------------------------

    def bean(self, type_id: str | None) -> Obj:
        key = type_id or "?"
        b = self.beans.get(key)
        if b is None:
            b = Obj(self.types.fqn(type_id), {}, open=True)
            for f in self.types.all_fields(type_id):
                ft = f.get("type") or ""
                anns = {a.get("name") for a in f.get("annotations") or []}
                if "Autowired" in anns or "Resource" in anns or ft.endswith("RestTemplate") or self.types.resolve(ft, None):
                    b.fields[f["name"]] = Bean(ft, f["name"])
            self.beans[key] = b
        return b

    def invoke(self, mid: str, this: Any, args: list[Any], unit: str, why: tuple[str, str]) -> Any:
        node = self.N.get(mid, {})
        owner = node.get("owner")
        if this is None and "static" not in (node.get("modifiers") or []) and not mid.endswith("#<init>()") \
                and "#<init>(" not in mid:
            this = self.bean(owner)
        if mid not in self.ir:
            return UNKNOWN
        if self.stack.count(mid) >= 2 or self.depth >= MAX_DEPTH:
            return UNKNOWN
        self.invocations += 1
        if self.invocations > MAX_INVOCATIONS:
            raise _Abort()
        return self._run_body(mid, this, args, unit, why)

    def _run_body(self, mid: str, this: Any, args: list[Any], unit: str, why: tuple[str, str]) -> Any:
        body = self.ir[mid]
        node = self.N.get(mid, {})
        env: dict[str, Any] = {}
        for i, p in enumerate(body.get("params") or []):
            env[p["name"]] = args[i] if i < len(args) else UNKNOWN
        fr = Frame(mid, this, env, unit, node.get("module", ""), node.get("owner"), why)
        self.depth += 1
        self.stack.append(mid)
        try:
            comp = self.exec_block(body.get("body") or [], fr)
        finally:
            self.depth -= 1
            self.stack.pop()
        if not comp.returns:
            return None if comp.normal else UNKNOWN
        ret = comp.returns[0]
        for r in comp.returns[1:]:
            ret = join(ret, r)
        if comp.normal and node.get("return") not in (None, "void"):
            # путь без return в методе с результатом бывает только при исключении
            pass
        return ret

    # --- операторы -----------------------------------------------------------

    def exec_block(self, stmts: list[dict[str, Any]], fr: Frame) -> Completion:
        comp = Completion()
        for s in stmts:
            c = self.exec_stmt(s, fr)
            comp = Completion(c.normal, comp.returns + c.returns, comp.brk or c.brk, comp.cont or c.cont,
                              comp.thrown or c.thrown)
            if not c.normal:
                return comp
        return comp

    def exec_stmt(self, s: dict[str, Any], fr: Frame) -> Completion:
        op = s.get("op")
        if op == "expr":
            self.eval(s["expr"], fr)
            return Completion()
        if op == "assign":
            val = self.eval(s["expr"], fr) if "expr" in s else UNKNOWN
            self.assign(s["target"], s.get("operator", "="), val, fr)
            return Completion()
        if op == "return":
            val = self.eval(s["expr"], fr) if "expr" in s else None
            if self.journal and isinstance(val, Obj) and val.uid < self.journal_start[-1]:
                val = Obj(val.type, dict(val.fields), open=val.open)  # плечо будет откачено
            return Completion(normal=False, returns=[val])
        if op == "throw":
            self.eval(s["expr"], fr)
            return Completion(normal=False, thrown=True)
        if op == "if":
            return self.exec_if(s, fr)
        if op == "foreach":
            return self.exec_foreach(s, fr)
        if op in ("while", "do", "for"):
            return self.exec_loop(s, fr)
        if op == "try":
            return self.exec_try(s, fr)
        if op == "switch":
            return self.exec_switch(s, fr)
        if op == "break":
            return Completion(normal=False, brk=True)
        if op == "continue":
            return Completion(normal=False, cont=True)
        if op == "block":
            return self.exec_block(s.get("body") or [], fr)
        return Completion()

    def _arm(self, stmts: list[dict[str, Any]], fr: Frame, why: tuple[str, str]) -> tuple[Completion, dict[str, Any]]:
        sub = Frame(fr.method, fr.this, dict(fr.env), fr.unit, fr.module, fr.owner, why)
        comp = self.exec_block(stmts, sub)
        return comp, sub.env

    def exec_if(self, s: dict[str, Any], fr: Frame) -> Completion:
        cond = tri(self.eval(s["cond"], fr))
        bid = s.get("id", f"b{s.get('line')}")
        short = fr.method.split(":", 2)[-1]
        then_s, else_s = s.get("then") or [], s.get("else") or []
        if cond is not UNKNOWN:
            arm, skipped = ("then", else_s) if cond else ("else", then_s)
            why = ("IR_BRANCH", f"{short}@{bid}:{arm}")
            self._prune_arm(skipped, fr, why)
            comp, env = self._arm(then_s if cond else else_s, fr, why)
            fr.env.update(env)
            return comp
        # UNKNOWN: правило успешного пути, затем судья, иначе оба плеча (ADR-005: сначала правила по умолчанию)
        if self.expected != "refused":
            tf, ef = arm_fails(then_s), arm_fails(else_s)
            if tf != ef:
                arm = "else" if tf else "then"
                why = ("DEFAULT_RULE", f"success_path:{short}@{bid}:{arm}")
                self._prune_arm(then_s if tf else else_s, fr, why)
                comp, env = self._arm(else_s if tf else then_s, fr, why)
                fr.env.update(env)
                self.sink.unknowns.append({"method": fr.method, "branch": bid, "line": s.get("line"),
                                           "decided": f"success_path:{arm}"})
                return comp
        verdict = None
        if self.judge is not None and not self.sink.muted:
            verdict = self.judge(fr, s)
        if verdict in (True, False):
            arm = "then" if verdict else "else"
            why = ("LLM_JUDGE", f"{short}@{bid}:{arm}")
            self._prune_arm(else_s if verdict else then_s, fr, why)
            comp, env = self._arm(then_s if verdict else else_s, fr, why)
            fr.env.update(env)
            self.sink.unknowns.append({"method": fr.method, "branch": bid, "line": s.get("line"),
                                       "decided": f"judge:{arm}"})
            return comp
        self.sink.unknowns.append({"method": fr.method, "branch": bid, "line": s.get("line"), "decided": "both"})
        return self.run_arms([then_s, else_s], fr)

    def _merge_env(self, fr: Frame, *arms: tuple[Completion, dict[str, Any]]) -> None:
        live = [env for comp, env in arms if comp.normal]
        if not live:
            return
        keys = set().union(*live)
        for k in keys:
            vals = [env.get(k, fr.env.get(k, UNKNOWN)) for env in live]
            v = vals[0]
            for x in vals[1:]:
                v = join(v, x)
            fr.env[k] = v

    def _prune_arm(self, stmts: list[dict[str, Any]], fr: Frame, why: tuple[str, str]) -> None:
        """Запись в журнал отсева: проектные вызовы в неисполненном плече."""
        if self.sink.muted:
            return
        for cs in iter_calls(stmts):
            for t in self.cs_calls.get(cs, ()):
                if not self.N.get(t, {}).get("abstract"):
                    self.sink.prune("calls", fr.method, t, why[0], why[1])
            for t in self.cs_remote.get(cs, ()):
                self.sink.prune("remote", fr.method, t, why[0], why[1])
            for t in self.cs_data.get(cs, ()):
                self.sink.prune("data", fr.method, t, why[0], why[1])

    def exec_foreach(self, s: dict[str, Any], fr: Frame) -> Completion:
        it = self.eval(s["iter"], fr)
        items, exact = iter_items(it)
        var = s.get("var")
        if exact and not items:
            why = ("STATE", f"R17:empty:{fr.method.split(':', 2)[-1]}@{s.get('id')}")
            self._prune_arm(s.get("body") or [], fr, why)
            return Completion()
        if not items:
            items = [UNKNOWN]
        total = Completion()
        envs = []
        for item in items[:MAX_LOOP]:
            fr.env[var] = item
            comp = self.exec_block(s.get("body") or [], fr)
            envs.append(comp)
            total = Completion(True, total.returns + comp.returns, False, False, total.thrown or comp.thrown)
            if comp.returns and not comp.normal and not comp.brk and not comp.cont:
                # выход из метода внутри цикла: остальные элементы не исполнялись бы, если return безусловный
                if exact and len(items) == 1:
                    return Completion(False, total.returns, False, False, total.thrown)
                break
            if comp.brk and not comp.normal and not comp.returns:
                break
        return total

    def exec_loop(self, s: dict[str, Any], fr: Frame) -> Completion:
        for st in s.get("init") or []:
            self.exec_stmt(st, fr)
        total = Completion()
        first = True
        for _ in range(MAX_LOOP):
            if s.get("op") != "do" or not first:
                c = tri(self.eval(s["cond"], fr)) if s.get("cond") is not None else True
                if c is False:
                    break
                unknown = c is UNKNOWN
            else:
                unknown = False
            first = False
            comp = self.exec_block(s.get("body") or [], fr)
            total = Completion(True, total.returns + comp.returns, False, False, total.thrown or comp.thrown)
            if (comp.brk and not comp.normal) or (comp.returns and not comp.normal):
                break
            for u in s.get("update") or []:
                self.eval(u, fr)
            if unknown:
                break
        return total

    def exec_try(self, s: dict[str, Any], fr: Frame) -> Completion:
        for r in s.get("resources") or []:
            self.exec_stmt(r, fr)
        comp = self.exec_block(s.get("body") or [], fr)
        catches = s.get("catches") or []
        if comp.thrown and catches:
            out = Completion(comp.normal and not comp.thrown, comp.returns, comp.brk, comp.cont, False)
            for c in catches:
                if c.get("var"):
                    fr.env[c["var"]] = UNKNOWN
                out = out.union(self.exec_block(c.get("body") or [], fr))
            comp = out
        elif catches and not self.sink.muted:
            why = ("DEFAULT_RULE", f"R15:{fr.method.split(':', 2)[-1]}@{s.get('id')}:catch")
            for c in catches:
                self._prune_arm(c.get("body") or [], fr, why)
        if s.get("finally"):
            fin = self.exec_block(s["finally"], fr)
            if not fin.normal:
                return fin
        return comp

    def exec_switch(self, s: dict[str, Any], fr: Frame) -> Completion:
        sel = self.eval(s["selector"], fr)
        cases = s.get("cases") or []
        start = None
        if sel is not UNKNOWN:
            for i, c in enumerate(cases):
                for lab in c.get("labels") or []:
                    lv = self._case_label(lab, sel, fr)
                    if same_value(lv, sel) is True:
                        start = i
                        break
                if start is not None:
                    break
            if start is None:
                start = next((i for i, c in enumerate(cases) if not c.get("labels")), None)
            if start is None:
                return Completion()
            total = Completion()
            for c in cases[start:]:
                comp = self.exec_block(c.get("body") or [], fr)
                total = total.union(comp) if not total.normal else comp
                if not comp.normal:
                    return Completion(not comp.returns and comp.brk, comp.returns, False, comp.cont, comp.thrown)
            return total
        bodies = [c.get("body") or [] for c in cases]
        if not any(not c.get("labels") for c in cases):
            bodies.append([])
        comp = self.run_arms(bodies, fr)
        return Completion(comp.normal or comp.brk, comp.returns, False, comp.cont, comp.thrown)

    def _case_label(self, lab: dict[str, Any], sel: Any, fr: Frame) -> Any:
        if "name" in lab and isinstance(sel, EnumV):
            tid = self.types.resolve(sel.type, fr.module)
            return self.enum_const(tid, lab["name"]) if tid else UNKNOWN
        return self.eval(lab, fr)

    # --- присваивание ---------------------------------------------------------

    def assign(self, target: dict[str, Any], operator: str, val: Any, fr: Frame) -> Any:
        if operator != "=":
            cur = self.eval(target, fr)
            val = self.binop(operator[:-1], cur, val)
        if "name" in target:
            if target.get("ref") == "field" and isinstance(fr.this, Obj) and target["name"] not in fr.env:
                self.set_field(fr.this, target["name"], val)
            else:
                fr.env[target["name"]] = val
        elif "field" in target:
            obj = self.eval(target["of"], fr)
            if isinstance(obj, (Obj, EnumV)):
                self.set_field(obj, target["field"], val)
        return val

    # --- выражения -----------------------------------------------------------

    def eval(self, e: Any, fr: Frame) -> Any:
        if not isinstance(e, dict):
            return UNKNOWN
        if "call" in e and "callee" in e:
            return self.eval_call(e, fr)
        if "new" in e:
            return self.eval_new(e, fr)
        if "lit" in e:
            t = e.get("type")
            v = e["lit"]
            if t == "null":
                return None
            if t in ("double", "float") and v is not None:
                return float(v)
            return v
        if "name" in e:
            return self.eval_name(e, fr)
        if "field" in e:
            return self.eval_field(e, fr)
        if "bin" in e:
            return self.eval_bin(e, fr)
        if "un" in e:
            return self.eval_un(e, fr)
        if "enum" in e:
            tid = self.types.resolve(e["enum"], fr.module)
            return self.enum_const(tid, e["constant"]) if tid else UNKNOWN
        if "const" in e:
            return self.eval(e.get("value"), fr)
        if "tern" in e:
            c = tri(self.eval(e["tern"], fr))
            if c is True:
                return self.eval(e["then"], fr)
            if c is False:
                return self.eval(e["else"], fr)
            return join(self.eval(e["then"], fr), self.eval(e["else"], fr))
        if "assign" in e:
            return self.assign(e["target"], e["assign"], self.eval(e["expr"], fr), fr)
        if "cast" in e:
            v = self.eval(e["e"], fr)
            if e["cast"] in ("int", "long") and isinstance(v, float):
                return int(v)
            if e["cast"] in ("double", "float") and isinstance(v, int) and not isinstance(v, bool):
                return float(v)
            return v
        if "instanceof" in e:
            v = self.eval(e["e"], fr)
            simple = re.sub(r"<.*>", "", e["instanceof"]).rsplit(".", 1)[-1]
            if v is None:
                return False
            if isinstance(v, Obj) and v.type:
                return v.type.rsplit(".", 1)[-1].split("$")[-1] == simple or UNKNOWN
            return UNKNOWN
        if "lambda" in e:
            lam = e["lambda"] if isinstance(e["lambda"], dict) else e
            return Lambda([p if isinstance(p, str) else p.get("name", "") for p in lam.get("params") or []],
                          lam.get("body") or [], dict(fr.env), fr.this, fr.method, lam.get("line", 0))
        if "method_ref" in e:
            cs = e.get("call")
            tgt = next(iter(self.cs_calls.get(cs, ())), None) if cs else None
            return MethodRef(tgt, cs)
        if "new_array" in e:
            return ListV([self.eval(x, fr) for x in e.get("init") or []], exact=True)
        if "this" in e or "super" in e:
            return fr.this
        if "class" in e:
            return UNKNOWN
        if "index" in e:
            arr = self.eval(e["of"], fr)
            i = self.eval(e["index"], fr)
            if isinstance(arr, ListV) and arr.exact and isinstance(i, int) and 0 <= i < len(arr.items):
                return arr.items[i]
            return UNKNOWN
        return UNKNOWN

    def eval_name(self, e: dict[str, Any], fr: Frame) -> Any:
        name, ref = e["name"], e.get("ref")
        if ref in ("local", "param", "unknown") or name in fr.env:
            return fr.env.get(name, UNKNOWN)
        if ref == "field":
            if isinstance(fr.this, (Obj, EnumV)):
                v = fr.this.get(name)
                if v is not UNKNOWN or name in fr.this.fields:
                    return v
            return self.static_field(fr.owner, name)
        if ref == "type":
            tid = self.types.resolve_simple(name, fr.module)
            return TypeRef(self.types.fqn(tid) if tid else name)
        return UNKNOWN

    def static_field(self, owner: str | None, name: str) -> Any:
        for f in self.types.fields.get(owner or "", ()):
            if f["name"] == name and f.get("init_literal") is not None:
                return lit_value(f["init_literal"])
        return UNKNOWN

    def eval_field(self, e: dict[str, Any], fr: Frame) -> Any:
        of = self.eval(e["of"], fr)
        name = e["field"]
        if isinstance(of, TypeRef):
            tid = self.types.resolve(of.fqn, fr.module)
            if tid and self.types.is_enum(tid):
                return self.enum_const(tid, name)
            if tid:
                return self.static_field(tid, name)
            simple = of.fqn.rsplit(".", 1)[-1]
            if simple in ("HttpMethod", "HttpStatus", "MediaType"):
                return name
            if simple == "Calendar":
                return library.CALENDAR_FIELDS.get(name, UNKNOWN)
            return library.JDK_CONSTANTS.get((simple, name), UNKNOWN)
        if isinstance(of, (Obj, EnumV)):
            return of.get(name)
        if isinstance(of, ListV) and name == "length":
            return len(of.items) if of.exact else UNKNOWN
        return UNKNOWN

    def eval_bin(self, e: dict[str, Any], fr: Frame) -> Any:
        op = e["bin"]
        if op == "&&":
            a = tri(self.eval(e["l"], fr))
            if a is False:
                return False
            return t_and(a, tri(self.eval(e["r"], fr)))
        if op == "||":
            a = tri(self.eval(e["l"], fr))
            if a is True:
                return True
            return t_or(a, tri(self.eval(e["r"], fr)))
        return self.binop(op, self.eval(e["l"], fr), self.eval(e["r"], fr))

    def binop(self, op: str, a: Any, b: Any) -> Any:
        if op == "==":
            return same_value(a, b)
        if op == "!=":
            return t_not(same_value(a, b))
        if op == "+" and (isinstance(a, (str, Concat)) or isinstance(b, (str, Concat))):
            return concat(a, b)
        if op in ("&", "|", "^") and isinstance(a, bool) and isinstance(b, bool):
            return {"&": a and b, "|": a or b, "^": a != b}[op]
        x, y = num(a), num(b)
        if x is UNKNOWN or y is UNKNOWN or isinstance(a, str) or isinstance(b, str):
            if op == "+" and (a is UNKNOWN or b is UNKNOWN):
                return UNKNOWN
            return UNKNOWN
        try:
            if op == "+":
                return x + y
            if op == "-":
                return x - y
            if op == "*":
                return x * y
            if op == "/":
                if y == 0:
                    return UNKNOWN
                return x // y if isinstance(x, int) and isinstance(y, int) else x / y
            if op == "%":
                return x % y if y else UNKNOWN
            if op == "<":
                return x < y
            if op == "<=":
                return x <= y
            if op == ">":
                return x > y
            if op == ">=":
                return x >= y
        except TypeError:
            return UNKNOWN
        return UNKNOWN

    def eval_un(self, e: dict[str, Any], fr: Frame) -> Any:
        op = e["un"]
        v = self.eval(e["e"], fr)
        if op == "!":
            return t_not(tri(v))
        if op == "-":
            n = num(v)
            return -n if n is not UNKNOWN else UNKNOWN
        if op in ("++pre", "--pre", "post++", "post--"):
            n = num(v)
            nv = UNKNOWN if n is UNKNOWN else (n + 1 if "++" in op else n - 1)
            self.assign(e["e"], "=", nv, fr)
            return nv if op.endswith("pre") else v
        return v

    # --- new -----------------------------------------------------------------

    def eval_new(self, e: dict[str, Any], fr: Frame) -> Any:
        args = [self.eval(a, fr) for a in e.get("args") or []]
        written = re.sub(r"<.*>", "", e["new"])
        fqn = e.get("fqn")
        tid = self.types.resolve(fqn, fr.module) if fqn else None
        if tid is None and not fqn:
            lib = library.new_library(self, written, args)
            if lib is not None:
                return lib
        if tid is None:
            lib = library.new_library(self, written, args)
            return lib if lib is not None else UNKNOWN
        obj = Obj(fqn, {}, open=False)
        for f in self.types.all_fields(tid):
            obj.fields[f["name"]] = default_value(f)
        cs = e.get("call")
        ctors = [t for t in self.cs_calls.get(cs, ())] if cs else []
        if not ctors and e.get("target"):
            ctors = [e["target"]]
        ran = False
        for ctor in ctors:
            if "Exception#<init>" in ctor:
                self.sink.prune("calls", fr.method, ctor, "DEFAULT_RULE", "exception_ctor")
                continue
            if ctor not in self.N or self.N[ctor].get("abstract"):
                continue
            self._record_call(fr, ctor, "IR_CALL" if not self.cs_calls.get(cs) else None)
            self.invoke(ctor, obj, args, fr.unit, fr.why)
            ran = True
        if not ran and args:
            fields = self.types.all_fields(tid)
            if len(fields) == len(args):
                for f, a in zip(fields, args):
                    obj.fields[f["name"]] = a
            else:
                obj.open = True
        return obj

    # --- вызовы --------------------------------------------------------------

    def _record_call(self, fr: Frame, target: str, ir_call: str | None = None) -> None:
        why = ("IR_CALL", ";".join(["R7", fr.why[1]])) if ir_call else fr.why
        self.sink.edge("calls", fr.method, target, why)
        self.sink.execute(target, why, f"calls|{fr.method}|{target}")

    def eval_call(self, e: dict[str, Any], fr: Frame) -> Any:
        cs = e.get("call")
        callee = e.get("callee", "")
        recv_e = e.get("recv")
        recv = self.eval(recv_e, fr) if recv_e is not None else None
        raw_args = e.get("args") or []
        args = [self.eval(a, fr) for a in raw_args]
        self.log_format(e, args, fr)
        if cs in self.cs_remote:
            return self.remote_call(fr, cs, callee, args)
        if cs in self.cs_data:
            return self.repository_call(fr, cs, callee, recv, args)
        if cs in self.cs_delivery:
            return self.message_call(fr, cs, args)
        targets = self.call_targets(fr, cs, recv)
        ir_target = False
        if not targets and e.get("target") and e["target"] in self.N:
            targets = [e["target"]]
            ir_target = True
        if targets:
            this = recv if isinstance(recv, (Obj, EnumV)) else (fr.this if recv_e is None else None)
            ret: Any = None
            first = True
            for t in targets:
                self._record_call(fr, t, "IR_CALL" if ir_target else None)
                if self.N[t].get("name") == "<init>":
                    this_t = this
                else:
                    this_t = this
                r = self.invoke(t, this_t, args, fr.unit, fr.why)
                ret = r if first else join(ret, r)
                first = False
            if ret is UNKNOWN and isinstance(recv, Obj):
                # проектный метод без тела в IR (не должно быть) — пробуем как геттер
                lib = library.call_library(self, fr, callee, recv, args, e)
                return lib
            return ret
        return library.call_library(self, fr, callee, recv, args, e)

    def call_targets(self, fr: Frame, cs: str | None, recv: Any) -> list[str]:
        """Цели проектного вызова (R2): runtime_dispatch, иначе метод и его переопределения (CHA)."""
        if not cs:
            return []
        out: list[str] = []
        disp = self.cs_dispatch.get(cs)
        for t in sorted(self.cs_calls.get(cs, ())):
            if disp:
                cands = set(disp)
            elif self.N.get(t, {}).get("abstract"):
                cands = self.index.cha(t)
            else:
                cands = {t} | self.index.cha(t)
            for x in sorted(cands):
                n = self.N.get(x, {})
                if n.get("abstract"):
                    continue
                if fr.unit not in self.index.units.get(self.index.module.get(x, ""), ()):
                    self.sink.prune("calls", fr.method, x, "SKELETON", "cross_unit")
                    continue
                if "Exception#<init>" in x:
                    self.sink.prune("calls", fr.method, x, "DEFAULT_RULE", "exception_ctor")
                    continue
                if x not in out:
                    out.append(x)
        # Тип получателя известен: оставляем реализацию его класса (R2)
        if len(out) > 1 and isinstance(recv, Obj) and recv.type:
            tid = self.types.resolve(recv.type, fr.module)
            chain = set()
            t = tid
            while t and t not in chain:
                chain.add(t)
                t = self.types.super_of.get(t)
            narrowed = [x for x in out if self.N[x].get("owner") in chain]
            if narrowed:
                for x in out:
                    if x not in narrowed:
                        self.sink.prune("calls", fr.method, x, "STATE", "receiver_type")
                out = narrowed
        return out

    # --- удалённые вызовы (RestTemplate, R3) ----------------------------------

    def remote_call(self, fr: Frame, cs: str, callee: str, args: list[Any]) -> Any:
        url = args[0] if args else UNKNOWN
        verb = {"getForObject": "GET", "getForEntity": "GET", "postForObject": "POST", "postForEntity": "POST",
                "put": "PUT", "delete": "DELETE"}.get(callee)
        body: Any = UNKNOWN
        if callee == "exchange" and len(args) >= 3:
            verb = args[1] if isinstance(args[1], str) else None
            body = args[2].body if isinstance(args[2], Wrapper) else UNKNOWN
        elif callee in ("postForObject", "postForEntity", "put") and len(args) >= 2:
            body = args[1].body if isinstance(args[1], Wrapper) else args[1]
        cands = sorted(self.cs_remote.get(cs, ()))
        chosen = self.select_handlers(cands, url, verb)
        rets: list[Any] = []
        for h, binding in chosen:
            why = fr.why if len(chosen) == len(cands) else ("IR_BRANCH", f"R3:url_dispatch@{cs.rsplit('@', 1)[-1]}")
            self.sink.edge("remote", fr.method, h, why)
            self.sink.execute(h, why, f"remote|{fr.method}|{h}")
            hargs = self.bind_handler(h, body, binding)
            r = self.invoke(h, None, hargs, self.index.unit_of(h), why)
            rets.append(r)
        for h in cands:
            if all(h != c for c, _ in chosen):
                self.sink.prune("remote", fr.method, h, "IR_BRANCH", f"R3:url_dispatch@{cs.rsplit('@', 1)[-1]}")
        if not rets:
            return Wrapper(UNKNOWN, "response")
        ret = rets[0]
        for r in rets[1:]:
            ret = join(ret, r)
        return ret if isinstance(ret, Wrapper) else Wrapper(ret, "response")

    def select_handlers(self, cands: list[str], url: Any, verb: str | None) -> list[tuple[str, dict[str, Any]]]:
        """Обработчики, чей сервис и шаблон пути совпадают с URL запроса."""
        text = url if isinstance(url, str) else (url.render() if isinstance(url, Concat) else None)
        if text is None:
            return [(h, {}) for h in cands]
        host = None
        path = text
        m = re.match(r"^https?://([^/:\x00]+)(?::\d+)?(/.*)?$", text)
        if m:
            host, path = m.group(1), m.group(2) or "/"
        query = ""
        if "?" in path:
            path, query = path.split("?", 1)
        segs = [s for s in path.split("/") if s]
        out: list[tuple[str, dict[str, Any], int]] = []
        for h in cands:
            mod = self.N.get(h, {}).get("module", "")
            if host and "\x00" not in host and host != mod:
                continue
            for tverb, tpl in self.templates.get(h, []):
                if verb and tverb and tverb != verb:
                    continue
                b = match_template(segs, tpl)
                if b is not None:
                    # дыра URL на месте литерального сегмента шаблона — совпадение хуже, чем с {переменной}
                    holes_on_literals = sum(1 for i, t in enumerate(tpl)
                                            if i < len(segs) and "\x00" in segs[i] and not t.startswith("{"))
                    if query:
                        for kv in query.split("&"):
                            if "=" in kv:
                                k, v = kv.split("=", 1)
                                b[k] = UNKNOWN if "\x00" in v else v
                    out.append((h, b, holes_on_literals))
                    break
        if not out:
            return [(h, {}) for h in cands]
        best = min(r for _, _, r in out)
        return [(h, b) for h, b, r in out if r == best]

    def bind_handler(self, h: str, body: Any, binding: dict[str, Any]) -> list[Any]:
        out = []
        for p in self.params.get(h, []):
            anns = {a.get("name"): a.get("args", "") for a in p.get("annotations") or []}
            if "RequestBody" in anns:
                self.jackson_new(p.get("type"), self.N[h].get("module"), h)
                out.append(self.jackson_fill(library.json_copy(body, p.get("type")), self.N[h].get("module")))
            elif "PathVariable" in anns:
                m = re.search(r'"([^"]+)"', anns["PathVariable"] or "")
                out.append(binding.get(m.group(1) if m else p["name"], UNKNOWN))
            elif "RequestHeader" in anns:
                out.append(UNKNOWN)
            else:
                out.append(binding.get(p["name"], UNKNOWN))
        return out

    def jackson_new(self, ftype: str | None, module: str | None, handler: str) -> None:
        """Jackson создаёт тело запроса конструктором без аргументов (R7, ADR-006).

        Исполняется только рукописный конструктор (узел скелета): из `RebookInfo()` вызывается
        `StringUtils.Date2String`. Ребра в конструктор нет, в ответ его пропускает проекция R7, только если из него
        исполнился вызов проекта. Значения конструктора в тело не идут: какие поля пришли в JSON, неизвестно,
        поэтому тело строит вызывающий (`build_dto`, `json_copy`), а конструктор даёт только события.
        """
        if getattr(self.rules, "jackson_ctor", "on") != "on":
            return
        tid = self.types.resolve(ftype, module) if ftype else None
        if not tid:
            return
        ctor = next((m for m in self.types.methods.get(tid, ())
                     if self.N[m].get("name") == "<init>" and not (self.N[m].get("params_as_written") or [])), None)
        if ctor is None or ctor not in self.ir:
            return
        why = ("FRAMEWORK_RULE", "R7:jackson_ctor")
        self.sink.execute(ctor, why, f"jackson|{handler}|{ctor}")
        obj = Obj(self.types.fqn(tid), {f["name"]: default_value(f) for f in self.types.all_fields(tid)}, open=False)
        self.invoke(ctor, obj, [], self.index.unit_of(ctor), why)

    # --- Lombok-toString при логировании (R5) --------------------------------

    LOG_LEVELS = ("info", "warn", "error")  # уровень по умолчанию Spring Boot — INFO: debug/trace не форматируются
    LOMBOK_TOSTRING = {"Data", "ToString", "Value"}

    def is_logger(self, recv_e: dict[str, Any] | None, fr: Frame) -> bool:
        """Приёмник — поле типа SLF4J Logger: `LOGGER` своего класса или `Cls.LOGGER`."""
        if not recv_e:
            return False
        if recv_e.get("ref") == "field" and recv_e.get("name"):
            name, owner = recv_e["name"], self.N.get(fr.method, {}).get("owner")
        elif recv_e.get("field") and (recv_e.get("of") or {}).get("ref") == "type":
            cls = recv_e["of"].get("name")
            name = recv_e["field"]
            owner = self.types.resolve(cls, fr.module) or self.types.resolve_simple(cls, fr.module)
        else:
            return False
        return any(f.get("name") == name and (f.get("type") or "").endswith("Logger")
                   for f in self.types.fields.get(owner or "", []))

    def log_format(self, e: dict[str, Any], args: list[Any], fr: Frame) -> None:
        """SLF4J подставляет аргументы в `{}` через toString: Lombok-toString читает поля через геттеры."""
        raw = e.get("args") or []
        if (getattr(self.rules, "lombok_tostring", "on") != "on" or e.get("callee") not in self.LOG_LEVELS
                or not raw or "{}" not in str(raw[0].get("lit") or "") or not self.is_logger(e.get("recv"), fr)):
            return
        seen: set[int] = set()
        for v in args[1:]:
            self.lombok_tostring(v, fr, seen, 0)

    def lombok_tostring(self, v: Any, fr: Frame, seen: set[int], depth: int) -> None:
        """toString значения: рукописный — исполняется; сгенерированный Lombok — рукописные геттеры полей
        исполняются (ребра calls нет, вызывает сгенерированный код, R5), вложенные объекты — так же."""
        if depth > 4 or id(v) in seen:
            return
        seen.add(id(v))
        if isinstance(v, ListV):
            for x in v.items:
                self.lombok_tostring(x, fr, seen, depth + 1)
            return
        if isinstance(v, MapV):
            for x in list(v.data.values()):
                self.lombok_tostring(x, fr, seen, depth + 1)
            return
        if not isinstance(v, Obj) or not v.type:
            return
        tid = self.types.resolve(v.type, fr.module)
        if not tid:
            return
        why = ("FRAMEWORK_RULE", "R5:lombok_tostring")
        own = {self.N[m].get("name"): m for m in self.types.methods.get(tid, ())
               if not (self.N[m].get("params_as_written") or [])}
        if "toString" in own:
            m = own["toString"]
            if m in self.ir:
                self.sink.execute(m, why, f"tostring|{fr.method}|{m}")
                self.invoke(m, v, [], self.index.unit_of(m), why)
            return
        anns = {a.get("name") for a in self.types.types.get(tid, {}).get("annotations") or []}
        if not anns & self.LOMBOK_TOSTRING:
            return
        for f in self.types.fields.get(tid, []):
            if "static" in (f.get("modifiers") or []):
                continue
            name = f["name"]
            cap = name[:1].upper() + name[1:]
            getter = own.get("is" + cap) if f.get("type") == "boolean" else None
            getter = getter or own.get("get" + cap)
            val = v.fields.get(name, UNKNOWN)
            if getter and getter in self.ir:
                self.sink.execute(getter, why, f"tostring|{fr.method}|{getter}")
                r = self.invoke(getter, v, [], self.index.unit_of(getter), why)
                if r is not UNKNOWN:
                    val = r
            self.lombok_tostring(val, fr, seen, depth + 1)

    def jackson_fill(self, obj: Any, module: str | None) -> Any:
        """Jackson заполняет DTO через сеттеры: рукописный сеттер (Station.setName нормализует имя) исполняется.

        Вызов идёт через отражение библиотеки, поэтому событий нет (REFERENCE исключает такие вызовы).
        """
        if not isinstance(obj, Obj) or not obj.type:
            return obj
        tid = self.types.resolve(obj.type, module)
        if not tid:
            return obj
        for name, v in list(obj.fields.items()):
            if v is UNKNOWN:
                continue
            setter = self.types.method_of(tid, "set" + name[:1].upper() + name[1:], 1)
            if setter and setter in self.ir:
                self.sink.muted += 1
                try:
                    self._run_body(setter, obj, [v], self.index.unit_of(setter), ("SKELETON", "jackson_setter"))
                except Exception:  # noqa: BLE001 — сеттер без модели значения не должен ронять шаг
                    obj.fields[name] = v
                finally:
                    self.sink.muted -= 1
        return obj

    def message_call(self, fr: Frame, cs: str, args: list[Any]) -> Any:
        if getattr(self.rules, "rabbitmq_delivery", "on") == "off":
            for t in self.cs_delivery.get(cs, ()):
                self.sink.prune("remote", fr.method, t, "DEFAULT_RULE", "ablate_rabbitmq_delivery")
            return None
        for t in sorted(self.cs_delivery.get(cs, ())):
            self.sink.edge("remote", fr.method, t, fr.why)
            self.sink.execute(t, fr.why, f"remote|{fr.method}|{t}")
            self.invoke(t, None, [UNKNOWN] * len(self.params.get(t, [])), self.index.unit_of(t), fr.why)
        return None

    # --- репозитории ----------------------------------------------------------

    def repository_call(self, fr: Frame, cs: str, callee: str, recv: Any, args: list[Any]) -> Any:
        node = self.N.get(cs, {})
        rc = self.repo_calls.get((fr.method, node.get("line"), node.get("col")))
        repo_m = next(iter(sorted(self.cs_calls.get(cs, ()))), None)
        repo_node = self.N.get(repo_m or "", {})
        entity = rc.entity.type if rc is not None and rc.entity is not None else None
        result, rows = self._repo_semantics(fr, callee, args, entity, repo_node)
        for t in sorted(self.cs_data.get(cs, ())):
            ok, why = self._data_table_allowed(fr, t)
            if ok:
                self.sink.edge("data", fr.method, t, why)
            else:
                self.sink.prune("data", fr.method, t, why[0], why[1])
        if rc is not None:
            self._hydrate(fr, rc, rows)
        return result

    def _data_table_allowed(self, fr: Frame, t: str) -> tuple[bool, tuple[str, str]]:
        sf_mode = getattr(self.rules, "station_food_collection", "store_browse_only")
        if "station_food_list" in t and sf_mode == "off":
            return False, ("FRAMEWORK_RULE", "store_browse_no_food_items")
        if getattr(self.rules, "collection_tables_on_read", "loaded") != "all":
            dec = self.index.entities.collection_table_loaded(fr.method, t)
            if dec is not None:
                return dec[0], ("STATE", dec[1])
        return True, fr.why

    def _repo_semantics(self, fr: Frame, callee: str, args: list[Any], entity: str | None,
                        repo_node: dict[str, Any]) -> tuple[Any, Any]:
        """Результат вызова репозитория и наличие строк (True, False, UNKNOWN) для R7."""
        w = self.world
        ret_t = repo_node.get("return") or ""
        many = any(x in ret_t for x in ("List", "Set", "Collection", "Iterable")) or ret_t.endswith("ArrayList")
        if entity is None or w is None or entity not in w.table_of:
            if callee.startswith("save"):
                return (args[0] if args else UNKNOWN), UNKNOWN
            if many:
                return ListV([], exact=False), UNKNOWN
            if "Optional" in ret_t:
                return OptionalV(UNKNOWN), UNKNOWN
            return UNKNOWN, UNKNOWN
        mod = fr.module
        if callee in ("save", "saveAndFlush"):
            obj = args[0] if args else UNKNOWN
            w.save(entity, obj, mod)
            return obj, True
        if callee == "saveAll":
            lst = args[0] if args else UNKNOWN
            if isinstance(lst, ListV):
                for x in lst.items:
                    w.save(entity, x, mod)
            return lst, True
        if callee in ("deleteById", "delete", "deleteAll"):
            if callee == "deleteById":
                id_field = w.id_field.get(entity, "id")
                n = w.delete(entity, [(id_field, args[0] if args else UNKNOWN)], mod)
            elif callee == "delete" and args and isinstance(args[0], Obj):
                id_field = w.id_field.get(entity, "id")
                n = w.delete(entity, [(id_field, args[0].get(id_field))], mod)
            else:
                n = 0
            return None, (n > 0) if n else UNKNOWN
        conds: list[tuple[str, Any]] | None
        kind = "find"
        if callee in ("findById", "getById", "getOne", "findOne"):
            conds = [(w.id_field.get(entity, "id"), args[0] if args else UNKNOWN)]
        elif callee == "findAll" and not args:
            conds = []
        elif callee in ("findAllById",):
            conds = [(w.id_field.get(entity, "id"), args[0] if args else UNKNOWN)]
        else:
            sql = next((a.get("args", "") for a in repo_node.get("annotations") or [] if a.get("name") == "Query"), None)
            conds = None
            if sql is not None:
                nq = native_query_conds(sql.encode().decode("unicode_escape") if "\\" in sql else sql)
                if nq is not None:
                    conds = [(f"#col:{c}", args[i] if i < len(args) else UNKNOWN) for c, i in nq]
            else:
                dp = derived_props(callee)
                if dp is not None:
                    kind, props = dp
                    conds = [(p, args[i] if i < len(args) else UNKNOWN) for i, p in enumerate(props)]
        if conds is None:
            objs, exact = w.select(entity, [], mod)
            exact = False
        else:
            objs, exact = w.select(entity, conds, mod)
        if kind.startswith("delete") or kind.startswith("remove"):
            n = w.delete(entity, conds or [], mod) if conds else 0
            return None, bool(n) if exact else UNKNOWN
        rows: Any = bool(objs) if exact else (UNKNOWN if objs else False if exact else UNKNOWN)
        if not objs and not exact:
            rows = UNKNOWN
        if kind == "exists":
            return (bool(objs) if exact else UNKNOWN), rows
        if kind == "count":
            return (len(objs) if exact else UNKNOWN), rows
        if many:
            return ListV(objs, exact=exact, elem_type=entity), rows
        if "Optional" in ret_t:
            return optional_of(objs, exact, entity), rows
        if exact:
            return (objs[0] if objs else None), rows
        # неточное условие: строка может быть любой из подходящих (или ни одной) — значения полей неизвестны
        if not objs:
            return None, rows
        obj = objs[0] if len(objs) == 1 else Obj(entity, {}, open=True)
        obj.maybe_null = True
        return obj, rows

    def _hydrate(self, fr: Frame, rc: Any, rows: Any) -> None:
        """Конструкторы сущности при загрузке строк Hibernate (R7) и equals из list.contains.

        Исполняются все конструкторы, которые допускает режим; в ответ их отбирает проекция (ADR-006).
        """
        mode = getattr(self.rules, "constructors", "caller_only")
        if mode == "off" or not rc.ctors:
            return
        allowed = self.index.entities.allowed_ctors(mode)
        ctors = [c for c in rc.ctors if allowed is None or c in allowed]
        if not ctors:
            return
        op = rc.operation
        via = f"data|{fr.method}|{rc.main_table or ''}"
        if op == "SAVE":
            if not rc.id_assigned:
                return
            rule = f"R7:save_merge({rc.id_assigned_reason})"
        elif op in ("READ", "DELETE"):
            if op == "READ" and rc.expects == "EMPTY":
                return
            if rows is False:
                for c in ctors:
                    self.sink.prune("executes", f"scenario:?", c, "STATE", "R7:read_no_rows(m4)")
                return
            rule = f"R7:{op.lower()}(m4 rows={'yes' if rows is True else 'unknown'})"
        else:
            return
        for c in ctors:
            self.sink.execute(c, ("STATE", rule), via)
            self.invoke(c, Obj(rc.entity.type if rc.entity else None, {}, open=True), [], fr.unit, ("STATE", rule))

    # --- лямбды ---------------------------------------------------------------

    def call_lambda(self, lam: Any, args: list[Any], fr: Frame) -> Any:
        if isinstance(lam, MethodRef):
            if lam.target and lam.target in self.N:
                self._record_call(fr, lam.target)
                recv = args[0] if args and isinstance(args[0], Obj) else None
                rest = args[1:] if recv is not None and not self.N[lam.target].get("params_as_written") is None else args
                return self.invoke(lam.target, recv, rest if recv is not None else args, fr.unit, fr.why)
            return UNKNOWN
        if not isinstance(lam, Lambda):
            return UNKNOWN
        env = dict(lam.env)
        for i, p in enumerate(lam.params):
            env[p] = args[i] if i < len(args) else UNKNOWN
        sub = Frame(lam.method, lam.this, env, fr.unit, fr.module, fr.owner, fr.why)
        comp = self.exec_block(lam.body, sub)
        if not comp.returns:
            return None
        ret = comp.returns[0]
        for r in comp.returns[1:]:
            ret = join(ret, r)
        return ret


# --- вспомогательное ---------------------------------------------------------

_MISSING = object()


def facts_lines(env: dict[str, Any], limit: int = 12) -> list[str]:
    """Известные значения переменных для судьи (только конкретные), по порядку появления в кадре."""
    out = []
    for k, v in env.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out.append(f"{k} = {v!r}")
        elif isinstance(v, (Obj, EnumV)):
            known = {f: x for f, x in v.fields.items() if isinstance(x, (str, int, float, bool)) or x is None}
            if known:
                out.append(f"{k} = {v!r} {known}")
        if len(out) >= limit:
            break
    return out


def _current(o: Any, f: str) -> Any:
    if f == "#list":
        return (list(o.items), o.exact)
    return o.fields.get(f, _MISSING)


def _restore(o: Any, f: str, old: Any) -> None:
    if f == "#list":
        o.items[:] = old[0]
        o.exact = old[1]
    elif old is _MISSING:
        o.fields.pop(f, None)
    else:
        o.fields[f] = old


def lit_value(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    t = text.strip()
    if t.startswith('"') and t.endswith('"'):
        return t[1:-1]
    if t in ("true", "false"):
        return t == "true"
    if t == "null":
        return None
    try:
        return int(t.rstrip("lL"))
    except ValueError:
        try:
            return float(t.rstrip("dDfF"))
        except ValueError:
            return UNKNOWN


_PRIM_DEFAULT = {"int": 0, "long": 0, "short": 0, "byte": 0, "double": 0.0, "float": 0.0, "boolean": False,
                 "char": "\x00"}


def default_value(f: dict[str, Any]) -> Any:
    if f.get("init_literal") is not None:
        return lit_value(f["init_literal"])
    return _PRIM_DEFAULT.get(f.get("type") or "", None)


def match_template(segs: list[str], tpl: list[str]) -> dict[str, Any] | None:
    """Сопоставление сегментов URL (с дырами \\x00) с шаблоном `@RequestMapping`."""
    if len(segs) != len(tpl):
        # дыра может покрывать несколько сегментов только в конце
        if not (segs and "\x00" in segs[-1] and len(segs) < len(tpl)):
            return None
    b: dict[str, Any] = {}
    for i, t in enumerate(tpl):
        s = segs[i] if i < len(segs) else "\x00"
        if t.startswith("{") and t.endswith("}"):
            b[t[1:-1]] = UNKNOWN if "\x00" in s else s
            continue
        if "\x00" in s:
            pat = "^" + ".*".join(re.escape(p) for p in s.split("\x00")) + "$"
            if not re.match(pat, t):
                return None
            continue
        if s != t:
            return None
    return b


def iter_items(v: Any) -> tuple[list[Any], bool]:
    if isinstance(v, ListV):
        return list(v.items), v.exact
    if isinstance(v, MapV):
        return list(v.data.keys()), v.exact
    return [], False


_FAIL_CTORS = ("Response",)


def is_failure_expr(e: Any) -> bool:
    if not isinstance(e, dict):
        return False
    if "new" in e and re.sub(r"<.*>", "", e["new"]).rsplit(".", 1)[-1] in _FAIL_CTORS:
        args = e.get("args") or []
        if args and isinstance(args[0], dict) and "lit" in args[0]:
            return args[0]["lit"] != 1
        return False
    if "call" in e and e.get("callee") in ("ok", "status", "body") and e.get("args"):
        return is_failure_expr(e["args"][-1])
    if "lit" in e and e.get("type") == "null":
        return True
    return False


def arm_fails(stmts: list[dict[str, Any]]) -> bool:
    """Плечо кончается отказом на всех путях: throw, return Response(статус != 1) или return null."""
    if not stmts:
        return False
    last = stmts[-1]
    op = last.get("op")
    if op == "throw":
        return True
    if op == "return":
        e = last.get("expr")
        if isinstance(e, dict) and "name" in e and "call" not in e:
            return any(_sets_failure_status(x, e["name"]) for x in stmts[:-1])
        return is_failure_expr(e)
    if op == "if":
        return bool(last.get("else")) and arm_fails(last.get("then") or []) and arm_fails(last.get("else") or [])
    if op in ("block", "try"):
        return arm_fails(last.get("body") or [])
    return False


def _sets_failure_status(stmt: dict[str, Any], var: str) -> bool:
    """`var.setStatus(0)` на верхнем уровне плеча: ответ-отказ, который вернут переменной."""
    e = stmt.get("expr") if stmt.get("op") == "expr" else None
    if not isinstance(e, dict) or e.get("callee") != "setStatus":
        return False
    recv = e.get("recv") or {}
    args = e.get("args") or []
    return (recv.get("name") == var and bool(args) and isinstance(args[0], dict) and "lit" in args[0]
            and args[0]["lit"] != 1 and args[0].get("type") == "int")


def iter_calls(x: Any):
    """Все call_site в операторах (для журнала отсева)."""
    if isinstance(x, dict):
        cs = x.get("call")
        if isinstance(cs, str) and cs.startswith("call:"):
            yield cs
        for k, v in x.items():
            if k != "call" and isinstance(v, (dict, list)):
                yield from iter_calls(v)
    elif isinstance(x, list):
        for v in x:
            yield from iter_calls(v)


__all__ = ["Interpreter", "Sink", "arm_fails", "match_template", "to_jstr", "MapV", "Bean"]
