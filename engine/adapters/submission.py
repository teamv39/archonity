from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from engine.evidence import EvidenceLogger


class SubmissionAdapter:
    """Адаптер экспорта результатов по сценариям."""

    def __init__(
        self,
        project: str = "trainticket",
        evidence_logger: EvidenceLogger | None = None,
    ) -> None:
        self.project = project
        self.evidence_logger = evidence_logger
        self.scenarios: dict[str, list[dict[str, str]]] = {}

    def add_scenario_edges(
        self,
        scenario_id: str,
        methods: Iterable[str],
        calls: Iterable[tuple[str, str]],
        remote: Iterable[tuple[str, str]],
        data: Iterable[tuple[str, str]],
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

        self.scenarios[scenario_id] = edges

        # Регистрация в EvidenceLogger
        if self.evidence_logger:
            for s, t in remote:
                self.evidence_logger.record_remote_call(s, t, scenario_id=scenario_id)
            for s, t in data:
                self.evidence_logger.record_data_access(s, t, scenario_id=scenario_id)
            for m in methods:
                if m.startswith("method:"):
                    svc = m.split(":")[1]
                    self.evidence_logger.record_gateway_route(svc)

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
                            ev_entry = (
                                self.evidence_logger.evidence.get(edge_id, {})
                                if self.evidence_logger
                                else {}
                            )
                            edge_data: dict[str, Any] = {
                                "id": edge_id,
                                "source": svc_src,
                                "target": svc_tgt,
                                "relation_type": "CALLS_HTTP",
                                "source_type": ev_entry.get("source_type", "AST_EXACT"),
                                "confidence": ev_entry.get("confidence", 1.0),
                                "is_reachable": True,
                            }
                            if ev_details := ev_entry.get("evidence_details"):
                                edge_data["evidence_details"] = ev_details
                            edges_list.append(edge_data)

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
                            ev_entry = (
                                self.evidence_logger.evidence.get(edge_id, {})
                                if self.evidence_logger
                                else {}
                            )
                            edge_data = {
                                "id": edge_id,
                                "source": svc_src,
                                "target": db_node_id,
                                "relation_type": "DATABASE",
                                "source_type": ev_entry.get("source_type", "AST_EXACT"),
                                "confidence": ev_entry.get("confidence", 1.0),
                                "is_reachable": True,
                            }
                            if ev_details := ev_entry.get("evidence_details"):
                                edge_data["evidence_details"] = ev_details
                            edges_list.append(edge_data)

        # 4. Маршруты шлюза из evidence_logger
        if self.evidence_logger:
            for edge_id, ev in self.evidence_logger.evidence.items():
                if ev.get("source") == "ts-gateway-service":
                    tgt = ev.get("target")
                    if tgt in nodes_map and edge_id not in seen_edges:
                        if "ts-gateway-service" not in nodes_map:
                            nodes_map["ts-gateway-service"] = {
                                "id": "ts-gateway-service",
                                "name": "ts-gateway-service",
                                "type": "SERVICE",
                                "endpoints": [],
                            }
                        seen_edges.add(edge_id)
                        edge_data = {
                            "id": edge_id,
                            "source": "ts-gateway-service",
                            "target": tgt,
                            "relation_type": "CALLS_HTTP",
                            "source_type": "CONFIG",
                            "confidence": 1.0,
                            "is_reachable": True,
                        }
                        if ev_details := ev.get("evidence_details"):
                            edge_data["evidence_details"] = ev_details
                        edges_list.append(edge_data)

        return {
            "metadata": {
                "generated_at": "2026-10-16T15:30:00Z",
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

    def save_evidence_log(self, output_path: str | Path) -> None:
        if self.evidence_logger:
            self.evidence_logger.save(output_path)
