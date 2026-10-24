"""Упаковка моделей: манифест models/manifest.json, автозапуск llama-server (engine/grounding/llm.py),
scripts/fetch_models.py с --from, эмбеддер из models/ и отказ модели. Без GPU, сети и настоящего сервера."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.grounding import embedder as E
from engine.grounding import llm as L

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((ROOT / "models" / "manifest.json").read_text(encoding="utf-8"))
_spec = importlib.util.spec_from_file_location("fetch_models", ROOT / "scripts" / "fetch_models.py")
fetch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch)

SHA = re.compile(r"^[0-9a-f]{64}$")
REV = re.compile(r"^[0-9a-f]{40}$")


class TestManifest:
    def test_llm_is_client_default_model(self) -> None:
        llm = MANIFEST["llm"]
        assert llm["name"] == L.DEFAULT_MODEL and REV.match(llm["revision"])
        assert list(llm["files"]) == [f"{L.DEFAULT_MODEL}.gguf"]
        assert L.model_path(MANIFEST) == ROOT / "models" / f"{L.DEFAULT_MODEL}.gguf"

    def test_embedder_is_spec_and_vector_cache_revision(self) -> None:
        emb = MANIFEST["embedder"]
        cache = json.loads((ROOT / "cache" / "emb" / emb["name"] / "manifest.json").read_text(encoding="utf-8"))
        assert emb["repo"] == E.SPECS[emb["name"]].repo == cache["repo"]
        assert emb["revision"] == cache["revision"] and REV.match(emb["revision"])
        assert {"config.json", "modules.json", "tokenizer.json"} <= set(emb["files"])

    def test_every_file_pinned(self) -> None:
        specs = [*MANIFEST["llm"]["files"].values(), *MANIFEST["embedder"]["files"].values(),
                 *MANIFEST["llama_cpp"]["linux_x64_cuda"]]
        assert all(SHA.match(s["sha256"]) and s["size"] > 0 for s in specs)

    def test_llama_cpp_build(self) -> None:
        lc = MANIFEST["llama_cpp"]
        assert re.match(r"^b\d+$", lc["build"]) and REV.match(lc["commit"])
        assert all(f"/{lc['build']}/" in a["url"] for a in lc["linux_x64_cuda"])
        assert lc["commit"] in lc["source"]

    def test_start_scripts_use_models_dir_and_client_args(self) -> None:
        gguf = next(iter(MANIFEST["llm"]["files"]))
        sh = (ROOT / "scripts" / "start_llm.sh").read_text(encoding="utf-8")
        ps1 = (ROOT / "scripts" / "start_llm.ps1").read_text(encoding="utf-8")
        assert f"models/{gguf}" in sh and f"models\\{gguf}" in ps1
        assert " ".join(L.SERVER_ARGS) in " ".join(sh.split())  # те же умолчания, что у автозапуска
        assert "-ncmoe" not in L.SERVER_ARGS

    def test_models_dir_ignored_except_manifest(self) -> None:
        if shutil.which("git") is None:
            pytest.skip("нет git")
        out = subprocess.run(["git", "check-ignore", "models/manifest.json", "models/x.gguf", "models/llama.cpp/a"],
                             cwd=ROOT, capture_output=True, text=True).stdout.split()
        assert out == ["models/x.gguf", "models/llama.cpp/a"]

    def test_linux_scripts_executable_in_git(self) -> None:
        if shutil.which("git") is None:
            pytest.skip("нет git")
        out = subprocess.run(["git", "ls-files", "-s", "scripts/run_final.sh", "scripts/start_llm.sh"],
                             cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
        if len(out) < 2:
            pytest.skip("скрипты ещё не в индексе")
        assert all(line.startswith("100755 ") for line in out)
        final = (ROOT / "scripts" / "run_final.sh").read_text(encoding="utf-8")
        assert "scripts/fetch_models.py" in final and "run_eval.py" in final


class FakeProc:
    def __init__(self, cmd: list[str], rc_after: int | None = None) -> None:
        self.cmd, self.returncode, self.terminated = cmd, None, False
        self._rc_after = rc_after
        self._polls = 0

    def poll(self) -> int | None:
        self._polls += 1
        if self._rc_after is not None and self._polls > self._rc_after:
            self.returncode = 1
        return self.returncode

    def terminate(self) -> None:
        self.terminated, self.returncode = True, 0

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


@pytest.fixture
def server_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """models/ с манифестом и GGUF модели `m`, бинарник из ARCHONITY_LLAMA_SERVER, Popen и /health — подмены."""
    models = tmp_path / "models"
    models.mkdir()
    (models / "manifest.json").write_text(json.dumps({"llm": {"name": "m", "files": {"m.gguf": {}}}}), encoding="utf-8")
    (models / "m.gguf").write_bytes(b"gguf")
    binary = tmp_path / "bin" / "llama-server"
    binary.parent.mkdir()
    binary.write_bytes(b"")
    monkeypatch.setattr(L, "MODELS_DIR", models)
    monkeypatch.setattr(L, "SERVER_LOG", tmp_path / "llama-server.log")
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    monkeypatch.setenv("ARCHONITY_LLAMA_SERVER", str(binary))
    monkeypatch.delenv("ARCHONITY_LLAMA_ARGS", raising=False)
    monkeypatch.delenv("ARCHONITY_LLAMA_START_TIMEOUT", raising=False)
    st: dict = {"procs": [], "health": [False], "atexit": [], "binary": binary, "models": models, "rc_after": None}

    def popen(cmd, **kw):
        p = FakeProc(cmd, st["rc_after"])
        st["procs"].append(p)
        return p

    monkeypatch.setattr(L.subprocess, "Popen", popen)
    monkeypatch.setattr(L, "_health", lambda url, timeout=3: st["health"].pop(0) if st["health"] else True)
    monkeypatch.setattr(L.atexit, "register", lambda fn, *a: st["atexit"].append((fn, a)))
    return st


class TestAutostart:
    def test_cache_hit_never_touches_server(self, server_env: dict, tmp_path: Path) -> None:
        c = L.LLMClient(model="m", cache_dir=tmp_path / "cache")
        msgs = [{"role": "user", "content": "x"}]
        key = c.key("v1", msgs, {"type": "object"})
        (tmp_path / "cache").mkdir()
        (tmp_path / "cache" / f"{key.split(':', 1)[1]}.json").write_text(json.dumps({"response": {"a": 1}}),
                                                                          encoding="utf-8")
        assert c.complete_json("k", "v1", msgs, {"type": "object"})[0] == {"a": 1}
        assert server_env["procs"] == [] and server_env["health"] == [False]

    def test_miss_starts_server_with_a100_defaults_and_extra_args(self, server_env: dict,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARCHONITY_LLAMA_ARGS", "-ncmoe 7")
        server_env["health"] = [False, False, False]  # проверка до запуска и два опроса во время загрузки
        c = L.LLMClient(model="m")
        assert c.server_available() and c.server_available()
        (p,) = server_env["procs"]
        assert p.cmd[0] == str(server_env["binary"])
        assert p.cmd[1:5] == ["-m", str(server_env["models"] / "m.gguf"), "--host", "127.0.0.1"]
        assert p.cmd[5:7] == ["--port", "8080"]
        assert p.cmd[7:-2] == L.SERVER_ARGS and p.cmd[-2:] == ["-ncmoe", "7"]
        (fn, args), = server_env["atexit"]
        fn(*args)
        assert p.terminated

    def test_running_server_is_used_as_is(self, server_env: dict) -> None:
        server_env["health"] = [True]
        assert L.LLMClient(model="m").server_available() and server_env["procs"] == []

    def test_server_exit_during_load_is_unavailable(self, server_env: dict) -> None:
        server_env["rc_after"], server_env["health"] = 1, [False] * 5
        c = L.LLMClient(model="m", cache_dir=server_env["models"] / "cache")
        assert c.complete_json("k", "v1", [{"role": "user", "content": "x"}], {"type": "object"})[0] is None
        assert c.stats.misses == 1 and len(server_env["procs"]) == 1

    def test_start_timeout_stops_server(self, server_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARCHONITY_LLAMA_START_TIMEOUT", "0")
        assert not L.LLMClient(model="m").server_available()
        assert server_env["procs"][0].terminated

    @pytest.mark.parametrize("case", ["no_model", "other_model", "private_net", "off"])
    def test_no_autostart(self, server_env: dict, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
        url, model = None, "m"
        if case == "no_model":
            (server_env["models"] / "m.gguf").unlink()
        elif case == "other_model":
            model = "Qwen3-4B-Q4_K_M"  # режим CPU: ключи другой модели, модель манифеста их не подменяет
        elif case == "private_net":
            url = "http://192.168.1.5:8080"
        else:
            monkeypatch.setenv("ARCHONITY_LLAMA_SERVER", "off")
        assert not L.LLMClient(url=url, model=model).server_available()
        assert server_env["procs"] == []


class TestPrestart:
    """Сервер заранее (`LLMClient.prestart`): только когда сервер и эмбеддер вместе помещаются в видеопамять."""

    @pytest.fixture
    def sized(self, server_env: dict, monkeypatch: pytest.MonkeyPatch) -> dict:
        manifest = {"llm": {"name": "m", "files": {"m.gguf": {"size": 18 * 2**30}}},
                    "embedder": {"name": "e", "files": {"a": {"size": 8 * 2**30}}}}
        (server_env["models"] / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        monkeypatch.delenv("ARCHONITY_LLM_PRESTART", raising=False)
        return server_env

    def test_need_fits_a100_not_16gb(self) -> None:
        assert 16_384 < L.prestart_need_mib(MANIFEST) < 39_000
        assert L.prestart_need_mib({"llm": {"files": {"x": {}}}}) is None and L.prestart_need_mib({}) is None

    @pytest.mark.parametrize("free, started", [(None, False), (16_000, False), (40_000, True)])
    def test_auto_by_free_vram(self, sized: dict, monkeypatch: pytest.MonkeyPatch, free, started: bool) -> None:
        monkeypatch.setattr(L, "gpu_free_mib", lambda: free)
        sized["health"] = [False]
        c = L.LLMClient(model="m")
        assert c.prestart() is started and len(sized["procs"]) == int(started)
        sized["health"] = [False, False]
        assert c.server_available() and len(sized["procs"]) == 1  # ждёт сервер prestart, второй не поднимает

    def test_off_cache_only_and_running_server(self, sized: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(L, "gpu_free_mib", lambda: 40_000)
        monkeypatch.setenv("ARCHONITY_LLM_PRESTART", "off")
        assert not L.LLMClient(model="m").prestart()
        monkeypatch.setenv("ARCHONITY_LLM_PRESTART", "on")
        assert not L.LLMClient(model="m", use_server=False).prestart()
        sized["health"] = [True]
        assert not L.LLMClient(model="m").prestart()
        assert sized["procs"] == []

    def test_dead_prestart_server_is_started_again(self, sized: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARCHONITY_LLM_PRESTART", "on")
        sized["rc_after"], sized["health"] = 0, [False] * 3
        c = L.LLMClient(model="m")
        assert c.prestart()
        sized["rc_after"] = None  # первый сервер упал при загрузке (рядом с эмбеддером), второй поднимается
        assert c.server_available() and len(sized["procs"]) == 2

    def test_gpu_free_without_nvidia_smi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(L.shutil, "which", lambda name: None)
        assert L.gpu_free_mib() is None


class TestFindLlamaServer:
    def test_unified_cli_gets_server_subcommand(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "llama").write_bytes(b"")
        monkeypatch.setenv("ARCHONITY_LLAMA_SERVER", str(tmp_path / "llama"))
        assert L.find_llama_server() == [str(tmp_path / "llama"), "server"]

    def test_missing_env_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARCHONITY_LLAMA_SERVER", str(tmp_path / "nope" / "llama-server"))
        assert L.find_llama_server() is None

    def test_models_llama_cpp_before_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = tmp_path / "llama.cpp" / ("llama-server.exe" if L.os.name == "nt" else "llama-server")
        exe.parent.mkdir()
        exe.write_bytes(b"")
        monkeypatch.setattr(L, "MODELS_DIR", tmp_path)
        monkeypatch.delenv("ARCHONITY_LLAMA_SERVER", raising=False)
        monkeypatch.setattr(L.shutil, "which", lambda name: f"/usr/bin/{name}")
        assert L.find_llama_server() == [str(exe)]
        exe.unlink()
        assert L.find_llama_server() == ["/usr/bin/llama-server"]
        monkeypatch.setattr(L.shutil, "which", lambda name: "/usr/bin/llama" if name == "llama" else None)
        assert L.find_llama_server() == ["/usr/bin/llama", "server"]


def _models(tmp_path: Path, files: dict[str, bytes], key: str = "llm", **entry) -> Path:
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    spec = {n: {"sha256": hashlib.sha256(b).hexdigest(), "size": len(b)} for n, b in files.items()}
    manifest = {"llm": {"name": "m", "repo": "r/llm", "revision": "0" * 40, "files": {"x.gguf": {"sha256": "0", "size": 1}}},
                "embedder": {"name": "e", "repo": "r/emb", "revision": "1" * 40, "dir": "emb",
                             "files": {"a.json": {"sha256": "0", "size": 1}}},
                "llama_cpp": {}}
    manifest[key] = {**manifest[key], **entry, "files": spec}
    (models / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return models


class TestFetchModels:
    def test_from_file_checks_sha_and_places(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "m.gguf"
        src.parent.mkdir()
        src.write_bytes(b"gguf-test")
        models = _models(tmp_path, {"m.gguf": b"gguf-test"})
        assert fetch.main(["--models-dir", str(models), "--from", str(src)]) == 0
        assert (models / "m.gguf").read_bytes() == b"gguf-test"
        assert fetch.main(["--models-dir", str(models), "--only", "llm", "--check"]) == 0

    def test_from_file_with_wrong_sha_is_rejected(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        src = tmp_path / "m.gguf"
        src.write_bytes(b"gguf-tesT")  # один перевёрнутый бит
        models = _models(tmp_path, {"m.gguf": b"gguf-test"})
        assert fetch.main(["--models-dir", str(models), "--from", str(src)]) == 1
        assert not (models / "m.gguf").exists() and "sha256" in capsys.readouterr().err

    def test_check_without_files_fails(self, tmp_path: Path) -> None:
        models = _models(tmp_path, {"m.gguf": b"gguf-test"})
        assert fetch.main(["--models-dir", str(models), "--only", "llm", "--check"]) == 1

    def test_from_dir_for_embedder(self, tmp_path: Path) -> None:
        files = {"config.json": b"{}", "1_Pooling/config.json": b"{\"p\": 1}"}
        snap = tmp_path / "snapshot"
        for n, b in files.items():
            (snap / n).parent.mkdir(parents=True, exist_ok=True)
            (snap / n).write_bytes(b)
        models = _models(tmp_path, files, key="embedder")
        assert fetch.main(["--models-dir", str(models), "--from", str(snap)]) == 0
        assert (models / "emb" / "1_Pooling" / "config.json").read_bytes() == b"{\"p\": 1}"

    def test_unknown_from_file_needs_only(self, tmp_path: Path) -> None:
        src = tmp_path / "other.gguf"
        src.write_bytes(b"gguf-test")
        models = _models(tmp_path, {"m.gguf": b"gguf-test"})
        assert fetch.main(["--models-dir", str(models), "--from", str(src)]) == 1
        assert fetch.main(["--models-dir", str(models), "--only", "llm", "--from", str(src)]) == 0
        assert (models / "m.gguf").read_bytes() == b"gguf-test"


class TestFetchLlamaCpp:
    @staticmethod
    def _tgz(path: Path, top: str, files: dict[str, bytes]) -> dict:
        import io
        import tarfile

        with tarfile.open(path, "w:gz") as tar:
            for name, data in files.items():
                info = tarfile.TarInfo(f"{top}/{name}")
                info.size, info.mode = len(data), 0o755
                tar.addfile(info, io.BytesIO(data))
        b = path.read_bytes()
        return {"url": f"https://example.invalid/b1/{path.name}", "sha256": hashlib.sha256(b).hexdigest(), "size": len(b)}

    def test_release_archives_unpacked_flat(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src = tmp_path / "src"
        src.mkdir()
        arts = [self._tgz(src / "llama-b1-bin.tar.gz", "llama-b1", {"llama-server": b"elf", "libggml.so": b"so"}),
                self._tgz(src / "cudart-llama-b1.tar.gz", "cudart-llama-b1", {"libcudart.so.12": b"rt"})]
        spec = {"build": "b1", "commit": "c" * 40, "source": "s", "dir": "llama.cpp", "linux_x64_cuda": arts}
        monkeypatch.setattr(fetch, "linux_x64", lambda: True)
        monkeypatch.setattr(fetch.urllib.request, "urlopen", lambda url, timeout: open(src / url.rsplit("/", 1)[1], "rb"))
        assert fetch.fetch_llama_cpp(spec, tmp_path / "models") == []
        dest = tmp_path / "models" / "llama.cpp"
        assert sorted(p.name for p in dest.iterdir()) == ["BUILD", "libcudart.so.12", "libggml.so", "llama-server"]
        monkeypatch.setattr(fetch.urllib.request, "urlopen", None)  # второй прогон ничего не качает
        assert fetch.fetch_llama_cpp(spec, tmp_path / "models") == []

    def test_bad_archive_sha_is_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        art = self._tgz(tmp_path / "llama-b1-bin.tar.gz", "llama-b1", {"llama-server": b"elf"})
        spec = {"build": "b1", "commit": "c" * 40, "source": "s", "dir": "llama.cpp",
                "linux_x64_cuda": [{**art, "sha256": "0" * 64}]}
        monkeypatch.setattr(fetch, "linux_x64", lambda: True)
        monkeypatch.setattr(fetch.urllib.request, "urlopen", lambda url, timeout: open(tmp_path / "llama-b1-bin.tar.gz", "rb"))
        (err,) = fetch.fetch_llama_cpp(spec, tmp_path / "models")
        assert "sha256" in err and not (tmp_path / "models" / "llama.cpp" / "llama-server").exists()

    def test_not_linux_points_to_source_build(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fetch, "linux_x64", lambda: False)
        spec = {**MANIFEST["llama_cpp"]}
        (err,) = fetch.fetch_llama_cpp(spec, tmp_path)
        assert spec["source"] in err


class TestEmbedderModel:
    def test_manifest_entry_only_for_pinned_embedder(self) -> None:
        assert E.manifest_entry("qwen3-4b")["revision"] == MANIFEST["embedder"]["revision"]
        assert E.manifest_entry("gemma2") is None

    def test_local_dir_without_download(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(E, "MODELS_DIR", tmp_path)
        entry = {"repo": "r", "revision": "1" * 40, "dir": "emb", "files": {"config.json": {}}}
        (tmp_path / "emb").mkdir()
        (tmp_path / "emb" / "config.json").write_text("{}", encoding="utf-8")
        assert E.ensure_local(entry) == tmp_path / "emb"

    def test_encode_error_turns_dense_off_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Broken:
            def encode(self, *a, **kw):
                raise RuntimeError("CUDA out of memory")

        loads = []
        emb = E.STEmbedder(E.EmbedSpec("test-none", "r/none", "{q}", "{text}"))
        monkeypatch.setattr(emb, "_load", lambda: loads.append(1) or Broken())
        assert emb.embed_queries(["a", "b"]) is None and emb.misses == 2
        assert emb.embed_queries(["c"]) is None and emb.misses == 3
        assert loads == [1] and "out of memory" in emb._broken
