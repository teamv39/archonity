"""Р2 (roadmap): выдача строится всегда, сбой виден в рамке последней строкой и в ATTENTION.txt.

Сбои вызываются нарочно: исключение M4 на шаге, битый файл сценария, конвейер, который не собирается.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from engine import attention

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "hackaton" / "tt-challenge" / "scenarios"
GOLD = ROOT / "hackaton" / "tt-challenge" / "gold" / "S0.json"


def _edges(adapter, sid: str) -> set[tuple[str, str, str]]:
    return {(e["source"], e["relation"], e["target"]) for e in adapter.scenarios[sid]}


def test_step_failure_keeps_other_steps(shared_pipeline, monkeypatch, tmp_path: Path) -> None:
    """Исключение M4 на шаге 2 S0: шаг без рёбер, остальные шаги в ответе, сбой записан."""
    full = _edges(shared_pipeline.run_all([SCENARIOS / "S0.json"], tmp_path / "full.json"), "S0")

    run_step = shared_pipeline.m4.run_step

    def broken(req, *a, **kw):
        if req.step == 2:
            raise KeyError("tripId")
        return run_step(req, *a, **kw)

    monkeypatch.setattr(shared_pipeline, "failures", [])
    monkeypatch.setattr(shared_pipeline.m4, "run_step", broken)
    part = _edges(shared_pipeline.run_all([SCENARIOS / "S0.json"], tmp_path / "part.json"), "S0")

    assert [(f["scenario"], f["step"], f["stage"]) for f in shared_pipeline.failures] == [("S0", 2, "M4")]
    assert "KeyError" in shared_pipeline.failures[0]["error"]
    assert part and part < full


def test_scenario_failure_gives_empty_block(shared_pipeline, monkeypatch, tmp_path: Path) -> None:
    """Битый файл сценария: пустой блок под именем файла, другие сценарии на месте."""
    bad = tmp_path / "S9.json"
    bad.write_text("{не json", encoding="utf-8")
    out = tmp_path / "submission.json"
    monkeypatch.setattr(shared_pipeline, "failures", [])
    shared_pipeline.run_all([SCENARIOS / "S0.json", bad], out)

    sub = json.loads(out.read_text(encoding="utf-8"))
    assert sub["scenarios"]["S9"] == {"edges": []}
    assert sub["scenarios"]["S0"]["edges"]
    assert [(f["scenario"], f["step"], f["stage"]) for f in shared_pipeline.failures] == [("S9", None, "сценарий")]


def test_attention_lines_end_with_contacts_and_cut_long_list(tmp_path: Path) -> None:
    fails = [attention.failure(f"X{i}", 1, "M4", ValueError(i)) for i in range(attention.SHOWN + 2)]
    report = {"mode": "partial", "steps": 10, "steps_by_retrieval": 3, "llm_enabled": True}
    out = tmp_path / "submission.json"

    short = attention.lines(fails, report, out)
    assert short[0] == short[-1] == attention.RULE
    assert attention.CONTACTS in short[-3]
    assert any("режим partial" in x for x in short)
    assert any("ещё 2" in x for x in short)

    path = attention.write(fails, report, out)
    text = path.read_text(encoding="utf-8")
    assert all(f"X{i}.1" in text for i in range(len(fails)))
    assert "ещё" not in text

    attention.clear(out)
    assert not path.exists()


def test_no_attention_on_clean_full_run() -> None:
    assert not attention.needed([], {"mode": "full", "steps": 3, "steps_by_retrieval": 0})
    assert not attention.needed([], {"mode": "full", "steps": 3, "steps_by_retrieval": 0, "embedding_misses": 0})
    assert attention.needed([], None)


def test_attention_on_embedder_failure(tmp_path: Path) -> None:
    """Эмбеддер отказал (например, не хватило видеопамяти рядом с сервером LLM): режим full, но поиск только BM25."""
    report = {"mode": "full", "steps": 3, "steps_by_retrieval": 0, "embedding_misses": 2,
              "embedding_failure": "OutOfMemoryError: CUDA out of memory"}
    assert attention.needed([], report)
    text = "\n".join(attention.lines([], report, tmp_path / "submission.json"))
    assert "только BM25" in text and "OutOfMemoryError" in text


def test_broken_pipeline_writes_empty_submission_and_frame_last(tmp_path: Path) -> None:
    """Конвейер не собирается (нет скелета): пустые блоки, ATTENTION.txt, рамка — последние строки, код 0."""
    out = tmp_path / "out" / "submission.json"
    res = subprocess.run(
        [sys.executable, str(ROOT / "run_eval.py"), "--skeleton", str(tmp_path / "missing.json.gz"),
         "--scenarios", str(SCENARIOS / "S0.json"), str(SCENARIOS / "S1.json"),
         "--no-server", "--no-eval", "-o", str(out)],
        capture_output=True, text=True, encoding="utf-8", cwd=tmp_path, timeout=300)

    assert res.returncode == 0, res.stderr[-2000:]
    sub = json.loads(out.read_text(encoding="utf-8"))
    assert sub["scenarios"] == {"S0": {"edges": []}, "S1": {"edges": []}}
    assert sub["project"]
    assert (out.parent / attention.FILE_NAME).is_file()
    for stream in (res.stdout, res.stderr):
        tail = stream.rstrip("\n").splitlines()
        assert tail[-1] == attention.RULE
        assert attention.CONTACTS in "\n".join(tail[-4:])
        assert "аварийный submission.json" in "\n".join(tail[-12:])


@pytest.mark.skipif(not GOLD.is_file(), reason="нет эталона S0")
def test_evaluate_skips_scenarios_outside_gold(tmp_path: Path, capsys) -> None:
    sys.path.insert(0, str(ROOT))
    import run_eval

    out = tmp_path / "submission.json"
    out.write_text(json.dumps({"project": "p", "scenarios": {"X1": {"edges": []}}}), encoding="utf-8")
    run_eval.evaluate(argparse.Namespace(no_eval=False, gold=GOLD, out=out))
    printed = capsys.readouterr()
    assert "Локальная оценка пропущена: сценариев X1" in printed.out
    assert "Ошибка" not in printed.out + printed.err
