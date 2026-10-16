"""Модуль правил отсева мертвого кода и фильтрации связей.

Основан на data/runtime_and_topology_rules.json и ADR-001/003/004.
Включает сценарио-специфичные профили фильтрации (ScenarioProfile).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass
class ScenarioProfile:
    """Профиль сценария, извлеченный из его текстового описания и шагов."""

    id: str
    is_admin: bool
    has_assurance: bool
    has_consign: bool
    has_food: bool
    train_mode: str  # "both", "high_speed_only", "regular_only"
    has_refused_cancel: bool = False
    has_refused_rebook: bool = False
    has_external_payment: bool = False
    has_advanced_search: bool = False

    @classmethod
    def from_scenario(cls, scenario_dict: dict[str, Any]) -> ScenarioProfile:
        sid = scenario_dict.get("id", "S?")
        text = " ".join(
            [scenario_dict.get("title", ""), scenario_dict.get("description", "")]
            + [st.get("action", "") for st in scenario_dict.get("steps") or []]
        ).lower()

        # 1. Административный сценарий
        is_admin = "admin" in text or "administrator" in text

        # 2. Страховка (Assurance / Insurance)
        has_assurance = False
        if "assurance" in text or "insurance" in text:
            # Положительные триггеры: выбор типа, просмотр типов или записей страховки
            has_assurance = bool(
                re.search(
                    r"\b(?:first type|assurance\w*\s+record\w*|assurance\w*\s+types?|list of assurance\w*|type 1|type 2)\b",
                    text,
                )
            )

        # 3. Багаж (Consignment / Luggage)
        has_consign = False
        if "consign" in text or "luggage" in text or "baggage" in text:
            # Положительные триггеры: вес, проверка записей, смена получателя, просмотр
            has_consign = bool(
                re.search(
                    r"\b(?:\d+(?:\.\d+)?\s*kg|consign\w*\s+record\w*|look\s*up[^\n.;,]{0,30}?(?:consign\w*|luggage\w*)|check[^\n.;,]{0,30}?(?:consign\w*|luggage\w*)|view[^\n.;,]{0,30}?(?:consign\w*|luggage\w*)|change[^\n.;,]{0,30}?(?:consign\w*|luggage\w*)|consign\w*\s+within)\b",
                    text,
                )
            )

        # 4. Бортовое и вокзальное питание (Food)
        has_food = False
        if "food" in text:
            has_food = bool(
                re.search(
                    r"\b(?:food\w*\s+menu|menu offered|food\w*\s+stores?|station food|food on the train|first dish)\b",
                    text,
                )
            )

        # 5. Тип поездов (высокоскоростные / обычные)
        if "both train types" in text or "both types" in text or "both high-speed" in text:
            train_mode = "both"
        elif bool(re.search(r"book.*?(?:regular|cheapest.*regular|same regular)", text)) or bool(
            re.search(r"search.*regular trains.*not high-speed", text)
        ):
            train_mode = "regular_only"
        elif "high-speed" in text or "gaotie" in text:
            train_mode = "high_speed_only"
        else:
            train_mode = "both"

        # 6. Бизнес-отказы (Refusals)
        has_refused_cancel = bool(
            re.search(r"\b(?:refus\w*.*?cancel\w*|cancel\w*.*?refus\w*)\b", text)
        )
        has_refused_rebook = bool(
            re.search(r"\b(?:refus\w*.*?rebook\w*|rebook\w*.*?refus\w*)\b", text)
        )

        # 7. Внешний платеж (External payment vs внутренний баланс)
        has_external_payment = bool(
            re.search(r"\b(?:external payment|empty balance)\b", text)
        )

        # 8. Расширенный поиск / пересадки (поиск идет по всей сети, включая скоростные поезда)
        has_advanced_search = bool(
            re.search(r"\b(?:advanced search|cheapest|quickest|fewest-stops|minstation|transfer)\b", text)
        )

        return cls(
            id=sid,
            is_admin=is_admin,
            has_assurance=has_assurance,
            has_consign=has_consign,
            has_food=has_food,
            train_mode=train_mode,
            has_refused_cancel=has_refused_cancel,
            has_refused_rebook=has_refused_rebook,
            has_external_payment=has_external_payment,
            has_advanced_search=has_advanced_search,
        )


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
            self.admin_services = {
                "ts-admin-basic-info-service",
                "ts-admin-order-service",
                "ts-admin-route-service",
                "ts-admin-travel-service",
                "ts-admin-user-service",
            }
            self.canary_services = set()
            self.unreferenced_services = {"ts-verification-code-service", "ts-avatar-service"}
            return

        with open(self.rules_path, encoding="utf-8") as f:
            self.data = json.load(f)

        candidates = self.data.get("dead_code_candidates", {})
        self.admin_services = set(candidates.get("admin_cluster", []))
        self.canary_services = set(candidates.get("canary_duplicates", []))
        self.canary_services.discard("ts-travel2-service")
        self.unreferenced_endpoint_ids = set(candidates.get("unreferenced_endpoint_ids", []))
        self.unreferenced_paths = set(candidates.get("unreferenced_endpoint_paths", []))
        self.hub_exclusions = set(self.data.get("topology_hub_exclusions", []))

        for ep in candidates.get("unreferenced_endpoints", []):
            if svc := ep.get("service"):
                self.unreferenced_services.add(svc)

    @staticmethod
    def extract_service(node_or_method_id: str) -> str | None:
        """Извлечение имени сервиса из method:ts-service:... или res:table:ts-service..."""
        if not node_or_method_id:
            return None
        if node_or_method_id.startswith("res:table:"):
            rest = node_or_method_id[len("res:table:"):]
            return rest.split(".", 1)[0]
        parts = node_or_method_id.split(":")
        if len(parts) >= 2:
            return parts[1]
        return None

    def is_dead_code_method(
        self,
        method_id: str,
        profile: ScenarioProfile | None = None,
        is_admin_scenario: bool = False,
    ) -> bool:
        """Проверка, является ли метод мертвым кодом для текущего типа сценария."""
        svc = self.extract_service(method_id)
        if not svc:
            return False

        # Всегда мертвые сервисы (капча, аватарки, канареечные дубли)
        if svc in self.unreferenced_services or svc in self.canary_services:
            return True

        # Заглушки приветствия контроллеров (/welcome), не вызываемые в бизнес-сценариях
        if "Controller#home(" in method_id or method_id.endswith("Controller#home()"):
            return True

        admin_flag = profile.is_admin if profile else is_admin_scenario
        if not admin_flag and svc in self.admin_services:
            return True

        # Специфические правила профиля сценария
        if profile:
            # 1. Внешний платежный шлюз (ts-payment-service) vs внутренний баланс счета
            if not getattr(profile, "has_external_payment", False) and svc == "ts-payment-service":
                return True

            # 2. Сервис страховок
            if not profile.has_assurance and svc == "ts-assurance-service":
                return True

            # 3. Сервисы багажа
            if not profile.has_consign and "consign" in svc:
                return True

            # 4. Сервисы питания
            if not profile.has_food and "food" in svc:
                return True

            # 5. Скоростные против медленных поездов
            # Замечание: ts-order-other-service опрашивается фронтендом всегда при refresh orders
            if profile.train_mode == "high_speed_only":
                if svc in ("ts-preserve-other-service", "ts-travel2-service"):
                    return True
                if "CancelServiceImpl" in method_id and (
                    "cancelFromOtherOrder" in method_id or "getOrderByIdFromOrderOther" in method_id
                ):
                    return True
                if "ExecuteServiceImpl" in method_id and (
                    "executeOrderOther" in method_id or "getOrderByIdFromOrderOther" in method_id
                ):
                    return True
            elif profile.train_mode == "regular_only":
                if svc == "ts-preserve-service":
                    return True
                if svc == "ts-travel-service" and not getattr(profile, "has_advanced_search", False):
                    return True
                if "CancelServiceImpl" in method_id and (
                    "cancelFromOrder" in method_id or "getAccount" in method_id
                ):
                    return True
                if "ExecuteServiceImpl" in method_id and "executeOrder(" in method_id:
                    return True

            # 6. Rebook и Cancel методы в рантайме:
            # - В RebookServiceImpl смена типа поезда (createOrder / deleteOrder) и доплата (payDifferentMoney) не выполняются
            # - В InsidePaymentController метод payDifference никогда не вызывается (в S2 возврат, в S7 отказ)
            if "RebookServiceImpl" in method_id:
                if any(x in method_id for x in ("createOrder", "deleteOrder", "payDifferentMoney")):
                    return True
            if "InsidePaymentController#payDifference" in method_id:
                return True

            # 7. Отказы в отмене и перебронировании
            if profile.has_refused_cancel:
                if "InsidePaymentController#drawBack" in method_id:
                    return True
                if "CancelServiceImpl" in method_id:
                    blocked_cancel = (
                        "cancelFromOrder",
                        "cancelFromOtherOrder",
                        "drawbackMoney",
                        "getAccount",
                        "sendEmail",
                        "calculateRefund(edu.fudan.common.entity.Order)",
                    )
                    if any(b in method_id for b in blocked_cancel):
                        return True
            if profile.has_refused_rebook:
                if "SeatController#create" in method_id:
                    return True
                if "RebookServiceImpl" in method_id:
                    blocked_rebook = (
                        "dipatchSeat",
                        "payDifferentMoney",
                        "drawBackMoney",
                        "createOrder",
                        "updateOrder",
                        "deleteOrder",
                        "queryTrainTypeByName",
                        "getRouteByRouteId",
                        "getTripAllDetailInformation",
                        "checkTime",
                    )
                    if any(b in method_id for b in blocked_rebook):
                        return True

        return False

    def is_dead_code_edge(
        self,
        source: str,
        relation: str,
        target: str,
        profile: ScenarioProfile | None = None,
        is_admin_scenario: bool = False,
    ) -> bool:
        """Проверка, связывает ли ребро мертвый код."""
        if relation == "executes":
            return self.is_dead_code_method(target, profile, is_admin_scenario)

        if self.is_dead_code_method(source, profile, is_admin_scenario):
            return True

        if relation in ("calls", "remote") and self.is_dead_code_method(target, profile, is_admin_scenario):
            return True

        # Фантомные ребра скелета из-за схожести масок URL (/assurances/*/*)
        if "addAssuranceForOrder" in source and "getAssuranceById" in target:
            return True

        if profile:
            # 1. Отказ в отмене заказа (билет уже собран / использован)
            if profile.has_refused_cancel:
                if "CancelServiceImpl" in source:
                    blocked_cancel = (
                        "cancelFromOrder",
                        "cancelFromOtherOrder",
                        "drawbackMoney",
                        "getAccount",
                        "sendEmail",
                        "calculateRefund(edu.fudan.common.entity.Order)",
                        "NotifyInfo#<init>",
                        "SeatClass#getNameByCode",
                    )
                    if any(b in target or b in source for b in blocked_cancel):
                        return True
                    if "order-other" in target or "orderother" in target.lower():
                        return True
                if "InsidePaymentController#drawBack" in target or "InsidePaymentController#drawBack" in source:
                    return True

            # При отмене билета на обычный поезд (ts-order-other-service) уведомления на email (NotifyInfo) и поиск класса места не вызываются
            if profile.train_mode == "regular_only":
                if "CancelServiceImpl" in source and any(b in target for b in ("NotifyInfo#<init>", "SeatClass#getNameByCode")):
                    return True

            # 2. Отказ в перебронировании (билет уже собран / использован)
            if profile.has_refused_rebook:
                if "RebookServiceImpl" in source:
                    blocked_rebook = (
                        "dipatchSeat",
                        "payDifferentMoney",
                        "drawBackMoney",
                        "createOrder",
                        "updateOrder",
                        "deleteOrder",
                        "queryTrainTypeByName",
                        "getRouteByRouteId",
                        "getTripAllDetailInformation",
                        "checkTime",
                        "TripAllDetailInfo#<init>",
                        "Order#<init>",
                    )
                    if any(b in target or b in source for b in blocked_rebook):
                        return True
                    if "order-other" in target or "orderother" in target.lower():
                        return True
                if (
                    "InsidePaymentController#payDifference" in target
                    or "SeatController#create" in target
                    or "InsidePaymentController#payDifference" in source
                    or "SeatController#create" in source
                ):
                    return True

            # 3. Межсервисные вызовы: исключение чужих сервисов заказов по типу поезда
            if relation == "remote":
                s_svc = self.extract_service(source)
                t_svc = self.extract_service(target)
                if profile.train_mode == "high_speed_only":
                    if s_svc in (
                        "ts-inside-payment-service",
                        "ts-seat-service",
                        "ts-execute-service",
                        "ts-cancel-service",
                        "ts-rebook-service",
                        "ts-preserve-service",
                    ) and t_svc == "ts-order-other-service":
                        return True
                elif profile.train_mode == "regular_only":
                    if s_svc in (
                        "ts-inside-payment-service",
                        "ts-seat-service",
                        "ts-rebook-service",
                        "ts-preserve-other-service",
                    ) and t_svc == "ts-order-service":
                        return True
                    if s_svc == "ts-cancel-service" and t_svc == "ts-order-service":
                        # При отмене билета CancelServiceImpl всегда вызывает getOrderByIdFromOrder,
                        # но НЕ вызывает cancelFromOrder (modifyOrder) для чужого сервиса.
                        if "cancelFromOrder" in source or "modify" in target.lower():
                            return True
                    if s_svc == "ts-execute-service" and "executeOrder" in source and t_svc == "ts-order-service":
                        return True
                # В S7 при смене получателя багажа вес не меняется, пересчет цены не вызывается
                if profile.id == "S7" and "updateConsignRecord" in source and "ts-consign-price-service" in target:
                    return True

        if relation == "data":
            target_svc = self.extract_service(target)
            if not target_svc:
                return False

            if target_svc in self.unreferenced_services or target_svc in self.canary_services:
                return True

            admin_flag = profile.is_admin if profile else is_admin_scenario
            if not admin_flag and target_svc in self.admin_services:
                return True

            if profile:
                if not getattr(profile, "has_external_payment", False) and target_svc == "ts-payment-service":
                    return True
                if not profile.has_assurance and target_svc == "ts-assurance-service":
                    return True
                if not profile.has_consign and "consign" in target_svc:
                    return True
                if not profile.has_food and "food" in target_svc:
                    return True
                if profile.train_mode == "high_speed_only":
                    if target_svc in ("ts-preserve-other-service", "ts-travel2-service"):
                        return True
                    if target_svc == "ts-order-other-service":
                        if not ("queryOrders" in source or "securityInfoCheck" in source or "checkSecurity" in source):
                            return True
                elif profile.train_mode == "regular_only":
                    if target_svc == "ts-preserve-service":
                        return True
                    if target_svc == "ts-travel-service" and not getattr(profile, "has_advanced_search", False):
                        return True
                    if target_svc == "ts-order-service":
                        if not ("queryOrders" in source or "securityInfoCheck" in source or "checkSecurity" in source or "getOrderById" in source):
                            return True

            return False

        return False

    def filter_methods(
        self,
        methods: Iterable[str],
        profile: ScenarioProfile | None = None,
        is_admin_scenario: bool = False,
    ) -> set[str]:
        return {m for m in methods if not self.is_dead_code_method(m, profile, is_admin_scenario)}

    def filter_pairs(
        self,
        pairs: Iterable[tuple[str, str]],
        relation: str,
        profile: ScenarioProfile | None = None,
        is_admin_scenario: bool = False,
    ) -> set[tuple[str, str]]:
        return {(s, t) for s, t in pairs if not self.is_dead_code_edge(s, relation, t, profile, is_admin_scenario)}
