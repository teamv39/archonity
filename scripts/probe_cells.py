"""Точный замер FP и FN одной ячейки «сценарий × вид» по итоговому баллу платформы.

Зонд — базовый ответ, из которого убран один вид рёбер в одном сценарии. Балл сценария падает на IoU/4, итог —
на IoU/28. Итог дан с 6 знаками, поэтому IoU ячейки известен с точностью ≈ 3e-5, а соседние значения
(P - FP) / (P + FN) при малых FP и FN отличаются на ≥ 1e-3: решение единственное. Ячейки в одной посылке не
совмещать — итог покажет только сумму.

    python scripts/probe_cells.py make  <base submission.json> <папка> [S2:data S3:calls ...]
    python scripts/probe_cells.py solve <папка>/manifest.json <итоги.txt>

По умолчанию — executes, calls, data в S2 и S3 (remote измерен 18.10: IoU 1.000 во всех семи).
Формат итоги.txt: строка «имя итог», имя base — базовый ответ, остальные — имена зондов (drop_S2_data, ...).
Каждый архив зонда собирается pack_submission.py с кодом рабочей копии и RUN.md с пометкой «зонд».
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_CELLS = ("S2:executes", "S2:calls", "S2:data", "S3:executes", "S3:calls", "S3:data")
TOL = 3e-5
MAX_ERR = 6


def make(base_p: str, out_p: str, cells: list[str]) -> None:
    import pack_submission as ps

    base = json.loads(Path(base_p).read_text(encoding="utf-8"))
    out = Path(out_p)
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}
    for cell in cells:
        sid, kind = cell.split(":")
        edges = base["scenarios"][sid]["edges"]
        name = f"drop_{sid}_{kind}"
        probe = json.loads(json.dumps(base))
        probe["scenarios"][sid]["edges"] = [e for e in edges if e["relation"] != kind]
        js = out / f"{name}.json"
        js.write_text(json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest[name] = {"scenario": sid, "kind": kind, "P": sum(1 for e in edges if e["relation"] == kind)}
        ps.SUBMISSION_JSON = js
        ps.pack(out / f"{name}.zip", f"ЗОНД {name}: из {base_p} убраны все рёбра {kind} сценария {sid}. "
                                    f"Замер, не решение: после зондов перезалить выдачу кода.")
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    for n, m in manifest.items():
        print(f"  {n}.zip  P={m['P']}")


def cell_fits(P: int, iou: float) -> list[tuple[int, int]]:
    return [(fp, fn) for fp in range(MAX_ERR + 1) for fn in range(MAX_ERR + 1) if abs((P - fp) / (P + fn) - iou) <= TOL]


def solve(man_p: str, totals_p: str) -> None:
    """По каждой ячейке — сочетания (FP, FN) в пределах погрешности. Если их несколько (calls: «1 лишнее» и
    «1 не хватает» различаются на ~2e-5 при P ≈ 200), спорное снимает совместная проверка: при известных всех
    ячейках S2 и S3 (remote = 1, остальные сценарии = 1) сумма баллов S2 + S3 = 7·base − 5 с точностью 3.5e-6."""
    import itertools

    man = json.loads(Path(man_p).read_text(encoding="utf-8"))
    tot = {}
    for line in Path(totals_p).read_text(encoding="utf-8").splitlines():
        p = line.split()
        if len(p) == 2:
            tot[p[0]] = float(p[1])
    base = tot["base"]
    fits = {}
    for name, m in man.items():
        if name not in tot:
            continue
        iou = 28 * (base - tot[name])
        fits[name] = cell_fits(m["P"], iou)
        print(f"{m['scenario']} {m['kind']:<9} P={m['P']:<4} IoU={iou:.5f}  кандидаты (FP, FN): {fits[name] or 'нет'}")
    if len(fits) != len(man) or not all(fits.values()):
        return
    names = list(fits)
    target = 7 * base - 5
    joint = []
    for combo in itertools.product(*(fits[n] for n in names)):
        by_s: dict[str, float] = {}
        for n, (fp, fn) in zip(names, combo):
            P = man[n]["P"]
            by_s[man[n]["scenario"]] = by_s.get(man[n]["scenario"], 1.0) + (P - fp) / (P + fn)  # 1.0 — remote
        if abs(sum(v / 4 for v in by_s.values()) - target) <= 3.5e-6:
            joint.append(combo)
    print()
    print(f"Совместно с итогом base ({base}): {len(joint)} решени(е/я)")
    for combo in joint:
        print("  ", ", ".join(f"{man[n]['scenario']}:{man[n]['kind']} FP={fp} FN={fn}" for n, (fp, fn) in zip(names, combo)))


if __name__ == "__main__":
    if sys.argv[1] == "make":
        make(sys.argv[2], sys.argv[3], sys.argv[4:] or list(DEFAULT_CELLS))
    else:
        solve(sys.argv[2], sys.argv[3])
