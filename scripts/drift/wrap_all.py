"""Замер: три механизма вместе (Jackson-конструктор, Lombok-toString при логировании, шаг 4 без запроса)."""
import os, sys, runpy
sys.path.insert(0, os.getcwd())
HERE = os.path.dirname(os.path.abspath(__file__))
src = lambda f: open(os.path.join(HERE, f), encoding="utf-8").read().split("sys.argv = [")[0]
exec(src("wrap_jackson_ctor.py"), {"__name__": "jk"})
exec(src("wrap_lombok_tostring.py"), {"__name__": "lb"})
from engine.executor import step as sm2
_orig_run_step = sm2.StepExecutor.run_step
def run_step(self, step_req, state, ledger=None, scenario=None):
    if os.environ.get("DROP_STEP4", "1") == "1" and "StationFoodController#getFoodStoresOfStation" in step_req.handler:
        return set(), set(), set(), set()
    return _orig_run_step(self, step_req, state, ledger, scenario)
sm2.StepExecutor.run_step = run_step
sys.argv = ["run_eval.py"] + sys.argv[1:]
runpy.run_path("run_eval.py", run_name="__main__")
