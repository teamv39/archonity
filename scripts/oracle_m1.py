#!/usr/bin/env python3
"""Оракул M1: запросы шагов строятся из ручной разметки (`eval/own/steps.json`), M4 и проекция исполняются как в конвейере.

    python scripts/oracle_m1.py X9 X10 X11 X12 [-o output/oracle]
    python scripts/m1_error_cost.py --run <прогон с M1> --base output/oracle --gold output/oracle/gold.json \\
        --labels eval/own/steps.json --scenarios eval/own/scenarios

Зачем. У своих сценариев нет эталона рёбер, поэтому ошибку M1 от ошибки M4 по выдаче не отличить. Здесь обработчик, исход и
параметры шага берутся из разметки, а рёбра, которые выдаёт M4 при верных запросах, пишутся как «эталон» для
`m1_error_cost.py`: цена каждого отклонения M1 в баллах сценария. Заодно печатается исход каждого шага против разметки
(как `check_own_outcomes.py`, но без M1): расхождение здесь — вопрос к M4.

Что в запросе не из разметки (рукописные правила под Train Ticket, для другого проекта правила свои):
- ссылки на пользователя и результаты поиска, контактов и еды — по порядку шагов: вход → `user`, поиск → `trip`, контакты →
  `contacts`, станционная еда → `stationFoodStore`; ссылки на заказ и другие виды — только из поля `refs` разметки;
- параметры поиска и брони (маршрут и дата) — таблица `ROUTES` ниже, вес багажа 0, если разметка его не задаёт.

Оракул не эталон организаторов: рёбра M4 верны настолько, насколько верен сам M4. Отклонение M1 с ценой 0 — его запрос
отличается от оракула, но рёбра те же.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_own_outcomes as C  # noqa: E402
from engine.executor.step import StepExecutor  # noqa: E402
from engine.grounding.prompts import request_fields  # noqa: E402
from engine.grounding.request import StepRequest  # noqa: E402
from engine.pipeline import ArchonityPipeline  # noqa: E402

TT = ROOT / "hackaton" / "tt-challenge"
DATE = "2026-10-01"
# маршрут поиска и брони по сценарию; остальные — Shanghai -> Suzhou
ROUTES = {"X10": ("Shanghai", "Nanjing")}
DEFAULT_ROUTE = ("Shanghai", "Suzhou")
# поля тела заказа, который администратор добавляет по тексту шага X12 (пассажир и контакт названы в тексте)
ADMIN_ORDER = {"contactsName": "Contacts_One", "trainNumber": "D1345", "from": "shanghai", "to": "suzhou",
               "travelDate": DATE, "price": "50"}


def short(h: str) -> str:
    return h.split("#")[0].split(".")[-1] + "#" + h.split("#")[1].split("(")[0]


class _Replay:
    """Сессия M1, которая отдаёт готовые запросы шагов вместо заземления."""

    def __init__(self, reqs: dict[int, StepRequest]) -> None:
        self.reqs = reqs

    def ground(self, st: dict[str, Any]) -> StepRequest:
        return self.reqs[st["n"]]


def build_requests(g: Any, sid: str, labels: list[dict[str, Any]]) -> dict[int, StepRequest]:
    """Запросы шагов сценария по разметке; `g` — `StepGrounder` (каталог обработчиков и UI)."""
    reqs: dict[int, StepRequest] = {}
    login = search = details = contacts = food = None
    src, dst = ROUTES.get(sid, DEFAULT_ROUTE)
    for lb in labels:
        n, h = lb["n"], lb["handler"]
        name = short(h)
        info = g.cat.handlers[h]
        ui = g._ui_for(info)
        ui_req = ui[0][0] if ui else None
        verb, path = info.routes[0]
        if verb == "ANY" and ui_req is not None:
            verb = ui_req.verb
        fields = {f for f, _, _ in request_fields(info)}
        params = {k: v for k, v in (ui_req.body_consts.items() if ui_req else ()) if k in fields}
        refs = dict(lb.get("refs") or {})
        if name.endswith("#getToken"):
            login = n
        elif name.endswith("queryInfo"):
            search = n
            params.update({"startPlace": src, "endPlace": dst, "departureTime": DATE})
        elif name.endswith("getTripAllDetailInfo"):
            details = n
            refs.setdefault("trip", f"first_of_step_{search}")
        elif name.endswith("findContactsByAccountId"):
            contacts = n
            refs.setdefault("user", f"new_of_step_{login}")
        elif "StationFood" in name:
            food = n
        elif name.endswith("#preserve"):
            params.update({"date": DATE, "from": src, "to": dst, "foodPrice": 0.0, "isWithin": False,
                           "consigneeWeight": 0.0, **({"stationName": "Suzhou"} if "Other" in name else {})})
            refs.setdefault("user", f"new_of_step_{login}")
            refs.setdefault("contacts", f"first_of_step_{contacts}")
            refs.setdefault("trip", f"first_of_step_{details or search}")
            if "Other" in name and food:
                refs.setdefault("stationFoodStore", f"first_of_step_{food}")
        elif name.endswith("queryOrdersForRefresh"):
            refs.setdefault("user", f"new_of_step_{login}")
        elif name.endswith("#addOrder"):
            params.update(ADMIN_ORDER)
        params.update(lb.get("params") or {})
        outcome = lb.get("outcome") if lb.get("outcome") in ("success", "refused") else "success"
        reqs[n] = StepRequest(
            scenario=sid, step=n, action=lb["action"], handler=h, http={"method": verb, "path": path}, params=params,
            expected_outcome=outcome, refs=refs,
            ui_source={"file": ui_req.file, "line": ui_req.line} if ui_req else None,
            body_src=dict(ui_req.body_src) if ui_req else {},
            body_groups=ui_req.body_groups() if ui_req else [])
    return reqs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenarios", nargs="+", help="ID сценариев разметки, например X9 X10")
    ap.add_argument("--steps", type=Path, default=ROOT / "eval" / "own" / "steps.json")
    ap.add_argument("--scenario-dir", type=Path, default=ROOT / "eval" / "own" / "scenarios")
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "output" / "oracle")
    args = ap.parse_args()

    labels_all = json.loads(args.steps.read_text(encoding="utf-8"))["scenarios"]
    captured: dict[tuple[str, int], dict[str, Any]] = {}
    orig = StepExecutor.run_step

    def run_step(self: StepExecutor, step_req: Any, state: Any, ledger: Any = None):
        n = getattr(step_req, "step", None)
        out = orig(self, step_req, state, ledger)
        outcome, detail = C.m4_outcome(self.results.get(n), self.it.envelope)
        captured[(self.sid, n)] = {"m4": outcome, "detail": detail, "methods": len(out[0]), "remote": len(out[2]),
                                   "data": len(out[3])}
        return out

    StepExecutor.run_step = run_step  # type: ignore[method-assign]
    p = ArchonityPipeline(skeleton_path=TT / "skeleton" / "trainticket.json.gz",
                          targets_root=TT / "targets" / "trainticket", m1_options={"llm": None})
    dump_reqs: dict[str, Any] = {}
    dump_gold: dict[str, Any] = {}
    tally: collections.Counter[str] = collections.Counter()
    for sid in args.scenarios:
        sc = json.loads((args.scenario_dir / f"{sid}.json").read_text(encoding="utf-8"))
        labels = labels_all[sid]
        reqs = build_requests(p.m1, sid, labels)
        p.m1.begin = lambda _sc, reqs=reqs: _Replay(reqs)  # type: ignore[method-assign]
        methods, calls, remote, data = p.run_scenario(sc)
        dump_reqs[sid] = [asdict(reqs[n]) for n in sorted(reqs)]
        dump_gold[sid] = {"methods": sorted(methods), "calls": sorted(map(list, calls)),
                          "remote": sorted(map(list, remote)), "data": sorted(map(list, data))}
        print(f"\n== {sid}: executes {len(methods)}, calls {len(calls)}, remote {len(remote)}, data {len(data)}")
        for lb in labels:
            got = captured.get((sid, lb["n"])) or {}
            ok = got.get("m4") in C.AGREE.get(lb.get("outcome", "success"), set())
            tally["ok" if ok else "расхождение"] += 1
            print(f"  {sid}.{lb['n']:<3} {'ok  ' if ok else 'DIFF'} разметка={lb.get('outcome', '-'):<8} "
                  f"M4={got.get('m4', '-'):<8} +{got.get('methods', 0)}м/{got.get('remote', 0)}р/{got.get('data', 0)}д "
                  f"{short(lb['handler'])}  {got.get('detail', '')}")
    print(dict(tally))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "step_requests.json").write_text(json.dumps(dump_reqs, ensure_ascii=False, indent=1), encoding="utf-8")
    (args.out / "gold.json").write_text(json.dumps({"scenarios": dump_gold}, ensure_ascii=False, indent=1),
                                        encoding="utf-8")


if __name__ == "__main__":
    main()
