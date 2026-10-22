"""Адаптер и индексатор скелета проекта (`skeleton/<project>.json.gz` пакета задачи)."""
from __future__ import annotations

import collections
import gzip
import json
import re
import zlib
from pathlib import Path
from typing import Any

from engine.adapters.db import DatabaseState, load_db_dump, parse_context
from engine.entities import EntityFacts


# Дамп БД перед каждым сценарием в пакете задачи: `<пакет>/skeleton/<скелет>` -> `<пакет>/context/<дамп>`
DB_DUMP_NAME = "db-after-warmup.sql.gz"


def default_db_dump(skeleton_path: str | Path) -> Path | None:
    """Дамп БД пакета задачи рядом со скелетом или None, если его нет."""
    p = Path(skeleton_path).resolve().parent.parent / "context" / DB_DUMP_NAME
    return p if p.is_file() else None


def load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if p.suffix == ".gz":
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def path_segs(p: str) -> list[str]:
    return [s for s in re.split(r"[/]+", p.split("?")[0]) if s]


def ann_paths(anns: list[dict[str, Any]] | None) -> list[tuple[str | None, list[str]]]:
    out: list[tuple[str | None, list[str]]] = []
    for a in anns or []:
        if a["name"].endswith("Mapping"):
            vals = re.findall(r'"([^"]*)"', a.get("args") or "")
            verb = a["name"].replace("Mapping", "").upper()
            out.append((verb if verb != "REQUEST" else None, vals or [""]))
    return out


def toks(t: str | None) -> list[str]:
    return [
        w.lower()
        for w in re.findall(
            r"[A-Za-z][a-z0-9]+|[A-Z]+(?![a-z])",
            re.sub(r"([a-z])([A-Z])", r"\1 \2", t or ""),
        )
        if len(w) > 2
    ]


