"""M1: шаг сценария → StepRequest (ADR-005).

Кандидаты — BM25 и dense через RRF плюс близнецы; выбор и параметры — LLM по JSON-схеме с кешем.
Без LLM (нет сервера и нет кеша) — первый кандидат, параметры только из констант UI.

    python -m engine.grounding.grounder                               # все сценарии, кеш + сервер, если поднят
    python -m engine.grounding.grounder --eval eval/m1_steps.json      # точность по эталону
    python -m engine.grounding.grounder --no-llm --no-embed            # детерминированный режим без моделей
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.grounding import prompts as P
from engine.grounding.docs import HandlerCatalog, HandlerInfo
from engine.grounding.llm import LLMClient
from engine.grounding.request import StepRequest
from engine.grounding.retrieval import Ranked, Retriever
from engine.grounding.ui_catalog import UIRequest, build_catalog

ROOT = Path(__file__).resolve().parent.parent.parent
TT = ROOT / "hackaton" / "tt-challenge"
DEFAULT_EMBEDDER = "qwen3-4b"
TOP_K = 10
REFUSED = re.compile(r"\b(refuse[sd]?|rejects?|rejected|denie[sd]|fails?)\b", re.I)
ENUM_CONST = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*(?:\(([^)]*)\))?\s*[,;]", re.M)


def enum_codes(ix: SkeletonIndex, targets_root: Path) -> dict[str, list[str]]:
    """Перечисления проекта с кодами из исходника: {"SeatClass": ["NONE=0 (NoSeat)", "FIRSTCLASS=2 (FirstClassSeat)", ...]}."""
    out: dict[str, list[str]] = {}
    for nid, n in sorted(ix.N.items()):
        if n.get("kind") != "type" or n.get("type_kind") != "enum":
            continue
        consts = {f["name"] for f in ix.N.values()
                  if f.get("kind") == "field" and f.get("owner") == nid and "static" in (f.get("modifiers") or [])}
        try:
            src = (targets_root / n["file"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            src = ""
        vals = []
        for m in ENUM_CONST.finditer(src):
            if m.group(1) not in consts:
                continue
            args = [a.strip().strip('"') for a in (m.group(2) or "").split(",") if a.strip()]
            vals.append(f"{m.group(1)}={args[0]}" + (f" ({', '.join(args[1:])})" if len(args) > 1 else "") if args
                        else m.group(1))
        name = n["fqn"].split(".")[-1]
        if name in out and out[name] != vals:
            name = n["fqn"]
        out[name] = vals or sorted(consts)
    return out


@dataclass
class ScenarioSession:
    """Заземление одного сценария шаг за шагом: история выбранных запросов идёт в промпт следующих шагов."""

    grounder: StepGrounder
    scenario: dict[str, Any]
    ranked: dict[int, Ranked]
    history: list[str] = field(default_factory=list)
    requests: list[StepRequest] = field(default_factory=list)

    def ground(self, st: dict[str, Any]) -> StepRequest:
        req = self.grounder.ground_step(self.scenario, st, self.ranked[st["n"]], self.history)
        h = self.grounder.cat.handlers[req.handler]
        self.history.append(P.history_line(st["n"], req.http["method"], req.http["path"], h, req.expected_outcome))
        self.requests.append(req)
        return req


class StepGrounder:
    def __init__(self, ix: SkeletonIndex, targets_root: str | Path, embedder: str | None = DEFAULT_EMBEDDER,
                 allow_embed_model: bool = False, llm: LLMClient | None = None, render: str = "code_ui",
                 top_k: int = TOP_K) -> None:
        self.root = Path(targets_root)
        self.ui = build_catalog(self.root, ix)
        self.cat = HandlerCatalog(ix, self.root, self.ui)
        emb = None
        if embedder:
            from engine.grounding.embedder import make_embedder

            emb = make_embedder(embedder, allow_model=allow_embed_model)
        self.retriever = Retriever(self.cat, render, emb)
        self.llm = llm
        self.top_k = top_k
        self.system = P.system_prompt(enum_codes(ix, self.root))

    def begin(self, sc: dict[str, Any]) -> ScenarioSession:
        steps = sc.get("steps") or []
        ranked = self.retriever.search([s.get("action") or "" for s in steps])
        return ScenarioSession(self, sc, {s["n"]: r for s, r in zip(steps, ranked)})

    def ground_scenario(self, sc: dict[str, Any]) -> list[StepRequest]:
        sess = self.begin(sc)
        for st in sc.get("steps") or []:
            sess.ground(st)
        return sess.requests

    # ------------------------------------------------------------------ шаг

    def _ui_for(self, h: HandlerInfo) -> list[tuple[UIRequest, list[UIRequest]]]:
        """UI-запросы обработчика: сначала активные страницы (assets/js), потом старые js/."""
        reqs = sorted(h.ui, key=lambda r: ("/static/js/" in r.file, not r.pages, r.id))
        return [(r, self.ui.siblings(r)) for r in reqs]

    def ground_step(self, sc: dict[str, Any], st: dict[str, Any], ranked: Ranked, history: list[str]) -> StepRequest:
        n, action = st["n"], st.get("action") or ""
        cands = ranked.candidates(self.top_k, self.retriever.twins)
        labels = [f"C{i + 1}" for i in range(len(cands))]
        prefix = P.scenario_block(sc) + "\n" + P.history_block(history) + "\n"
        grounding: dict[str, Any] = {"candidates": cands, "cache_keys": {}}

        sel = None
        if self.llm is not None:
            blocks = "\n".join(
                P.candidate_block(lb, self.cat.handlers[h], self._ui_for(self.cat.handlers[h]),
                                  P.train_kind(self.cat.handlers[h].module) if h in self.retriever.twins else None)
                for lb, h in zip(labels, cands))
            msgs = [{"role": "system", "content": self.system},
                    {"role": "user", "content": prefix + P.SELECT_TASK.format(n=n, action=action, candidates=blocks)}]
            sel, key = self.llm.complete_json("select", P.PROMPT_VERSION, msgs, P.select_schema(labels, n))
            grounding["cache_keys"]["select"] = key
        if sel is not None and sel.get("candidate") in labels:
            handler = cands[labels.index(sel["candidate"])]
            outcome = sel.get("expected_outcome") or "success"
            refs = {k: v for k, v in (sel.get("refs") or {}).items() if v}
            grounding.update(source="LLM", reasoning=sel.get("reasoning", ""))
        else:
            handler = cands[0]
            outcome = "refused" if REFUSED.search(action) else "success"
            refs = {}
            grounding["source"] = "RETRIEVAL"

        h = self.cat.handlers[handler]
        ui = self._ui_for(h)
        ui_req = ui[0][0] if ui else None
        verb, path = h.routes[0]
        if verb == "ANY" and ui_req is not None:
            verb = ui_req.verb
        fields = P.request_fields(h)
        names = {f for f, _, _ in fields}
        params: dict[str, Any] = {}
        sources: dict[str, str] = {}
        if ui_req is not None:
            for k, v in ui_req.body_consts.items():
                if k in names:
                    params[k], sources[k] = v, "UI"
        if self.llm is not None and grounding["source"] == "LLM" and P.needs_params(h):
            msgs = [{"role": "system", "content": self.system},
                    {"role": "user", "content": prefix + P.params_task(n, action, verb, path, h, fields, ui_req)}]
            got, key = self.llm.complete_json("params", P.PROMPT_VERSION, msgs, P.params_schema(fields))
            grounding["cache_keys"]["params"] = key
            for k, v in (got or {}).items():
                if v is not None and k in names:
                    params[k], sources[k] = v, "LLM"
        grounding["param_sources"] = sources
        grounding["ranks"] = {"bm25": _rank(ranked.bm25, handler), "dense": _rank(ranked.dense, handler),
                              "fused": _rank(ranked.fused, handler)}
        return StepRequest(
            scenario=sc.get("id", "S?"), step=n, action=action, handler=handler,
            http={"method": verb, "path": path}, params=params, expected_outcome=outcome, refs=refs,
            ui_source={"file": ui_req.file, "line": ui_req.line} if ui_req is not None else None,
            grounding=grounding,
        )


def _rank(lst: list[str], h: str) -> int | None:
    return lst.index(h) + 1 if h in lst else None


# ---------------------------------------------------------------------- CLI


def _short(h: str) -> str:
    return h.split(":", 2)[2].split("(")[0].split(".")[-1]


def evaluate(results: dict[str, list[StepRequest]], gold_path: Path) -> dict[str, Any]:
    gold = json.loads(gold_path.read_text(encoding="utf-8"))["scenarios"]
    total = hit = cand_hit = 0
    wrong = []
    for sid, reqs in results.items():
        g = {s["n"]: s for s in gold.get(sid, [])}
        for r in reqs:
            if r.step not in g:
                continue
            s = g[r.step]
            ok = {s["handler"]} | (set(s.get("alt") or []) if s.get("status") == "disputed" else set())
            total += 1
            hit += r.handler in ok
            cand_hit += bool(ok & set(r.grounding["candidates"]))
            if r.handler not in ok:
                wrong.append((sid, r.step, r.action, _short(r.handler), _short(s["handler"]),
                              bool(ok & set(r.grounding["candidates"]))))
    print(f"\nточность top-1 {hit}/{total} = {hit / max(1, total):.3f}; эталон среди кандидатов {cand_hit}/{total}")
    for sid, n, act, got, want, in_c in wrong:
        print(f"  {sid}.{n:<3} {act[:64]:<64} got {got:<34} want {want}{'' if in_c else '  (нет в кандидатах)'}")
    p_total = p_hit = 0
    p_wrong = []
    for sid, reqs in results.items():
        g = {s["n"]: s for s in gold.get(sid, [])}
        for r in reqs:
            for k, want in (g.get(r.step, {}).get("params") or {}).items():
                got = r.params.get(k)
                p_total += 1
                if _same(got, want):
                    p_hit += 1
                else:
                    p_wrong.append(f"{sid}.{r.step} {k}: got {got!r} want {want!r}")
    if p_total:
        print(f"параметры {p_hit}/{p_total} = {p_hit / p_total:.3f}")
        for w in p_wrong:
            print("  " + w)
    return {"total": total, "top1": hit, "in_candidates": cand_hit, "params": p_hit, "params_total": p_total}


def _same(got: Any, want: Any) -> bool:
    if isinstance(want, bool) or isinstance(got, bool):
        return got is want
    if isinstance(want, (int, float)):
        try:
            return abs(float(got) - float(want)) < 1e-6
        except (TypeError, ValueError):
            return False
    return str(got).strip().lower() == str(want).strip().lower()


def main() -> None:
    ap = argparse.ArgumentParser(description="M1: заземление шагов сценариев")
    ap.add_argument("scenarios", nargs="*", help="по умолчанию hackaton/tt-challenge/scenarios/*.json")
    ap.add_argument("--skeleton", type=Path, default=TT / "skeleton" / "trainticket.json.gz")
    ap.add_argument("--targets", type=Path, default=TT / "targets" / "trainticket")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "steps")
    ap.add_argument("--eval", type=Path, help="эталон шагов (eval/m1_steps.json)")
    ap.add_argument("--embedder", default=DEFAULT_EMBEDDER)
    ap.add_argument("--no-embed", action="store_true", help="без dense-ретривера")
    ap.add_argument("--embed-model", action="store_true", help="разрешить загрузку эмбеддера на промахе кеша")
    ap.add_argument("--no-llm", action="store_true", help="без LLM: первый кандидат")
    ap.add_argument("--no-server", action="store_true", help="LLM только из кеша")
    ap.add_argument("--no-cache", action="store_true", help="пересчитать ответы LLM")
    ap.add_argument("--top-k", type=int, default=TOP_K)
    a = ap.parse_args()

    paths = a.scenarios or sorted(glob.glob(str(TT / "scenarios" / "*.json")))
    ix = SkeletonIndex(load_json(a.skeleton))
    llm = None if a.no_llm else LLMClient(use_server=not a.no_server, refresh=a.no_cache)
    g = StepGrounder(ix, a.targets, embedder=None if a.no_embed else a.embedder,
                     allow_embed_model=a.embed_model, llm=llm, top_k=a.top_k)
    a.out.mkdir(parents=True, exist_ok=True)
    results: dict[str, list[StepRequest]] = {}
    for p in paths:
        sc = load_json(p)
        reqs = g.ground_scenario(sc)
        results[sc["id"]] = reqs
        (a.out / f"{sc['id']}.json").write_text(
            json.dumps([r.to_dict() for r in reqs], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{sc['id']}: шагов {len(reqs)}, через LLM {sum(r.grounding['source'] == 'LLM' for r in reqs)}",
              file=sys.stderr)
    if llm is not None:
        print(f"LLM: {llm.stats}", file=sys.stderr)
    if a.eval:
        evaluate(results, a.eval)


if __name__ == "__main__":
    main()
