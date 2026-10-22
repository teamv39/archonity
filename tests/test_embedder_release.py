"""Выгрузка эмбеддера: модель и `llama server` не бывают в памяти вместе (docs/run_on_a100.md, «Память»).

Настоящий `STEmbedder` с подставной моделью: проверяем, что модель выгружается после порции промахов, что
`StepGrounder.prepare` считает векторы всех сценариев одной пачкой и что ключи и тексты векторов не изменились.
"""
from __future__ import annotations

import hashlib
import weakref
from pathlib import Path

import numpy as np
import pytest

from engine.adapters.skeleton import SkeletonIndex, load_json
from engine.grounding import embedder as E
from engine.grounding.grounder import StepGrounder

ROOT = Path(__file__).resolve().parent.parent
TT = ROOT / "hackaton" / "tt-challenge"
TARGETS = TT / "targets" / "trainticket"
SCENARIOS = TT / "scenarios"
DIM = 8


class FakeModel:
    """Вместо SentenceTransformer: вектор текста зависит только от текста, как у настоящей модели."""

    def __init__(self, batches: list[list[str]] | None = None) -> None:
        self.batches = batches if batches is not None else []

    def encode(self, texts: list[str], **kw) -> np.ndarray:
        self.batches.append(list(texts))
        out = []
        for t in texts:
            seed = int.from_bytes(hashlib.sha256(t.encode("utf-8")).digest()[:4], "little")
            v = np.random.default_rng(seed).normal(size=DIM)
            out.append(v / np.linalg.norm(v))
        return np.stack(out)


def _embedder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, make=FakeModel, **kw) -> tuple[E.STEmbedder, list]:
    """Эмбеддер с настоящим кешем векторов; `make` создаёт модель на каждой загрузке, `loads` — слабые ссылки на них."""
    monkeypatch.setattr(E, "CACHE_DIR", tmp_path)
    emb = E.STEmbedder(E.EmbedSpec("test-release", "r/none", "{q}", "{text}"), **kw)
    loads: list = []

    def load():
        emb._model = make()
        loads.append(weakref.ref(emb._model))
        return emb._model

    monkeypatch.setattr(emb, "_load", load)
    return emb, loads


class TestRelease:
    def test_model_freed_after_batch_and_vectors_stay(self, monkeypatch, tmp_path) -> None:
        emb, loads = _embedder(monkeypatch, tmp_path)
        vecs = emb.embed_queries(["a", "b"])
        assert vecs.shape == (2, DIM) and emb._model is None and [r() for r in loads] == [None]
        assert emb.embed_queries(["b", "a"]).shape == (2, DIM) and len(loads) == 1  # из кеша, модель не нужна
        emb.embed_queries(["c"])
        assert len(loads) == 2 and loads[1]() is None  # новый промах — модель грузится заново и снова выгружается

    def test_model_freed_after_encode_error(self, monkeypatch, tmp_path) -> None:
        class Broken:
            def encode(self, *a, **kw):
                raise RuntimeError("CUDA out of memory")

        emb, loads = _embedder(monkeypatch, tmp_path, Broken)
        assert emb.embed_queries(["a"]) is None
        assert emb._model is None and loads[0]() is None and "out of memory" in emb._broken and emb.misses == 1

    def test_misses_counted_once_per_vector(self, monkeypatch, tmp_path) -> None:
        """prepare и begin просят один и тот же вектор: в отчёте M1 это один промах."""
        emb, loads = _embedder(monkeypatch, tmp_path, allow_model=False)
        assert emb.embed_queries(["a", "b"]) is None and emb.embed_queries(["a", "b"]) is None
        assert emb.misses == 2 and loads == []

    def test_release_without_torch_is_noop(self) -> None:
        emb = E.STEmbedder(E.EmbedSpec("test-noop", "r/none", "{q}", "{text}"))
        emb.release()
        assert emb._model is None


@pytest.fixture(scope="module")
def ix() -> SkeletonIndex:
    return SkeletonIndex(load_json(TT / "skeleton" / "trainticket.json.gz"))


def _grounder(ix: SkeletonIndex, emb: E.STEmbedder) -> StepGrounder:
    """M1 с настоящим кешем эмбеддера и векторами обработчиков из подставной модели."""
    g = StepGrounder(ix, TARGETS, embedder=None, llm=None)
    g.retriever.embedder = emb
    g.retriever.doc_vecs = FakeModel().encode([f"doc{i}" for i in range(len(g.retriever.ids))])
    return g


