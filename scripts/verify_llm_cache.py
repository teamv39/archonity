#!/usr/bin/env python3
"""Проверка кеша ответов LLM (`cache/llm/`) без GPU: что ответы привязаны к промптам, которые строит код.

    python scripts/verify_llm_cache.py                      # целостность + прогон run_eval.py --require-cache
    python scripts/verify_llm_cache.py --run-dir output      # покрытие по готовому прогону (m1_report.json)
    python scripts/verify_llm_cache.py --recheck 10          # + 10 случайных ответов прогона заново у сервера LLM

1. Целостность (каждая запись): ключ, пересчитанный из записанных модели, версии промпта, сообщений, схемы и
   параметров выборки (`LLMClient.key`), совпадает с полем `key` и именем файла; ответ проходит JSON-схему запроса;
   ответ не оборван (`finish_reason` = stop). Ответ в ключ не входит: правка ответа руками ключ не ломает.
2. Покрытие: прогон с `--require-cache` пишет ключи всех запросов к LLM (`m1_report.json`, `llm_keys`). Каждый
   должен быть в кеше и пройти п. 1 — то есть промпты, которые строит текущий код, дословно те, на которые записаны
   ответы. Записи вне прогона (ответы старых версий промпта) показываются по группам.
3. Перепроверка (`--recheck N`, нужен сервер `ARCHONITY_LLM_URL`): N случайных записей прогона спрашиваются заново
   с теми же сообщениями, схемой и выборкой; ответ сравнивается с записанным. Кеш не меняется (ответы — во временную
   папку). На другом железе или другой сборке llama.cpp ответ модели может отличаться — это видно по доле совпадений.

Код выхода: 0 — всё сходится; 1 — записи с нарушенной целостностью; 2 — прогону не хватает записей.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.grounding.llm import CACHE_DIR, LLMClient  # noqa: E402

def check_entry(path: Path, client: LLMClient, validator: object | None) -> list[str]:
    """Нарушения целостности одной записи (пусто — запись цела)."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"не читается: {e}"]
    bad = []
    client.model = d.get("model") or client.model
    key = client.key(d.get("prompt_version", ""), d.get("messages") or [], d.get("schema") or {}, d.get("sampling"))
    if key != d.get("key"):
        bad.append("ключ не совпадает с пересчитанным из записи")
    if path.stem != key.split(":", 1)[1]:
        bad.append("имя файла не совпадает с ключом")
    if d.get("finish_reason") not in (None, "stop"):
        bad.append(f"ответ оборван: finish_reason={d.get('finish_reason')}")
    if validator is not None:
        try:
            validator(d.get("response"), d.get("schema") or {})
        except Exception as e:  # noqa: BLE001 — jsonschema.ValidationError и SchemaError
            bad.append(f"ответ не проходит схему: {str(e).splitlines()[0][:120]}")
    return bad


def run_keys(run_dir: Path | None) -> tuple[list[str], dict]:
    """Ключи запросов к LLM за прогон: из готового m1_report.json или прогона run_eval.py --require-cache."""
    if run_dir is None:
        run_dir = Path(tempfile.mkdtemp(prefix="verify_llm_cache_"))
        cmd = [sys.executable, str(ROOT / "run_eval.py"), "--require-cache", "--no-eval", "-o",
               str(run_dir / "submission.json")]
        print(f"прогон: {' '.join(cmd[1:])}")
        env = dict(os.environ, PYTHONUTF8="1")
        res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=env)
        if res.returncode not in (0, 2):
            print(res.stdout[-2000:], res.stderr[-2000:], sep="\n", file=sys.stderr)
            raise SystemExit(f"run_eval.py завершился с кодом {res.returncode}")
    report = json.loads((run_dir / "m1_report.json").read_text(encoding="utf-8"))
    return report.get("llm_keys") or [], report


def recheck(keys: list[str], n: int, seed: int) -> int:
    """N случайных записей прогона заново у сервера; ответы — во временную папку. → число расхождений."""
    with tempfile.TemporaryDirectory(prefix="verify_llm_recheck_") as tmp:
        client = LLMClient(refresh=True, cache_dir=Path(tmp))
        if not client.server_available():
            raise SystemExit("--recheck: сервер LLM недоступен (ARCHONITY_LLM_URL)")
        sample = random.Random(seed).sample(keys, min(n, len(keys)))
        diff = 0
        for k in sample:
            d = json.loads((CACHE_DIR / f"{k.split(':', 1)[1]}.json").read_text(encoding="utf-8"))
            client.model = d["model"]
            got, key = client.complete_json(d["kind"], d["prompt_version"], d["messages"], d["schema"],
                                            sampling=d.get("sampling"))
            same = got == d["response"]
            diff += not same
            print(f"  {k[7:19]}… {d['kind']:<7} {'совпал' if same else 'ДРУГОЙ ответ'}")
        print(f"перепроверка: совпало {len(sample) - diff} из {len(sample)}")
        return diff


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", type=Path, help="папка готового прогона с m1_report.json (иначе — новый прогон)")
    ap.add_argument("--recheck", type=int, default=0, metavar="N", help="перепроверить N ответов у сервера LLM")
    ap.add_argument("--seed", type=int, default=0, help="выбор записей для --recheck")
    args = ap.parse_args()

    try:
        from jsonschema import validate as validator
    except ImportError:
        validator = None
        print("jsonschema не установлен: ответы по схеме не проверяются (pip install jsonschema)")

    client = LLMClient(use_server=False)
    files = sorted(CACHE_DIR.glob("*.json"))
    broken: dict[str, list[str]] = {}
    groups: dict[str, set[str]] = collections.defaultdict(set)
    for p in files:
        bad = check_entry(p, client, validator)
        if bad:
            broken[p.stem] = bad
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            groups[f"{d.get('prompt_version')}/{d.get('kind')}"].add("sha256:" + p.stem)
        except (OSError, ValueError):
            pass
    print(f"1. целостность: записей {len(files)}, нарушений {len(broken)}")
    for stem, bad in sorted(broken.items())[:20]:
        print(f"   {stem[:16]}…: {'; '.join(bad)}")

    keys, report = run_keys(args.run_dir)
    have = {"sha256:" + p.stem for p in files}
    missing = [k for k in keys if k not in have]
    used_broken = [k for k in keys if k.split(":", 1)[1] in broken]
    print(f"2. покрытие: прогон (режим {report.get('mode')}) запросил {len(keys)} ответов LLM; "
          f"нет в кеше {len(missing)}, с нарушенной целостностью {len(used_broken)}")
    used = set(keys)
    for g, ks in sorted(groups.items()):
        n_used = len(ks & used)
        why = "" if n_used else " — не используется"
        print(f"   {g:<22} записей {len(ks):4}, в прогоне {n_used:4}{why}")

    diff = recheck(keys, args.recheck, args.seed) if args.recheck else 0
    if broken:
        sys.exit(1)
    if missing or used_broken:
        sys.exit(2)
    print("кеш сходится с кодом: каждый ответ прогона записан на промпт, который строит текущий код"
          + ("" if not args.recheck else f"; перепроверка: расхождений {diff}"))


if __name__ == "__main__":
    main()
