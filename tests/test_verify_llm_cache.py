"""scripts/verify_llm_cache.py: целостность записи кеша LLM — ключ, имя файла, схема ответа, обрыв."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from engine.grounding.llm import LLMClient

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("verify_llm_cache", ROOT / "scripts" / "verify_llm_cache.py")
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)

SCHEMA = {"type": "object", "properties": {"handler": {"type": "string"}}, "required": ["handler"]}
MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "step 1"}]


def _validator():
    jsonschema = pytest.importorskip("jsonschema")
    return jsonschema.validate


def _write(tmp: Path, client: LLMClient, **over) -> Path:
    key = client.key("m1-v8", MESSAGES, SCHEMA)
    d = {"key": key, "model": client.model, "prompt_version": "m1-v8", "kind": "select", "messages": MESSAGES,
         "schema": SCHEMA, "response": {"handler": "A"}, "finish_reason": "stop", **over}
    p = tmp / f"{key.split(':', 1)[1]}.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


class TestCheckEntry:
    def test_intact_entry(self, tmp_path: Path) -> None:
        c = LLMClient(use_server=False, cache_dir=tmp_path)
        assert verify.check_entry(_write(tmp_path, c), c, _validator()) == []

    def test_edited_prompt_breaks_key(self, tmp_path: Path) -> None:
        c = LLMClient(use_server=False, cache_dir=tmp_path)
        p = _write(tmp_path, c, messages=[{"role": "user", "content": "другой шаг"}])
        assert any("ключ" in b for b in verify.check_entry(p, c, _validator()))

    def test_renamed_file(self, tmp_path: Path) -> None:
        c = LLMClient(use_server=False, cache_dir=tmp_path)
        p = _write(tmp_path, c)
        q = p.rename(tmp_path / ("0" * 64 + ".json"))
        assert any("имя файла" in b for b in verify.check_entry(q, c, _validator()))

    def test_response_outside_schema_and_truncated(self, tmp_path: Path) -> None:
        c = LLMClient(use_server=False, cache_dir=tmp_path)
        p = _write(tmp_path, c, response={"handler": 7}, finish_reason="length")
        bad = verify.check_entry(p, c, _validator())
        assert any("схему" in b for b in bad) and any("оборван" in b for b in bad)


def test_client_records_requested_keys(tmp_path: Path) -> None:
    c = LLMClient(use_server=False, cache_dir=tmp_path)
    _write(tmp_path, c)
    got, key = c.complete_json("select", "m1-v8", MESSAGES, SCHEMA)
    miss, key2 = c.complete_json("select", "m1-v8", [{"role": "user", "content": "x"}], SCHEMA)
    assert got == {"handler": "A"} and miss is None and c.requested == [key, key2]
