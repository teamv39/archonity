#!/usr/bin/env python3
"""Черновик эталона M1: входы шагов S0–S7 по текущему resolver.py.

Результат — eval/m1_steps.json. Это заготовка под ручную сверку: каждую пару «шаг — обработчик»
проверяем по ts-ui-dashboard и контроллерам и правим руками. Пайплайн этот файл не читает.

    python scripts/m1_bootstrap_eval.py [-o eval/m1_steps.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.adapters.skeleton import SkeletonIndex, load_json  # noqa: E402
from engine.resolver import ScenarioGrounder  # noqa: E402
from engine.rules import ScenarioProfile  # noqa: E402

TT = ROOT / "hackaton" / "tt-challenge"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "eval" / "m1_steps.json")
    a = ap.parse_args()

    ix = SkeletonIndex(load_json(TT / "skeleton" / "trainticket.json.gz"))
    grounder = ScenarioGrounder(ix, TT / "targets" / "trainticket")
    out: dict = {"source": "engine/resolver.py ScenarioGrounder.ground_step, затем ручная сверка", "scenarios": {}}
    for path in sorted(glob.glob(str(TT / "scenarios" / "*.json"))):
        sc = load_json(path)
        profile = ScenarioProfile.from_scenario(sc)
        steps = []
        prev: set[str] = set()
        for st in sc["steps"]:
            entries, prev = grounder.ground_step(st, profile.for_step(st), prev_files=prev)
            hs = sorted(entries)
            steps.append({
                "n": st["n"],
                "action": st["action"],
                "handler": hs[0] if len(hs) == 1 else None,
                "alt": hs if len(hs) > 1 else [],
                "status": "draft",
                "note": "",
            })
        out["scenarios"][sc["id"]] = steps
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n = sum(len(v) for v in out["scenarios"].values())
    amb = sum(1 for v in out["scenarios"].values() for s in v if s["handler"] is None)
    print(f"шагов {n}, без однозначного обработчика {amb} -> {a.out}")


if __name__ == "__main__":
    main()
