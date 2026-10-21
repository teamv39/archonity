"""Stage 0: профиль проекта для промпта M1 v8 (ADR-007, решение 4).

Строит профиль тем же путём, что M1 при сборке (`engine/grounding/profile.py`): один вызов LLM, ответ в кеше
`cache/llm/`. Пишет копию для чтения в `data/project_profile.json`; конвейер её не читает.

    python scripts/profile_project.py                     # кеш, на промахе — сервер, если поднят
    python scripts/profile_project.py --no-server         # только кеш
    python scripts/profile_project.py --show-prompt       # напечатать вход профилировщика
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.adapters.skeleton import SkeletonIndex, load_json  # noqa: E402
from engine.grounding.docs import HandlerCatalog  # noqa: E402
from engine.grounding.llm import LLMClient  # noqa: E402
from engine.grounding.profile import build_profile, profile_messages, twin_pairs  # noqa: E402
from engine.grounding.retrieval import twin_groups  # noqa: E402
from engine.grounding.ui_catalog import build_catalog  # noqa: E402

TT = ROOT / "hackaton" / "tt-challenge"


def main() -> None:
    ap = argparse.ArgumentParser(description="Профиль проекта для M1 v8 (Stage 0)")
    ap.add_argument("--skeleton", type=Path, default=TT / "skeleton" / "trainticket.json.gz")
    ap.add_argument("--targets", type=Path, default=TT / "targets" / "trainticket")
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "data" / "project_profile.json")
    ap.add_argument("--no-server", action="store_true", help="только кеш")
    ap.add_argument("--no-cache", action="store_true", help="пересчитать ответ")
    ap.add_argument("--show-prompt", action="store_true", help="напечатать сообщения профилировщика")
    a = ap.parse_args()

    ix = SkeletonIndex(load_json(a.skeleton))
    ui = build_catalog(a.targets, ix)
    cat = HandlerCatalog(ix, a.targets, ui)
    twins = twin_groups(cat)
    if a.show_prompt:
        for m in profile_messages(ix, a.targets, cat, ui, twin_pairs(cat, twins)):
            print(f"--- {m['role']}\n{m['content']}\n")
    llm = LLMClient(use_server=not a.no_server, refresh=a.no_cache)
    prof = build_profile(ix, a.targets, cat, ui, twins, llm)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(prof.to_dict(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(prof.to_dict(), ensure_ascii=False, indent=1))
    print(f"LLM: {llm.stats}; записано {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
