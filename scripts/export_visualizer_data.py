#!/usr/bin/env python3
"""Экспорт и синхронизация реальных данных пайплайна для visualizer/.

Генерирует:
1. visualizer/public/data/canonical_graph.json — граф архитектуры (сервисы, БД, очереди).
2. visualizer/public/data/scenarios_data.json — 8 сценариев TechArena (S0–S7) с полной трассировкой шагов.
3. visualizer/public/data/decisions.json — Decision Ledger (evidence v2) со всеми правилами.
4. visualizer/public/data/step_requests.json — заземленные запросы шагов M1.
5. visualizer/src/data/scenariosData.ts — типизированный TS-модуль сценариев для мгновенного offline-демо.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = ROOT / "hackaton" / "tt-challenge" / "scenarios"
OUTPUT_DIR = ROOT / "output"
VIS_DATA_DIR = ROOT / "visualizer" / "public" / "data"
VIS_SRC_DATA_DIR = ROOT / "visualizer" / "src" / "data"

SCENARIO_TITLES_RU: dict[str, str] = {
    "S0": "S0: Калибровка пользователя и контактов",
    "S1": "S1: Бронирование скоростного поезда (еда, страховка, багаж)",
    "S2": "S2: Обычный поезд, отмена и пересадка на дешевое место",
    "S3": "S3: Бронирование со станционной едой и пересадка",
    "S4": "S4: Регистрация, вход и внешняя оплата",
    "S5": "S5: Сложный маршрут и пересадка на обычный поезд",
    "S6": "S6: Админ-операции (маршруты, поезда, цены, конфиги)",
    "S7": "S7: Пересадка с доплатой и отказ при возврате",
}


def build_scenarios_data(out_dir: Path = OUTPUT_DIR) -> list[dict[str, Any]]:
    """Сборка структурированных данных сценариев S0–S7 на базе step_requests и decisions прогона в `out_dir`."""
    step_requests_file = out_dir / "step_requests.json"
    decisions_file = out_dir / "decisions.json"

    if not step_requests_file.is_file() or not decisions_file.is_file():
        raise FileNotFoundError("Сначала выполните run_eval.py для генерации step_requests и decisions!")

    step_requests_all: dict[str, list[dict[str, Any]]] = json.loads(step_requests_file.read_text(encoding="utf-8"))
    decisions_all: dict[str, dict[str, Any]] = json.loads(decisions_file.read_text(encoding="utf-8")).get("scenarios", {})

    canonical_file = out_dir / "canonical_graph.json"
    canonical_edges: set[str] = set()
    if canonical_file.is_file():
        cg = json.loads(canonical_file.read_text(encoding="utf-8"))
        canonical_edges = {e["id"] for e in cg.get("edges", [])}

    scenarios_list: list[dict[str, Any]] = []

    scenario_paths = sorted(SCENARIOS_DIR.glob("S*.json"), key=lambda p: int(p.stem[1:]) if p.stem[1:].isdigit() else 99)

    for sp in scenario_paths:
        sid = sp.stem
        raw_sc = json.loads(sp.read_text(encoding="utf-8"))
        sc_reqs = {r["step"]: r for r in step_requests_all.get(sid, [])}
        sc_decs = decisions_all.get(sid, {})

        sc_title_ru = SCENARIO_TITLES_RU.get(sid, f"{sid}: {raw_sc.get('title', '')}")

        steps_data: list[dict[str, Any]] = []

        for st in raw_sc.get("steps", []):
            n = st.get("n", 1)
            action = st.get("action", "")
            req = sc_reqs.get(n, {})

            # Находим все рёбра decisions, активные на этом шаге
            active_dec_keys = [k for k, v in sc_decs.items() if n in v.get("steps", []) and v.get("included")]

            services: set[str] = set()
            tables: set[str] = set()
            rules: set[str] = set()
            active_edges: set[str] = set()
            active_nodes: set[str] = set()

            handler = req.get("handler", "")
            primary_service = ""
            if handler.startswith("method:"):
                primary_service = handler.split(":")[1]
                services.add(primary_service)
                active_nodes.add(primary_service)

            http_info = req.get("http") or {}
            verb = http_info.get("method", "GET")
            path = http_info.get("path", "")

            # Разбор рёбер decisions текущего шага
            for k in active_dec_keys:
                d_info = sc_decs[k]
                rule = d_info.get("rule")
                if rule:
                    rules.add(rule)

                parts = k.split("|")
                rel = parts[0]
                src = parts[1] if len(parts) > 1 else ""
                tgt = parts[2] if len(parts) > 2 else ""

                src_svc = src.split(":")[1] if src.startswith("method:") else ""
                tgt_svc = tgt.split(":")[1] if tgt.startswith("method:") else ""

                if src_svc:
                    services.add(src_svc)
                    active_nodes.add(src_svc)
                if tgt_svc:
                    services.add(tgt_svc)
                    active_nodes.add(tgt_svc)

                if tgt.startswith("res:table:"):
                    tbl_raw = tgt.split(":", 2)[2]
                    tables.add(tbl_raw)
                    db_node_id = f"db-{tbl_raw.replace('.', '-')}"
                    active_nodes.add(db_node_id)
                    if src_svc:
                        db_edge_id = f"{src_svc}->{db_node_id}:DATABASE"
                        active_edges.add(db_edge_id)

                if rel == "remote" and src_svc and tgt_svc:
                    remote_edge_id = f"{src_svc}->{tgt_svc}:REST_HTTP"
                    active_edges.add(remote_edge_id)

            target_service = ""
            for s in services:
                if s != primary_service:
                    target_service = s
                    break
            if not target_service:
                target_service = primary_service

            # Формируем primary edgeId для подсветки
            primary_edge_id = ""
            if primary_service and target_service and primary_service != target_service:
                primary_edge_id = f"{primary_service}->{target_service}:REST_HTTP"
            elif primary_service and tables:
                tbl = sorted(tables)[0]
                db_id = f"db-{tbl.replace('.', '-')}"
                primary_edge_id = f"{primary_service}->{db_id}:DATABASE"

            steps_data.append({
                "step": n,
                "action": action,
                "edgeId": primary_edge_id,
                "source": primary_service or "client",
                "target": target_service or primary_service or "server",
                "httpMethod": verb,
                "endpoint": path,
                "relationType": "REST_HTTP" if verb else "CALL",
                "handler": handler,
                "params": req.get("params") or {},
                "expectedOutcome": req.get("expected_outcome", "success"),
                "reasoning": (req.get("grounding") or {}).get("reasoning", ""),
                "services": sorted(services),
                "tables": sorted(tables),
                "rules": sorted(rules),
                "activeNodes": sorted(active_nodes),
                "activeEdges": sorted(active_edges),
            })

        scenarios_list.append({
            "id": sid,
            "name": sc_title_ru,
            "title": raw_sc.get("title", ""),
            "description": raw_sc.get("description", ""),
            "steps": steps_data,
        })

    return scenarios_list


def export_all(out_dir: Path = OUTPUT_DIR) -> None:
    """Полный экспорт артефактов прогона из `out_dir` в visualizer/public/data и visualizer/src/data."""
    VIS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    VIS_SRC_DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Генерация данных сценариев...")
    scenarios_list = build_scenarios_data(out_dir)

    # 1. Сохранение public/data/scenarios_data.json
    sc_json_path = VIS_DATA_DIR / "scenarios_data.json"
    sc_json_path.write_text(json.dumps(scenarios_list, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  -> {sc_json_path} ({len(scenarios_list)} сценариев)")

    # 2. Копирование остальных ключевых JSON
    import shutil
    for fname in ["canonical_graph.json", "decisions.json", "evidence.json", "submission.json", "step_requests.json"]:
        src = out_dir / fname
        if src.is_file():
            dst = VIS_DATA_DIR / fname
            shutil.copy(src, dst)
            print(f"  -> {dst} ({src.stat().st_size // 1024} KB)")

    # 3. Генерация visualizer/src/data/scenariosData.ts
    ts_path = VIS_SRC_DATA_DIR / "scenariosData.ts"
    ts_content = f"""// Автоматически сгенерировано scripts/export_visualizer_data.py
import type {{ RuntimeScenario }} from '../types/graph';

export const TOPOLOGY_HUB_EXCLUSIONS = new Set<string>([
  'ts-eureka-service',
  'ts-eureka-auth-server',
  'ts-config-service',
  'rabbitmq',
  'zipkin',
  'ts-gateway-service',
]);

export const BENCHMARK_SCENARIOS: RuntimeScenario[] = {json.dumps(scenarios_list, ensure_ascii=False, indent=2)};
"""
    ts_path.write_text(ts_content, encoding="utf-8")
    print(f"  -> {ts_path} ({ts_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    import sys

    export_all(Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT_DIR)
