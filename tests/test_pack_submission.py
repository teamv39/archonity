import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from pack_submission import pack

ROOT = Path(__file__).resolve().parent.parent


def test_pack_submission_creates_valid_archive(tmp_path: Path):
    # Свой прогон из кеша во временную папку: тест не зависит от output/ и не трогает его
    run_dir = tmp_path / "run"
    res = subprocess.run([sys.executable, str(ROOT / "run_eval.py"), "--require-cache", "--no-eval",
                          "-o", str(run_dir / "submission.json")], cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "PYTHONUTF8": "1"})
    if res.returncode == 2:
        pytest.skip("нет кеша LLM")
    assert res.returncode == 0, res.stderr[-2000:]
    submission = run_dir / "submission.json"

    out_zip = pack(tmp_path / "submission.zip", run_dir=run_dir)
    assert out_zip.is_file()

    with zipfile.ZipFile(out_zip, "r") as zf:
        names = set(zf.namelist())

        # 1. Корневые обязательные файлы
        assert "submission.json" in names
        assert "evidence.json" in names
        assert "report.html" in names

        # 2. Исходный код пайплайна
        assert "code/" in names
        assert "code/engine/" in names
        assert "code/engine/executor/" in names
        assert "code/engine/adapters/" in names
        assert "code/engine/grounding/" in names
        assert "code/data/" in names
        assert "code/run_eval.py" in names

        # 2a. Команда запуска, зависимости, модели, данные прогона (docs/run_on_a100.md)
        for f in ("RUN.md", "code/requirements.txt", "code/uv.lock", "code/pyproject.toml", "code/models/manifest.json",
                  "code/facts/configs_topology.json", "code/data/entity_ir.json", "code/scripts/fetch_models.py",
                  "code/archparse/src/main/java/com/v39a/Main.java"):
            assert f in names, f"Нет {f} в архиве"
        # 2b. Исходники Rust-движка (надбавка ×1.10 за исходный код), без rust/target
        for f in ("code/rust/Cargo.toml", "code/rust/Cargo.lock", "code/rust/README.md",
                  "code/rust/crates/archonity-exec/tests/parity.rs",
                  "code/rust/crates/archonity-exec/tests/data/step_requests_raw.json",
                  "code/eval/records/submission_p27_1.00000.json"):
            assert f in names, f"Нет {f} в архиве"
        assert any(n.startswith("code/rust/crates/archonity-exec/") and n.endswith(".rs") for n in names)
        assert any(n.startswith("code/rust/crates/archonity-m4/") and n.endswith(".rs") for n in names)
        assert not any(n.startswith("code/rust/target") for n in names)
        assert any(n.startswith("code/data/ir/") and n.endswith(".json") for n in names)
        assert any(n.startswith("code/cache/llm/") and n.endswith(".json") for n in names)
        assert "code/cache/emb/qwen3-4b/vectors.npz" in names
        run_final = zf.getinfo("code/scripts/run_final.sh")
        assert (run_final.external_attr >> 16) & 0o111, "run_final.sh должен быть исполняемым"
        assert b"\r\n" not in zf.read("code/scripts/run_final.sh")
        assert not any(n.startswith(("code/hackaton/", "code/models/Qwen")) for n in names)

        # 3. Отсутствие артефактов и кэшей
        for name in names:
            assert "__pycache__" not in name, f"Мусорный кэш в архиве: {name}"
            assert not name.endswith(".pyc"), f"Скомпилированный файл в архиве: {name}"

        # 4. Проверка содержимого submission.json внутри архива
        sub_raw = zf.read("submission.json")
        assert b"\r\n" not in sub_raw, "submission.json должен иметь только Unix LF"
        sub_data = json.loads(sub_raw.decode("utf-8"))
        assert "scenarios" in sub_data
        for s in ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"):
            assert s in sub_data["scenarios"], f"Сценарий {s} отсутствует в submission.json"

    # 5. Оценка S0 через evaluate_golden.py
    eval_script = ROOT / "hackaton" / "tt-challenge" / "platform" / "evaluate_golden.py"
    gold_file = ROOT / "hackaton" / "tt-challenge" / "gold" / "S0.json"
    if eval_script.is_file() and gold_file.is_file():
        res = subprocess.run(
            [sys.executable, str(eval_script), str(gold_file), str(submission), "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        eval_res = json.loads(res.stdout)
        assert eval_res.get("score") == 1.0, f"S0 score должен быть 1.0, получен {eval_res.get('score')}"
