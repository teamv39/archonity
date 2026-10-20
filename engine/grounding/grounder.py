"""M1: шаг сценария → StepRequest (ADR-005).

Кандидаты — BM25 и dense через RRF плюс близнецы; выбор и параметры — LLM по JSON-схеме с кешем.
LLM видит подробные карточки кандидатов и индекс всех обработчиков, выбрать может любой из индекса.
Без LLM (нет сервера и нет кеша) — первый кандидат, параметры только из констант UI.

    python -m engine.grounding.grounder                               # все сценарии, кеш + сервер, если поднят
    python -m engine.grounding.grounder --eval eval/m1_steps.json      # точность по эталону
    python -m engine.grounding.grounder --no-llm --no-embed            # детерминированный режим без моделей
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import sys
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.grounding import prompts as P
from engine.grounding.docs import HandlerCatalog, HandlerInfo
from engine.grounding.binding import rebind
from engine.grounding.llm import LLMClient
from engine.grounding.profile import ProjectProfile, build_profile
from engine.grounding.request import REF_ENTITIES, StepRequest
from engine.grounding.retrieval import Ranked, Retriever
from engine.grounding.text import DOMAIN_SYN
from engine.grounding.ui_catalog import UIRequest, build_catalog, find_ui_dir, match_handlers
from engine.manifest import entity_kinds

ROOT = Path(__file__).resolve().parent.parent.parent
TT = ROOT / "hackaton" / "tt-challenge"
DEFAULT_EMBEDDER = "qwen3-4b"
TOP_K = 10
# Режим v8: выбор обработчика голосованием — жадный ответ и SELECT_VOTES выборок с параметрами модели по умолчанию
# для режима без thinking и seed 1..SELECT_VOTES (заданы заранее, под результат не подбираются); побеждает
# обработчик большинства (`StepGrounder._vote`). При temperature 0 правка текста промпта переставляла пограничные шаги.
SELECT_VOTES = 5
SAMPLING = {"temperature": 0.7, "top_p": 0.8, "top_k": 20}
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


def _majority(xs: list[str]) -> str:
    """Самое частое значение; при равенстве — встреченное раньше."""
    c = collections.Counter(xs)
    return max(c, key=lambda x: (c[x], -xs.index(x)))


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
                 top_k: int = TOP_K, module_roles: str = "skeleton", prompt: str = "v8") -> None:
        """`prompt` — режим промпта (ADR-007): v8 — общий шаблон и профиль проекта, v7 — промпт до ADR-007."""
        if prompt not in P.PROMPT_MODES:
            raise ValueError(f"prompt: {prompt!r}, ожидается одно из {P.PROMPT_MODES}")
        self.ix = ix
        self.root = Path(targets_root)
        self.prompt = prompt
        self.version = P.PROMPT_VERSIONS[prompt]
        v7 = prompt == "v7"
        self.ui_dir = find_ui_dir(self.root, ix)
        self.ui = build_catalog(self.root, ix, self.ui_dir)
        self.cat = HandlerCatalog(ix, self.root, self.ui, ROOT / "data" / "ir")
        emb = None
        if embedder:
            from engine.grounding.embedder import QUERY_TASK, QUERY_TASK_V7, make_embedder

            emb = make_embedder(embedder, allow_model=allow_embed_model, task=QUERY_TASK_V7 if v7 else QUERY_TASK)
        self.retriever = Retriever(self.cat, render, emb, module_roles, syn=DOMAIN_SYN if v7 else None)
        self.llm = llm
        self.top_k = top_k
        self.labels = P.handler_labels(self.cat.handlers)
        self.by_label = {lb: h for h, lb in self.labels.items()}
        enums = enum_codes(ix, self.root)
        index = P.handler_index(self.cat.handlers, self.labels)
        self.profile: ProjectProfile | None = None
        self.ref_kinds: tuple[str, ...] = REF_ENTITIES
        self.example_kinds: tuple[str, str] | None = None
        if v7:
            self.system_select = P.system_prompt(enums, index)
            self.system_params = P.system_prompt(enums)
        else:
            # Виды refs — из манифеста сущностей (ADR-007, решение 2), M4 их понимает в режиме --ref-kinds v8
            kinds = entity_kinds(ix)
            self.ref_kinds = tuple(kinds)
            self.example_kinds = P.example_kinds(kinds, self.cat.handlers)
            modules = {n.get("fqn"): n.get("module", "") for n in ix.N.values() if n.get("kind") == "type"}
            self.profile = build_profile(ix, self.root, self.cat, self.ui, self.retriever.twins, llm)
            env = (ix.sk.get("context") or {}).get("profile")
            admin = any("admin" in h.module.split("-") for h in self.cat.handlers.values())
            self.system_select = P.system_prompt_v8(enums, self.profile, self.ui_dir, env, admin, index,
                                                    P.ref_kinds_block(kinds, modules))
            self.system_params = P.system_prompt_v8(enums, self.profile, self.ui_dir, env, admin)

    def rebind(self, req: StepRequest) -> StepRequest | None:
        """R20: M1 выбрал обработчик, который Spring вызвать не может (`@PathVariable` не совпадает с шаблоном
        пути). Шаг идёт через рабочий обработчик того же контроллера с тем же входом (`engine/grounding/binding.py`).

        Замена — после заземления: выбор M1 и история в промпте следующих шагов не меняются, кеш LLM цел.
        Параметры не переносятся: тело нового обработчика другое (имя станции → список имён)."""
        got = rebind(self.ix, self.cat, req.handler)
        if got is None:
            return None
        handler, why = got
        verb, path = self.cat.handlers[handler].routes[0]
        return dataclasses.replace(req, handler=handler, http={"method": verb, "path": path}, params={},
                                   ui_source=None, grounding=dict(req.grounding, rebound=why))

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

    def _candidate(self, h: str) -> str:
        """Карточка кандидата; у близнеца — какие данные он обслуживает (v7 — типы поездов, v8 — профиль)."""
        info = self.cat.handlers[h]
        twin = h in self.retriever.twins
        if self.prompt == "v7":
            return P.candidate_block(self.labels[h], info, self._ui_for(info), P.train_kind(info.module) if twin else None)
        ui = self._ui_for(info)
        return P.candidate_block(self.labels[h], info, ui, twin=P.twin_note(self.profile, info.module) if twin else None,
                                 notes=P.followup_notes(ui, self._answers, self._answer_guards),
                                 calls=self.cat.service_calls(h))

    def _vote(self, msgs: list[dict[str, str]], schema: dict[str, Any],
              grounding: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """Выбор голосованием: жадный ответ и `SELECT_VOTES` выборок, обработчик большинства (при равенстве —
        жадного ответа). Ответ целиком (refs, исход) — жадный, если его обработчик победил; иначе самый частый
        среди выборок победителя. Выборки проверяют решение, детали — от жадного вывода: при temperature 0.7 refs
        шумят (trip -> train для «первого рейса шага 2»)."""
        got = [self.llm.complete_json("select", self.version, msgs, schema)]
        got += [self.llm.complete_json("select", self.version, msgs, schema, sampling={**SAMPLING, "seed": i + 1})
                for i in range(SELECT_VOTES)]
        valid = [(sel, key) for sel, key in got if sel is not None and sel.get("handler") in self.by_label]
        grounding["cache_keys"]["select_votes"] = [key for _, key in got]
        if not valid:
            return None, got[0][1]
        grounding["votes"] = dict(collections.Counter(sel["handler"] for sel, _ in valid))
        best = _majority([sel["handler"] for sel, _ in valid])
        greedy = got[0][0]
        if greedy is not None and greedy.get("handler") == best:
            return got[0]
        mine = [(sel, key) for sel, key in valid if sel["handler"] == best]
        answers = [json.dumps({"refs": P.refs_of(sel),
                               "outcome": sel.get("expected_outcome")}, sort_keys=True) for sel, _ in mine]
        return mine[answers.index(_majority(answers))]

    def _answers(self, verb: str, url: str) -> dict[int, list[str]]:
        """Коды ответа обработчиков запроса `verb url` из их исходника (для `followup_notes`)."""
        out: dict[int, list[str]] = {}
        for h in match_handlers(verb, url, self.ix.handlers):
            for code, msgs in self.cat.answers(h).items():
                out.setdefault(code, []).extend(m for m in msgs if m not in out[code])
        return out

    def _answer_guards(self, verb: str, url: str) -> dict[int, list[str]]:
        """Условия возврата кодов ответа обработчиков запроса `verb url` по IR (для `followup_notes`)."""
        out: dict[int, list[str]] = {}
        for h in match_handlers(verb, url, self.ix.handlers):
            for code, conds in self.cat.answer_guards(h).items():
                out.setdefault(code, []).extend(c for c in conds if c not in out[code])
        return out

    def ground_step(self, sc: dict[str, Any], st: dict[str, Any], ranked: Ranked, history: list[str]) -> StepRequest:
        n, action = st["n"], st.get("action") or ""
        cands = ranked.candidates(self.top_k, self.retriever.twins)
        prefix = P.scenario_block(sc) + "\n" + P.history_block(history) + "\n"
        grounding: dict[str, Any] = {"candidates": cands, "cache_keys": {}}
        v7 = self.prompt == "v7"
        if self.profile is not None and self.profile.key:
            grounding["cache_keys"]["profile"] = self.profile.key

        sel = None
        if self.llm is not None:
            blocks = "\n".join(self._candidate(h) for h in cands)
            if v7:
                task = P.SELECT_TASK.format(n=n, action=action, candidates=blocks)
            else:
                ex1, ex2 = self.example_kinds or ("", "")
                task = P.SELECT_TASK_V8.format(n=n, action=action, candidates=blocks, ex1=ex1, ex2=ex2)
            msgs = [{"role": "system", "content": self.system_select}, {"role": "user", "content": prefix + task}]
            schema = P.select_schema(list(self.by_label), n, self.ref_kinds, ref_pairs=not v7)
            if v7:
                sel, key = self.llm.complete_json("select", self.version, msgs, schema)
            else:
                sel, key = self._vote(msgs, schema, grounding)
            grounding["cache_keys"]["select"] = key
        if sel is not None and sel.get("handler") in self.by_label:
            handler = self.by_label[sel["handler"]]
            outcome = sel.get("expected_outcome") or "success"
            refs = P.refs_of(sel)
            grounding.update(source="LLM", reasoning=sel.get("reasoning", ""), from_index=handler not in cands)
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
            task = P.params_task(n, action, verb, path, h, fields, ui_req, P.PARAMS_TASK if v7 else P.PARAMS_TASK_V8,
                                 optional=not v7)
            msgs = [{"role": "system", "content": self.system_params}, {"role": "user", "content": prefix + task}]
            got, key = self.llm.complete_json("params", self.version, msgs, P.params_schema(fields))
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
    ap.add_argument("--prompt", choices=P.PROMPT_MODES, default="v8", help="режим промпта M1 (ADR-007); v7 — откат")
    a = ap.parse_args()

    paths = a.scenarios or sorted(glob.glob(str(TT / "scenarios" / "*.json")))
    ix = SkeletonIndex(load_json(a.skeleton))
    llm = None if a.no_llm else LLMClient(use_server=not a.no_server, refresh=a.no_cache)
    g = StepGrounder(ix, a.targets, embedder=None if a.no_embed else a.embedder,
                     allow_embed_model=a.embed_model, llm=llm, top_k=a.top_k, prompt=a.prompt)
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
