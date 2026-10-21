"""Оракулы для переноса engine на Rust (ADR-008, rust_port_split.md, «Оракулы»).

Выдачу Python не меняет: прогон идёт обычным `ArchonityPipeline.run_all` с кешем, оракул только записывает то, что
в нём происходит (обёртки вокруг `rebind` и `run_step`).

    python scripts/rust_oracles.py steps  <папка>  [сценарии...]   # шаги до R20 и сырые рёбра с журналом по шагам
    python scripts/rust_oracles.py slices <папка>                  # срезы загрузчиков: скелет, дамп БД, entity_ir
    python scripts/rust_oracles.py sweep  <папка>                  # по каждому обработчику каталога как по сценарию из одного шага
    ARCHONITY_TRACE=<папка>/trace.tsv python scripts/rust_oracles.py steps <папка>   # плюс трасса вызовов

Файлы в `<папка>`:
- `step_requests_raw.json` — `StepRequest` шага до R20 (`StepGrounder.rebind`): вход Rust;
- `raw_steps.json` — по сценарию: пассажир, по шагу: запрос после R20, рёбра `StepExecutor.run_step` и записи журнала
  решений этого шага (до правила Spring Security и проекции M5);
- `trace.tsv` — при `ARCHONITY_TRACE`: строки `глубина<TAB>ID метода` и отметки `# scenario S0`, `# step 3`;
- `sweep_steps.json` — формат `raw_steps.json`: сценарий `H<k>` на каждый обработчик каталога M1 (шаг без параметров);
  сверка Rust-исполнителя на обработчиках, которых нет в S1–S7 (`replay_steps`, `scripts/rust_compare.py`);
- `slices.json` — индекс скелета, таблицы дампа, факты сущностей (сортированно, для сравнения с Rust).

По умолчанию сценарии — S0–S7 пакета организаторов. Модели и сервер не нужны: LLM и эмбеддинги из `cache/`.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TT = ROOT / "hackaton" / "tt-challenge"


def _dump(obj: Any, path: Path, sort_keys: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=sort_keys, default=lambda o: sorted(o))
        f.write("\n")


def _build():
    from engine.grounding.llm import LLMClient
    from engine.pipeline import ArchonityPipeline

    return ArchonityPipeline(
        skeleton_path=TT / "skeleton" / "trainticket.json.gz",
        targets_root=TT / "targets" / "trainticket",
        m1_options={"embedder": "qwen3-4b", "llm": LLMClient(use_server=False)},
    )


def steps(out: Path, scenarios: list[Path]) -> None:
    from engine.executor import interpreter

    p = _build()
    raw_requests: dict[str, dict[int, dict[str, Any]]] = {}
    raw_steps: dict[str, dict[str, Any]] = {}
    seen_scenarios: set[str] = set()

    rebind, run_step = p.m1.rebind, p.m4.run_step

    def rebind_hook(req):
        raw_requests.setdefault(req.scenario, {})[req.step] = req.to_dict()
        return rebind(req)

    def run_step_hook(req, state, ledger=None):
        sid = ledger.scenario_id
        if sid not in seen_scenarios:
            seen_scenarios.add(sid)
            interpreter.trace(f"# scenario {sid}")
            raw_steps[sid] = {"passenger": dataclasses.asdict(state), "steps": []}
        interpreter.trace(f"# step {req.step}")
        m, c, r, d = run_step(req, state, ledger=ledger)
        journal = {key: [x.to_dict() for x in decisions if x.step == req.step]
                   for key, decisions in sorted(ledger._scenarios[sid].items())}
        raw_steps[sid]["steps"].append({
            "step": req.step,
            "request": req.to_dict(),
            "methods": sorted(m),
            "calls": sorted(map(list, c)),
            "remote": sorted(map(list, r)),
            "data": sorted(map(list, d)),
            "journal": {k: v for k, v in journal.items() if v},
        })
        return m, c, r, d

    p.m1.rebind = rebind_hook
    p.m4.run_step = run_step_hook
    paths = scenarios or sorted((TT / "scenarios").glob("S*.json"))
    p.run_all(paths, out / "submission.json")
    if p.failures:
        raise SystemExit(f"сбои в прогоне: {p.failures}")

    ordered = {sid: [raw_requests[sid][n] for n in sorted(raw_requests[sid])] for sid in sorted(raw_requests)}
    _dump(ordered, out / "step_requests_raw.json")
    _dump({sid: raw_steps[sid] for sid in sorted(raw_steps)}, out / "raw_steps.json")
    n = sum(len(v["steps"]) for v in raw_steps.values())
    print(f"шагов {n} в {len(raw_steps)} сценариях: {out}")


def sweep(out: Path) -> None:
    """M4 по каждому обработчику каталога как по одношаговому сценарию без параметров (как `handler_sweep.py`)."""
    from engine.grounding.request import StepRequest
    from engine.pipeline import resolve_passenger_context

    p = _build()
    result: dict[str, Any] = {}
    failed = 0
    for k, (nid, h) in enumerate(p.m1.cat.handlers.items()):
        sid = f"H{k}"
        verb = h.routes[0][0] if h.routes else "GET"
        req = StepRequest(scenario=sid, step=1, action="", handler=nid,
                          http={"method": verb, "path": h.routes[0][1] if h.routes else ""})
        ctx = resolve_passenger_context(p.index, scenario_id=sid)
        p.ledger.begin_scenario(sid)
        p.ledger.begin_step(1)
        p.m4.begin_scenario(sid)
        try:
            m, c, r, d = p.m4.run_step(req, ctx, ledger=p.ledger)
        except Exception:  # noqa: BLE001 — сбой Python: сверять нечего
            failed += 1
            continue
        journal = {key: [x.to_dict() for x in decisions if x.step == 1]
                   for key, decisions in sorted(p.ledger._scenarios[sid].items())}
        result[sid] = {"passenger": dataclasses.asdict(ctx), "steps": [{
            "step": 1, "request": req.to_dict(), "methods": sorted(m), "calls": sorted(map(list, c)),
            "remote": sorted(map(list, r)), "data": sorted(map(list, d)),
            "journal": {k2: v for k2, v in journal.items() if v},
        }]}
    _dump(result, out / "sweep_steps.json")
    print(f"обработчиков {len(result)}, сбоев Python {failed}: {out / 'sweep_steps.json'}")


def _sorted_sets(d: dict[str, Any]) -> dict[str, list]:
    return {k: sorted(v) for k, v in sorted(d.items())}


def slices(out: Path) -> None:
    from engine.adapters.skeleton import SkeletonIndex

    ix = SkeletonIndex(TT / "skeleton" / "trainticket.json.gz")
    db = ix.db_state
    tables = {name: {"columns": db.get_columns(name), "rows": db.get_table(name)} for name in sorted(db.table_names())}
    facts = ix.entities
    data = {
        "skeleton": {
            "project": ix.project,
            "nodes": list(ix.N),
            "handlers": [[h, v, segs] for h, v, segs in ix.handlers],
            "module": ix.module,
            "units": _sorted_sets(ix.units),
            "unit_of": {m: ix.unit_of(m) for m in ix.module},
            "cha": {m: sorted(ix.cha(m)) for m in ix.over},
            "calls": _sorted_sets(ix.calls),
            "over": _sorted_sets(ix.over),
            "wiring": {k: _sorted_sets(v) for k, v in sorted(ix.wiring.items())},
            "context": ix.context,
        },
        "db": tables,
        "entities": {
            "entities": {k: dataclasses.asdict(v) for k, v in sorted(facts.entities.items())},
            "calls_by_method": {k: [dataclasses.asdict(c) for c in v] for k, v in sorted(facts.calls_by_method.items())},
            "ctors_with_project_calls": sorted(facts.ctors_with_project_calls),
            "allowed_ctors": {mode: sorted(facts.allowed_ctors(mode) or ()) for mode in ("caller_only", "all", "off")},
        },
    }
    # ключи сортируем: порядок словарей из множеств (lazy_tables) в Python зависит от PYTHONHASHSEED
    _dump(data, out / "slices.json", sort_keys=True)
    _dump(_m4_slices(ix), out / "m4_slices.json", sort_keys=True)
    print(f"срезы: {out / 'slices.json'}")


def _m4_slices(ix) -> dict[str, Any]:
    """Срезы исполнителя: ответ-обёртка проекта, виды сущностей, число тел IR."""
    from engine.executor.step import StepExecutor
    from engine.manifest import entity_kinds
    from engine.rules import RuntimeRules

    ex = StepExecutor(ix, RuntimeRules(), ROOT / "data" / "ir", TT / "targets" / "trainticket")
    env = ex.it.envelope
    return {
        "envelope": dataclasses.asdict(env) if env else None,
        "kinds": {k: dataclasses.asdict(v) for k, v in entity_kinds(ix).items()},
        "ir_methods": sorted(ex.it.ir),
        "known_kinds": sorted(ex.schema.known_kinds),
        "login_ids": {m: list(v) for m, v in ex._login_ids.items()},
        "login_blanks": sorted(ex._login_blanks),
    }


def main(argv: list[str]) -> None:
    if len(argv) < 3 or argv[1] not in ("steps", "slices", "sweep"):
        raise SystemExit(__doc__)
    out = Path(argv[2])
    if argv[1] == "steps":
        if os.environ.get("ARCHONITY_TRACE"):
            Path(os.environ["ARCHONITY_TRACE"]).unlink(missing_ok=True)
        steps(out, [Path(x) for x in argv[3:]])
    elif argv[1] == "sweep":
        sweep(out)
    else:
        slices(out)


if __name__ == "__main__":
    main(sys.argv)
