"""Прототип: Jackson исполняет конструктор без аргументов у тела запроса (@RequestBody), R7/ADR-006.

Запуск из корня worktree: python wrap_jackson_ctor.py <аргументы run_eval.py>
JACKSON_NESTED=1 — то же для вложенных DTO (поля проектного типа, которые пришли в теле).
"""
import os
import runpy
import sys

sys.path.insert(0, os.getcwd())
from engine.executor import step as sm  # noqa: E402
from engine.executor.values import Obj, UNKNOWN  # noqa: E402

NESTED = os.environ.get("JACKSON_NESTED") == "1"
LOG = []


def run_ctor(self, ftype, module, handler, seen):
    it = self.it
    tid = it.types.resolve(ftype, module)
    if not tid or tid in seen:
        return
    seen.add(tid)
    ctor = next((m for m in it.types.methods.get(tid, ())
                 if it.N[m].get("name") == "<init>" and not (it.N[m].get("params_as_written") or [])), None)
    if ctor and ctor in it.ir:
        LOG.append((handler, ctor))
        it._pending_jackson.append((ctor, ftype, handler))
    if NESTED:
        for f in it.types.all_fields(tid):
            if it.types.resolve(f.get("type"), module):
                run_ctor(self, f.get("type"), module, handler, seen)


orig = sm.StepExecutor.build_dto


def build_dto(self, ftype, params, ents, user, handler):
    if not hasattr(self.it, "_pending_jackson"):
        self.it._pending_jackson = []
    module = self.index.N.get(handler, {}).get("module")
    run_ctor(self, ftype, module, handler, set())
    return orig(self, ftype, params, ents, user, handler)


sm.StepExecutor.build_dto = build_dto

from engine.executor import interpreter as im  # noqa: E402


def run_handler(self, handler, args, expected, step):
    self.sink = im.Sink()
    self.expected = expected or "success"
    self.step = step
    self.invocations = 0
    self.depth = 0
    self.stack = []
    self.sink.execute(handler, ("SKELETON", "ENTRY"), None)
    # Jackson: тело запроса создаётся до вызова обработчика, конструктор без аргументов исполняется (R7)
    for ctor, ftype, h in getattr(self, "_pending_jackson", []):
        why = ("FRAMEWORK_RULE", "R7:jackson_ctor")
        self.sink.execute(ctor, why, f"jackson|{h}|{ctor}")
        self.invoke(ctor, Obj(ftype, {}, open=True), [], self.index.unit_of(ctor), why)
    self._pending_jackson = []
    unit = self.index.unit_of(handler)
    try:
        ret = self.invoke(handler, None, args, unit, ("SKELETON", "ENTRY"))
    except im._Abort:
        ret = UNKNOWN
    return self.sink, ret


im.Interpreter.run_handler = run_handler
sys.argv = ["run_eval.py"] + sys.argv[1:]
try:
    runpy.run_path("run_eval.py", run_name="__main__")
finally:
    print("JACKSON CTORS:", file=sys.stderr)
    for h, c in sorted(set(LOG)):
        print("  ", h.split(":")[-1][:70], "->", c.split(":")[-1], file=sys.stderr)
