"""Отчёт прогона для жюри: один статический report.html по файлам рядом с выдачей, без сервера и зависимостей.

    python scripts/report.py output/                       # output/report.html
    python scripts/report.py output/ --compare output-py/  # и паритет файлов с другим прогоном (Rust и Python)

Что в отчёте:
- сводка: sha256 выдачи и совпадение с рекордом, режим M1, ответы и время LLM, сбои (Р2);
- качество: IoU по видам рёбер против эталона организаторов (S0) и рекорда платформы 1.0 (S1–S7), формула
  evaluate_golden.py;
- M1 на своих сценариях: верный ли обработчик по ручной разметке eval/own/steps.json;
- по сценариям и шагам: текст шага, обработчик, голоса LLM, параметры, рёбра с правилом и местом в коде (скелет).

Выдачу не меняет и не пересчитывает: читает submission.json, decisions.json, step_requests.json, m1_report.json.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "hackaton" / "tt-challenge"
KINDS = ("executes", "calls", "remote", "data")
COMPARED = ("submission.json", "decisions.json", "evidence.json", "step_requests.json")
# Выдача кода с баллом 1.00000 на S0–S7 (eval/records/README.md): эталон воспроизводимости
RECORD_SHA256 = "94463c41a72c244fc548cbb52d009cff7c65f44ad5e682b7176a156cb66a5a08"


def load(path: Path):
    with (gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else open(path, encoding="utf-8")) as f:
        return json.load(f)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def edge_sets(block: dict) -> dict[str, set]:
    """Блок сценария выдачи → множества по видам, как в evaluate_golden.py."""
    out = {k: set() for k in KINDS}
    for e in block.get("edges", []):
        rel = e["relation"]
        if rel in out:
            out[rel].add(e["target"] if rel == "executes" else (e["source"], e["target"]))
    return out


def gold_sets(block: dict) -> dict[str, set]:
    """Блок эталона организаторов (`methods`, `calls`, `remote`, `data`) → множества по видам."""
    return {"executes": set(block.get("methods", [])),
            **{k: {tuple(x) for x in block.get(k, [])} for k in ("calls", "remote", "data")}}


def iou(p: set, g: set) -> float:
    return 1.0 if not p and not g else len(p & g) / len(p | g)


def short(node: str) -> str:
    """`method:ts-x-service:pkg.Cls#m(args)` → `x:Cls#m(…)`, таблица → `таблица ts-x.t`."""
    if node.startswith("res:table:"):
        return "таблица " + node[len("res:table:"):]
    m = re.match(r"method:([^:]+):(.*?)(\(.*\))$", node)
    if not m:
        return node
    svc, name, args = m.groups()
    cls, meth = name.rsplit("#", 1)
    return f"{svc.removeprefix('ts-').removesuffix('-service')}:{cls.rsplit('.', 1)[-1]}#{meth}" \
           f"({'…' if args != '()' else ''})"


class CodeIndex:
    """Место ребра в коде по скелету: метод — его объявление, вызов — call_site источника к цели."""

    def __init__(self, skeleton: dict, targets: Path, out_dir: Path) -> None:
        self.nodes = skeleton["nodes"]
        self.targets, self.out_dir = targets, out_dir
        self.sites: dict[tuple[str, str], tuple[str, int]] = {}
        for e in skeleton["edges"]:
            if e["type"] not in ("calls", "runtime_dispatch", "remote_call", "data_access"):
                continue
            cs = self.nodes.get(e["source"])
            if not cs or cs.get("kind") != "call_site":
                continue
            key = (cs["method"], e["target"])
            if key not in self.sites or cs["line"] < self.sites[key][1]:
                self.sites[key] = (cs["file"], cs["line"])

    def where(self, kind: str, src: str, tgt: str) -> tuple[str, int] | None:
        if kind != "executes" and (src, tgt) in self.sites:
            return self.sites[(src, tgt)]
        node = self.nodes.get(tgt if kind == "executes" else src) or {}
        return (node["file"], node["line"]) if node.get("file") else None

    def link(self, loc: tuple[str, int] | None) -> str:
        if loc is None:
            return ""
        file, line = loc
        href = os.path.relpath(self.targets / file, self.out_dir).replace(os.sep, "/")
        return f'<a href="{html.escape(href)}">{html.escape(Path(file).name)}:{line}</a>'


def esc(x) -> str:
    return html.escape(str(x))


def score_class(v: float) -> str:
    return "ok" if v >= 0.99995 else "warn" if v >= 0.9 else "bad"


def quality(sub: dict, gold_path: Path, record_path: Path) -> list[dict]:
    """IoU сценариев, для которых есть эталон: S0 — эталон организаторов, остальные — рекорд платформы 1.0."""
    refs: dict[str, tuple[str, dict]] = {}
    if record_path.is_file():
        for sid, block in load(record_path)["scenarios"].items():
            refs[sid] = ("рекорд платформы 1.0", edge_sets(block))
    if gold_path.is_file():
        for sid, block in load(gold_path)["scenarios"].items():
            refs[sid] = ("эталон организаторов", gold_sets(block))
    rows = []
    for sid in sorted(sub["scenarios"]):
        if sid not in refs:
            continue
        src, ref = refs[sid]
        got = edge_sets(sub["scenarios"][sid])
        per = {k: iou(got[k], ref[k]) for k in KINDS}
        rows.append({"sid": sid, "src": src, "per": per, "score": sum(per.values()) / len(KINDS),
                     "diff": {k: (len(got[k] - ref[k]), len(ref[k] - got[k])) for k in KINDS}})
    return rows


def m1_accuracy(steps: dict, labels: dict) -> list[dict]:
    """Обработчик M1 против ручной разметки: верно — `handler`, при `status: disputed` ещё и `alt`."""
    rows = []
    for sid, reqs in sorted(steps.items()):
        marked = {s["n"]: s for s in labels.get(sid, [])}
        for r in reqs:
            lab = marked.get(r["step"])
            if lab is None:
                continue
            ok = {lab["handler"]} | (set(lab.get("alt", [])) if lab.get("status") == "disputed" else set())
            rows.append({"sid": sid, "n": r["step"], "action": r["action"], "got": r["handler"],
                         "want": lab["handler"], "hit": r["handler"] in ok})
    return rows


def llm_seconds(keys: list[str], cache: Path) -> tuple[float, int]:
    """Сумма времени ответов модели по записям кеша и число найденных записей."""
    total, found = 0.0, 0
    for k in keys:
        p = cache / f"{k.removeprefix('sha256:')}.json"
        if p.is_file():
            total += float(load(p).get("seconds") or 0)
            found += 1
    return total, found


CSS = """
:root { --bg:#fff; --fg:#1f2328; --muted:#59636e; --line:#d1d9e0; --card:#f6f8fa;
        --ok:#1a7f37; --warn:#9a6700; --bad:#cf222e; --link:#0969da; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --line:#3d444d; --card:#151b23;
          --ok:#3fb950; --warn:#d29922; --bad:#f85149; --link:#4493f8; } }
body { background:var(--bg); color:var(--fg); font:14px/1.5 system-ui, sans-serif; margin:2rem auto; max-width:1200px;
       padding:0 1rem; }
h1 { font-size:1.6rem; margin-bottom:.2rem; } h2 { margin-top:2rem; border-bottom:1px solid var(--line); }
.muted { color:var(--muted); } a { color:var(--link); }
table { border-collapse:collapse; width:100%; margin:.5rem 0 1rem; }
th, td { border:1px solid var(--line); padding:.3rem .5rem; text-align:left; vertical-align:top; }
th { background:var(--card); } td.num { text-align:right; font-variant-numeric:tabular-nums; }
.ok { color:var(--ok); font-weight:600; } .warn { color:var(--warn); font-weight:600; }
.bad { color:var(--bad); font-weight:600; }
.tiles { display:flex; flex-wrap:wrap; gap:.75rem; margin:1rem 0; }
.tile { background:var(--card); border:1px solid var(--line); border-radius:6px; padding:.6rem .9rem; min-width:150px; }
.tile b { display:block; font-size:1.3rem; font-variant-numeric:tabular-nums; }
details { border:1px solid var(--line); border-radius:6px; margin:.4rem 0; padding:.3rem .7rem; }
summary { cursor:pointer; font-weight:600; } code { font-size:12.5px; }
.kind { display:inline-block; min-width:4.5rem; color:var(--muted); }
"""


def render(run: Path, args: argparse.Namespace) -> str:
    sub = load(run / "submission.json")
    decisions = load(run / "decisions.json")["scenarios"] if (run / "decisions.json").is_file() else {}
    steps = load(run / "step_requests.json") if (run / "step_requests.json").is_file() else {}
    m1 = load(run / "m1_report.json") if (run / "m1_report.json").is_file() else None
    usage = load(run / "resources.json") if (run / "resources.json").is_file() else None
    code = CodeIndex(load(args.skeleton), args.targets, args.out.parent)
    labels = load(args.labels)["scenarios"] if args.labels.is_file() else {}

    digest = sha256(run / "submission.json")
    kinds = Counter(e["relation"] for b in sub["scenarios"].values() for e in b.get("edges", []))
    q = quality(sub, args.gold, args.record)
    acc = m1_accuracy(steps, labels)
    n_steps = sum(len(v) for v in steps.values())

    out = [f"<!doctype html><html lang=ru><meta charset=utf-8><title>Archonity — отчёт прогона</title><style>{CSS}</style>",
           "<h1>Archonity — отчёт прогона</h1>",
           f"<p class=muted>Папка прогона: <code>{esc(run.resolve().relative_to(ROOT) if run.resolve().is_relative_to(ROOT) else run)}</code>. Проект: {esc(sub.get('project'))}. "
           "Отчёт читает файлы прогона и выдачу не меняет.</p>"]

    # Сводка
    tiles = [("Сценариев", len(sub["scenarios"])), ("Шагов", n_steps)]
    tiles += [(k, kinds.get(k, 0)) for k in KINDS]
    if q:
        tiles.append(("IoU (сценарии с эталоном)", f"{sum(r['score'] for r in q) / len(q):.5f}"))
    if acc:
        tiles.append(("M1 на своих сценариях", f"{sum(r['hit'] for r in acc)}/{len(acc)}"))
    if usage:
        total = (usage.get("run_final") or {}).get("total_seconds", usage["total_seconds"])
        tiles.append(("Время прогона, с", f"{total:.0f}" if total >= 10 else f"{total:.1f}"))
    out.append("<div class=tiles>" + "".join(f"<div class=tile><span class=muted>{esc(a)}</span><b>{esc(b)}</b></div>"
                                             for a, b in tiles) + "</div>")
    out.append("<h2>Сводка</h2><table>")
    same = (" — <span class=ok>выдача рекорда 1.00000 (S0–S7), байт в байт</span>" if digest == RECORD_SHA256
            else " — <span class=muted>не выдача рекорда: другой набор сценариев или правка</span>")
    out.append(f"<tr><th>sha256 submission.json</th><td><code>{digest}</code>{same}</td></tr>")
    if m1:
        llm = m1["llm"]
        keys = m1.get("llm_keys", [])
        secs, found = llm_seconds(keys, args.llm_cache)
        partial = f", найдено записей {found} из {len(keys)}" if found < len(keys) else ""
        mode = "ok" if m1["mode"] == "full" else "bad"
        out.append(f"<tr><th>M1</th><td>режим <span class={mode}>{esc(m1['mode'])}</span>; шагов {m1['steps']}, "
                   f"выбрано моделью {m1['steps_by_llm']}, первым кандидатом поиска {m1['steps_by_retrieval']}</td></tr>")
        out.append(f"<tr><th>Ответы LLM</th><td>из кеша {llm['from_cache']}, от сервера {llm['from_server']}, "
                   f"без ответа {llm['missing']}, ошибок {llm['errors']}; время ответов модели по записям кеша "
                   f"{secs:.0f} с (на той видеокарте, где записаны{partial})</td></tr>")
        fails = m1.get("failures") or []
        cls = "ok" if not fails else "bad"
        out.append(f"<tr><th>Сбои (Р2)</th><td><span class={cls}>{len(fails)}</span>"
                   + "".join(f"<br><code>{esc(f.get('scenario'))}.{esc(f.get('step'))} {esc(f['stage'])}: "
                             f"{esc(f['error'])}</code>" for f in fails) + "</td></tr>")
    out.append("</table>")
    if usage:
        out.append(resources_section(usage))

    # Паритет с другим прогоном
    if args.compare:
        out.append(f"<h2>Паритет с прогоном <code>{esc(args.compare)}</code></h2><table><tr><th>Файл</th><th>Итог</th></tr>")
        for name in COMPARED:
            a, b = run / name, args.compare / name
            if a.is_file() and b.is_file():
                eq = a.read_bytes() == b.read_bytes()
                out.append(f"<tr><td>{name}</td><td class={'ok' if eq else 'bad'}>"
                           f"{'байт в байт' if eq else 'отличается'}</td></tr>")
        out.append("</table>")

    # Качество
    if q:
        out.append("<h2>Качество</h2><p class=muted>IoU = |P∩G| / |P∪G| по каждому виду рёбер, балл сценария — "
                   "среднее по четырём видам (формула evaluate_golden.py). Рекорд платформы — посылка с баллом "
                   "1.00000, его множества совпадают с эталоном. «+/−» — лишние и пропущенные рёбра.</p>")
        out.append("<table><tr><th>Сценарий</th><th>Эталон</th>" + "".join(f"<th>{k}</th>" for k in KINDS)
                   + "<th>Балл</th></tr>")
        for r in q:
            cells = "".join(f"<td class=num><span class={score_class(r['per'][k])}>{r['per'][k]:.4f}</span>"
                            f" <span class=muted>+{r['diff'][k][0]}/−{r['diff'][k][1]}</span></td>" for k in KINDS)
            out.append(f"<tr><td>{r['sid']}</td><td>{esc(r['src'])}</td>{cells}"
                       f"<td class=num><span class={score_class(r['score'])}>{r['score']:.5f}</span></td></tr>")
        out.append("</table>")

    # M1 на своих сценариях
    if acc:
        miss = [r for r in acc if not r["hit"]]
        out.append(f"<h2>M1 на своих сценариях</h2><p>Верный обработчик в {len(acc) - len(miss)} шагах из {len(acc)} "
                   f"(ручная разметка <code>{esc(args.labels.relative_to(ROOT) if args.labels.is_relative_to(ROOT) else args.labels)}</code>, "
                   "сценарии на обработчики вне S1–S7).</p>")
        if miss:
            out.append("<table><tr><th>Шаг</th><th>Текст</th><th>Выбрал M1</th><th>По разметке</th></tr>")
            out += [f"<tr><td>{r['sid']}.{r['n']}</td><td>{esc(r['action'])}</td><td><code>{esc(short(r['got']))}</code>"
                    f"</td><td><code>{esc(short(r['want']))}</code></td></tr>" for r in miss]
            out.append("</table>")

    # По сценариям и шагам
    out.append("<h2>Сценарии по шагам</h2><p class=muted>Для каждого шага: обработчик, который выбрал M1, голоса "
               "модели, параметры из текста и рёбра, которые дал этот шаг, с правилом (decisions.json) и местом "
               "в коде по скелету. Рёбра без шага добавило правило R19 после шагов.</p>")
    for sid in sorted(sub["scenarios"]):
        by_step: dict = defaultdict(list)
        for key, rec in decisions.get(sid, {}).items():
            if not rec["included"]:
                continue
            kind, src, tgt = key.split("|", 2)
            for st in rec["steps"] or [None]:
                by_step[st].append((kind, src, tgt, rec["rule"], rec["source_type"]))
        n_edges = len(sub["scenarios"][sid].get("edges", []))
        qrow = next((r for r in q if r["sid"] == sid), None)
        badge = f" — IoU <span class={score_class(qrow['score'])}>{qrow['score']:.5f}</span>" if qrow else ""
        out.append(f"<details><summary>{esc(sid)}: шагов {len(steps.get(sid, []))}, рёбер {n_edges}{badge}</summary>")
        for r in steps.get(sid, []):
            g = r.get("grounding") or {}
            votes = ", ".join(f"{k}: {v}" for k, v in (g.get("votes") or {}).items())
            params = ", ".join(f"{k}={v}" for k, v in (r.get("params") or {}).items())
            out.append(f"<details><summary>Шаг {r['step']}. {esc(r['action'])}</summary><table>"
                       f"<tr><th>Обработчик</th><td><code>{esc(short(r['handler']))}</code> "
                       f"{code.link(code.where('executes', '', r['handler']))}"
                       + (f" <span class=muted>{esc(r['http']['method'])} {esc(r['http']['path'])}</span>"
                          if r.get("http") else "") + "</td></tr>"
                       f"<tr><th>Выбор M1</th><td>{esc(g.get('source', ''))}"
                       + (f"; голоса {esc(votes)}" if votes else "")
                       + (f"; ранг BM25 {g['ranks'].get('bm25')}, векторов {g['ranks'].get('dense')}" if g.get("ranks") else "")
                       + "</td></tr>"
                       + (f"<tr><th>Почему</th><td>{esc(g['reasoning'])}</td></tr>" if g.get("reasoning") else "")
                       + f"<tr><th>Параметры</th><td>{esc(params) or '—'}; ожидаемый исход "
                       f"{esc(r.get('expected_outcome'))}</td></tr></table>")
            out.append(edge_table(by_step.get(r["step"], []), code))
            out.append("</details>")
        if by_step.get(None):
            out.append("<details><summary>После шагов (R19)</summary>" + edge_table(by_step[None], code) + "</details>")
        out.append("</details>")
    out.append("</html>")
    return "\n".join(out)


def resources_section(u: dict) -> str:
    """Ресурсы прогона из resources.json (engine/resources.py): при равном балле организаторы сравнивают их."""
    rows = [f"<tr><td>{esc(s['stage'])}</td><td class=num>{s['seconds']:.1f}</td></tr>" for s in u["stages"]]
    rows.append(f"<tr><th>run_eval.py всего</th><th class=num>{u['total_seconds']:.1f}</th></tr>")
    script = u.get("run_final")
    if script:
        rows += [f"<tr><td>run_final.sh: модели (докачка, sha256)</td><td class=num>{script['models_seconds']}</td></tr>",
                 f"<tr><td>run_final.sh: сборка Rust</td><td class=num>{script['rust_build_seconds']}</td></tr>",
                 f"<tr><th>run_final.sh всего</th><th class=num>{script['total_seconds']}</th></tr>"]
    mem, gpu, llm = u["memory"], u["gpu"], u.get("llm")
    info = []
    if mem.get("peak_rss_tree_mib") is not None:
        info.append(f"<tr><th>Пик памяти</th><td>{mem['peak_rss_tree_mib']} МиБ — процесс с дочерними (Rust, llama-server)</td></tr>")
    else:
        info.append(f"<tr><th>Пик памяти</th><td>Python {mem.get('peak_rss_self_mib')} МиБ, дочерние процессы "
                    f"{mem.get('peak_rss_child_mib')} МиБ</td></tr>")
    if gpu.get("devices"):
        devs = "<br>".join(f"GPU {d['index']}: пик {d['peak_mib']} из {d['total_mib']} МиБ, до старта {d['baseline_mib']}"
                           for d in gpu["devices"])
        info.append(f"<tr><th>Видеопамять</th><td>наши процессы: пик {gpu['peak_ours_mib']} МиБ<br>{devs}</td></tr>")
    else:
        info.append("<tr><th>Видеопамять</th><td>не использовалась (нет nvidia-smi)</td></tr>")
    if llm:
        info.append(f"<tr><th>LLM</th><td>из кеша {llm['from_cache']}, вызовов сервера {llm['server_calls']} за "
                    f"{llm['server_seconds']:.1f} с, токенов {llm['prompt_tokens']} + {llm['completion_tokens']}, "
                    f"подъём сервера {llm['server_start_seconds']:.0f} с</td></tr>")
    return ("<h2>Ресурсы</h2><p class=muted>Замер прогона (engine/resources.py): время этапов, пик памяти, пик "
            "видеопамяти по nvidia-smi, вызовы LLM. При равном балле организаторы сравнивают ресурсы.</p>"
            "<table><tr><th>Этап</th><th>Секунды</th></tr>" + "".join(rows) + "</table><table>" + "".join(info)
            + "</table>")


def edge_table(edges: list, code: CodeIndex) -> str:
    if not edges:
        return "<p class=muted>Рёбер нет.</p>"
    rows = []
    for kind, src, tgt, rule, stype in sorted(edges, key=lambda e: (KINDS.index(e[0]), e[1], e[2])):
        ends = esc(short(tgt)) if kind == "executes" else f"{esc(short(src))} → {esc(short(tgt))}"
        rows.append(f"<tr><td><span class=kind>{kind}</span></td><td><code>{ends}</code></td>"
                    f"<td><code>{esc(rule if len(rule) < 80 else rule[:77] + '…')}</code> "
                    f"<span class=muted>{esc(stype)}</span></td><td>{code.link(code.where(kind, src, tgt))}</td></tr>")
    return "<table><tr><th>Вид</th><th>Ребро</th><th>Правило</th><th>Код</th></tr>" + "".join(rows) + "</table>"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run", type=Path, help="папка прогона: submission.json и файлы рядом с ним")
    ap.add_argument("-o", "--out", type=Path, help="куда писать (по умолчанию <run>/report.html)")
    ap.add_argument("--compare", type=Path, help="другой прогон тех же сценариев: сверка файлов байт в байт")
    ap.add_argument("--gold", type=Path, default=TASK / "gold" / "S0.json", help="эталон организаторов")
    ap.add_argument("--record", type=Path, default=ROOT / "eval" / "records" / "submission_p27_1.00000.json",
                    help="рекорд платформы 1.0 (S0–S7)")
    ap.add_argument("--labels", type=Path, default=ROOT / "eval" / "own" / "steps.json",
                    help="ручная разметка обработчиков своих сценариев")
    ap.add_argument("--llm-cache", type=Path, default=ROOT / "cache" / "llm", help="кеш ответов LLM прогона")
    ap.add_argument("--skeleton", type=Path, default=TASK / "skeleton" / "trainticket.json.gz")
    ap.add_argument("--targets", type=Path, default=TASK / "targets" / "trainticket", help="исходники для ссылок")
    args = ap.parse_args(argv)
    args.out = args.out or args.run / "report.html"
    return args


def main(argv: list[str] | None = None) -> Path:
    args = parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(args.run, args), encoding="utf-8", newline="\n")
    print(f"Отчёт: {args.out}")
    return args.out


if __name__ == "__main__":
    main(sys.argv[1:])
