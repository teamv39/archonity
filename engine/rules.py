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
    has_consign_weight_change: bool = False
    is_new_user: bool = False
    has_order_filter: bool = False
    has_status_filter: bool = False

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
        neg_ass = bool(re.search(r"\b(?:no|without)\b[^\n.;]*?\b(?:assurance|insurance)\b", text))
        pos_ass = bool(
            re.search(
                r"\b(?:with\s+assurance|assurance\s+of|insurance\s+of|type\s+1|type\s+2|first\s+type|assurance\w*\s+record|list\s+of\s+assurance)\b",
                text,
            )
        )
        has_assurance = pos_ass and not (
            neg_ass and not bool(re.search(r"\b(?:with\s+assurance|first\s+type|assurance\w*\s+record)\b", text))
        )

        # 3. Багаж (Consignment / Luggage)
        neg_con = bool(re.search(r"\b(?:no|without)\b[^\n.;]*?\b(?:consign\w*|luggage|baggage)\b", text))
        pos_con = bool(
            re.search(
                r"\b(?:\d+(?:\.\d+)?\s*kg|with\s+(?:a\s+)?luggage|with\s+(?:a\s+)?consign\w*|look\s*up[^\n.;,]{0,30}?(?:consign\w*|luggage\w*)|check[^\n.;,]{0,30}?(?:consign\w*|luggage\w*)|view[^\n.;,]{0,30}?(?:consign\w*|luggage\w*)|change[^\n.;,]{0,30}?(?:consign\w*|luggage\w*)|consign\w*\s+within)\b",
                text,
            )
        )
        has_consign = pos_con and not (
            neg_con and not bool(re.search(r"\b(?:\d+(?:\.\d+)?\s*kg|look\s*up[^\n.;,]{0,30}?(?:consign\w*|luggage\w*))\b", text))
        )

        # Изменение веса багажа при модификации consignment (ConsignServiceImpl.java:97)
        has_consign_weight_change = bool(
            re.search(
                r"\b(?:change\w*|update\w*|modif\w*|alter\w*)\b[^\n.;,]{0,40}?\b(?:weight|heavy|kg|kilo)\b",
                text,
            )
        )

        # 4. Бортовое и вокзальное питание (Food)
        neg_food = bool(re.search(r"\b(?:no|without)\b[^\n.;]*?\bfood\b", text))
        pos_food = bool(
            re.search(
                r"\b(?:with\s+food|food\s+on|station\s+food|food\s+from|food\s+offered|first\s+dish|food\w*\s+menu|food\w*\s+stores?)\b",
                text,
            )
        )
        has_food = pos_food and not (
            neg_food and not bool(re.search(r"\b(?:with\s+food|station\s+food|first\s+dish|food\w*\s+menu)\b", text))
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

        # 9. Новый пользователь (регистрация аккаунта с нуля, пустая история заказов)
        is_new_user = bool(re.search(r"\bregister(?:s|\s+a\s+new)\b", text))

        # 10. Фильтрация заказов по статусу или датам (OrderServiceImpl / OrderOtherServiceImpl)
        has_order_filter = bool(
            re.search(
                r"\b(?:filtered\b|filter\w*\s+by|travel\s+date|purchase\s+date|bought\s+date)\b",
                text,
            )
        )
        if "status" in text and ("filter" in text or "paid" in text or "cancel" in text):
            has_order_filter = True

        has_status_filter = bool(
            re.search(r"\b(?:filtered\b|filter\w*\s+by)[^\n.;]*?\bstatus\b", text)
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
            has_consign_weight_change=has_consign_weight_change,
            is_new_user=is_new_user,
            has_order_filter=has_order_filter,
            has_status_filter=has_status_filter,
        )

    def for_step(self, step_dict: dict[str, Any]) -> ScenarioProfile:
        """Построение профиля, адаптированного под конкретный шаг сценария."""
        act = (step_dict.get("action") or "").lower()

        # По умолчанию наследуем параметры сценария
        step_has_assurance = self.has_assurance
        step_has_food = self.has_food
        step_has_consign = self.has_consign
        step_train_mode = self.train_mode
        step_has_refused_cancel = self.has_refused_cancel
        step_has_refused_rebook = self.has_refused_rebook

        is_preserve = (
            bool(re.search(r"\b(?:book\s+(?:a|an|one|another|\d+)|book\b.*?seat|reserve|preserve)\b", act))
            and "contact book" not in act
            and "address book" not in act
        )
        if is_preserve:
            # Опции заказа при бронировании (билет со страховкой/едой/багажом или без)
            neg_step_ass = bool(re.search(r"\b(?:no|without)\b[^\n.;]*?\b(?:assurance|insurance)\b", act))
            pos_step_ass = bool(re.search(r"\b(?:with\s+assurance|assurance\s+of|insurance\s+of|first\s+type)\b", act))
            step_has_assurance = pos_step_ass and not neg_step_ass

            neg_step_food = bool(re.search(r"\b(?:no|without)\b[^\n.;]*?\bfood\b", act))
            pos_step_food = bool(re.search(r"\b(?:with\s+food|food\s+on|station\s+food|food\s+from|first\s+dish)\b", act))
            step_has_food = pos_step_food and not neg_step_food

            neg_step_con = bool(re.search(r"\b(?:no|without)\b[^\n.;]*?\b(?:consign\w*|luggage|baggage)\b", act))
            pos_step_con = bool(re.search(r"\b(?:\d+(?:\.\d+)?\s*kg|with\s+(?:a\s+)?luggage|with\s+(?:a\s+)?consign\w*)\b", act))
            step_has_consign = pos_step_con and not neg_step_con

        # Уточнение типа поезда для конкретного шага
        if "advanced search" in act or "transfer" in act:
            step_train_mode = "both"
        elif "regular" in act or re.search(r"\bother\b", act):
            step_train_mode = "regular_only"
        elif "high-speed" in act or "gaotie" in act or "dongche" in act:
            step_train_mode = "high_speed_only"

        # Шаги с отказом (refused)
        if "refuses" in act or "try to" in act or "refused" in act:
            if "cancel" in act:
                step_has_refused_cancel = True
            if "rebook" in act:
                step_has_refused_rebook = True

        # Фильтрация заказов на данном конкретном шаге
        step_has_order_filter = bool(
            re.search(
                r"\b(?:filtered\b|filter\w*\s+by|travel\s+date|purchase\s+date|bought\s+date)\b",
                act,
            )
        )
        if "status" in act and ("filter" in act or "paid" in act or "cancel" in act):
            step_has_order_filter = True

        step_has_status_filter = bool(
            re.search(r"\b(?:filtered\b|filter\w*\s+by)[^\n.;]*?\bstatus\b", act)
        )

        return ScenarioProfile(
            id=self.id,
            is_admin=self.is_admin,
            has_assurance=step_has_assurance,
            has_consign=step_has_consign,
            has_food=step_has_food,
            train_mode=step_train_mode,
            has_refused_cancel=step_has_refused_cancel,
            has_refused_rebook=step_has_refused_rebook,
            has_external_payment=self.has_external_payment,
            has_advanced_search=self.has_advanced_search,
            has_consign_weight_change=self.has_consign_weight_change,
            is_new_user=self.is_new_user,
            has_order_filter=step_has_order_filter,
            has_status_filter=step_has_status_filter,
        )


class RuntimeRules:
    """Загрузчик и провайдер правил отсева мертвого кода."""

    DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "runtime_and_topology_rules.json"

    # Режимы правила R7 (конструктор сущности при загрузке строк Hibernate), см. engine/entities.py:
    # project_calls (по умолчанию) — только конструктор с вызовом проектного метода (как Order#<init>());
    # body — любой конструктор с непустым телом (опровергнуто платформой 17.10: 0.8842 против 0.8927);
    # off — правило выключено целиком.
    ENTITY_CTOR_MODES = ("body", "project_calls", "off")

    # Таблицы ленивых коллекций при чтении (R10), см. engine/entities.py:
    # loaded (по умолчанию) — только коллекции, которые метод загрузил, пока он на стеке;
    # all — все таблицы data_access исполненного вызова (поведение до 17.10, для отката).
    COLLECTION_TABLE_MODES = ("loaded", "all")

    # equals сущности из list.contains(x) на результате чтения: on (по умолчанию) или off (до 17.10).
    ELEMENT_CALLBACK_MODES = ("on", "off")

    def __init__(
        self,
        rules_path: str | Path | None = None,
        entity_constructors_on_load: str = "project_calls",
        collection_tables_on_read: str = "loaded",
        element_callbacks: str = "on",
    ) -> None:
        if entity_constructors_on_load not in self.ENTITY_CTOR_MODES:
            raise ValueError(
                f"entity_constructors_on_load: {entity_constructors_on_load!r}, ожидается одно из {self.ENTITY_CTOR_MODES}"
            )
        if collection_tables_on_read not in self.COLLECTION_TABLE_MODES:
            raise ValueError(
                f"collection_tables_on_read: {collection_tables_on_read!r}, ожидается одно из {self.COLLECTION_TABLE_MODES}"
            )
        self.entity_constructors_on_load = entity_constructors_on_load
        if element_callbacks not in self.ELEMENT_CALLBACK_MODES:
            raise ValueError(f"element_callbacks: {element_callbacks!r}, ожидается одно из {self.ELEMENT_CALLBACK_MODES}")
        self.collection_tables_on_read = collection_tables_on_read
        self.element_callbacks = element_callbacks
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
        self.unreferenced_services.add("ts-notification-service")

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

            # 2. Сервис страховок и вызовы в preserve
            if not profile.has_assurance:
                if svc == "ts-assurance-service" or "addAssuranceForOrder" in method_id:
                    return True

            # 3. Сервисы багажа и вызовы в preserve
            if not profile.has_consign:
                if "consign" in svc or "createConsign" in method_id:
                    return True

            # 4. Сервисы питания и вызовы в preserve
            if not profile.has_food:
                if "food" in svc or "createFoodOrder" in method_id or "FoodOrder#<init>" in method_id:
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

            # R17: Для нового пользователя (S4) в БД нет существующих заказов,
            # поэтому цикл по заказам в checkSecurityAboutOrder не выполняется (0 итераций)
            if profile.is_new_user:
                if "checkSecurityAboutOrder" in source and "String2Date" in target:
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
                        "SeatClass#getCode",
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
                # В ConsignServiceImpl.java:97 пересчет цены (ts-consign-price-service) вызывается
                # только если originalRecord.getWeight() != consignRequest.getWeight().
                # Если вес не меняется (например, меняется только получатель/телефон), пересчет цены не вызывается.
                if not getattr(profile, "has_consign_weight_change", False):
                    if "updateConsignRecord" in source and "ts-consign-price-service" in target:
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
                        if not ("queryOrders" in source or "securityInfoCheck" in source or "checkSecurity" in source or "getAllOrders" in source):
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
