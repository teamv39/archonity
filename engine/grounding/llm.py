"""Клиент локальной LLM (`llama server` из llama.cpp, OpenAI-совместимый API) с кешем ответов в репозитории (ADR-005, «Кеш LLM»).

- Ключ — sha256 от имени модели, версии промпта, сообщений и JSON-схемы ответа.
- Кеш — `cache/llm/<ключ>.json`, входит в сдачу. По умолчанию сначала кеш; на промахе — сервер, если доступен,
  иначе `None` (вызывающий берёт правило по умолчанию). `refresh=True` (`--no-cache`) пересчитывает всё.
- `temperature = 0`, thinking выключен, вывод по JSON-схеме, вызовы по одному (параллельность не ускоряет).

Сервер: `ARCHONITY_LLM_URL` (по умолчанию http://127.0.0.1:8080), имя модели для ключа — `ARCHONITY_LLM_MODEL`.
Strict Local-First: адрес вне loopback и частной сети клиент не принимает (`LocalOnlyError`).
Параметры запуска `llama server` — docs/researches/model_selection.md.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "cache" / "llm"
DEFAULT_URL = "http://127.0.0.1:8080"
DEFAULT_MODEL = "Qwen3.6-35B-A3B-UD-IQ4_XS"
MAX_TOKENS = 600
TIMEOUT_S = 300


class LocalOnlyError(ValueError):
    """Адрес LLM-сервера не локальный: облачные и внешние API запрещены (AGENTS.md)."""


def check_local_url(url: str) -> str:
    """Разрешены только loopback и частная сеть (сервер на машине команды)."""
    host = urllib.parse.urlparse(url).hostname or ""
    if host == "localhost":
        return url
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise LocalOnlyError(f"LLM: разрешён только локальный сервер по IP или localhost, получено {url}") from None
    if not (ip.is_loopback or ip.is_private):
        raise LocalOnlyError(f"LLM: адрес {url} не локальный")
    return url


@dataclass
class LLMStats:
    hits: int = 0
    calls: int = 0
    misses: int = 0  # промах кеша без сервера
    errors: int = 0
    seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def __str__(self) -> str:
        return (f"кеш {self.hits}, вызовов {self.calls} за {self.seconds:.0f} с "
                f"(промпт {self.prompt_tokens}, ответ {self.completion_tokens} ток.), "
                f"без ответа {self.misses}, ошибок {self.errors}")


class LLMClient:
    def __init__(self, url: str | None = None, model: str | None = None, use_server: bool = True,
                 refresh: bool = False, cache_dir: Path = CACHE_DIR) -> None:
        self.url = check_local_url((url or os.environ.get("ARCHONITY_LLM_URL") or DEFAULT_URL).rstrip("/"))
        self.model = model or os.environ.get("ARCHONITY_LLM_MODEL") or DEFAULT_MODEL
        self.use_server = use_server
        self.refresh = refresh
        self.cache_dir = cache_dir
        self.stats = LLMStats()
        self._server_ok: bool | None = None

    def key(self, prompt_version: str, messages: list[dict[str, str]], schema: dict[str, Any]) -> str:
        raw = json.dumps({"model": self.model, "prompt_version": prompt_version, "messages": messages,
                          "schema": schema}, ensure_ascii=False, sort_keys=True)
        return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key.split(':', 1)[1]}.json"

    def is_cached(self, key: str) -> bool:
        """Есть ли файл кеша для ключа (без чтения; `refresh` не учитывается)."""
        return self._path(key).is_file()

    def server_available(self) -> bool:
        if self._server_ok is None:
            try:
                with urllib.request.urlopen(f"{self.url}/health", timeout=3) as r:
                    self._server_ok = r.status == 200
            except (urllib.error.URLError, OSError, ValueError):
                self._server_ok = False
            if not self._server_ok:
                print(f"[llm] сервер {self.url} недоступен — только кеш", file=sys.stderr)
        return self._server_ok

    def complete_json(self, kind: str, prompt_version: str, messages: list[dict[str, str]],
                      schema: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """→ (ответ по схеме или None, ключ кеша)."""
        key = self.key(prompt_version, messages, schema)
        path = self._path(key)
        if not self.refresh and path.is_file():
            self.stats.hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["response"], key
        if not self.use_server or not self.server_available():
            self.stats.misses += 1
            return None, key
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": MAX_TOKENS,
            "cache_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {"name": kind, "strict": True, "schema": schema}},
        }
        t0 = time.time()
        try:
            req = urllib.request.Request(f"{self.url}/v1/chat/completions", data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                out = json.loads(r.read().decode("utf-8"))
            content = out["choices"][0]["message"]["content"]
            resp = json.loads(content)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            self.stats.errors += 1
            print(f"[llm] {kind}: ошибка {e}", file=sys.stderr)
            return None, key
        dt = time.time() - t0
        usage = out.get("usage") or {}
        self.stats.calls += 1
        self.stats.seconds += dt
        self.stats.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.stats.completion_tokens += int(usage.get("completion_tokens") or 0)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "key": key, "model": self.model, "prompt_version": prompt_version, "kind": kind,
            "messages": messages, "schema": schema, "response": resp,
            "finish_reason": out["choices"][0].get("finish_reason"), "usage": usage, "seconds": round(dt, 2),
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return resp, key
