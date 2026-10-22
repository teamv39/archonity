"""Ресурсы прогона (engine/resources.py): этапы, память, LLM; run_eval.py пишет resources.json рядом с выдачей."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine import resources

ROOT = Path(__file__).resolve().parent.parent
S0 = ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S0.json"


def test_meter_stages_memory_and_llm(tmp_path: Path) -> None:
    meter = resources.Resources().start()
    with meter.stage("этап"):
        time.sleep(0.05)
    stats = SimpleNamespace(hits=3, calls=2, seconds=1.5, prompt_tokens=10, completion_tokens=4,
                            server_start_seconds=7.0, errors=0)
    data = meter.finish(SimpleNamespace(stats=stats), embedding_misses=1)

    assert [s["stage"] for s in data["stages"]] == ["этап"] and data["stages"][0]["seconds"] >= 0.05
    assert data["total_seconds"] >= data["stages"][0]["seconds"]
    mem = data["memory"]
    assert (mem["peak_rss_tree_mib"] or mem["peak_rss_self_mib"] or 0) > 0 or sys.platform == "win32"
    assert data["llm"]["server_calls"] == 2 and data["llm"]["server_start_seconds"] == 7.0
    text = "\n".join(resources.lines(data))
    assert "этап 0." in text and "подъём сервера 7 с" in text

    path = resources.write(data, tmp_path / "submission.json")
    assert json.loads(path.read_text(encoding="utf-8"))["embedding_misses"] == 1


def test_run_eval_writes_resources(tmp_path: Path) -> None:
    out = tmp_path / "run" / "submission.json"
    res = subprocess.run(
        [sys.executable, str(ROOT / "run_eval.py"), "--scenarios", str(S0), "--require-cache", "--no-eval",
         "-o", str(out)], capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=300)
    if res.returncode == 2:
        pytest.skip("нет кеша LLM")
    assert res.returncode == 0, res.stderr[-2000:]
    data = json.loads((out.parent / resources.FILE_NAME).read_text(encoding="utf-8"))
    assert {s["stage"] for s in data["stages"]} >= {"сборка конвейера", "M1 и исполнение Python"}
    assert data["llm"]["from_cache"] > 0 and data["llm"]["server_calls"] == 0
    assert "Ресурсы: всего" in res.stdout
