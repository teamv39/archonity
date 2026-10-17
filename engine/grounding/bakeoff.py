"""Бейкофф ретриверов M1: Recall@k BM25, dense и RRF по эталону eval/m1_steps.json.

    python -m engine.grounding.bakeoff                      # только BM25
    python -m engine.grounding.bakeoff --embedder qwen3-4b  # + dense и RRF (векторы из кеша или модели)
    python -m engine.grounding.bakeoff --embedder qwen3-4b --embedder gemma2 --lost

Шаг засчитан, если эталонный обработчик (`handler`) среди первых k кандидатов. Для `disputed` подходит и `alt`.
Кандидаты с близнецами считаются отдельной колонкой `+tw` (что реально уходит в LLM).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.grounding.docs import RENDERS, HandlerCatalog
from engine.grounding.retrieval import Ranked, Retriever
from engine.grounding.ui_catalog import build_catalog

ROOT = Path(__file__).resolve().parent.parent.parent
TT = ROOT / "hackaton" / "tt-challenge"
KS = (1, 5, 10, 15)


def load_eval(path: Path) -> list[dict[str, Any]]:
    d = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for sid, steps in d["scenarios"].items():
        for s in steps:
            ok = {s["handler"]} | (set(s.get("alt") or []) if s.get("status") == "disputed" else set())
            out.append({"sid": sid, "n": s["n"], "action": s["action"], "ok": ok, "status": s.get("status")})
    return out


def recall(ranked: list[list[str]], gold: list[dict[str, Any]], k: int) -> float:
    hit = sum(1 for r, g in zip(ranked, gold) if g["ok"] & set(r[:k]))
    return hit / max(1, len(gold))


def report(name: str, res: list[Ranked], gold: list[dict[str, Any]], twins: dict[str, list[str]]) -> dict[str, float]:
    row: dict[str, float] = {}
    for label, lists in (("bm25", [r.bm25 for r in res]), ("dense", [r.dense for r in res]),
                         ("rrf", [r.fused for r in res])):
        if not lists[0]:
            continue
        for k in KS:
            row[f"{label}@{k}"] = recall(lists, gold, k)
    cand10 = [r.candidates(10, twins) for r in res]
    row["rrf@10+tw"] = sum(1 for c, g in zip(cand10, gold) if g["ok"] & set(c)) / len(gold)
    row["avg_cand@10+tw"] = sum(len(c) for c in cand10) / len(cand10)
    cells = "  ".join(f"{k}={v:.3f}" if "avg" not in k else f"{k}={v:.1f}" for k, v in row.items())
    print(f"{name:<28} {cells}")
    return row


def lost(res: list[Ranked], gold: list[dict[str, Any]], k: int, twins: dict[str, list[str]]) -> None:
    short = lambda h: h.split(":", 2)[2].split("(")[0]  # noqa: E731
    for r, g in zip(res, gold):
        c = r.candidates(k, twins)
        if not g["ok"] & set(c):
            pos = min((r.fused.index(h) for h in g["ok"] if h in r.fused), default=-1)
            print(f"   {g['sid']}.{g['n']:<3} rank {pos + 1:<4} {g['action'][:70]:<70} want {short(min(g['ok']))}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", type=Path, default=ROOT / "eval" / "m1_steps.json")
    ap.add_argument("--embedder", action="append", default=[], help="qwen3-4b, gemma2, qwen3-0.6b")
    ap.add_argument("--render", action="append", choices=RENDERS, default=None)
    ap.add_argument("--lost", action="store_true", help="показать шаги, потерянные в кандидатах @10+близнецы")
    ap.add_argument("--json", type=Path, help="сохранить таблицу")
    a = ap.parse_args()

    ix = SkeletonIndex(load_json(TT / "skeleton" / "trainticket.json.gz"))
    cat = HandlerCatalog(ix, TT / "targets" / "trainticket", build_catalog(TT / "targets" / "trainticket", ix))
    gold = load_eval(a.eval)
    queries = [g["action"] for g in gold]
    print(f"шагов {len(gold)}, обработчиков {len(cat.handlers)}")
    table: dict[str, dict[str, float]] = {}
    embedders = [None] + a.embedder
    for render in a.render or list(RENDERS):
        for emb_name in embedders:
            emb = None
            if emb_name:
                from engine.grounding.embedder import make_embedder

                emb = make_embedder(emb_name)
            ret = Retriever(cat, render, emb)
            res = ret.search(queries)
            name = f"{render}/{emb_name or 'bm25'}"
            table[name] = report(name, res, gold, ret.twins)
            if a.lost:
                lost(res, gold, 10, ret.twins)
    if a.json:
        a.json.write_text(json.dumps(table, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
