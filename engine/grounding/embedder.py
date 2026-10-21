"""Плотные эмбеддинги для M1 (sentence-transformers) с кешем векторов в репозитории.

Кеш: `cache/emb/<модель>/vectors.npz` (ключи и векторы) и `manifest.json` (репозиторий, ревизия, форматы промптов).
Ключ вектора — sha256 от имени модели, версии формата промпта, вида (query/doc) и итогового текста. Прогон из кеша
не требует ни torch, ни GPU. Промах без модели, нехватка памяти или другая ошибка модели — `None` и предупреждение:
ретривер работает на одном BM25.

Эмбеддер из `models/manifest.json` (qwen3-4b) грузится из `models/<dir>` с ревизией манифеста; нет файлов — качает их
туда же (проверка sha256 — scripts/fetch_models.py). Остальные эмбеддеры (bakeoff) — из кеша Hugging Face (`HF_HOME`).
Устройство — `ARCHONITY_EMBED_DEVICE` (`cuda`, `cpu`), по умолчанию GPU, если есть.

Модель живёт только пока считает: после каждой порции промахов её выгружает `release()`, векторы остаются в кеше
процесса. Так эмбеддер (около 8 ГБ) и `llama server` (около 20 ГБ на A100) не бывают в памяти одновременно, где бы
ни стоял вызов; пачку на весь прогон собирает `StepGrounder.prepare`, чтобы модель не грузилась по сценарию.
"""
from __future__ import annotations

import gc
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "cache" / "emb"
MODELS_DIR = ROOT / "models"
# Инструкция запроса Qwen3-Embedding, без слов домена (ADR-007); входит в ключ вектора запроса
QUERY_TASK = "Given a user action in a web application, retrieve the REST endpoint handler that implements it"


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
    """Эмбеддер на sentence-transformers; модель грузится лениво, только на промахе кеша, и выгружается после него."""

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
        self._broken: str | None = None  # причина отказа модели: после первой ошибки модель больше не трогаем
        self._missed: set[str] = set()  # ключи векторов, которых не было в кеше и не было модели

    @property
    def misses(self) -> int:
        """Векторов без кеша и без модели (итог M1, engine/grounding/report.py). Считаются разные ключи: вектор шага
        из `StepGrounder.prepare` и из `begin` — один и тот же промах."""
        return len(self._missed)

    def key(self, kind: str, text: str) -> str:
        raw = f"{self.spec.name}|{self.spec.fmt_version}|{kind}|{text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def release(self) -> None:
        """Выгружает модель из памяти: память и видеопамять нужны `llama server` (LLM рядом с эмбеддером в 16 ГБ
        VRAM и в лимит выделенной памяти Windows не помещается). Векторы остаются в `self.cache`; следующий промах
        загрузит модель заново. Вызывающий не должен держать ссылку на модель."""
        loaded = self._model is not None
        self._model = None
        gc.collect()
        torch = sys.modules.get("torch")  # без torch (прогон из кеша) ничего не грузим
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
        if loaded:
            print(f"[embed] {self.name}: модель выгружена", file=sys.stderr)

    def _load(self) -> Any:
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            device = os.environ.get("ARCHONITY_EMBED_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
            source, self._revision = self.spec.repo, None
            entry = manifest_entry(self.spec.name)
            if entry:
                source, self._revision = str(ensure_local(entry)), entry["revision"]
            mk = {"dtype": getattr(torch, self.spec.dtype), **self.spec.model_kwargs}
            self._model = SentenceTransformer(
                source, device=device, model_kwargs=mk, config_kwargs=self.spec.config_kwargs or None,
                tokenizer_kwargs=self.spec.tokenizer_kwargs or None,
            )
            self._revision = self._revision or _revision(self.spec.repo)
            print(f"[embed] {self.spec.repo} rev {self._revision} на {device}", file=sys.stderr)
        return self._model

    def _embed(self, kind: str, texts: list[str]) -> np.ndarray | None:
        keys = [self.key(kind, t) for t in texts]
        miss = [i for i, k in enumerate(keys) if k not in self.cache.vecs]
        if miss:
            if not self.allow_model:
                self._missed.update(keys[i] for i in miss)
                print(f"[embed] {self.name}: {len(miss)} промахов кеша, модель запрещена — dense выключен", file=sys.stderr)
                return None
            if self._broken:
                self._missed.update(keys[i] for i in miss)
                print(f"[embed] {self.name}: {len(miss)} промахов кеша, модель недоступна ({self._broken}) — "
                      f"dense выключен", file=sys.stderr)
                return None
            model, vecs = None, None
            try:
                model = self._load()
                vecs = model.encode([texts[i] for i in miss], batch_size=self.batch_size, normalize_embeddings=True,
                                    convert_to_numpy=True, show_progress_bar=False)
            except Exception as e:  # noqa: BLE001 — нет torch/модели, не хватило памяти: работаем без dense
                self._broken = f"{type(e).__name__}: {e}"
                print(f"[embed] {self.name}: модель недоступна ({self._broken}) — dense выключен", file=sys.stderr)
            finally:
                del model  # последняя ссылка вызывающего: без неё release() не освободит веса
                self.release()
            if vecs is None:
                self._missed.update(keys[i] for i in miss)
                return None
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


def manifest_entry(name: str) -> dict[str, Any] | None:
    """Запись эмбеддера `name` в `models/manifest.json` (репозиторий, ревизия, каталог, файлы) или None."""
    try:
        entry = json.loads((MODELS_DIR / "manifest.json").read_text(encoding="utf-8")).get("embedder") or {}
    except (OSError, ValueError):
        return None
    return entry if entry.get("name") == name else None


def ensure_local(entry: dict[str, Any]) -> Path:
    """Каталог модели в `models/`; нет файлов — качает их с ревизией манифеста (sha256 проверяет fetch_models.py)."""
    local = MODELS_DIR / entry["dir"]
    missing = [f for f in entry["files"] if not (local / f).is_file()]
    if missing:
        from huggingface_hub import snapshot_download

        print(f"[embed] качаю {entry['repo']}@{entry['revision'][:12]} в {local} ({len(missing)} файлов)", file=sys.stderr)
        snapshot_download(entry["repo"], revision=entry["revision"], local_dir=local, allow_patterns=missing)
    return local


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
