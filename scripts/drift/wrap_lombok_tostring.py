"""Прототип: Lombok-toString вызывает рукописные геттеры, когда объект форматируется (R5).

Запуск из корня worktree: python wrap_lombok_tostring.py <аргументы run_eval.py>
LOMBOK_LOG=1      — аргументы SLF4J info/warn/error при шаблоне с {} (уровень по умолчанию Spring Boot — INFO)
LOMBOK_EXPLICIT=1 — явный x.toString() у объекта с Lombok-toString
LOMBOK_NEST=0     — не обходить вложенные объекты
"""
import os
import re
import runpy
import sys
from collections import defaultdict

sys.path.insert(0, os.getcwd())
from engine.executor import interpreter as im  # noqa: E402
from engine.executor.values import UNKNOWN, ListV, MapV, Obj  # noqa: E402

LOG_ON = os.environ.get("LOMBOK_LOG", "1") == "1"
EXPLICIT = os.environ.get("LOMBOK_EXPLICIT", "0") == "1"
NEST = os.environ.get("LOMBOK_NEST", "1") == "1"
LOMBOK = {"Data", "ToString", "Value"}
LOGGER_NAME = re.compile(r"(?i)^(log|logger)$")
WHY = ("FRAMEWORK_RULE", "R5:lombok_tostring")
HITS = defaultdict(set)
_fields = None


def own_fields(it, tid):
    global _fields
    if _fields is None:
        _fields = defaultdict(list)
        for nid, n in it.N.items():
            if n.get("kind") == "field" and "static" not in (n.get("modifiers") or []):
                _fields[n["owner"]].append(n)
    return _fields.get(tid, [])


def own_method(it, tid, name):
    return next((m for m in it.types.methods.get(tid, ())
                 if it.N[m].get("name") == name and not (it.N[m].get("params_as_written") or [])), None)


def lombok_tostring(it, v, fr, seen, depth=0):
    if depth > 4:
        return
    if isinstance(v, ListV):
        for x in v.items:
            lombok_tostring(it, x, fr, seen, depth + 1)
        return
    if isinstance(v, MapV):
        for x in list(v.data.values()):
            lombok_tostring(it, x, fr, seen, depth + 1)
        return
    if not isinstance(v, Obj) or not v.type or id(v) in seen:
        return
    seen.add(id(v))
    tid = it.types.resolve(v.type, fr.module)
    if not tid:
        return
    hand = own_method(it, tid, "toString")
    if hand:
        if hand in it.ir:
            HITS[fr.method].add(hand)
            it.sink.execute(hand, WHY, f"tostring|{fr.method}|{hand}")
            it.invoke(hand, v, [], it.index.unit_of(hand), WHY)
        return
    anns = {a.get("name") for a in it.N.get(tid, {}).get("annotations") or []}
    if not anns & LOMBOK:
        return
    for f in own_fields(it, tid):
        name = f["name"]
        cap = name[:1].upper() + name[1:]
        getter = None
        for g in (("is" + cap, "get" + cap) if f.get("type") == "boolean" else ("get" + cap,)):
            getter = own_method(it, tid, g)
            if getter:
                break
        val = v.fields.get(name, UNKNOWN)
        if getter and getter in it.ir:
            HITS[fr.method].add(getter)
            it.sink.execute(getter, WHY, f"tostring|{fr.method}|{getter}")
            r = it.invoke(getter, v, [], it.index.unit_of(getter), WHY)
            if r is not UNKNOWN:
                val = r
        if NEST:
            lombok_tostring(it, val, fr, seen, depth + 1)


orig = im.Interpreter.eval_call


def eval_call(self, e, fr):
    ret = orig(self, e, fr)
    callee = e.get("callee", "")
    recv_e = e.get("recv") or {}
    args = e.get("args") or []
    if LOG_ON and callee in ("info", "warn", "error") and args and LOGGER_NAME.match(
            recv_e.get("name") or recv_e.get("field") or "") and "{}" in str(args[0].get("lit") or ""):
        for a in args[1:]:
            if "name" in a or "field" in a:  # простые ссылки — без повторных побочных эффектов
                lombok_tostring(self, self.eval(a, fr), fr, set())
    if EXPLICIT and callee == "toString" and not args and recv_e and ("name" in recv_e or "field" in recv_e):
        lombok_tostring(self, self.eval(recv_e, fr), fr, set())
    return ret


im.Interpreter.eval_call = eval_call
sys.argv = ["run_eval.py"] + sys.argv[1:]
try:
    runpy.run_path("run_eval.py", run_name="__main__")
finally:
    print("LOMBOK TOSTRING:", file=sys.stderr)
    for caller, ms in sorted(HITS.items()):
        print("  ", caller.split(":")[-1][:80], "->", sorted(m.split(":")[-1] for m in ms), file=sys.stderr)
