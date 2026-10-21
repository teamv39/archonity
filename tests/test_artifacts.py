"""Привязка артефактов к проекту (аудит универсальности, раздел 12): кеш каталога UI пересобирается при чужом
отпечатке, IR и `entity_ir.json` чужого проекта останавливают конвейер понятной ошибкой с командой archparse.

Игрушечный проект `toyshop`: один обработчик `GET /api/ping`, UI из двух файлов, IR и entity_ir во временных папках.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from engine import attention
from engine.adapters.skeleton import SkeletonIndex
from engine.artifacts import DEFAULT_ARTIFACTS_DIR, STALE_SHARE_LIMIT, ArtifactMismatch, check_artifacts
from engine.entities import EntityFacts
from engine.grounding.ui_catalog import build_catalog, catalog_fingerprint, find_ui_dir
from engine.pipeline import ArchonityPipeline

ROOT = Path(__file__).resolve().parent.parent
TT = ROOT / "hackaton" / "tt-challenge"

CONTROLLER = "type:toy-api:shop.PingController"
PING = "method:toy-api:shop.PingController#ping()"
TOY_SKELETON: dict[str, Any] = {
    "project": "toyshop",
    "commit": "c0ffee",
    "nodes": {
        "module:toy-api": {"kind": "module", "name": "toy-api", "path": "toy-api", "deployment_units": ["toy-api"]},
        CONTROLLER: {"kind": "type", "fqn": "shop.PingController", "type_kind": "class", "module": "toy-api",
                     "annotations": [{"name": "RestController", "args": ""},
                                     {"name": "RequestMapping", "args": '("/api")'}]},
        PING: {"kind": "method", "owner": CONTROLLER, "name": "ping", "module": "toy-api",
               "annotations": [{"name": "GetMapping", "args": '("/ping")'}]},
    },
    "edges": [],
}
TOY_HTML = '<html><head><title>Toy</title></head><body><button onclick="ping()">Ping</button>' \
           '<script src="app.js"></script></body></html>'
TOY_JS = 'function ping() { $.ajax({type: "get", url: "/api/ping"}); }\n'
EMPTY_ENTITY_IR = {"schema": "entity_ir/2", "entities": [], "repository_calls": []}


def _toy_skeleton(**patch: Any) -> dict[str, Any]:
    return {**copy.deepcopy(TOY_SKELETON), **patch}


def _toy_index(sk: dict[str, Any] | None = None) -> SkeletonIndex:
    return SkeletonIndex(sk or _toy_skeleton(), entity_facts=EntityFacts())


@pytest.fixture
def toy_targets(tmp_path: Path) -> Path:
    ui = tmp_path / "targets" / "toy-ui"
    ui.mkdir(parents=True)
    (ui / "index.html").write_text(TOY_HTML, encoding="utf-8")
    (ui / "app.js").write_text(TOY_JS, encoding="utf-8", newline="\n")
    return tmp_path / "targets"


def _foreign_cache(path: Path, project: str | None = "other") -> None:
    """Кеш каталога другого проекта: один запрос, которого в игрушечном проекте нет."""
    bogus = {"id": "x.js:1", "file": "x.js", "line": 1, "function": "f", "verb": "GET", "url": "/foreign", "handlers": []}
    d: dict[str, Any] = {"requests": [bogus], "unresolved": [], "pages_title": {}}
    if project is not None:
        d["fingerprint"] = {"project": project, "commit": "abc", "ui_dir": "ui", "handlers": "0", "ui_files": "0"}
    path.write_text(json.dumps(d), encoding="utf-8")


def _urls(cat: Any) -> list[str]:
    return [r.url for r in cat.requests]


class TestCatalogFingerprint:
    def test_foreign_cache_is_rebuilt_and_not_overwritten(self, toy_targets: Path, tmp_path: Path, caplog) -> None:
        cache = tmp_path / "ui_catalog.json"
        _foreign_cache(cache)
        before = cache.read_bytes()
        with caplog.at_level(logging.WARNING, logger="engine.grounding.ui_catalog"):
            cat = build_catalog(toy_targets, _toy_index(), cache_path=cache)
        assert _urls(cat) == ["/api/ping"] and cat.requests[0].handlers == [PING]
        assert cache.read_bytes() == before, "кеш другого проекта затёрт"
        assert "чужой кеш не перезаписан" in caplog.text

    def test_force_rebuild_replaces_foreign_cache(self, toy_targets: Path, tmp_path: Path) -> None:
        cache = tmp_path / "ui_catalog.json"
        _foreign_cache(cache)
        build_catalog(toy_targets, _toy_index(), cache_path=cache, force_rebuild=True)
        saved = json.loads(cache.read_text(encoding="utf-8"))
        assert saved["fingerprint"]["project"] == "toyshop"
        assert [r["url"] for r in saved["requests"]] == ["/api/ping"]

    def test_cache_without_fingerprint_is_rebuilt(self, toy_targets: Path, tmp_path: Path) -> None:
        cache = tmp_path / "ui_catalog.json"
        _foreign_cache(cache, project=None)
        cat = build_catalog(toy_targets, _toy_index(), cache_path=cache)
        assert _urls(cat) == ["/api/ping"]
        assert json.loads(cache.read_text(encoding="utf-8"))["fingerprint"]["commit"] == "c0ffee"

    def test_matching_cache_is_used(self, toy_targets: Path, tmp_path: Path) -> None:
        cache = tmp_path / "ui_catalog.json"
        build_catalog(toy_targets, _toy_index(), cache_path=cache)
        saved = json.loads(cache.read_text(encoding="utf-8"))
        saved["pages_title"] = {"marker": "из кеша"}
        cache.write_text(json.dumps(saved), encoding="utf-8")
        assert build_catalog(toy_targets, _toy_index(), cache_path=cache).pages_title == {"marker": "из кеша"}

    def test_same_project_stale_cache_is_rewritten(self, toy_targets: Path, tmp_path: Path) -> None:
        cache = tmp_path / "ui_catalog.json"
        build_catalog(toy_targets, _toy_index(), cache_path=cache)
        old = json.loads(cache.read_text(encoding="utf-8"))["fingerprint"]
        # UI изменился
        (toy_targets / "toy-ui" / "app.js").write_text(TOY_JS.replace("/api/ping", "/api/pong"), encoding="utf-8")
        cat = build_catalog(toy_targets, _toy_index(), cache_path=cache)
        new = json.loads(cache.read_text(encoding="utf-8"))["fingerprint"]
        assert new["ui_files"] != old["ui_files"] and new["project"] == old["project"]
        assert _urls(cat) == [] and [u["url"] for u in cat.unresolved] == ["/api/pong"]
        # коммит скелета изменился
        build_catalog(toy_targets, _toy_index(_toy_skeleton(commit="deadbeef")), cache_path=cache)
        assert json.loads(cache.read_text(encoding="utf-8"))["fingerprint"]["commit"] == "deadbeef"

    def test_fingerprint_ignores_line_endings_and_location(self, toy_targets: Path, tmp_path: Path) -> None:
        ix = _toy_index()
        ref = catalog_fingerprint(toy_targets, ix, "toy-ui")
        other = tmp_path / "copy" / "root"
        (other / "toy-ui").mkdir(parents=True)
        (other / "toy-ui" / "index.html").write_bytes(TOY_HTML.encode("utf-8"))
        (other / "toy-ui" / "app.js").write_bytes(TOY_JS.replace("\n", "\r\n").encode("utf-8"))
        assert catalog_fingerprint(other, ix, "toy-ui") == ref

    def test_committed_trainticket_cache_matches_its_inputs(self) -> None:
        """Закоммиченный `data/ui_catalog.json` собран по текущим скелету и UI пакета (иначе каждый прогон
        пересобирает его заново)."""
        sk = TT / "skeleton" / "trainticket.json.gz"
        targets = TT / "targets" / "trainticket"
        ix = SkeletonIndex(sk)
        saved = json.loads((ROOT / "data" / "ui_catalog.json").read_text(encoding="utf-8"))
        assert saved["fingerprint"] == catalog_fingerprint(targets, ix, find_ui_dir(targets, ix))


@pytest.fixture
def toy_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    """IR и entity_ir.json, построенные по игрушечному скелету."""
    ir = tmp_path / "ir"
    ir.mkdir()
    (ir / "toy-api.json").write_text(
        json.dumps({"schema": "method_ir/1", "module": "toy-api", "methods": {PING: {"body": []}}}), encoding="utf-8")
    ent = tmp_path / "entity_ir.json"
    ent.write_text(json.dumps(EMPTY_ENTITY_IR), encoding="utf-8")
    return ir, ent


def _check(ix: SkeletonIndex, ir: Path, tmp_path: Path, artifacts: Path | None = None) -> None:
    """`artifacts` по умолчанию — своя папка прогона (не `data/`): команды пересборки только для несошедшегося."""
    check_artifacts(ix, ir, tmp_path / "toy.json", tmp_path / "targets", artifacts or tmp_path / "artifacts")


class TestCheckArtifacts:
    def test_matching_artifacts_pass(self, toy_artifacts, tmp_path: Path) -> None:
        ir, ent = toy_artifacts
        _check(SkeletonIndex(_toy_skeleton(), entity_ir_path=ent), ir, tmp_path)

    def test_trainticket_artifacts_match_its_skeleton(self, shared_skeleton_index) -> None:
        check_artifacts(shared_skeleton_index, ROOT / "data" / "ir", TT / "skeleton" / "trainticket.json.gz",
                        TT / "targets" / "trainticket")

    def test_foreign_ir_is_an_error_with_rebuild_command(self, toy_artifacts, tmp_path: Path) -> None:
        _, ent = toy_artifacts
        with pytest.raises(ArtifactMismatch) as e:
            _check(SkeletonIndex(_toy_skeleton(), entity_ir_path=ent), ROOT / "data" / "ir", tmp_path)
        msg = str(e.value)
        assert "1196 из 1196 (100%)" in msg and "проект toyshop, коммит c0ffee" in msg
        assert "--mode bodies --targets-dir" in msg and "--skeleton" in msg and "environment_guide.md" in msg
        assert "--mode entities" not in msg, "entity_ir в порядке, пересборка не нужна"
        assert "--artifacts-dir" not in msg, "папка артефактов уже своя"

    def test_default_artifacts_dir_suggests_separate_project_folder(self, toy_artifacts, tmp_path: Path) -> None:
        _, ent = toy_artifacts
        with pytest.raises(ArtifactMismatch) as e:
            _check(SkeletonIndex(_toy_skeleton(), entity_ir_path=ent), ROOT / "data" / "ir", tmp_path,
                   DEFAULT_ARTIFACTS_DIR)
        msg = str(e.value)
        assert "--mode bodies" in msg and "--mode entities" in msg, "в новую папку нужны оба артефакта"
        assert "artifacts/toyshop/ir" in msg and "artifacts/toyshop/entity_ir.json" in msg
        assert "--artifacts-dir artifacts/toyshop" in msg and "-o ../data/ir" in msg

    def test_missing_ir_dir_is_an_error(self, toy_artifacts, tmp_path: Path) -> None:
        _, ent = toy_artifacts
        with pytest.raises(ArtifactMismatch, match="нет ни одного"):
            _check(SkeletonIndex(_toy_skeleton(), entity_ir_path=ent), tmp_path / "no_ir", tmp_path)

    def test_foreign_entity_ir_is_an_error(self, toy_artifacts, tmp_path: Path) -> None:
        ir, _ = toy_artifacts
        # entity_ir.json по умолчанию (data/entity_ir.json) построен по другому проекту
        with pytest.raises(ArtifactMismatch) as e:
            _check(SkeletonIndex(_toy_skeleton()), ir, tmp_path)
        msg = str(e.value)
        assert "вызовы репозиториев" in msg and "без call_site в скелете" in msg and "сущности" in msg
        assert "--mode entities" in msg and "--mode bodies" not in msg

    def test_unreadable_entity_ir_is_an_error(self, toy_artifacts, tmp_path: Path) -> None:
        ir, _ = toy_artifacts
        with pytest.raises(ArtifactMismatch, match="не загружен"):
            _check(SkeletonIndex(_toy_skeleton(), entity_ir_path=tmp_path / "absent.json"), ir, tmp_path)

    def test_small_stale_share_is_only_a_warning(self, toy_artifacts, tmp_path: Path, caplog) -> None:
        ir, ent = toy_artifacts
        n = 40
        sk = _toy_skeleton()
        ids = [f"method:toy-api:shop.PingController#m{i}()" for i in range(n)]
        for mid in ids:
            sk["nodes"][mid] = {"kind": "method", "owner": CONTROLLER, "name": "m", "module": "toy-api"}
        stale = {"method:toy-api:shop.Gone#old()": {"body": []}}
        (ir / "toy-api.json").write_text(
            json.dumps({"schema": "method_ir/1", "module": "toy-api", "methods": {**{i: {} for i in ids}, **stale}}),
            encoding="utf-8")
        assert 1 / (n + 1) < STALE_SHARE_LIMIT
        with caplog.at_level(logging.WARNING, logger="engine.artifacts"):
            _check(SkeletonIndex(sk, entity_ir_path=ent), ir, tmp_path)
        assert "1 из 41" in caplog.text
        # столько же чужих ID, но доля выше предела — ошибка
        (ir / "toy-api.json").write_text(
            json.dumps({"schema": "method_ir/1", "module": "toy-api", "methods": {**{i: {} for i in ids[:10]}, **stale}}),
            encoding="utf-8")
        with pytest.raises(ArtifactMismatch):
            _check(SkeletonIndex(sk, entity_ir_path=ent), ir, tmp_path)

    def test_unmatched_repository_calls_counted_by_bind(self, toy_artifacts, tmp_path: Path) -> None:
        _, ent = toy_artifacts
        ent.write_text(json.dumps({**EMPTY_ENTITY_IR, "repository_calls": [
            {"file": "X.java", "line": 1, "col": 1, "callee": "findAll", "repository": "R", "entity": "e.E"}]}),
            encoding="utf-8")
        facts = SkeletonIndex(_toy_skeleton(), entity_ir_path=ent).entities
        assert (facts.unmatched_calls, len(facts.raw_calls), facts.source, facts.load_error) == (1, 1, ent, None)


class TestPipelineStart:
    def _toy_files(self, tmp_path: Path) -> tuple[Path, Path]:
        skeleton = tmp_path / "skeleton" / "toy.json"
        skeleton.parent.mkdir()
        skeleton.write_text(json.dumps(_toy_skeleton()), encoding="utf-8")
        targets = tmp_path / "targets"
        targets.mkdir(exist_ok=True)
        return skeleton, targets

    def test_pipeline_refuses_foreign_artifacts_before_grounding(self, tmp_path: Path) -> None:
        skeleton, targets = self._toy_files(tmp_path)
        with pytest.raises(ArtifactMismatch) as e:
            ArchonityPipeline(skeleton, targets)  # IR и entity_ir по умолчанию — data/, построены по другому проекту
        assert "--mode bodies" in str(e.value) and "--mode entities" in str(e.value)

    def test_pipeline_takes_artifacts_from_their_dir(self, toy_artifacts, tmp_path: Path, monkeypatch) -> None:
        """IR, entity_ir и кеш каталога UI — из `artifacts_dir`, а не из `data/` (артефакты другого проекта)."""
        ir, ent = toy_artifacts
        art = tmp_path / "project_artifacts"
        art.mkdir()
        ir.rename(art / "ir")
        ent.rename(art / "entity_ir.json")
        skeleton, targets = self._toy_files(tmp_path)
        seen: dict[str, Any] = {}

        class StubGrounder:  # M1 на проекте без сущностей не строится (prompts.example_kinds): проверяем проводку
            def __init__(self, ix, root, **kw) -> None:
                seen.update(kw)

        monkeypatch.setattr("engine.pipeline.StepGrounder", StubGrounder)
        pipe = ArchonityPipeline(skeleton, targets, artifacts_dir=art)
        assert pipe.m4.it.ir.keys() == {PING} and pipe.index.entities.source == art / "entity_ir.json"
        assert seen["ir_dir"] == art / "ir" and seen["ui_cache"] == art / "ui_catalog.json"

    def test_copy_of_data_as_artifacts_dir_passes_the_check(self, shared_pipeline, tmp_path: Path, monkeypatch) -> None:
        """Копия `data/` в другой папке читается так же, как `data/`: та же сверка, тот же IR у M4."""
        shutil.copytree(ROOT / "data", tmp_path / "project")
        monkeypatch.setattr("engine.pipeline.StepGrounder", lambda *a, **kw: None)
        pipe = ArchonityPipeline(TT / "skeleton" / "trainticket.json.gz", TT / "targets" / "trainticket",
                                 artifacts_dir=tmp_path / "project")
        assert pipe.m4.it.ir.keys() == shared_pipeline.m4.it.ir.keys()
        assert pipe.index.entities.source == tmp_path / "project" / "entity_ir.json"

    def _run_eval(self, tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
        skeleton, targets = self._toy_files(tmp_path)
        return subprocess.run(
            [sys.executable, str(ROOT / "run_eval.py"), "--skeleton", str(skeleton), "--targets", str(targets),
             "--no-llm", "--no-embed", "--no-eval", "-o", str(tmp_path / "out" / "submission.json"), *extra],
            capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"})

    def _assert_frame_with_error(self, res: subprocess.CompletedProcess, out: Path) -> str:
        """Р2: выдача строится всегда (пустые блоки), код 0, ошибка с командой пересборки — в рамке последними
        строками и в ATTENTION.txt; без трассы и без повторной сборки в аварийном режиме."""
        assert res.returncode == 0, res.stderr[-2000:]
        scenarios = json.loads(out.read_text(encoding="utf-8"))["scenarios"]
        assert scenarios and all(block == {"edges": []} for block in scenarios.values())
        text = (out.parent / attention.FILE_NAME).read_text(encoding="utf-8")
        assert "ArtifactMismatch: Артефакты не соответствуют скелету" in text and "--mode bodies" in text
        for stream in (res.stdout, res.stderr):
            tail = stream.rstrip("\n").splitlines()
            assert tail[-1] == attention.RULE and "--mode bodies" in "\n".join(tail[-14:])
        assert "Traceback" not in res.stderr and res.stderr.count("Артефакты не соответствуют скелету") == 1
        return text

    def test_run_eval_gives_empty_answer_and_frame(self, tmp_path: Path) -> None:
        res = self._run_eval(tmp_path)
        text = self._assert_frame_with_error(res, tmp_path / "out" / "submission.json")
        assert "--artifacts-dir artifacts/toyshop" in text, "по умолчанию подсказывает отдельную папку"

    def test_run_eval_artifacts_dir_without_artifacts(self, tmp_path: Path) -> None:
        res = self._run_eval(tmp_path, "--artifacts-dir", str(tmp_path / "empty"))
        text = self._assert_frame_with_error(res, tmp_path / "out" / "submission.json")
        assert "Артефакты:  " + str(tmp_path / "empty") in res.stdout
        assert "нет ни одного" in text and "не загружен" in text and "--mode entities" in text
        assert "--artifacts-dir" not in text