class SkeletonIndex:
    """Индекс скелета графа микросервисов."""

    def __init__(
        self,
        skeleton_source: dict[str, Any] | str | Path,
        db_dump_path: str | Path | None = None,
        db_path: str | Path | None = None,
        db_state: DatabaseState | None = None,
        entity_facts: EntityFacts | None = None,
        entity_ir_path: str | Path | None = None,
    ) -> None:
        """Дамп БД: `db_state`, иначе `db_dump_path`, иначе — дамп пакета рядом со скелетом, если скелет передан
        путём (`default_db_dump`). Без дампа мир БД пуст."""
        resolved_db_path = db_path or db_dump_path
        if isinstance(skeleton_source, (str, Path)):
            skeleton_dict = load_json(skeleton_source)
            if resolved_db_path is None and db_state is None:
                resolved_db_path = default_db_dump(skeleton_source)
        else:
            skeleton_dict = skeleton_source

        self.sk = skeleton_dict
        self.project: str = skeleton_dict.get("project", "")
        self.N: dict[str, dict[str, Any]] = skeleton_dict["nodes"]

        # Пре-индексация узлов таблиц для быстрого доступа
        self.table_nodes: dict[str, dict[str, Any]] = {
            nid: n for nid, n in self.N.items() if nid.startswith("res:table:")
        }

        # Состояние БД перед сценарием (дамп пакета задачи). Дампа нет или он битый — мир БД пуст, а причина в
        # `db_error`: run_eval.py выносит её в рамку ATTENTION (Р2), иначе M4 молча теряет рёбра чтения
        self.db_error: Exception | None = None
        if db_state is not None:
            self.db_state: DatabaseState = db_state
        elif resolved_db_path is not None:
            try:
                self.db_state = load_db_dump(resolved_db_path)
            except (OSError, ValueError, EOFError, zlib.error) as e:  # обрезанный gzip — EOFError или zlib.error
                self.db_state = DatabaseState()
                self.db_error = e
        else:
            self.db_state = DatabaseState()
            if isinstance(skeleton_source, (str, Path)):
                expected = Path(skeleton_source).resolve().parent.parent / "context" / DB_DUMP_NAME
                self.db_error = FileNotFoundError(f"дамп БД не найден: {expected}")

        # Контекст сценариев (поле `context` скелета): пассажир, даты, баланс
        ctx = skeleton_dict.get("context")
        self.context: dict[str, Any] = parse_context(
            " ".join(str(v) for v in ctx.values()) if isinstance(ctx, dict) else str(ctx or ""))

        self.handlers: list[tuple[str, str | None, list[str]]] = []
        for nid, n in self.N.items():
            if n.get("kind") != "method":
                continue
            mp = ann_paths(n.get("annotations"))
            if not mp:
                continue
            cls_paths = [
                v
                for _, vals in ann_paths(self.N.get(n["owner"], {}).get("annotations"))
                for v in vals
            ] or [""]
            for verb, vals in mp:
                for v in vals:
                    for cp in cls_paths:
                        self.handlers.append((nid, verb, path_segs(cp + "/" + v)))

        cs_method: dict[str, str] = {}
        self.cs_nodes_by_method: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        self.type_nodes: dict[str, dict[str, Any]] = {}
        self.methods_by_owner: dict[str, list[tuple[str, dict[str, Any]]]] = collections.defaultdict(list)
        for nid, n in self.N.items():
            k = n.get("kind")
            if k == "call_site":
                m = n.get("method")
                if m:
                    cs_method[nid] = m
                    self.cs_nodes_by_method[m].append(n)
            elif k == "type":
                self.type_nodes[nid] = n
            elif k == "method":
                owner = n.get("owner")
                if owner:
                    self.methods_by_owner[owner].append((nid, n))
        # Факты archparse о сущностях (R7, R10)
        self.entities: EntityFacts = (
            entity_facts if entity_facts is not None else EntityFacts.load(entity_ir_path)
        )

        self.calls: dict[str, set[str]] = collections.defaultdict(set)
        self.over: dict[str, set[str]] = collections.defaultdict(set)
        self.wiring: dict[str, dict[str, set[str]]] = collections.defaultdict(
            lambda: collections.defaultdict(set)
        )
        for e in skeleton_dict.get("edges", []):
            etype = e["type"]
            src = e["source"]
            tgt = e["target"]
            if etype == "calls":
                self.calls[cs_method.get(src, src)].add(tgt)
            elif etype == "overrides":
                self.over[tgt].add(src)
            elif etype in ("remote_call", "message_delivery", "runtime_dispatch", "data_access"):
                self.wiring[etype][cs_method.get(src, src)].add(tgt)

        self.entities.bind(self.N, skeleton_dict.get("edges", []))

        self.module = {
            nid: n.get("module") for nid, n in self.N.items() if n.get("kind") == "method"
        }
        self.units = {
            n.get("name", ""): set(n.get("deployment_units") or [n.get("name", "")])
            for n in self.N.values()
            if n.get("kind") == "module"
        }
        self.size = collections.Counter(u for us in self.units.values() for u in us)

    def unit_of(self, m: str) -> str:
        mod = self.module.get(m, "")
        units = self.units.get(mod, {mod})
        return min(units, key=lambda u: (self.size.get(u, 0), u))

    def cha(self, m: str) -> set[str]:
        out, st = set(), [m]
        while st:
            x = st.pop()
            for o in self.over.get(x, ()):
                if o not in out:
                    out.add(o)
                    st.append(o)
        return out

    def table_resource_to_db(self, table_node_id: str) -> str:
        """Имя таблицы дампа по ID узла скелета: 'res:table:<service>.orders' -> 'orders'."""
        if self.db_state is not None:
            return self.db_state.normalize_table_name(table_node_id)
        if table_node_id.startswith("res:table:"):
            raw = table_node_id[len("res:table:"):]
            return raw.split(".", 1)[1] if "." in raw else raw
        return table_node_id

    def get_table_records(self, table_or_node: str) -> list[dict[str, Any]]:
        """Возвращает записи таблицы по имени или ID узла скелета."""
        if self.db_state is None:
            return []
        return self.db_state.get_table(table_or_node)
