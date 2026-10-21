"""Привязка артефактов к проекту: IR тел методов (`data/ir`) и `entity_ir.json` строит archparse по одному проекту,
а читаются они при любом `--skeleton`/`--targets`. Здесь их сверяют со скелетом при старте конвейера: на другом
проекте прогон не должен молча взять чужие факты (аудит универсальности, раздел 12).

Признаки чужих артефактов:
- IR: доля ID методов, которых нет в `nodes` скелета (archparse берёт ID из скелета дословно, свой IR даёт 0%);
- entity_ir: вызовы репозиториев без call_site в скелете (`EntityFacts.bind`), сущности без типа в скелете, файл
  не загрузился.

Доля от `STALE_SHARE_LIMIT` и выше — ошибка с командой пересборки archparse, меньшая — предупреждение
(скелет и артефакты разных коммитов одного проекта). Кеш каталога UI проверяется отдельно: он пересобирается
сам, чистым Python (`engine/grounding/ui_catalog.py`, `catalog_fingerprint`).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.adapters.skeleton import SkeletonIndex

LOGGER = logging.getLogger(__name__)

ARCHPARSE_DIR = Path(__file__).resolve().parent.parent / "archparse"
STALE_SHARE_LIMIT = 0.05
EXAMPLES = 2
EXAMPLE_WIDTH = 100


class ArtifactMismatch(RuntimeError):
    """Артефакты построены не по этому скелету; в тексте — что не сошлось и как пересобрать."""


def method_ir_ids(ir_dir: Path) -> tuple[set[str], int]:
    """ID методов во всех `<module>.json` папки IR и число этих файлов."""
    ids: set[str] = set()
    files = sorted(Path(ir_dir).glob("*.json")) if Path(ir_dir).is_dir() else []
    for p in files:
        with open(p, encoding="utf-8") as f:
            ids.update(json.load(f).get("methods", {}))
    return ids, len(files)


def _share(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


def _arg(path: Path) -> str:
    """Путь для `--args` gradle: от `archparse/`, без пробелов в абсолютном пути (environment_guide, раздел 2)."""
    p = Path(path).resolve()
    try:
        return Path(os.path.relpath(p, ARCHPARSE_DIR)).as_posix()
    except ValueError:  # другой диск Windows
        return p.as_posix()


def _examples(ids: list[str]) -> str:
    return ", ".join(i if len(i) <= EXAMPLE_WIDTH else i[:EXAMPLE_WIDTH - 1] + "…" for i in ids[:EXAMPLES])


def _problem(what: str, bad: int, whole: int, kind: str, examples: list[str]) -> str:
    tail = f", например {_examples(examples)}" if examples else ""
    return f"{what}: {bad} из {whole} ({_share(bad, whole):.0%}) {kind}{tail}"


def check_artifacts(index: SkeletonIndex, ir_dir: Path, skeleton_path: Path, targets_root: Path) -> None:
    """Сверка IR тел методов и `entity_ir.json` со скелетом; несовпадение — `ArtifactMismatch`.

    Вызывать до M1 и M4: ошибка должна прийти раньше, чем начнётся долгая работа над чужим проектом."""
    problems: list[str] = []
    rebuild: list[str] = []
    ir_dir = Path(ir_dir)
    base = f"--targets-dir {_arg(targets_root)} --skeleton {_arg(skeleton_path)}"

    ir_ids, files = method_ir_ids(ir_dir)
    if not files:
        problems.append(f"IR тел методов ({ir_dir}): нет ни одного <module>.json")
        rebuild.append(f"--mode bodies {base} -o {_arg(ir_dir)}")
    else:
        stale = sorted(ir_ids - set(index.N))
        share = _share(len(stale), len(ir_ids))
        if share >= STALE_SHARE_LIMIT:
            problems.append(_problem(f"IR тел методов ({ir_dir})", len(stale), len(ir_ids),
                                     "ID методов нет в скелете", stale))
            rebuild.append(f"--mode bodies {base} -o {_arg(ir_dir)}")
        elif stale:
            LOGGER.warning("IR тел методов (%s): %d из %d ID методов нет в скелете (%s), например %s: возможно, IR "
                           "другого коммита", ir_dir, len(stale), len(ir_ids), f"{share:.1%}", _examples(stale))

    facts = index.entities
    entity_ir = facts.source
    entity_bad = False
    if facts.load_error:
        entity_bad = True
        problems.append(f"entity_ir.json ({entity_ir}): не загружен ({facts.load_error})")
    else:
        types = {n.get("fqn") for n in index.type_nodes.values()}
        no_type = sorted(e["type"] for e in facts.raw_entities if e["type"] not in types)
        for what, bad, whole, kind, examples in (
            ("вызовы репозиториев", facts.unmatched_calls, len(facts.raw_calls), "без call_site в скелете", []),
            ("сущности", len(no_type), len(facts.raw_entities), "без типа в скелете", no_type),
        ):
            share = _share(bad, whole)
            if share >= STALE_SHARE_LIMIT:
                entity_bad = True
                problems.append(_problem(f"entity_ir.json ({entity_ir}), {what}", bad, whole, kind, examples))
            elif bad:
                LOGGER.warning("entity_ir.json (%s), %s: %d из %d (%s) %s: возможно, факты другого коммита",
                               entity_ir, what, bad, whole, f"{share:.1%}", kind)
    if entity_bad:
        rebuild.append(f"--mode entities {base} -o {_arg(entity_ir) if entity_ir else 'entity_ir.json'}")

    if not problems:
        return
    cmds = "\n".join(f'  gradlew -q run "--args={r}"' for r in dict.fromkeys(rebuild))
    raise ArtifactMismatch(
        f"Артефакты не соответствуют скелету {skeleton_path} (проект {index.project or '?'}, коммит "
        f"{str(index.sk.get('commit') or '?')[:12]}):\n  - " + "\n  - ".join(problems)
        + "\nВероятно, они построены по другому проекту или коммиту. Пересоберите archparse (JDK 17+, из папки "
        "archparse/; Windows: gradlew.bat, docs/environment_guide.md, раздел 2):\n" + cmds)
