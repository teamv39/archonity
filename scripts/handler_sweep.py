"""Прогон M4 по каждому обработчику каталога M1 как по одношаговому сценарию без параметров.

Проверяет устойчивость исполнителя на обработчиках, которых нет в S1–S7: исключения, время, пустой ответ.
Ответ по каждому обработчику — оракул для правок M4 и порта на Rust (roadmap, П4).

    python scripts/handler_sweep.py . output/handler_sweep.json
"""
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT))

from engine.grounding.llm import LLMClient  # noqa: E402
from engine.grounding.request import StepRequest  # noqa: E402
from engine.pipeline import ArchonityPipeline, resolve_passenger_context  # noqa: E402

TT = ROOT / "hackaton" / "tt-challenge"
p = ArchonityPipeline(
    skeleton_path=TT / "skeleton" / "trainticket.json.gz",
    targets_root=TT / "targets" / "trainticket",
    m1_options={"embedder": "qwen3-4b", "llm": LLMClient(use_server=False)},
)
used = set()
for f in (ROOT / "eval" / "m1_steps.json",):
    for steps in json.loads(f.read_text(encoding="utf-8"))["scenarios"].values():
        used |= {s["handler"] for s in steps}

cat = p.m1.cat.handlers
res = []
for nid, h in cat.items():
    verb = h.routes[0][0] if h.routes else "GET"
    req = StepRequest(scenario="SX", step=1, action="", handler=nid,
                      http={"method": verb, "path": h.routes[0][1] if h.routes else ""})
    ctx = resolve_passenger_context(getattr(p.index, "context", None), db_state=getattr(p.index, "db_state", None),
                                    scenario_id="SX")
    p.ledger.begin_scenario("SX")
    p.ledger.begin_step(1)
    p.m4.begin_scenario("SX")
    t = time.perf_counter()
    rec = {"handler": nid, "in_s1_s7": nid in used}
    try:
        m, c, r, d = p.m4.run_step(req, ctx, ledger=p.ledger)
        rec.update(ok=True, executes=sorted(m), calls=sorted(c), remote=sorted(r), data=sorted(d))
    except Exception as e:  # noqa: BLE001
        rec.update(ok=False, error=f"{type(e).__name__}: {e}", where=traceback.format_exc().splitlines()[-3].strip())
    rec["sec"] = round(time.perf_counter() - t, 3)
    res.append(rec)

Path(sys.argv[2]).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
bad = [r for r in res if not r["ok"]]
print(f"обработчиков {len(res)}, из них в S1–S7 {sum(r['in_s1_s7'] for r in res)}")
print(f"исключений {len(bad)} (в S1–S7 {sum(r['in_s1_s7'] for r in bad)})")
print(f"пустой executes {sum(1 for r in res if r['ok'] and not r['executes'])}")
print(f"время: сумма {sum(r['sec'] for r in res):.1f} с, макс {max(r['sec'] for r in res):.2f} с")
errs = {}
for r in bad:
    errs.setdefault(r["error"][:90], []).append(r["handler"])
for e, hs in sorted(errs.items(), key=lambda x: -len(x[1])):
    print(f"  {len(hs):3}  {e}  напр. {hs[0]}")
