"""Привязка артефактов к проекту: IR тел методов (`data/ir`) и `entity_ir.json` строит разбор исходников
(`archonity-parse`, Rust, ADR-009; Java-`archparse` — эталон) по одному проекту,
а читаются они при любом `--skeleton`/`--targets`. Здесь их сверяют со скелетом при старте конвейера: на другом
проекте прогон не должен молча взять чужие факты (аудит универсальности, раздел 12).

Признаки чужих артефактов:
- IR: доля ID методов, которых нет в `nodes` скелета (разбор берёт ID из скелета дословно, свой IR даёт 0%);
- entity_ir: вызовы репозиториев без call_site в скелете (`EntityFacts.bind`), сущности без типа в скелете, файл
  не загрузился.

Доля от `STALE_SHARE_LIMIT` и выше — ошибка с командой пересборки разбора, меньшая — предупреждение
(скелет и артефакты разных коммитов одного проекта). Кеш каталога UI проверяется отдельно: он пересобирается
сам, чистым Python (`engine/grounding/ui_catalog.py`, `catalog_fingerprint`).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.adapters.skeleton import SkeletonIndex

LOGGER = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
PARSE_BIN = "rust/target/release/archonity-parse"
# Артефакты проекта по умолчанию: ir/, entity_ir.json, ui_catalog.json; другой проект — `--artifacts-dir`
DEFAULT_ARTIFACTS_DIR = ROOT / "data"
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
    """Путь для команды пересборки: от корня репозитория, если он внутри, иначе абсолютный."""
    p = Path(path).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def _examples(ids: list[str]) -> str:
    return ", ".join(i if len(i) <= EXAMPLE_WIDTH else i[:EXAMPLE_WIDTH - 1] + "…" for i in ids[:EXAMPLES])


def _problem(what: str, bad: int, whole: int, kind: str, examples: list[str]) -> str:
    tail = f", например {_examples(examples)}" if examples else ""
    return f"{what}: {bad} из {whole} ({_share(bad, whole):.0%}) {kind}{tail}"


def check_artifacts(index: SkeletonIndex, ir_dir: Path, skeleton_path: Path, targets_root: Path,
                    artifacts_dir: Path = DEFAULT_ARTIFACTS_DIR) -> None:
    """Сверка IR тел методов и `entity_ir.json` со скелетом; несовпадение — `ArtifactMismatch`.

    Вызывать до M1 и M4: ошибка должна прийти раньше, чем начнётся долгая работа над чужим проектом.
    `artifacts_dir` — папка артефактов прогона: если это не `data/` по умолчанию, команды пересборки пишут в неё
    только то, что не сошлось; иначе — в новую папку проекта `artifacts/<проект>`, чтобы не затереть `data/`."""
    problems: list[str] = []
    bad_ir = False
    ir_dir = Path(ir_dir)
    base = f"--targets-dir {_arg(targets_root)} --skeleton {_arg(skeleton_path)}"

    ir_ids, files = method_ir_ids(ir_dir)
    if not files:
        bad_ir = True
        problems.append(f"IR тел методов ({ir_dir}): нет ни одного <module>.json")
    else:
        stale = sorted(ir_ids - set(index.N))
        share = _share(len(stale), len(ir_ids))
        if share >= STALE_SHARE_LIMIT:
            bad_ir = True
            problems.append(_problem(f"IR тел методов ({ir_dir})", len(stale), len(ir_ids),
                                     "ID методов нет в скелете", stale))
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
    if not problems:
        return
    own = Path(artifacts_dir).resolve() != DEFAULT_ARTIFACTS_DIR.resolve()
    if own:
        out_ir, out_entity = ir_dir, entity_ir or Path("entity_ir.json")
        modes = [(m, o) for ok, m, o in ((bad_ir, "bodies", out_ir), (entity_bad, "entities", out_entity)) if ok]
        hint = ""
    else:
        slug = re.sub(r"[^\w.-]+", "-", index.project).strip("-") or "project"
        out = ROOT / "artifacts" / slug
        modes = [("bodies", out / "ir"), ("entities", out / "entity_ir.json")]
        hint = (f"\nАртефакты другого проекта держите в отдельной папке, не в {DEFAULT_ARTIFACTS_DIR.name}/: "
                f"после пересборки запускайте run_eval.py --artifacts-dir {out.relative_to(ROOT).as_posix()}. "
                f"Тот же проект, новый коммит: те же команды с -o {DEFAULT_ARTIFACTS_DIR.name}/ir и "
                f"-o {DEFAULT_ARTIFACTS_DIR.name}/entity_ir.json.")
    cmds = "\n".join(f"  {PARSE_BIN} --mode {m} {base} -o {_arg(o)}" for m, o in modes)
    raise ArtifactMismatch(
        f"Артефакты не соответствуют скелету {skeleton_path} (проект {index.project or '?'}, коммит "
        f"{str(index.sk.get('commit') or '?')[:12]}):\n  - " + "\n  - ".join(problems)
        + "\nВероятно, они построены по другому проекту или коммиту. Пересоберите их разбором исходников на Rust (из "
        "корня репозитория; сборка: (cd rust && cargo build --release --locked); docs/environment_guide.md, раздел 2; "
        "Java-archparse остаётся эталоном):\n" + cmds + hint)
