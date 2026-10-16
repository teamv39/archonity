"""Модуль правил отсева мертвого кода и фильтрации связей.

Основан на data/runtime_and_topology_rules.json и ADR-001/003/004.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


class RuntimeRules:
    """Загрузчик и провайдер правил отсева мертвого кода."""

    DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "runtime_and_topology_rules.json"

    def __init__(self, rules_path: str | Path | None = None) -> None:
        self.rules_path = Path(rules_path) if rules_path else self.DEFAULT_RULES_PATH
        self.data: dict[str, Any] = {}
        self.admin_services: set[str] = set()
        self.canary_services: set[str] = set()
        self.unreferenced_services: set[str] = set()
        self.unreferenced_endpoint_ids: set[str] = set()
        self.unreferenced_paths: set[str] = set()
        self.hub_exclusions: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.rules_path.is_file():
            # Защита от отсутствия файла (fallbacks)
            self.admin_services = {
                "ts-admin-basic-info-service",
                "ts-admin-order-service",
                "ts-admin-route-service",
                "ts-admin-travel-service",
                "ts-admin-user-service",
            }
            self.canary_services = {"ts-travel2-service"}
            self.unreferenced_services = {"ts-verification-code-service", "ts-avatar-service"}
            return

        with open(self.rules_path, encoding="utf-8") as f:
            self.data = json.load(f)

        candidates = self.data.get("dead_code_candidates", {})
        self.admin_services = set(candidates.get("admin_cluster", []))
        self.canary_services = set(candidates.get("canary_duplicates", []))
        self.unreferenced_endpoint_ids = set(candidates.get("unreferenced_endpoint_ids", []))
        self.unreferenced_paths = set(candidates.get("unreferenced_endpoint_paths", []))
        self.hub_exclusions = set(self.data.get("topology_hub_exclusions", []))

        # Сервисы с нереференцированными эндпоинтами (весь сервис не участвует в runtime-трассах)
        for ep in candidates.get("unreferenced_endpoints", []):
            if svc := ep.get("service"):
                self.unreferenced_services.add(svc)

    @staticmethod
    def extract_service(node_or_method_id: str) -> str | None:
        """Извлечение имени сервиса из method:ts-service:... или res:table:ts-service..."""
        if not node_or_method_id:
            return None
        parts = node_or_method_id.split(":")
        if len(parts) >= 2:
            # parts[1] это имя сервиса
            return parts[1]
        return None

    def is_dead_code_method(self, method_id: str, is_admin_scenario: bool = False) -> bool:
        """Проверка, является ли метод мертвым кодом для текущего типа сценария."""
        svc = self.extract_service(method_id)
        if not svc:
            return False

        # Всегда мертвые сервисы (капча, аватарки, канареечные дубли)
        if svc in self.unreferenced_services or svc in self.canary_services:
            return True

        # Административные сервисы в пользовательских сценариях
        if not is_admin_scenario and svc in self.admin_services:
            return True

        return False

    def is_dead_code_edge(self, source: str, relation: str, target: str, is_admin_scenario: bool = False) -> bool:
        """Проверка, связывает ли ребро мертвый код."""
        if relation == "executes":
            return self.is_dead_code_method(target, is_admin_scenario)

        if self.is_dead_code_method(source, is_admin_scenario):
            return True

        if relation in ("calls", "remote") and self.is_dead_code_method(target, is_admin_scenario):
            return True

        if relation == "data":
            # Проверяем, не обращается ли метод к таблице мертвого сервиса
            target_svc = self.extract_service(target)
            if target_svc and (target_svc in self.unreferenced_services or target_svc in self.canary_services):
                return True
            if not is_admin_scenario and target_svc in self.admin_services:
                return True

        return False

    def filter_methods(self, methods: Iterable[str], is_admin_scenario: bool = False) -> set[str]:
        return {m for m in methods if not self.is_dead_code_method(m, is_admin_scenario)}

    def filter_pairs(self, pairs: Iterable[tuple[str, str]], relation: str, is_admin_scenario: bool = False) -> set[tuple[str, str]]:
        return {(s, t) for s, t in pairs if not self.is_dead_code_edge(s, relation, t, is_admin_scenario)}
