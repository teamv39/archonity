"""Клиент локальной LLM (`llama server` из llama.cpp, OpenAI-совместимый API) с кешем ответов в репозитории (ADR-005, «Кеш LLM»).

- Ключ — sha256 от имени модели, версии промпта, сообщений и JSON-схемы ответа; у выборки ещё и её параметры (`sampling`).
- Кеш — `cache/llm/<ключ>.json`, входит в сдачу. По умолчанию сначала кеш; на промахе — сервер, если доступен,
  иначе `None` (вызывающий берёт правило по умолчанию). `refresh=True` (`--no-cache`) пересчитывает всё.
- По умолчанию `temperature = 0`; `sampling` (temperature, top_p, top_k, seed) — выборка, её ведёт голосование выбора
  в режиме v8 (`grounder.SELECT_VOTES`). Thinking выключен, вывод по JSON-схеме, вызовы по одному.

Сервер: `ARCHONITY_LLM_URL` (по умолчанию http://127.0.0.1:8080), имя модели для ключа — `ARCHONITY_LLM_MODEL`.
Strict Local-First: адрес вне loopback и частной сети клиент не принимает (`LocalOnlyError`); прокси для него не нужен
и не используется.
Параметры запуска `llama server` — docs/researches/model_selection.md.

Автозапуск: нужен ответ не из кеша, а сервер не отвечает — клиент сам поднимает `llama-server` и ждёт `/health`
(загрузка модели — минуты), при выходе гасит его. Условия: адрес — loopback, имя модели ключа — модель манифеста
`models/manifest.json`, GGUF лежит в `models/` (scripts/fetch_models.py), найден бинарник (`find_llama_server`).
Параметры по умолчанию — под A100 40 ГБ (`SERVER_ARGS`); дополнительные — `ARCHONITY_LLAMA_ARGS`, они идут после
умолчаний и перекрывают их (на 16 ГБ — `-ncmoe 7`). Лог сервера — `output/llama-server.log`. Прогон из кеша сервер
не поднимает.

Запуск заранее (`prestart`): у шагов новые тексты (промах кеша векторов) — значит, будут и промахи кеша LLM, и
`StepGrounder.prepare` поднимает сервер до эмбеддера, а не после: модели грузятся одновременно. Только если обе
помещаются в видеопамять (`ARCHONITY_LLM_PRESTART=auto|on|off`, `prestart_need_mib`); сервер не поднялся — обычный
автозапуск на первом промахе.
"""
from __future__ import annotations

import atexit
import hashlib
import ipaddress
import json
import os
import shlex
import shutil
import subprocess
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
MODELS_DIR = ROOT / "models"
DEFAULT_URL = "http://127.0.0.1:8080"
DEFAULT_MODEL = "Qwen3.6-35B-A3B-UD-IQ4_XS"
MAX_TOKENS = 600
TIMEOUT_S = 300
# Автозапуск под A100 40 ГБ: все слои на GPU, без -ncmoe; контекст и KV — как в scripts/start_llm.ps1
SERVER_ARGS = ["--fit", "off", "-ngl", "999", "-fa", "1", "-ctk", "q8_0", "-ctv", "q8_0", "-c", "32768"]
START_TIMEOUT_S = 1800  # ожидание /health: чтение 17.7 ГБ с диска; ARCHONITY_LLAMA_START_TIMEOUT
PRESTART_SPARE_MIB = 5120  # сверх файлов моделей: KV q8_0 на 32K и буферы сервера, активации эмбеддера (пик 7.7 ГиБ)
SERVER_LOG = ROOT / "output" / "llama-server.log"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # сервер локальный: системный прокси мимо


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


