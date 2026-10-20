"""Контрфакт ADR-007, фаза A: ссылки M1 v7 переписываются на виды манифеста, M4 — в режиме --ref-kinds v8.

Запуск из корня worktree: python scripts/drift/wrap_ref_kinds_v8.py <аргументы run_eval.py>
Затем: python scripts/compare_submissions.py eval/records/submission_p27_1.00000.json <submission.json>

Перевод по таблице решения 2 ADR-007: contact -> contacts, price -> priceConfig, consign -> consignRecord,
store -> stationFoodStore; train — тип поезда в S6 (trainType), рейс из поиска в S4.6 и S7.10 (trip), как M1 v8
назовёт их по смыслу шага. TRAIN_COLLISION=keep (по умолчанию) | override — если `trip` в шаге уже есть (S4.6).
Перевод v7 в коде (StepExecutor._v7_refs) обёртка не использует: ссылки уходят в M4 уже видами v8.
"""
import copy
import os
import runpy
import sys

sys.path.insert(0, os.getcwd())
from engine.executor import step as sm  # noqa: E402

V7_TO_V8 = {"contact": "contacts", "price": "priceConfig", "consign": "consignRecord", "store": "stationFoodStore"}
COLLISION = os.environ.get("TRAIN_COLLISION", "keep")
LOG = []

orig = sm.StepExecutor.run_step


def run_step(self, step_req, state, ledger=None, scenario=None):
    refs = dict(getattr(step_req, "refs", None) or {})
    if refs:
        train = refs.pop("train", None)
        new = {V7_TO_V8.get(k, k): v for k, v in refs.items()}
        if train is not None:
            k = "trainType" if self.sid == "S6" else "trip"
            if k in new and COLLISION == "keep":
                LOG.append(f"{self.sid}.{step_req.step}: train={train} не перенесён, {k}={new[k]} остался")
            else:
                new[k] = train
        if new != step_req.refs:
            LOG.append(f"{self.sid}.{step_req.step}: {step_req.refs} -> {new}")
        step_req = copy.copy(step_req)
        step_req.refs = new
    return orig(self, step_req, state, ledger, scenario)


sm.StepExecutor.run_step = run_step
sys.argv = ["run_eval.py"] + sys.argv[1:] + ["--ref-kinds", "v8"]
try:
    runpy.run_path("run_eval.py", run_name="__main__")
finally:
    print("\n".join(LOG), file=sys.stderr)
