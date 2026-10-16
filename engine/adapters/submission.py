"""Адаптер для формирования submission.json и канонического графа для visualizer/."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


class SubmissionAdapter:
    """Адаптер экспорта результатов по сценариям."""

    def __init__(self, project: str = "trainticket") -> None:
        self.project = project
        self.scenarios: dict[str, list[dict[str, str]]] = {}

    def add_scenario_edges(
        self,
        scenario_id: str,
        methods: Iterable[str],
        calls: Iterable[tuple[str, str]],
        remote: Iterable[tuple[str, str]],
        data: Iterable[tuple[str, str]],
        stmts: dict[str, list[str]] | None = None,
    ) -> None:
        edges: list[dict[str, str]] = []

        # 1. executes: scenario:S<N> -> method:...
        for m in sorted(methods):
            edges.append({
                "source": f"scenario:{scenario_id}",
                "relation": "executes",
                "target": m,
            })

        # 2. calls: method -> method
        for s, t in sorted(calls):
            edges.append({
                "source": s,
                "relation": "calls",
                "target": t,
            })

        # 3. remote: method -> method (другого сервиса)
        for s, t in sorted(remote):
            edges.append({
                "source": s,
                "relation": "remote",
                "target": t,
            })

        # 4. data: method -> res:table:...
        for s, t in sorted(data):
            edges.append({
                "source": s,
                "relation": "data",
                "target": t,
            })

        # Операторы методов (если есть в скелете, для полноты)
        if stmts:
            for m in sorted(methods):
                for st in stmts.get(m, []):
                    edges.append({
                        "source": f"scenario:{scenario_id}",
                        "relation": "executes",
                        "target": st,
                    })

        self.scenarios[scenario_id] = edges

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "scenarios": {
                sid: {"edges": edges} for sid, edges in sorted(self.scenarios.items())
            },
        }

    def to_canonical_graph(self) -> dict[str, Any]:
        """Преобразование предсказанных связей в канонический формат графа для visualizer/ (ADR-001 / ADR-002)."""
        nodes_map: dict[str, dict[str, Any]] = {}
        edges_list: list[dict[str, Any]] = []
        seen_edges: set[str] = set()

        for sid, edge_list in self.scenarios.items():
            for e in edge_list:
                rel = e["relation"]
                src = e["source"]
                tgt = e["target"]

                # 1. Сервисы из executes / calls
                if rel in ("executes", "calls"):
                    if tgt.startswith("method:"):
                        svc = tgt.split(":")[1]
                        if svc not in nodes_map:
                            nodes_map[svc] = {
                                "id": svc,
                                "name": svc,
                                "type": "SERVICE",
                                "endpoints": [],
                            }
                    if rel == "calls" and src.startswith("method:"):
                        svc_src = src.split(":")[1]
                        if svc_src not in nodes_map:
                            nodes_map[svc_src] = {
                                "id": svc_src,
                                "name": svc_src,
                                "type": "SERVICE",
                                "endpoints": [],
                            }

                # 2. Межсервисные вызовы remote
                elif rel == "remote":
                    if src.startswith("method:") and tgt.startswith("method:"):
                        svc_src = src.split(":")[1]
                        svc_tgt = tgt.split(":")[1]
                        for s in (svc_src, svc_tgt):
                            if s not in nodes_map:
                                nodes_map[s] = {"id": s, "name": s, "type": "SERVICE", "endpoints": []}
                        edge_id = f"{svc_src}->{svc_tgt}:CALLS_HTTP"
                        if edge_id not in seen_edges:
                            seen_edges.add(edge_id)
                            edges_list.append({
                                "id": edge_id,
                                "source": svc_src,
                                "target": svc_tgt,
                                "relation_type": "REST_HTTP",
                                "source_type": "AST_EXACT",
                                "confidence": 1.0,
                                "is_reachable": True,
                            })

                # 3. Базы данных data
                elif rel == "data":
                    if src.startswith("method:") and tgt.startswith("res:table:"):
                        svc_src = src.split(":")[1]
                        db_name = tgt.split(":", 2)[2]
                        db_node_id = f"db-{db_name.replace('.', '-')}"
                        if svc_src not in nodes_map:
                            nodes_map[svc_src] = {"id": svc_src, "name": svc_src, "type": "SERVICE", "endpoints": []}
                        if db_node_id not in nodes_map:
                            nodes_map[db_node_id] = {
                                "id": db_node_id,
                                "name": db_name,
                                "type": "DATABASE",
                                "isTerminalSink": True,
                            }
                        edge_id = f"{svc_src}->{db_node_id}:DATABASE"
                        if edge_id not in seen_edges:
                            seen_edges.add(edge_id)
                            edges_list.append({
                                "id": edge_id,
                                "source": svc_src,
                                "target": db_node_id,
                                "relation_type": "DATABASE",
                                "source_type": "AST_EXACT",
                                "confidence": 1.0,
                                "is_reachable": True,
                            })

        return {
            "metadata": {
                "generated_at": "2026-10-16T14:40:00Z",
                "version": "1.0.0-archonity-engine",
                "total_nodes": len(nodes_map),
                "total_edges": len(edges_list),
            },
            "nodes": sorted(nodes_map.values(), key=lambda n: n["id"]),
            "edges": edges_list,
        }

    def save(self, output_path: str | Path) -> None:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)

    def save_canonical_graph(self, output_path: str | Path) -> None:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_canonical_graph(), f, ensure_ascii=False, indent=2)
