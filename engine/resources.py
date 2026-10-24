"""Ресурсы прогона (roadmap, П3): время этапов, пик памяти процесса с дочерними, пик видеопамяти, вызовы LLM.

При равном балле организаторы сравнивают ресурсы, поэтому каждый прогон пишет `resources.json` рядом с выдачей и
печатает итог. Только стандартная библиотека: замер работает, даже если конвейер не собрался.

- Время — по этапам `run_eval.py` (`stage`), сумма и полное время от старта.
- Память — пик RSS дерева процессов: наш процесс, бинарники Rust, `llama-server`. На Linux — опрос `/proc` раз в
  секунду; на других ОС — пик своего процесса (`getrusage`), без дочерних.
- Видеопамять — опрос `nvidia-smi` раз в секунду: занято на каждой GPU (пик и фон до старта) и сумма по процессам
  нашего дерева. Нет `nvidia-smi` — поля `null`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

FILE_NAME = "resources.json"
PERIOD_S = 1.0


def _tree_pids(root: int) -> set[int]:
    """Наш процесс и все потомки по `/proc/*/stat` (Linux)."""
    children: dict[int, list[int]] = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            stat = Path(f"/proc/{d}/stat").read_text()
        except OSError:
            continue
        ppid = int(stat[stat.rindex(")") + 2:].split()[1])
        children.setdefault(ppid, []).append(int(d))
    out, todo = set(), [root]
    while todo:
        p = todo.pop()
        if p not in out:
            out.add(p)
            todo += children.get(p, [])
    return out


def _rss_kib(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        pass
    return 0


def _peak_mib(who: str) -> float | None:
    """Пик RSS по `getrusage`: `self` — свой процесс, `children` — самый большой из завершившихся дочерних."""
    try:
        import resource
    except ImportError:  # Windows
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF if who == "self" else resource.RUSAGE_CHILDREN).ru_maxrss
    return peak / 1024 / (1024 if sys.platform == "darwin" else 1)  # macOS — байты, Linux — КиБ


def _smi(args: list[str]) -> list[list[str]]:
    res = subprocess.run(["nvidia-smi", *args, "--format=csv,noheader,nounits"], capture_output=True, text=True,
                         timeout=10)
    if res.returncode != 0:
        return []
    return [[x.strip() for x in line.split(",")] for line in res.stdout.splitlines() if line.strip()]


class Resources:
    """Замер прогона: `start()` в начале, `stage(имя)` вокруг этапов, `finish(...)` в конце."""

    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.stages: list[dict[str, Any]] = []
        self.linux = Path("/proc/self/stat").is_file()
        self.smi = shutil.which("nvidia-smi") is not None
        self.peak_tree_kib = 0
        self.gpus: dict[str, dict[str, int]] = {}
        self.peak_ours_mib = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "Resources":
        if self.smi:
            try:
                for idx, used, total in _smi(["--query-gpu=index,memory.used,memory.total"]):
                    self.gpus[idx] = {"total_mib": int(total), "baseline_mib": int(used), "peak_mib": int(used)}
            except (OSError, ValueError, subprocess.SubprocessError):
                self.smi = False
        if self.linux or self.smi:
            self._thread = threading.Thread(target=self._poll, name="resources", daemon=True)
            self._thread.start()
        return self

    def _poll(self) -> None:
        while not self._stop.is_set():
            self.sample()
            self._stop.wait(PERIOD_S)

    def sample(self) -> None:
        pids = _tree_pids(os.getpid()) if self.linux else {os.getpid()}
        if self.linux:
            self.peak_tree_kib = max(self.peak_tree_kib, sum(_rss_kib(p) for p in pids))
        if not self.smi:
            return
        try:
            for idx, used in _smi(["--query-gpu=index,memory.used"]):
                g = self.gpus.setdefault(idx, {"total_mib": 0, "baseline_mib": int(used), "peak_mib": 0})
                g["peak_mib"] = max(g["peak_mib"], int(used))
            ours = sum(int(mem) for pid, mem in _smi(["--query-compute-apps=pid,used_memory"])
                       if pid.isdigit() and int(pid) in pids)
            self.peak_ours_mib = max(self.peak_ours_mib, ours)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        t = time.perf_counter()
        try:
            yield
        finally:
            self.stages.append({"stage": name, "seconds": round(time.perf_counter() - t, 3)})

    def finish(self, llm: Any = None, embedding_misses: int = 0) -> dict[str, Any]:
        """Остановить опрос и собрать итог. `llm` — `LLMClient` прогона (или None)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.sample()
        self_peak, child_peak = _peak_mib("self"), _peak_mib("children")
        tree = self.peak_tree_kib / 1024 if self.linux else None
        out: dict[str, Any] = {
            "total_seconds": round(time.perf_counter() - self.t0, 3),
            "stages": self.stages,
            "memory": {"peak_rss_tree_mib": round(tree) if tree is not None else None,
                       "peak_rss_self_mib": round(self_peak) if self_peak is not None else None,
                       "peak_rss_child_mib": round(child_peak) if child_peak is not None else None},
            "gpu": {"peak_ours_mib": self.peak_ours_mib if self.smi else None,
                    "devices": [{"index": int(i), **g} for i, g in sorted(self.gpus.items())] if self.smi else None},
            "llm": None,
            "embedding_misses": embedding_misses,
        }
        if llm is not None:
            st = llm.stats
            out["llm"] = {"from_cache": st.hits, "server_calls": st.calls, "server_seconds": round(st.seconds, 3),
                          "prompt_tokens": st.prompt_tokens, "completion_tokens": st.completion_tokens,
                          "server_start_seconds": round(st.server_start_seconds, 3), "errors": st.errors}
        return out


def write(data: dict[str, Any], out: Path) -> Path:
    path = out.parent / FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return path


def lines(data: dict[str, Any]) -> list[str]:
    """Итог для вывода прогона: время по этапам, память, видеопамять, LLM."""
    st = ", ".join(f"{s['stage']} {s['seconds']:.1f}" for s in data["stages"])
    out = [f"Ресурсы: всего {data['total_seconds']:.1f} с" + (f" ({st})" if st else "")]
    mem = data["memory"]
    if mem["peak_rss_tree_mib"] is not None:
        out.append(f"  память: пик {mem['peak_rss_tree_mib']} МиБ (процесс с дочерними: Rust, llama-server)")
    elif mem["peak_rss_self_mib"] is not None:
        out.append(f"  память: пик Python {mem['peak_rss_self_mib']} МиБ"
                   + (f", дочерних процессов {mem['peak_rss_child_mib']} МиБ"
                      if mem["peak_rss_child_mib"] else ""))
    gpu = data["gpu"]
    if gpu["devices"]:
        devs = "; ".join(f"GPU {d['index']}: пик {d['peak_mib']} из {d['total_mib']} МиБ, до старта {d['baseline_mib']}"
                         for d in gpu["devices"])
        out.append(f"  видеопамять: наши процессы пик {gpu['peak_ours_mib']} МиБ; {devs}")
    else:
        out.append("  видеопамять: не использовалась (нет nvidia-smi)")
    llm = data["llm"]
    if llm:
        out.append(f"  LLM: из кеша {llm['from_cache']}, вызовов сервера {llm['server_calls']} за "
                   f"{llm['server_seconds']:.1f} с, токенов {llm['prompt_tokens']} + {llm['completion_tokens']}"
                   + (f", подъём сервера {llm['server_start_seconds']:.0f} с" if llm["server_start_seconds"] else ""))
    return out
