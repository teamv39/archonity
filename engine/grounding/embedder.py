"""Плотные эмбеддинги для M1 (sentence-transformers) с кешем векторов в репозитории.

Кеш: `cache/emb/<модель>/vectors.npz` (ключи и векторы) и `manifest.json` (репозиторий, ревизия, форматы промптов).
Ключ вектора — sha256 от имени модели, версии формата промпта, вида (query/doc) и итогового текста. Прогон из кеша
не требует ни torch, ни GPU. Промах без модели — `None` и предупреждение: ретривер работает на одном BM25.

Модели качаются в кеш Hugging Face; путь задаётся `HF_HOME` (у нас `D:/models/hf`).
LLM и эмбеддер вместе в 16 ГБ VRAM не помещаются: векторы считаем при остановленном `llama server`.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "cache" / "emb"
# Инструкция запроса Qwen3-Embedding: общая (M1 v8) и прежняя, про Train Ticket (M1 v7, векторы кеша v7), ADR-007
QUERY_TASK = "Given a user action in a web application, retrieve the REST endpoint handler that implements it"
QUERY_TASK_V7 = "Given a user action in a train ticket booking web app, retrieve the REST endpoint handler that implements it"


@dataclass(frozen=True)
class EmbedSpec:
    name: str
    repo: str
    query_fmt: str
    doc_fmt: str
    fmt_version: int = 1
    dtype: str = "bfloat16"
    model_kwargs: dict[str, Any] = field(default_factory=dict)
    config_kwargs: dict[str, Any] = field(default_factory=dict)
    tokenizer_kwargs: dict[str, Any] = field(default_factory=dict)


SPECS = {
    "qwen3-4b": EmbedSpec(
        "qwen3-4b", "Qwen/Qwen3-Embedding-4B",
        query_fmt="Instruct: {task}\nQuery: {q}", doc_fmt="{text}",
        tokenizer_kwargs={"padding_side": "left"},
    ),
    "qwen3-0.6b": EmbedSpec(
        "qwen3-0.6b", "Qwen/Qwen3-Embedding-0.6B",
        query_fmt="Instruct: {task}\nQuery: {q}", doc_fmt="{text}",
        tokenizer_kwargs={"padding_side": "left"},
    ),
    # Промпты из карточки EmbeddingGemma; float16 даёт NaN — только bfloat16/float32
    "gemma2": EmbedSpec(
        "gemma2", "google/embeddinggemma-2",
        query_fmt="task: code retrieval | query: {q}", doc_fmt="title: {title} | text: {text}",
        config_kwargs={"vision_config": None, "audio_config": None},
    ),
}


class VectorCache:
    def __init__(self, name: str) -> None:
        self.dir = CACHE_DIR / name
        self.path = self.dir / "vectors.npz"
        self.vecs: dict[str, np.ndarray] = {}
        self.dirty = False
        if self.path.is_file():
            z = np.load(self.path, allow_pickle=False)
            for k, v in zip(z["keys"], z["vecs"]):
                self.vecs[str(k)] = v

    def save(self, manifest: dict[str, Any]) -> None:
        if not self.dirty:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        keys = sorted(self.vecs)
        np.savez_compressed(self.path, keys=np.array(keys), vecs=np.stack([self.vecs[k] for k in keys]).astype(np.float32))
        (self.dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        self.dirty = False


class STEmbedder:
    """Эмбеддер на sentence-transformers; модель грузится лениво, только на промахе кеша."""

    def __init__(self, spec: EmbedSpec, allow_model: bool = True, batch_size: int = 8,
                 task: str = QUERY_TASK) -> None:
        self.spec = spec
        self.task = task  # инструкция запроса ({task} в query_fmt)
        self.name = spec.name
        self.allow_model = allow_model
        self.batch_size = batch_size
        self.cache = VectorCache(spec.name)
        self._model: Any = None
        self._revision: str | None = None
        self.misses = 0  # векторы, которых не было в кеше и не было модели (итог M1, engine/grounding/report.py)

    def key(self, kind: str, text: str) -> str:
        raw = f"{self.spec.name}|{self.spec.fmt_version}|{kind}|{text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _load(self) -> Any:
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            device = "cuda" if torch.cuda.is_available() else "cpu"
            mk = {"dtype": getattr(torch, self.spec.dtype), **self.spec.model_kwargs}
            self._model = SentenceTransformer(
                self.spec.repo, device=device, model_kwargs=mk, config_kwargs=self.spec.config_kwargs or None,
                tokenizer_kwargs=self.spec.tokenizer_kwargs or None,
            )
            self._revision = _revision(self.spec.repo)
            print(f"[embed] {self.spec.repo} rev {self._revision} на {device}", file=sys.stderr)
        return self._model

    def _embed(self, kind: str, texts: list[str]) -> np.ndarray | None:
        keys = [self.key(kind, t) for t in texts]
        miss = [i for i, k in enumerate(keys) if k not in self.cache.vecs]
        if miss:
            if not self.allow_model:
                self.misses += len(miss)
                print(f"[embed] {self.name}: {len(miss)} промахов кеша, модель запрещена — dense выключен", file=sys.stderr)
                return None
            try:
                model = self._load()
            except Exception as e:  # noqa: BLE001 — нет torch/модели: работаем без dense
                self.misses += len(miss)
                print(f"[embed] {self.name}: модель недоступна ({e}) — dense выключен", file=sys.stderr)
                return None
            vecs = model.encode([texts[i] for i in miss], batch_size=self.batch_size, normalize_embeddings=True,
                                convert_to_numpy=True, show_progress_bar=False)
            for i, v in zip(miss, vecs):
                self.cache.vecs[keys[i]] = np.asarray(v, dtype=np.float32)
            self.cache.dirty = True
            self.cache.save({"name": self.spec.name, "repo": self.spec.repo, "revision": self._revision,
                             "query_fmt": self.spec.query_fmt, "doc_fmt": self.spec.doc_fmt,
                             "fmt_version": self.spec.fmt_version, "dtype": self.spec.dtype})
        return np.stack([self.cache.vecs[k] for k in keys])

    def embed_queries(self, texts: list[str]) -> np.ndarray | None:
        return self._embed("query", [self.spec.query_fmt.format(q=t, task=self.task) for t in texts])

    def embed_docs(self, docs: list[tuple[str, str]]) -> np.ndarray | None:
        return self._embed("doc", [self.spec.doc_fmt.format(title=t, text=x) for t, x in docs])


def _revision(repo: str) -> str | None:
    """Коммит снимка модели в кеше HF (`.../snapshots/<sha>/config.json`)."""
    try:
        from huggingface_hub import try_to_load_from_cache

        p = try_to_load_from_cache(repo, "config.json")
        return Path(p).parent.name if isinstance(p, str) else None
    except Exception:  # noqa: BLE001
        return None


def make_embedder(name: str, allow_model: bool = True, task: str = QUERY_TASK) -> STEmbedder:
    if name not in SPECS:
        raise SystemExit(f"неизвестный эмбеддер {name}; есть: {', '.join(SPECS)}")
    return STEmbedder(SPECS[name], allow_model=allow_model, task=task)