class TestPrepare:
    def test_one_batch_for_all_scenarios_then_cache(self, ix, monkeypatch, tmp_path) -> None:
        scenarios = [load_json(SCENARIOS / f"{s}.json") for s in ("S0", "S1", "S2")]
        batches: list[list[str]] = []
        emb, loads = _embedder(monkeypatch, tmp_path, lambda: FakeModel(batches))
        g = _grounder(ix, emb)
        g.prepare(scenarios)
        assert len(loads) == 1 and len(batches) == 1 and emb._model is None and loads[0]() is None
        batch = batches[0]
        steps = [s.get("action") or "" for sc in scenarios for s in sc["steps"]]
        assert len(batch) == len(set(batch)) == len(set(steps))

        sessions = [g.begin(sc) for sc in scenarios]
        assert len(loads) == 1 and len(batches) == 1  # begin берёт векторы из кеша, модель не нужна
        assert all(r.dense for s in sessions for r in s.ranked.values())

    def test_same_vectors_and_keys_as_without_prepare(self, ix, monkeypatch, tmp_path) -> None:
        scenarios = [load_json(SCENARIOS / f"{s}.json") for s in ("S0", "S1")]
        with_prep, _ = _embedder(monkeypatch, tmp_path / "a")
        g1 = _grounder(ix, with_prep)
        g1.prepare(scenarios)
        r1 = [g1.begin(sc) for sc in scenarios]

        without, loads = _embedder(monkeypatch, tmp_path / "b")
        g2 = _grounder(ix, without)
        r2 = [g2.begin(sc) for sc in scenarios]

        assert len(loads) == 2  # без prepare — по загрузке на сценарий
        assert set(with_prep.cache.vecs) == set(without.cache.vecs)
        for a, b in zip(r1, r2):
            assert {n: r.fused for n, r in a.ranked.items()} == {n: r.fused for n, r in b.ranked.items()}

    def test_server_prestart_only_before_model_load(self, ix, monkeypatch, tmp_path) -> None:
        """Новые тексты шагов — сервер LLM поднимается до загрузки эмбеддера; векторы в кеше или модель
        запрещена — эмбеддер не грузится, и сервер заранее не нужен."""
        scenarios = [load_json(SCENARIOS / "S0.json")]
        emb, loads = _embedder(monkeypatch, tmp_path)
        g = _grounder(ix, emb)

        class LLM:
            at: list[int] = []

            def prestart(self) -> bool:
                self.at.append(len(loads))
                return True

        g.llm = LLM()
        g.prepare(scenarios)
        assert g.llm.at == [0] and len(loads) == 1  # сервер — до первой загрузки эмбеддера
        g.prepare(scenarios)
        assert g.llm.at == [0]
        g.retriever.embedder, _ = _embedder(monkeypatch, tmp_path / "off", allow_model=False)
        g.prepare(scenarios)
        assert g.llm.at == [0]

    def test_no_dense_without_embedder_or_steps(self, ix) -> None:
        g = StepGrounder(ix, TARGETS, embedder=None, llm=None)
        g.prepare([load_json(SCENARIOS / "S0.json")])  # без эмбеддера — ничего не делает
        g.retriever.embedder = object()  # embed_queries нет: упал бы, если бы prepare вызвал его
        g.prepare([{"id": "E", "steps": []}])  # doc_vecs нет, шагов нет


class TestRunAll:
    def test_prepare_before_first_scenario(self, shared_pipeline, monkeypatch, tmp_path) -> None:
        """Векторы всех сценариев считаются до первого `begin`, то есть до любого ответа LLM по сценариям."""
        calls: list = []
        prepare, begin = shared_pipeline.m1.prepare, shared_pipeline.m1.begin
        monkeypatch.setattr(shared_pipeline.m1, "prepare", lambda scs: calls.append(("prepare", [s["id"] for s in scs])) or prepare(scs))
        monkeypatch.setattr(shared_pipeline.m1, "begin", lambda sc: calls.append(("begin", sc["id"])) or begin(sc))
        shared_pipeline.run_all([SCENARIOS / "S1.json", SCENARIOS / "S0.json"], tmp_path / "s.json")
        assert calls == [("prepare", ["S0", "S1"]), ("begin", "S0"), ("begin", "S1")]

    def test_prepare_failure_does_not_stop_run(self, shared_pipeline, monkeypatch, tmp_path) -> None:
        """Р2: сбой при подготовке векторов виден в `failures`, сценарии строятся как раньше."""
        full = shared_pipeline.run_all([SCENARIOS / "S0.json"], tmp_path / "full.json")
        monkeypatch.setattr(shared_pipeline, "failures", [])

        def boom(scs):
            raise RuntimeError("не хватило памяти")

        monkeypatch.setattr(shared_pipeline.m1, "prepare", boom)
        part = shared_pipeline.run_all([SCENARIOS / "S0.json"], tmp_path / "part.json")
        assert [(f["scenario"], f["step"], f["stage"]) for f in shared_pipeline.failures] == [(None, None, "векторы шагов M1")]
        assert part.scenarios["S0"] == full.scenarios["S0"]