def read_manifest() -> dict[str, Any]:
    """`models/manifest.json`: версии LLM, эмбеддера и llama.cpp; без файла — пустой словарь."""
    try:
        return json.loads((MODELS_DIR / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def model_path(manifest: dict[str, Any]) -> Path | None:
    """Путь GGUF модели манифеста в `models/` (файл может ещё не быть скачан)."""
    llm = manifest.get("llm") or {}
    files = list(llm.get("files") or {})
    return MODELS_DIR / llm.get("dir", ".") / files[0] if files else None


def prestart_need_mib(manifest: dict[str, Any] | None = None) -> int | None:
    """Видеопамять, МиБ, под сервер и эмбеддер разом: файлы обеих моделей манифеста и запас (`PRESTART_SPARE_MIB`:
    KV-кеш и буферы сервера, активации эмбеддера). На A100 40 ГБ — около 29.7 тыс. из 40 тыс.; нет манифеста — None."""
    manifest = read_manifest() if manifest is None else manifest
    sizes = [f.get("size") or 0 for k in ("llm", "embedder")
             for f in ((manifest.get(k) or {}).get("files") or {}).values()]
    if not manifest.get("llm") or not all(sizes):
        return None
    return sum(sizes) // 2**20 + PRESTART_SPARE_MIB


def gpu_free_mib() -> int | None:
    """Свободная видеопамять GPU 0 по `nvidia-smi`, МиБ; нет NVIDIA или утилиты — None."""
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return int(out.split()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def find_llama_server() -> list[str] | None:
    """Команда сервера llama.cpp. По порядку: `ARCHONITY_LLAMA_SERVER` (путь или имя в PATH; `off` — без автозапуска),
    `models/llama.cpp/llama-server` (scripts/fetch_models.py --llama-cpp), `llama-server` в PATH, единый CLI
    `llama server`. Для единого CLI (`llama`) подкоманда `server` добавляется сама."""
    env = os.environ.get("ARCHONITY_LLAMA_SERVER", "").strip()
    if env.lower() == "off":
        return None
    if env:
        path = shutil.which(env) or (env if Path(env).is_file() else None)
        if path is None:
            print(f"[llm] ARCHONITY_LLAMA_SERVER={env}: файл не найден", file=sys.stderr)
            return None
    else:
        exe = "llama-server.exe" if os.name == "nt" else "llama-server"
        local = MODELS_DIR / ((read_manifest().get("llama_cpp") or {}).get("dir") or "llama.cpp") / exe
        path = str(local) if local.is_file() else shutil.which("llama-server") or shutil.which("llama")
        if path is None:
            return None
    return [path, "server"] if Path(path).stem.lower() == "llama" else [path]


def _health(url: str, timeout: float = 3) -> bool:
    try:
        with _OPENER.open(f"{url}/health", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()


def _log_tail(path: Path, lines: int = 15) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


@dataclass
class LLMStats:
    hits: int = 0
    calls: int = 0
    misses: int = 0  # промах кеша без сервера
    errors: int = 0
    seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    server_start_seconds: float = 0.0  # от запуска llama-server до /health (ресурсы прогона)

    def __str__(self) -> str:
        return (f"кеш {self.hits}, вызовов {self.calls} за {self.seconds:.0f} с "
                f"(промпт {self.prompt_tokens}, ответ {self.completion_tokens} ток.), "
                f"без ответа {self.misses}, ошибок {self.errors}")


class LLMClient:
    def __init__(self, url: str | None = None, model: str | None = None, use_server: bool = True,
                 refresh: bool = False, cache_dir: Path = CACHE_DIR, timeout: float = TIMEOUT_S) -> None:
        """`timeout` — на один вызов сервера, с; на CPU вызов выбора идёт минуты (исследование GPU, раздел 7.5)."""
        self.url = check_local_url((url or os.environ.get("ARCHONITY_LLM_URL") or DEFAULT_URL).rstrip("/"))
        self.model = model or os.environ.get("ARCHONITY_LLM_MODEL") or DEFAULT_MODEL
        self.use_server = use_server
        self.refresh = refresh
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.stats = LLMStats()
        self.requested: list[str] = []  # ключи всех запросов прогона, по порядку (scripts/verify_llm_cache.py)
        self._server_ok: bool | None = None
        self._started: tuple[subprocess.Popen, float] | None = None  # сервер `prestart`, ещё не дождались /health

    def key(self, prompt_version: str, messages: list[dict[str, str]], schema: dict[str, Any],
            sampling: dict[str, Any] | None = None) -> str:
        """`sampling` входит в ключ, только когда задан: ключи жадных вызовов (temperature 0) прежние."""
        d: dict[str, Any] = {"model": self.model, "prompt_version": prompt_version, "messages": messages, "schema": schema}
        if sampling:
            d["sampling"] = sampling
        raw = json.dumps(d, ensure_ascii=False, sort_keys=True)
        return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key.split(':', 1)[1]}.json"

    def is_cached(self, key: str) -> bool:
        """Есть ли файл кеша для ключа (без чтения; `refresh` не учитывается)."""
        return self._path(key).is_file()

    def server_available(self) -> bool:
        """Отвечает ли сервер; не отвечает — автозапуск (`_autostart`). Вызывается только на промахе кеша."""
        if self._server_ok is None:
            self._server_ok = _health(self.url) or self._autostart()
            if not self._server_ok:
                print(f"[llm] сервер {self.url} недоступен — только кеш", file=sys.stderr)
        return self._server_ok

    def prestart(self) -> bool:
        """Поднять `llama-server` заранее, не дожидаясь `/health`: модель грузится, пока прогон занят другим
        (`StepGrounder.prepare` — векторы шагов). Первый промах кеша потом ждёт готовности (`_autostart`).

        Только когда сервер рядом с эмбеддером точно помещается: `ARCHONITY_LLM_PRESTART` — `on`, `off` или `auto`
        (по умолчанию: свободной видеопамяти GPU 0 по `nvidia-smi` не меньше `prestart_need_mib`). На 16 ГБ вместе
        они не помещаются, там сервер по-прежнему поднимается на первом промахе. → запущен ли сервер."""
        if not self.use_server or self._server_ok is not None or self._started is not None:
            return False
        mode = (os.environ.get("ARCHONITY_LLM_PRESTART") or "auto").strip().lower()
        if mode == "off" or _health(self.url):
            return False
        if mode != "on":
            need, free = prestart_need_mib(), gpu_free_mib()
            if need is None or free is None or free < need:
                return False
        self._started = self._launch()
        if self._started is not None:
            print("[llm] сервер грузится заранее, пока M1 считает векторы шагов", file=sys.stderr)
        return self._started is not None

    def _launch(self) -> tuple[subprocess.Popen, float] | None:
        """Запустить `llama-server` с моделью манифеста, не дожидаясь готовности; сервер гасится при выходе (atexit).
        → (процесс, время запуска) или None, если запускать нечего или некуда."""
        u = urllib.parse.urlparse(self.url)
        host = u.hostname or ""
        if host != "localhost" and not ipaddress.ip_address(host).is_loopback:
            return None  # сервер в частной сети поднимает его хозяин
        manifest = read_manifest()
        if (manifest.get("llm") or {}).get("name") != self.model:
            return None  # ключи кеша другой модели (ARCHONITY_LLM_MODEL): модель манифеста её не заменяет
        model = model_path(manifest)
        if model is None or not model.is_file():
            print(f"[llm] автозапуск: нет модели {model} — python scripts/fetch_models.py", file=sys.stderr)
            return None
        cmd = find_llama_server()
        if cmd is None:
            print("[llm] автозапуск: не найден llama-server (ARCHONITY_LLAMA_SERVER, models/llama.cpp, PATH)",
                  file=sys.stderr)
            return None
        cmd += ["-m", str(model), "--host", host, "--port", str(u.port or 80), *SERVER_ARGS,
                *shlex.split(os.environ.get("ARCHONITY_LLAMA_ARGS", ""))]
        SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
        print(f"[llm] автозапуск: {shlex.join(cmd)}\n[llm] лог {SERVER_LOG}", file=sys.stderr)
        t0 = time.time()
        with open(SERVER_LOG, "w", encoding="utf-8") as log:
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            except OSError as e:
                print(f"[llm] автозапуск: {e}", file=sys.stderr)
                return None
        atexit.register(_stop, proc)
        return proc, t0

    def _autostart(self) -> bool:
        """Поднять `llama-server` (или взять запущенный `prestart`) и дождаться `/health`. Сервер `prestart` не
        поднялся (например, не хватило памяти рядом с эмбеддером) — ещё одна попытка, как без `prestart`: эмбеддер
        к этому времени выгружен."""
        if self._started is not None:
            started, self._started = self._started, None
            if self._wait(*started):
                return True
            print("[llm] сервер, запущенный заранее, не поднялся — запускаю заново", file=sys.stderr)
        started = self._launch()
        return started is not None and self._wait(*started)

    def _wait(self, proc: subprocess.Popen, t0: float) -> bool:
        """Ждать `/health` сервера `proc`, запущенного в `t0`; не дождались — сервер останавливается."""
        timeout = float(os.environ.get("ARCHONITY_LLAMA_START_TIMEOUT") or START_TIMEOUT_S)
        print(f"[llm] жду {self.url}/health до {timeout:.0f} с от запуска", file=sys.stderr)
        while time.time() - t0 < timeout:
            if proc.poll() is not None:
                print(f"[llm] llama-server завершился с кодом {proc.returncode}:\n{_log_tail(SERVER_LOG)}",
                      file=sys.stderr)
                return False
            if _health(self.url):
                self.stats.server_start_seconds += time.time() - t0
                print(f"[llm] сервер готов за {time.time() - t0:.0f} с", file=sys.stderr)
                return True
            time.sleep(2)
        print(f"[llm] сервер не ответил за {timeout:.0f} с — останавливаю:\n{_log_tail(SERVER_LOG)}", file=sys.stderr)
        _stop(proc)
        return False

    def complete_json(self, kind: str, prompt_version: str, messages: list[dict[str, str]],
                      schema: dict[str, Any], max_tokens: int = MAX_TOKENS,
                      sampling: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
        """→ (ответ по схеме или None, ключ кеша). `max_tokens` в ключ не входит: обрыв ответа виден по схеме.
        `sampling` — параметры выборки (temperature, top_p, top_k, seed) вместо жадного вывода; входят в ключ."""
        key = self.key(prompt_version, messages, schema, sampling)
        self.requested.append(key)
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
            "max_tokens": max_tokens,
            "cache_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {"name": kind, "strict": True, "schema": schema}},
        }
        body.update(sampling or {})
        t0 = time.time()
        try:
            req = urllib.request.Request(f"{self.url}/v1/chat/completions", data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            with _OPENER.open(req, timeout=self.timeout) as r:
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
            "messages": messages, "schema": schema, **({"sampling": sampling} if sampling else {}), "response": resp,
            "finish_reason": out["choices"][0].get("finish_reason"), "usage": usage, "seconds": round(dt, 2),
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return resp, key
