import json
import subprocess
import sys
import zipfile
from pathlib import Path

from pack_submission import pack, ZIP_OUT, SUBMISSION_JSON, EVIDENCE_JSON

ROOT = Path(__file__).resolve().parent.parent


def test_pack_submission_creates_valid_archive():
    # Убеждаемся, что исходные файлы есть
    assert SUBMISSION_JSON.is_file(), "submission.json должен существовать"
    assert EVIDENCE_JSON.is_file(), "evidence.json должен существовать"

    out_zip = pack()
    assert out_zip == ZIP_OUT
    assert out_zip.is_file()

    with zipfile.ZipFile(out_zip, "r") as zf:
        names = set(zf.namelist())

        # 1. Корневые обязательные файлы
        assert "submission.json" in names
        assert "evidence.json" in names

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
            [sys.executable, str(eval_script), str(gold_file), str(SUBMISSION_JSON), "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        eval_res = json.loads(res.stdout)
        assert eval_res.get("score") == 1.0, f"S0 score должен быть 1.0, получен {eval_res.get('score')}"
