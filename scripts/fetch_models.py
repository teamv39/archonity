"""Модели по манифесту `models/manifest.json`: скачать в `models/` с закреплённой ревизией и проверить sha256.

    python scripts/fetch_models.py                       # LLM (17.7 ГБ) и эмбеддер (8 ГБ)
    python scripts/fetch_models.py --llama-cpp           # и сборка llama.cpp (Linux x64, CUDA 12.8) в models/llama.cpp
    python scripts/fetch_models.py --check               # только проверить то, что уже лежит в models/
    python scripts/fetch_models.py --from D:\\models\\Qwen3.6-35B-A3B-UD-IQ4_XS.gguf
    python scripts/fetch_models.py --only embedder --from <кеш HF>/models--Qwen--Qwen3-Embedding-4B/snapshots/<ревизия>

`--from` — локальный файл (LLM) или каталог (эмбеддер) вместо скачивания. Запись манифеста выбирается по имени файла
или по `--only`; другие записи не трогаются. Сначала проверяется sha256 источника, затем в `models/` ставится жёсткая
ссылка (тот же диск) или копия; копия проверяется ещё раз. Файл, который уже лежит в `models/` с верным sha256,
не перекачивается. Код выхода 1 — хоть один файл не прошёл проверку.

LLM качается файлом GGUF в `models/`, эмбеддер — каталогом `models/<dir>` (так их ищут engine/grounding/llm.py и
embedder.py). llama.cpp — релизный архив сборки манифеста и архив CUDA runtime, распакованные в `models/llama.cpp`;
`llama-server` оттуда клиент LLM находит сам.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import tarfile
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"
ENTRIES = ("llm", "embedder")
CHUNK = 16 << 20


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(CHUNK):
            h.update(b)
    return h.hexdigest()


def check(path: Path, spec: dict[str, Any]) -> str | None:
    """None — файл совпал с манифестом; иначе причина."""
    if not path.is_file():
        return "нет файла"
    size = path.stat().st_size
    if size != spec["size"]:
        return f"размер {size}, ожидается {spec['size']}"
    digest = sha256(path)
    if digest != spec["sha256"]:
        return f"sha256 {digest}, ожидается {spec['sha256']}"
    return None


def place(src: Path, dst: Path, spec: dict[str, Any], name: str) -> str | None:
    """Проверить источник и поставить его в `dst`: жёсткая ссылка, если тот же диск, иначе копия с повторной проверкой."""
    err = check(src, spec)
    if err:
        return f"источник {src}: {err}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    part.unlink(missing_ok=True)
    try:
        os.link(src.resolve(), part)
        how = "жёсткая ссылка"
    except OSError:
        shutil.copyfile(src, part)
        how = "копия"
        err = check(part, spec)
        if err:
            part.unlink(missing_ok=True)
            return f"копия {src}: {err}"
    os.replace(part, dst)
    print(f"  {name}: sha256 верен, {how} из {src}")
    return None


def download(entry: dict[str, Any], name: str, root: Path, spec: dict[str, Any]) -> str | None:
    """Файл `name` записи с ревизией манифеста в `root` (подкаталоги имени сохраняются)."""
    from huggingface_hub import hf_hub_download

    path = Path(hf_hub_download(entry["repo"], name, revision=entry["revision"], local_dir=root))
    err = check(path, spec)
    if err:
        path.unlink(missing_ok=True)
        return f"{entry['repo']}@{entry['revision'][:12]}/{name}: {err}"
    print(f"  {name}: скачан, sha256 верен")
    return None


def fetch_entry(key: str, entry: dict[str, Any], models_dir: Path, src: Path | None, only_check: bool) -> list[str]:
    root = models_dir / entry.get("dir", ".")
    print(f"{key}: {entry['repo']}@{entry['revision']} -> {root}")
    errors = []
    for name, spec in entry["files"].items():
        dst = root / name
        if dst.is_file() and check(dst, spec) is None:
            print(f"  {name}: на месте, sha256 верен")
            continue
        if only_check:
            errors.append(f"{dst}: {check(dst, spec)}")
            continue
        if src is not None:
            err = place(src if src.is_file() else src / name, dst, spec, name)
        else:
            err = download(entry, name, root, spec)
        if err:
            errors.append(err)
    return errors


def match_from(src: Path, manifest: dict[str, Any], only: str | None) -> str | None:
    """Запись манифеста для `--from`: `--only` или та, где есть файл с этим именем (файл) или все файлы (каталог)."""
    if only:
        return only
    for key in ENTRIES:
        files = manifest[key]["files"]
        if (src.is_file() and src.name in files) or (src.is_dir() and all((src / f).is_file() for f in files)):
            return key
    return None


def linux_x64() -> bool:
    return sys.platform.startswith("linux") and platform.machine() in ("x86_64", "AMD64")


def fetch_llama_cpp(spec: dict[str, Any], models_dir: Path) -> list[str]:
    """Релизные архивы llama.cpp (сборка и CUDA runtime) в `models/<dir>`, без верхнего каталога архива."""
    dest = models_dir / spec["dir"]
    stamp = dest / "BUILD"
    want = " ".join([spec["build"], *(a["sha256"] for a in spec["linux_x64_cuda"])])
    print(f"llama.cpp {spec['build']} ({spec['commit'][:9]}) -> {dest}")
    if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == want and (dest / "llama-server").is_file():
        print("  на месте")
        return []
    if not linux_x64():
        return [f"llama.cpp: релизные архивы манифеста — для Linux x64, здесь {sys.platform}/{platform.machine()}; "
                f"сборка из исходников: {spec['source']}"]
    dest.mkdir(parents=True, exist_ok=True)
    for art in spec["linux_x64_cuda"]:
        tgz = dest / art["url"].rsplit("/", 1)[1]
        if check(tgz, art) is not None:
            t0 = time.time()
            print(f"  качаю {art['url']} ({art['size'] / 2**20:.0f} МБ)")
            with urllib.request.urlopen(art["url"], timeout=60) as r, open(tgz, "wb") as f:
                shutil.copyfileobj(r, f, CHUNK)
            err = check(tgz, art)
            if err:
                tgz.unlink(missing_ok=True)
                return [f"{art['url']}: {err}"]
            print(f"  {tgz.name}: sha256 верен, {time.time() - t0:.0f} с")
        with tarfile.open(tgz) as tar:
            members = []
            for m in tar.getmembers():
                parts = m.name.split("/", 1)
                if len(parts) < 2 or not parts[1]:
                    continue
                m.name = parts[1]
                if m.islnk():
                    m.linkname = m.linkname.split("/", 1)[-1]
                members.append(m)
            kw = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
            tar.extractall(dest, members=members, **kw)
        tgz.unlink()
    if not (dest / "llama-server").is_file():
        return [f"llama.cpp: в архивах нет llama-server ({dest})"]
    stamp.write_text(want + "\n", encoding="utf-8")
    print(f"  {dest / 'llama-server'} готов")
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Скачать и проверить модели по models/manifest.json")
    ap.add_argument("--only", choices=ENTRIES, help="одна запись манифеста")
    ap.add_argument("--from", dest="src", type=Path, help="локальный файл или каталог вместо скачивания")
    ap.add_argument("--check", action="store_true", help="только проверить models/, ничего не качать")
    ap.add_argument("--llama-cpp", action="store_true", help="ещё сборку llama.cpp (Linux x64, CUDA 12.8)")
    ap.add_argument("--models-dir", type=Path, default=MODELS_DIR, help="каталог моделей с manifest.json")
    a = ap.parse_args(argv)
    manifest = json.loads((a.models_dir / "manifest.json").read_text(encoding="utf-8"))
    keys = [a.only] if a.only else list(ENTRIES)
    if a.src is not None:
        if not a.src.exists():
            print(f"--from {a.src}: нет такого файла или каталога", file=sys.stderr)
            return 1
        key = match_from(a.src, manifest, a.only)
        if key is None:
            print(f"--from {a.src}: не совпадает ни с одной записью манифеста, укажите --only", file=sys.stderr)
            return 1
        keys = [key]
    errors = []
    for key in keys:
        errors += fetch_entry(key, manifest[key], a.models_dir, a.src, a.check)
    if a.llama_cpp and not a.check:
        errors += fetch_llama_cpp(manifest["llama_cpp"], a.models_dir)
    for e in errors:
        print(f"ОШИБКА: {e}", file=sys.stderr)
    print("готово" if not errors else f"ошибок: {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
