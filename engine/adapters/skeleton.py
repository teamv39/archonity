"""Адаптер и индексатор скелета проекта skeleton/trainticket.json.gz."""
from __future__ import annotations

import collections
import gzip
import json
import re
from pathlib import Path
from typing import Any

from engine.adapters.db import DatabaseState, TableNodeResolution, load_db_dump


def load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if p.suffix == ".gz":
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def path_segs(p: str) -> list[str]:
    return [s for s in re.split(r"[/]+", p.split("?")[0]) if s]


def match_path(req: list[str], tpl: list[str]) -> bool:
    """Сегменты запроса против шаблона Spring: {x} — один сегмент, ** — хвост."""
    if not tpl:
        return not req
    t = tpl[0]
    if t == "**":
        return True
    if not req:
        return False
    if t.startswith("{") or t == "*" or t == req[0]:
        return match_path(req[1:], tpl[1:])
    return False


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
    ) -> None:
        if isinstance(skeleton_source, (str, Path)):
            skeleton_dict = load_json(skeleton_source)
        else:
            skeleton_dict = skeleton_source

        self.sk = skeleton_dict
        self.project: str = skeleton_dict.get("project", "trainticket")
        self.N: dict[str, dict[str, Any]] = skeleton_dict["nodes"]

        # Пре-индексация узлов таблиц для быстрого доступа
        self.table_nodes: dict[str, dict[str, Any]] = {
            nid: n for nid, n in self.N.items() if nid.startswith("res:table:")
        }

        # Интеграция состояния БД (Milestone M0)
        resolved_db_path = db_path or db_dump_path
        if db_state is not None:
            self.db_state: DatabaseState = db_state
        elif resolved_db_path is not None:
            try:
                self.db_state = load_db_dump(resolved_db_path)
            except (FileNotFoundError, OSError, ValueError):
                self.db_state = DatabaseState()
        else:
            default_path = self._find_default_db_dump()
            if default_path is not None and default_path.is_file():
                try:
                    self.db_state = load_db_dump(default_path)
                except (FileNotFoundError, OSError, ValueError):
                    self.db_state = DatabaseState()
            else:
                self.db_state = DatabaseState()

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

        self.cs_method = {
            nid: n["method"] for nid, n in self.N.items() if n.get("kind") == "call_site"
        }
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
                caller = self.cs_method.get(src, src)
                self.calls[caller].add(tgt)
            elif etype == "overrides":
                self.over[tgt].add(src)
            elif etype in ("remote_call", "message_delivery", "runtime_dispatch", "data_access"):
                caller = self.cs_method.get(src, src)
                self.wiring[etype][caller].add(tgt)

        self.module = {
            nid: n.get("module") for nid, n in self.N.items() if n.get("kind") == "method"
        }
        self.units = {
            n.get("name", ""): set(n.get("deployment_units") or [n.get("name", "")])
            for n in self.N.values()
            if n.get("kind") == "module"
        }
        self.size = collections.Counter(u for us in self.units.values() for u in us)
        self.stmts: dict[str, list[str]] = collections.defaultdict(list)
        for e in skeleton_dict.get("edges", []):
            if e["type"] == "contains" and e["target"].startswith("stmt:"):
                self.stmts[e["source"]].append(e["target"])

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

    def handlers_for(self, method: str | None, path: str, host: str | None = None) -> set[str]:
        segs = path_segs(path)
        out = set()
        for nid, verb, tpl in self.handlers:
            if host and host not in (self.N[nid].get("module") or ""):
                continue
            if (verb is None or method is None or verb == method) and match_path(segs, tpl):
                out.add(nid)
        return out

    def handler_docs(self) -> dict[str, list[str]]:
        docs: dict[str, list[str]] = {}
        for nid, _, tpl in self.handlers:
            docs.setdefault(nid, []).extend(
                toks(" ".join(tpl)) * 3
                + toks(self.N[nid].get("name", "")) * 2
                + toks(self.N[nid].get("module", ""))
            )
        return docs

    @staticmethod
    def _find_default_db_dump() -> Path | None:
        """Поиск дампа базы данных по стандартным путям проекта."""
        candidates = [
            Path("hackaton/tt-challenge/context/db-after-warmup.sql.gz"),
            Path("context/db-after-warmup.sql.gz"),
            Path(__file__).resolve().parent.parent.parent / "hackaton" / "tt-challenge" / "context" / "db-after-warmup.sql.gz",
        ]
        for c in candidates:
            if c.is_file():
                return c
        return None

    @staticmethod
    def service_to_db_name(service_name: str) -> str:
        """Преобразует имя сервиса в имя базы данных MySQL:
        'ts-order-service' -> 'ts_order'
        'ts-consign-mysql' -> 'ts_consign'
        'ts-travel2-service' -> 'ts_travel2'
        'ts-food-delivery-service' -> 'ts_food_delivery'
        """
        clean = service_name
        if clean.endswith("-service"):
            clean = clean[:-len("-service")]
        elif clean.endswith("-mysql"):
            clean = clean[:-len("-mysql")]
        return clean.replace("-", "_")

    def table_resource_to_db(self, table_node_id: str) -> str:
        """Извлекает каноническое имя таблицы из ID узла скелета.
        'res:table:ts-order-service.orders' -> 'orders'
        'res:table:ts-consign-mysql.consign_record' -> 'consign_record'
        """
        if self.db_state is not None:
            return self.db_state.normalize_table_name(table_node_id)
        if table_node_id.startswith("res:table:"):
            raw = table_node_id[len("res:table:"):]
            return raw.split(".", 1)[1] if "." in raw else raw
        return table_node_id

    def table_resource_to_qualified_db(self, table_node_id: str) -> str:
        """Преобразует узел скелета в квалифицированное имя <db>.<table_name>.
        'res:table:ts-order-service.orders' -> 'ts_order.orders'
        'res:table:ts-consign-mysql.consign_record' -> 'ts_consign.consign_record'
        """
        if not table_node_id.startswith("res:table:"):
            raise ValueError(f"Not a table resource node: {table_node_id}")
        raw = table_node_id[len("res:table:"):]
        svc, tbl = raw.split(".", 1) if "." in raw else ("", raw)
        dbname = self.service_to_db_name(svc)
        return f"{dbname}.{tbl}" if dbname else tbl

    def resolve_table_node(self, table_node_id: str) -> TableNodeResolution:
        """Возвращает метаданные и записи узла таблицы скелета:
        {
            'node_id': 'res:table:ts-order-service.orders',
            'service': 'ts-order-service',
            'db': 'ts_order',
            'table': 'orders',
            'qualified': 'ts_order.orders',
        }
        Поддерживает интерфейсы dict[str, str] и list[dict[str, Any]].
        """
        if not table_node_id.startswith("res:table:"):
            raise ValueError(f"Not a table resource node: {table_node_id}")
        raw = table_node_id[len("res:table:"):]
        svc, tbl = raw.split(".", 1) if "." in raw else ("", raw)
        dbname = self.service_to_db_name(svc)
        meta = {
            "node_id": table_node_id,
            "service": svc,
            "db": dbname,
            "table": tbl,
            "qualified": f"{dbname}.{tbl}" if dbname else tbl,
        }
        rows = self.get_table_records(table_node_id)
        return TableNodeResolution(rows, meta)

    def get_table_records(self, table_or_node: str) -> list[dict[str, Any]]:
        """Возвращает записи таблицы по имени или ID узла скелета."""
        if self.db_state is None:
            return []
        return self.db_state.get_table(table_or_node)

    def get_table_rows(self, table_node_id: str) -> list[dict[str, Any]]:
        """Алиас для get_table_records."""
        return self.get_table_records(table_node_id)

