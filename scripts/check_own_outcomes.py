#!/usr/bin/env python3
"""Исход каждого шага у M4 против ручной разметки своих сценариев (`eval/own/steps.json`, поле `outcome`).

    python scripts/check_own_outcomes.py -o <папка> [--steps eval/own/steps.json] [--show all|diff] [-- <ключи run_eval>]

Прогон — сам `run_eval.py` с теми же ключами (по умолчанию сценарии `eval/own/scenarios/*.json`, `--no-eval`),
поэтому исходы сняты с выдачи кода, а не с отдельной сборки конвейера. Исход M4 — ответ обработчика шага
(`StepExecutor.results`): обёртка проекта (`envelope.py`) со статусом успеха — `success`, с другим известным
статусом — `failure`, статус неизвестен — `unknown`, `null` — `null`; ответ не обёртка — `value`.

Сверка: `success` в разметке ждёт `success` или `value`, `refused` и `other` — `failure` или `null`. Шаг, где M1 выбрал
не тот обработчик (не `handler` и не `alt` у `disputed`), считается отдельно: его исход — ошибка M1, а не M4.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.executor.step import StepExecutor, _payload  # noqa: E402
from engine.executor.values import UNKNOWN, Obj, Wrapper  # noqa: E402

AGREE = {"success": {"success", "value"}, "refused": {"failure", "null"}, "other": {"failure", "null"}}


def m4_outcome(ret: Any, env: Any) -> tuple[str, str]:
    """(исход, деталь): статус и первая строка обёртки, тип значения."""
    v = ret
    for _ in range(3):
        if isinstance(v, Wrapper):
            v = v.body
    if v is None:
        return "null", ""
    if v is UNKNOWN:
        return "unknown", "ret UNKNOWN"
    if env is not None and isinstance(v, Obj) and env.is_type(v.type):
        st = v.fields.get(env.status)
        msg = next((x for x in v.fields.values() if isinstance(x, str)), "")
        if isinstance(st, int) and not isinstance(st, bool):
            return ("success" if st == env.success else "failure"), f"status={st} {msg!r}"[:90]
        return "unknown", f"status={st!r} {msg!r}"[:90]
    p = _payload(ret, env)
    return "value", type(p).__name__ if not isinstance(p, Obj) else (p.type or "Obj").rsplit(".", 1)[-1]


def short(h: str | None) -> str:
    return (h or "-").split(":", 2)[-1].split("(")[0].rsplit(".", 1)[-1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", type=Path, required=True, help="папка прогона: выдача, журналы, outcomes.json")
    ap.add_argument("--steps", type=Path, default=ROOT / "eval" / "own" / "steps.json")
    ap.add_argument("--show", choices=("all", "diff"), default="diff", help="какие шаги печатать")
    args, rest = ap.parse_known_args()
    rest = [a for a in rest if a != "--"]

    captured: dict[tuple[str, int], dict[str, Any]] = {}
    orig = StepExecutor.run_step

    def run_step(self: StepExecutor, step_req: Any, state: Any, ledger: Any = None):
        n = getattr(step_req, "step", None)
        start = len(self.unknowns.get(self.sid, []))
        out = orig(self, step_req, state, ledger)
        outcome, detail = m4_outcome(self.results.get(n), self.it.envelope)
        retry = [u["decided"] for u in self.unknowns.get(self.sid, [])[start:]
                 if u.get("branch") == "step" and str(u.get("decided", "")).startswith("success_retry")]
        captured[(self.sid, n)] = {"handler": step_req.handler, "expected": getattr(step_req, "expected_outcome", None),
                                   "m4": outcome, "detail": detail, "retry": retry, "methods": len(out[0]),
                                   "remote": len(out[2]), "data": len(out[3])}
        return out

    StepExecutor.run_step = run_step  # type: ignore[method-assign]
    args.out.mkdir(parents=True, exist_ok=True)
    if not any(a.startswith("--scenarios") for a in rest):
        rest += ["--scenarios", str(ROOT / "eval" / "own" / "scenarios" / "*.json")]
    if "--no-eval" not in rest:
        rest.append("--no-eval")
    sys.argv = ["run_eval.py", "-o", str(args.out / "submission.json"), *rest]
    import run_eval  # noqa: E402 — после подмены run_step

    try:
        run_eval.main()
    except SystemExit as e:  # run_eval завершает прогон через sys.exit(code)
        if e.code:
            raise

    gold = json.loads(args.steps.read_text(encoding="utf-8"))["scenarios"]
    rows, tally = [], collections.Counter()
    for sid, steps in gold.items():
        for g in steps:
            got = captured.get((sid, g["n"]))
            ok_handlers = {g["handler"], *(g.get("alt") or [])} if g.get("status") == "disputed" else {g["handler"]}
            if got is None:
                verdict = "нет шага"
            elif got["handler"] not in ok_handlers:
                verdict = "M1"
            elif got["m4"] in AGREE.get(g.get("outcome", "success"), set()):
                verdict = "ok"
            elif got["m4"] == "unknown":
                verdict = "M4?"
            else:
                verdict = "M4"
            tally[verdict] += 1
            rows.append({"scenario": sid, "n": g["n"], "action": g["action"], "gold_handler": g["handler"],
                         "gold_outcome": g.get("outcome"), "branch": g.get("branch"), "verdict": verdict, **(got or {})})

    (args.out / "outcomes.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n== исходы M4 против eval/own/steps.json")
    for r in rows:
        if args.show == "diff" and r["verdict"] == "ok":
            continue
        print(f"{r['scenario']}.{r['n']:<3} {r['verdict']:<4} разметка={r['gold_outcome']:<8} M4={r.get('m4', '-'):<8} "
              f"M1ждёт={r.get('expected') or '-':<8} {short(r.get('handler'))}  {r.get('detail', '')}"
              f"{'  ' + ','.join(r['retry']) if r.get('retry') else ''}")
        if r["verdict"] != "ok":
            print(f"      {r['action']}")
            if r["verdict"] == "M1":
                print(f"      верный: {short(r['gold_handler'])}")
    print("итог:", dict(tally), f"шагов {len(rows)};", f"подробно — {args.out / 'outcomes.json'}")


if __name__ == "__main__":
    main()
