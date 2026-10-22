#!/usr/bin/env python3
"""Цена каждой ошибки M1 в баллах: шаг прогона заменяется верным запросом, M4 и проекция исполняются заново.

    python scripts/m1_error_cost.py --run output/paraphrase --base output/base [--gold eval/paraphrase/gold.json]
                                    [--labels eval/m1_steps.json] [--show 20]

`--run` — папка прогона с ошибками (`step_requests.json`, `submission.json`), например перефразированных S0–S7
(`eval/paraphrase/`). `--base` — папка прогона с верными запросами тех же шагов: исходные S0–S7 из кеша
(`python run_eval.py --require-cache -o output/base/submission.json`, рекорд 1.0). Номера шагов у них общие —
перефразировка сохраняет структуру сценария.

Шаг считается отличным, если у него другой обработчик, параметры, ссылки, ожидаемый исход или источники полей тела
(`body_src`), чем у базы. Ошибка M1 по обработчику —
по разметке `--labels` (`handler`, у `disputed` ещё `alt`). Для каждого отличного шага: балл сценария, если заменить
только его запросом базы; цена = прирост. Последняя строка сценария — все отличные шаги заменены разом (должно быть
1.0: иначе отличие не в M1). LLM не нужна: запросы шагов готовые, M1 не вызывается.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.grounding.request import StepRequest  # noqa: E402
from engine.pipeline import ArchonityPipeline  # noqa: E402

KINDS = ("executes", "calls", "remote", "data")
# Поля запроса шага, которые решает M1 (http следует за обработчиком, grounding — диагностика)
FIELDS = ("handler", "params", "refs", "expected_outcome", "body_src")
TT = ROOT / "hackaton" / "tt-challenge"


def iou(p: set, g: set) -> float:
    if not p and not g:
        return 1.0
    return len(p & g) / len(p | g)


def gold_sets(block: dict[str, Any]) -> dict[str, set]:
    return {"executes": set(block.get("methods") or ()),
            **{k: {tuple(x) for x in block.get(k) or ()} for k in ("calls", "remote", "data")}}


def sub_sets(edges: list[dict[str, Any]]) -> dict[str, set]:
    out: dict[str, set] = {k: set() for k in KINDS}
    for e in edges:
        out[e["relation"]].add(e["target"] if e["relation"] == "executes" else (e["source"], e["target"]))
    return out


def score(got: dict[str, set], gold: dict[str, set]) -> float:
    return sum(iou(got[k], gold[k]) for k in KINDS) / len(KINDS)


class _Replay:
    """Сессия M1, которая отдаёт готовые запросы шагов вместо заземления."""

    def __init__(self, reqs: dict[int, dict[str, Any]]) -> None:
        self.reqs = reqs

    def ground(self, st: dict[str, Any]) -> StepRequest:
        return StepRequest(**self.reqs[st["n"]])


def replay(p: ArchonityPipeline, scenario: dict[str, Any], reqs: dict[int, dict[str, Any]]) -> dict[str, set]:
    p.m1.begin = lambda sc: _Replay(reqs)  # type: ignore[method-assign]
    methods, calls, remote, data = p.run_scenario(scenario)
    return {"executes": set(methods), "calls": set(calls), "remote": set(remote), "data": set(data)}


def short(h: str | None) -> str:
    return (h or "-").split(":", 2)[-1].split("(")[0].rsplit(".", 1)[-1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True, help="папка прогона с ошибками")
    ap.add_argument("--base", type=Path, required=True, help="папка прогона с верными запросами тех же шагов")
    ap.add_argument("--gold", type=Path, default=ROOT / "eval" / "paraphrase" / "gold.json")
    ap.add_argument("--labels", type=Path, default=ROOT / "eval" / "m1_steps.json")
    ap.add_argument("--scenarios", type=Path, default=ROOT / "eval" / "paraphrase" / "scenarios",
                    help="папка сценариев прогона --run (тексты шагов для run_scenario)")
    ap.add_argument("-o", "--out", type=Path, help="JSON с ценой каждого шага")
    args = ap.parse_args()

    run = json.loads((args.run / "step_requests.json").read_text(encoding="utf-8"))
    base = json.loads((args.base / "step_requests.json").read_text(encoding="utf-8"))
    sub = json.loads((args.run / "submission.json").read_text(encoding="utf-8"))["scenarios"]
    gold = json.loads(args.gold.read_text(encoding="utf-8"))["scenarios"]
    labels = json.loads(args.labels.read_text(encoding="utf-8"))["scenarios"]

    p = ArchonityPipeline(skeleton_path=TT / "skeleton" / "trainticket.json.gz",
                          targets_root=TT / "targets" / "trainticket", m1_options={"llm": None})
    rows: list[dict[str, Any]] = []
    total_now = total_fixed = 0.0
    for sid in sorted(gold):
        if sid not in run or sid not in base:
            continue
        sc = json.loads((args.scenarios / f"{sid}.json").read_text(encoding="utf-8"))
        g = gold_sets(gold[sid])
        mine = {r["step"]: r for r in run[sid]}
        good = {r["step"]: r for r in base[sid]}
        lab = {s["n"]: s for s in labels.get(sid, [])}
        now = score(sub_sets(sub[sid]["edges"]), g)
        same = replay(p, sc, mine)
        if abs(score(same, g) - now) > 1e-9:
            print(f"!! {sid}: повтор запросов прогона даёт {score(same, g):.5f}, а submission.json — {now:.5f}; "
                  f"цены ниже неточны", file=sys.stderr)
        diff = [n for n in sorted(mine) if n in good and any(mine[n].get(k) != good[n].get(k)
                                                             for k in FIELDS)]
        for n in diff:
            fixed = score(replay(p, sc, {**mine, n: good[n]}), g)
            lb = lab.get(n, {})
            ok_h = {lb.get("handler"), *(lb.get("alt") or [] if lb.get("status") == "disputed" else [])}
            what = [k for k in FIELDS if mine[n].get(k) != good[n].get(k)]
            rows.append({"scenario": sid, "step": n, "cost": fixed - now, "what": what,
                         "m1_handler_ok": mine[n]["handler"] in ok_h, "action": mine[n]["action"],
                         "got": mine[n]["handler"], "want": good[n]["handler"],
                         **{f"got_{k}": mine[n].get(k) for k in FIELDS if k != "handler"},
                         **{f"want_{k}": good[n].get(k) for k in FIELDS if k != "handler"}})
        all_fixed = score(replay(p, sc, {**mine, **{n: good[n] for n in diff}}), g) if diff else now
        total_now += now
        total_fixed += all_fixed
        print(f"{sid}: балл {now:.5f}; шагов отлично от базы {len(diff)}; все заменены — {all_fixed:.5f}")

    n_sc = len([s for s in gold if s in run and s in base]) or 1
    print(f"итог: {total_now / n_sc:.5f}; все отличные шаги заменены — {total_fixed / n_sc:.5f}\n")
    print("Цена шага (прирост балла сценария, если исправить только его), по убыванию:")
    for r in sorted(rows, key=lambda r: -r["cost"]):
        tag = "обработчик" if "handler" in r["what"] else "+".join(r["what"])
        print(f"  {r['scenario']}.{r['step']:<3} +{r['cost']:.4f}  {tag:<14} {short(r['got'])} -> {short(r['want'])}"
              f"  | {r['action'][:70]}")
        if "handler" not in r["what"]:
            for k in r["what"]:
                print(f"        {k}: {json.dumps(r['got_' + k], ensure_ascii=False)} -> "
                      f"{json.dumps(r['want_' + k], ensure_ascii=False)}")
    if args.out:
        args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
