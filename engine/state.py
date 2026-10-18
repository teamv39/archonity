"""Scenario state tracker and mutation engine for Train Ticket static analysis (Milestone M3).

Tracks dynamic scenario execution state across Train Ticket microservices with
strict scenario isolation (< 50 µs fork latency) between S0–S7.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any


class OrderStatus(IntEnum):
    """Lifecycle status codes for Train Ticket orders."""

    NOTPAID = 0    # Order created / reserved, awaiting payment
    PAID = 1       # Paid via internal balance or external payment gateway
    COLLECTED = 2  # Physical ticket collected at station kiosk
    CHANGE = 3     # Cancelled & rebooked
    CANCEL = 4     # Cancelled
    REFUND = 5     # Refunded
    USED = 6       # Ticket validated at turnstile / boarded train

    # Parity aliases
    CANCELLED = 4
    REFUNDS = 5

    @classmethod
    def from_value(cls, val: Any) -> OrderStatus:
        """Robust parser converting ints, enum instances, or case-insensitive string names."""
        if isinstance(val, cls):
            return val
        if isinstance(val, str):
            clean = val.strip().upper()
            if clean in ("CANCEL", "CANCELLED"):
                return cls.CANCEL
            if clean in ("REFUND", "REFUNDS"):
                return cls.REFUND
            return cls[clean]
        return cls(int(val))


class TrainType(str, Enum):
    """Train classification determining target order and travel services."""

    GaoTie = "GaoTie"
    Other = "Other"

    @classmethod
    def from_train_number(cls, train_number: str) -> TrainType:
        """Infers train type from train number prefix ('G'/'D' -> GaoTie, others -> Other)."""
        if not train_number:
            return cls.Other
        prefix = train_number.strip()[:1].upper()
        if prefix in ("G", "D"):
            return cls.GaoTie
        return cls.Other

    @classmethod
    def from_table(cls, table_name: str) -> TrainType:
        """Infers train type from DB table name ('orders_other' -> Other, 'orders' -> GaoTie)."""
        if "other" in table_name.lower():
            return cls.Other
        return cls.GaoTie

    @property
    def is_high_speed(self) -> bool:
        return self == TrainType.GaoTie


# TrainType aliases
TrainType.HIGH_SPEED = TrainType.GaoTie  # type: ignore[attr-defined]
TrainType.REGULAR = TrainType.Other  # type: ignore[attr-defined]

# edu.fudan.common.entity.Type: порядковый номер константы — значение колонки type в trip/trip2
_TRIP_TYPE_ORDINAL = {"G": 0, "D": 1, "Z": 2, "T": 3, "K": 4}


def _db_name(name: Any) -> str:
    """Имя станции, как его хранят сервисы: без пробелов, строчными."""
    return str(name or "").replace(" ", "").lower()


# Canonical entity aliases for ADR-005 refs
_REF_ENTITY_ALIASES: dict[str, str] = {
    "contacts": "contact",
    "contact": "contact",
    "orders": "order",
    "order": "order",
    "consignments": "consign",
    "consign_record": "consign",
    "consign": "consign",
    "assurances": "assurance",
    "assurance": "assurance",
    "food_orders": "food",
    "food_order": "food",
    "food": "food",
    "stores": "store",
    "store": "store",
    "stations": "station",
    "station": "station",
    "trains": "train",
    "train_types": "train",
    "train_type": "train",
    "train": "train",
    "routes": "route",
    "route": "route",
    "trips": "trip",
    "trip": "trip",
    "prices": "price",
    "price_configs": "price",
    "price_config": "price",
    "price": "price",
    "users": "user",
    "user": "user",
}


@dataclass
class RefusalEvent:
    """Record of a business rule refusal during scenario execution."""

    step_index: int
    action: str
    entity_id: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepMutationResult:
    """Result of applying a scenario step mutation."""

    step_index: int
    action_name: str
    status: str  # "SUCCESS", "REFUSED", "NOOP", "SKIPPED"
    mutations: list[str] = field(default_factory=list)
    refusal_reason: str | None = None
    affected_entities: dict[str, Any] = field(default_factory=dict)


class ScenarioState:
    """Mutable scenario state model with fast isolation for Train Ticket scenarios S0–S7."""

    DEFAULT_ACCOUNT_ID = "4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f"
    DEFAULT_USERNAME = "fdse_microservice"
    DEFAULT_BALANCE = 10000.0
    DEFAULT_TRAVEL_DATE = "2026-10-01"
    DEFAULT_SYSTEM_DATE = "2026-09-15"

    def __init__(
        self,
        user_name: str = DEFAULT_USERNAME,
        account_id: str = DEFAULT_ACCOUNT_ID,
        balance: float = DEFAULT_BALANCE,
        travel_date: str = DEFAULT_TRAVEL_DATE,
        system_date: str = DEFAULT_SYSTEM_DATE,
        contacts: list[dict[str, Any]] | None = None,
        orders: list[dict[str, Any]] | None = None,
        consignments: list[dict[str, Any]] | None = None,
        assurances: list[dict[str, Any]] | None = None,
        food_orders: list[dict[str, Any]] | None = None,
        balances: dict[str, float] | None = None,
        users: list[dict[str, Any]] | None = None,
        admin_entities: dict[str, list[dict[str, Any]]] | None = None,
        refusals: dict[str, str] | None = None,
        refusal_events: list[RefusalEvent] | None = None,
        extra: dict[str, Any] | None = None,
        step_artifacts: dict[int, dict[str, list[dict[str, Any]]]] | None = None,
        db_state: Any = None,
        scenario_id: str = "S?",
        is_admin: bool = False,
        is_new_user: bool = False,
        has_external_payment: bool = False,
        has_refused_cancel: bool = False,
        has_refused_rebook: bool = False,
        has_advanced_search: bool = False,
        has_assurance: bool = False,
        has_consign: bool = False,
        has_food: bool = False,
        has_date_filtering: bool = False,
    ) -> None:
        self.user_name = user_name
        self.account_id = account_id
        self.balance = float(balance)
        self.travel_date = travel_date
        self.system_date = system_date
        self.contacts = contacts if contacts is not None else []
        self.orders = orders if orders is not None else []
        self.consignments = consignments if consignments is not None else []
        self.assurances = assurances if assurances is not None else []
        self.food_orders = food_orders if food_orders is not None else []
        self.balances = balances if balances is not None else {self.account_id: self.balance}
        self.users = users if users is not None else []
        self.admin_entities = admin_entities if admin_entities is not None else {
            "stations": [],
            "train_types": [],
            "routes": [],
            "trips": [],
            "price_configs": [],
        }
        self.step_artifacts: dict[int, dict[str, list[dict[str, Any]]]] = (
            step_artifacts if step_artifacts is not None else {}
        )
        self.refusals = refusals if refusals is not None else {}
        self.refusal_events = refusal_events if refusal_events is not None else []
        self.last_refusal: dict[str, Any] | None = None
        self.extra = extra if extra is not None else {}
        self.db_state = db_state
        self.scenario_id = scenario_id
        self.is_admin = is_admin
        self.is_new_user = is_new_user
        self.has_external_payment = has_external_payment
        self.has_refused_cancel = has_refused_cancel
        self.has_refused_rebook = has_refused_rebook
        self.has_advanced_search = has_advanced_search
        self.has_assurance = has_assurance
        self.has_consign = has_consign
        self.has_food = has_food
        self.has_date_filtering = has_date_filtering

    @property
    def user_id(self) -> str:
        """Alias for account_id."""
        return self.account_id

    @property
    def travel_date_display(self) -> str:
        """Returns travel date in Russian format '01.10.2026'."""
        if "-" in self.travel_date:
            parts = self.travel_date.split("-")
            return f"{parts[2]}.{parts[1]}.{parts[0]}"
        return self.travel_date

    @property
    def system_date_display(self) -> str:
        """Returns system date in Russian format '15.09.2026'."""
        if "-" in self.system_date:
            parts = self.system_date.split("-")
            return f"{parts[2]}.{parts[1]}.{parts[0]}"
        return self.system_date

    @classmethod
    def create_initial(
        cls,
        db_state: Any = None,
        scenario_profile: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ScenarioState:
        """Constructs canonical initial state from DatabaseState loaded via M0 and execution context."""
        context = context or {}
        user_name = context.get("user_name", cls.DEFAULT_USERNAME)
        account_id = cls.DEFAULT_ACCOUNT_ID
        balance = float(context.get("balance", cls.DEFAULT_BALANCE))
        travel_date = context.get("travel_date", cls.DEFAULT_TRAVEL_DATE)
        system_date = context.get("system_date", cls.DEFAULT_SYSTEM_DATE)

        scenario_id = getattr(scenario_profile, "id", "S?") if scenario_profile else "S?"
        is_admin = getattr(scenario_profile, "is_admin", False) if scenario_profile else False

        contacts: list[dict[str, Any]] = []
        users: list[dict[str, Any]] = []
        consignments: list[dict[str, Any]] = []
        orders: list[dict[str, Any]] = []

        if db_state is not None:
            # Check user table
            user_rows = db_state.get_table("user") if hasattr(db_state, "get_table") else []
            for u in user_rows:
                users.append(dict(u))
                if u.get("user_name") == user_name:
                    account_id = u.get("user_id", account_id)

            # If user_name not found by exact match, but users exist and account_id is still default
            if user_rows and account_id == cls.DEFAULT_ACCOUNT_ID and not any(u.get("user_id") == account_id for u in user_rows):
                account_id = user_rows[0].get("user_id", account_id)
                user_name = user_rows[0].get("user_name", user_name)

            # Contacts table
            for c in (db_state.get_table("contacts") if hasattr(db_state, "get_table") else []):
                contacts.append(dict(c))

            # Consignments
            for cr in (db_state.get_table("consign_record") if hasattr(db_state, "get_table") else []):
                consignments.append(dict(cr))

            # GaoTie Orders
            for o in (db_state.get_table("orders") if hasattr(db_state, "get_table") else []):
                od = dict(o)
                od["train_type"] = TrainType.GaoTie
                od["status"] = OrderStatus.from_value(od.get("status", 0))
                od["price"] = float(od.get("price", 0.0))
                orders.append(od)

            # Other Orders
            for o in (db_state.get_table("orders_other") if hasattr(db_state, "get_table") else []):
                od = dict(o)
                od["train_type"] = TrainType.Other
                od["status"] = OrderStatus.from_value(od.get("status", 0))
                od["price"] = float(od.get("price", 0.0))
                orders.append(od)

        return cls(
            user_name=user_name,
            account_id=account_id,
            balance=balance,
            travel_date=travel_date,
            system_date=system_date,
            contacts=contacts,
            orders=orders,
            consignments=consignments,
            users=users,
            balances={account_id: balance},
            db_state=db_state,
            scenario_id=scenario_id,
            is_admin=is_admin,
        )

    def fork(self) -> ScenarioState:
        """Creates an isolated deep copy in < 50 µs for strict scenario isolation."""
        cloned_db = self.db_state.fork() if hasattr(self.db_state, "fork") else self.db_state
        cloned_artifacts = {
            st_idx: {
                k: [dict(item) if isinstance(item, dict) else item for item in v]
                for k, v in ent_map.items()
            }
            for st_idx, ent_map in self.step_artifacts.items()
        }
        return ScenarioState(
            user_name=self.user_name,
            account_id=self.account_id,
            balance=self.balance,
            travel_date=self.travel_date,
            system_date=self.system_date,
            contacts=[dict(c) for c in self.contacts],
            orders=[dict(o) for o in self.orders],
            consignments=[dict(c) for c in self.consignments],
            assurances=[dict(a) for a in self.assurances],
            food_orders=[dict(f) for f in self.food_orders],
            balances=dict(self.balances),
            users=[dict(u) for u in self.users],
            admin_entities={k: [dict(item) if isinstance(item, dict) else item for item in v] for k, v in self.admin_entities.items()},
            refusals=dict(self.refusals),
            refusal_events=list(self.refusal_events),
            extra=dict(self.extra),
            step_artifacts=cloned_artifacts,
            db_state=cloned_db,
            scenario_id=self.scenario_id,
            is_admin=self.is_admin,
            is_new_user=self.is_new_user,
            has_external_payment=self.has_external_payment,
            has_refused_cancel=self.has_refused_cancel,
            has_refused_rebook=self.has_refused_rebook,
            has_advanced_search=self.has_advanced_search,
            has_assurance=self.has_assurance,
            has_consign=self.has_consign,
            has_food=self.has_food,
            has_date_filtering=self.has_date_filtering,
        )

    # -------------------------------------------------------------------------
    # Step Artifacts & Refs Resolution (ADR-005 Contract)
    # -------------------------------------------------------------------------

    def record_step_entity(
        self,
        step_index: int,
        entity_type: str,
        entity_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Records an entity created or discovered during a specific scenario step.

        Args:
            step_index: Scenario step index (e.g. 1, 4, 6).
            entity_type: Entity category (e.g. 'order', 'contact', 'trip', 'user').
            entity_data: Entity dictionary.

        Returns:
            The recorded entity dictionary (with 'created_at_step' populated).
        """
        norm_type = _REF_ENTITY_ALIASES.get(entity_type.lower(), entity_type.lower())
        if "created_at_step" not in entity_data:
            entity_data["created_at_step"] = step_index
        step_dict = self.step_artifacts.setdefault(step_index, {})
        step_dict.setdefault(norm_type, []).append(entity_data)
        return entity_data

    def get_step_artifacts(
        self,
        step_index: int | None = None,
    ) -> dict[str, list[dict[str, Any]]] | dict[int, dict[str, list[dict[str, Any]]]]:
        """Returns step artifacts for a specific step or all steps."""
        if step_index is not None:
            return dict(self.step_artifacts.get(step_index, {}))
        return self.step_artifacts

    def resolve_ref(self, entity_type: str, ref: str) -> dict[str, Any] | None:
        """Resolves reference formatted as '<pick>_of_step_<n>' (ADR-005 contract).

        Args:
            entity_type: Entity category (e.g. 'order', 'contact', 'trip', 'user').
            ref: Reference string, e.g. 'new_of_step_4', 'first_of_step_2'.

        Returns:
            Resolved entity dict or None if reference cannot be matched.
        """
        if not ref or not isinstance(ref, str):
            return None

        norm_type = _REF_ENTITY_ALIASES.get(entity_type.lower(), entity_type.lower())
        m = re.match(r"^(first|second|new)_of_step_(\d+)$", ref.strip())
        if not m:
            return None

        pick, step_str = m.groups()
        step_num = int(step_str)

        # 1. Exact match in recorded step_artifacts
        entities = self.step_artifacts.get(step_num, {}).get(norm_type, [])
        if entities:
            if pick == "new":
                return entities[-1]
            elif pick == "first":
                return entities[0]
            elif pick == "second":
                return entities[1] if len(entities) > 1 else entities[0]

        # 2. Fallback search across global collections
        if norm_type == "order":
            step_orders = [o for o in self.orders if o.get("created_at_step") == step_num]
            if step_orders:
                return step_orders[-1] if pick == "new" else step_orders[0]
            if step_num == 0:
                untracked = [o for o in self.orders if "created_at_step" not in o]
                if untracked:
                    return untracked[-1] if pick == "new" else untracked[0]
            return None

        elif norm_type == "contact":
            step_contacts = [c for c in self.contacts if c.get("created_at_step") == step_num]
            if step_contacts:
                return step_contacts[-1] if pick == "new" else step_contacts[0]
            if step_num == 0:
                untracked = [c for c in self.contacts if "created_at_step" not in c]
                if untracked:
                    if pick == "second" and len(untracked) > 1:
                        return untracked[1]
                    return untracked[0]
            return None

        elif norm_type == "trip":
            step_trips = self.admin_entities.get("trips", [])
            for tr in step_trips:
                if tr.get("created_at_step") == step_num:
                    return tr
            if step_num == 0:
                return {
                    "id": "G1234",
                    "trip_id": "G1234",
                    "train_number": "G1234",
                    "train_type": TrainType.GaoTie,
                }
            return None

        elif norm_type == "user":
            step_users = [u for u in self.users if u.get("created_at_step") == step_num]
            if step_users:
                return step_users[0]
            if step_num == 0:
                return {"user_id": self.account_id, "username": self.user_name}
            return None

        elif norm_type == "consign":
            step_cs = [c for c in self.consignments if c.get("created_at_step") == step_num]
            if step_cs:
                return step_cs[-1] if pick == "new" else step_cs[0]
            if step_num == 0 and self.consignments:
                return self.consignments[-1]
            return None

        elif norm_type == "assurance":
            step_ass = [a for a in self.assurances if a.get("created_at_step") == step_num]
            if step_ass:
                return step_ass[-1] if pick == "new" else step_ass[0]
            if step_num == 0 and self.assurances:
                return self.assurances[-1]
            return None

        elif norm_type == "food":
            step_fo = [f for f in self.food_orders if f.get("created_at_step") == step_num]
            if step_fo:
                return step_fo[-1] if pick == "new" else step_fo[0]
            if step_num == 0 and self.food_orders:
                return self.food_orders[-1]
            return None

        elif norm_type in ("station", "train", "route", "price"):
            cat_map = {
                "station": "stations",
                "train": "train_types",
                "route": "routes",
                "price": "price_configs",
            }
            sub_items = self.admin_entities.get(cat_map[norm_type], [])
            for item in sub_items:
                if item.get("created_at_step") == step_num:
                    return item
            if step_num == 0 and sub_items:
                return sub_items[-1] if pick == "new" else sub_items[0]
            return None

    def resolve_ref_id(self, entity_type: str, ref: str) -> str | None:
        """Resolves reference to the entity's primary identifier string."""
        ent = self.resolve_ref(entity_type, ref)
        if not ent:
            return None
        return ent.get("id") or ent.get("user_id") or ent.get("order_id") or ent.get("trip_id")

    def resolve_step_refs(self, refs: dict[str, str] | None) -> dict[str, dict[str, Any]]:
        """Resolves all refs for a StepRequest into concrete entity dictionaries."""
        if not refs:
            return {}
        resolved: dict[str, dict[str, Any]] = {}
        for entity_type, ref_str in refs.items():
            ent = self.resolve_ref(entity_type, ref_str)
            if ent is not None:
                resolved[entity_type] = ent
        return resolved


    # -------------------------------------------------------------------------
    # Query Helpers
    # -------------------------------------------------------------------------

    def get_orders(
        self,
        account_id: str | None = None,
        status: OrderStatus | int | str | None = None,
        train_type: TrainType | str | None = None,
    ) -> list[dict[str, Any]]:
        """Returns orders filtered by account, status, and/or train type."""
        results = self.orders
        if account_id is not None:
            results = [o for o in results if o.get("account_id") == account_id]
        if status is not None:
            norm_status = OrderStatus.from_value(status)
            results = [o for o in results if o.get("status") == norm_status]
        if train_type is not None:
            tt_val = TrainType(train_type) if isinstance(train_type, str) else train_type
            results = [o for o in results if o.get("train_type") == tt_val]
        return results

    def get_balance(self, account_id: str | None = None) -> float:
        """Returns account balance (defaults to active user)."""
        if account_id is None or account_id == self.account_id:
            return self.balance
        return self.balances.get(account_id, 0.0)

    def get_contacts(self, account_id: str | None = None) -> list[dict[str, Any]]:
        """Returns contacts list for user or all contacts."""
        if account_id == "all":
            return list(self.contacts)
        target_uid = account_id if account_id is not None else self.account_id
        return [c for c in self.contacts if c.get("account_id") == target_uid]

    def get_order_by_id(self, order_id: str) -> dict[str, Any] | None:
        """Finds an order by its ID."""
        for o in self.orders:
            if o.get("id") == order_id:
                return o
        return None

    def has_active_orders(self, account_id: str | None = None, train_type: TrainType | str | None = None) -> bool:
        """Checks if account has active orders (NOTPAID, PAID, or COLLECTED)."""
        active_statuses = {OrderStatus.NOTPAID, OrderStatus.PAID, OrderStatus.COLLECTED}
        orders = self.get_orders(account_id=account_id, train_type=train_type)
        return any(o.get("status") in active_statuses for o in orders)

    def has_orders(self, account_id: str | None = None) -> bool:
        """Checks if account has any orders."""
        return len(self.get_orders(account_id=account_id)) > 0

    def get_consignments(self, account_id: str | None = None) -> list[dict[str, Any]]:
        """Returns consignments for account."""
        target_uid = account_id if account_id is not None else self.account_id
        return [c for c in self.consignments if c.get("account_id") == target_uid]

    def get_admin_entities(self, entity_type: str) -> list[dict[str, Any]]:
        """Returns admin entities (stations, train_types, routes, trips, price_configs)."""
        return list(self.admin_entities.get(entity_type, []))

    def has_custom_station(self, name: str) -> bool:
        """Checks if an admin station exists."""
        stations = self.admin_entities.get("stations", [])
        return any(s.get("name") == name for s in stations)

    def is_refused(self, action: str) -> bool:
        """Checks if an action was marked refused."""
        return action in self.refusals

    def has_date_filter_query(self) -> bool:
        """Returns whether scenario requested date-filtered queries."""
        return self.has_date_filtering

    # -------------------------------------------------------------------------
    # Step Mutation Engine across S0–S7
    # -------------------------------------------------------------------------

    def apply_step(
        self,
        step: dict[str, Any] | Any,
        scenario_dict: dict[str, Any] | None = None,
    ) -> StepMutationResult:
        """Unified entrypoint for applying a scenario step mutation."""
        step_index = getattr(step, "step", None) if not isinstance(step, dict) else step.get("step", 0)
        action_name = getattr(step, "action", "") if not isinstance(step, dict) else step.get("action", "")
        payload = getattr(step, "params", {}) if not isinstance(step, dict) else step.get("params", {}) or {}
        handler = getattr(step, "handler", None) if not isinstance(step, dict) else step.get("handler", None)
        refs = getattr(step, "refs", {}) if not isinstance(step, dict) else step.get("refs", {}) or {}

        if step_index is None:
            step_index = 0

        return self.apply_step_mutation(
            step_index=step_index,
            action_name=action_name,
            payload=payload,
            handler=handler,
            refs=refs,
        )

    def apply_step_request(self, step_req: Any) -> StepMutationResult:
        """Applies mutation from a StepRequest object (ADR-005)."""
        return self.apply_step(step_req)

    def apply_step_mutation(
        self,
        step_index: int,
        action_name: str,
        payload: dict[str, Any] | None = None,
        handler: str | None = None,
        refs: dict[str, str] | None = None,
    ) -> StepMutationResult:
        """Applies state mutation triggered by scenario action step."""
        p = dict(payload) if payload else {}
        r = dict(refs) if refs else {}
        t = action_name.lower()

        # Resolve entity references into payload parameters if omitted
        if r:
            if "order" in r and "orderId" not in p and "order_id" not in p:
                r_oid = self.resolve_ref_id("order", r["order"])
                if r_oid:
                    p["orderId"] = r_oid
                    p["order_id"] = r_oid
            if "trip" in r and "tripId" not in p and "trip_id" not in p:
                r_tid = self.resolve_ref_id("trip", r["trip"])
                if r_tid:
                    p["tripId"] = r_tid
                    p["trip_id"] = r_tid
            if "contact" in r and "contactsId" not in p and "contact_id" not in p and "id" not in p:
                r_cid = self.resolve_ref_id("contact", r["contact"])
                if r_cid:
                    p["contactsId"] = r_cid
                    p["contact_id"] = r_cid
            if "consign" in r and "consignId" not in p and "consign_id" not in p:
                r_csid = self.resolve_ref_id("consign", r["consign"])
                if r_csid:
                    p["consignId"] = r_csid
                    p["consign_id"] = r_csid

        # 1. User Registration (S4)
        if (handler and "registerUser" in handler) or re.search(r"\bregister\b.*?(?:account|passenger|user)\b", t):
            return self._mutate_user_registration(step_index, action_name, p)

        # 2. Login
        if (handler and "getToken" in handler) or re.search(r"\blog\s*in\b", t):
            return self._mutate_login(step_index, action_name, p)

        # 3. Add Contact (S3, S4)
        if (handler and "createNewContacts" in handler) or re.search(r"\badd\b.*?\bcontact\b", t):
            return self._mutate_add_contact(step_index, action_name, p)

        # 4. Admin Entity Creation (S6). Обработчик важнее текста: «Add a new trip ... on the new route» — поездка
        admin = (
            ("addStation", r"\badd\b.*?\bstation\b", self._mutate_admin_station),
            ("addPrice", r"\badd\b.*?\bprice\b", self._mutate_admin_price),
            ("addTrain", r"\badd\b.*?\b(?:new\s+)?train\b", self._mutate_admin_train),
            ("addRoute", r"\badd\b.*?\broute\b", self._mutate_admin_route),
            ("addTravel", r"\badd\b.*?\b(?:trip|travel)\b", self._mutate_admin_travel),
        )
        for key, rx, mutate in admin:
            if handler and key in handler:
                return mutate(step_index, action_name, p)
        for key, rx, mutate in admin:
            if not handler and re.search(rx, t):
                return mutate(step_index, action_name, p)

        # 5. Order Booking (S1–S7)
        if (handler and "preserve" in handler.lower()) or re.search(r"\b(?:book|reserve)\b.*?\b(?:seat|ticket|trip)\b", t):
            return self._mutate_booking(step_index, action_name, p, refs=r)

        # 6. Order Payment (S1–S7)
        if (handler and "InsidePaymentController#pay" in handler) or re.search(r"\bpay\s+for\b.*?\border\b|\bpay\b", t):
            return self._mutate_payment(step_index, action_name, p, refs=r)

        # 7. Collect Ticket (S1, S5, S7)
        if (handler and "collectTicket" in handler) or re.search(r"\bcollect\s+(?:the\s+)?ticket\b", t):
            return self._mutate_collect_ticket(step_index, action_name, p, refs=r)

        # 8. Enter Station / Board (S1, S5)
        if (handler and "executeTicket" in handler) or re.search(r"\b(enter\s+the\s+station|board\s+the\s+train)\b", t):
            return self._mutate_enter_station(step_index, action_name, p, refs=r)

        # 9. Cancel Order (S2, S4, S7)
        if (handler and "cancelTicket" in handler) or re.search(r"\b(?:cancel\s+(?:the\s+)?(?:paid\s+)?order|try\s+to\s+cancel)\b", t):
            return self._mutate_cancellation(step_index, action_name, p, refs=r)

        # 10. Rebook Order (S2, S7)
        if (handler and "RebookController#rebook" in handler) or re.search(r"\b(?:rebook|try\s+to\s+rebook)\b", t):
            return self._mutate_rebook(step_index, action_name, p, refs=r)

        # 11. Change Consignee (S7)
        if (handler and "updateConsign" in handler) or re.search(r"\bchange\b.*?\bconsignee\b", t):
            return self._mutate_update_consignee(step_index, action_name, p, refs=r)

        # 12. Date Queries (S7)
        if re.search(r"\b(?:travel\s+date|purchase\s+date|bought\s+date)\b", t):
            self.has_date_filtering = True
            return StepMutationResult(step_index, action_name, "SUCCESS", ["flag_date_filtering_set"])

        # 13. Advanced Search Flags (S5)
        if re.search(r"\b(?:cheapest|quickest|fewest-stops|transfer)\b", t):
            self.has_advanced_search = True
            return StepMutationResult(step_index, action_name, "SUCCESS", ["flag_advanced_search_set"])

        # 14. Trip Search / Schedule Query (S0–S7)
        if (handler and any(h in handler for h in ("queryForTravel", "getTripAllDetailInformation", "queryAlready", "queryForStationId"))) or \
           re.search(r"\b(?:search|query|check\s+(?:the\s+)?train\s+schedule|look\s+up|find)\b.*?\b(?:train|trip|schedule|ticket|travel)\b", t):
            m_trip = re.search(r"\b([GDZK]\d+)\b", action_name)
            trip_id = p.get("tripId") or p.get("trip_id") or (m_trip.group(1) if m_trip else None)
            if not trip_id:
                is_regular = ("regular" in t or "other" in t) and "high-speed" not in t
                if self.db_state is not None and hasattr(self.db_state, "get_table"):
                    tbl = "trip2" if is_regular else "trip"
                    rows = self.db_state.get_table(tbl)
                    if rows:
                        num = rows[0].get("number")
                        if num:
                            trip_id = f"K{num}" if is_regular else f"G{num}"
                        else:
                            trip_id = str(rows[0].get("id", ""))
                if not trip_id:
                    trip_id = "K1235" if is_regular else "G1234"
            trip_data = {
                "id": trip_id,
                "trip_id": trip_id,
                "train_number": trip_id,
                "train_type": TrainType.from_train_number(trip_id),
                "created_at_step": step_index,
            }
            self.record_step_entity(step_index, "trip", trip_data)
            return StepMutationResult(step_index, action_name, "SUCCESS", [f"trip_searched:{trip_id}"])

        # 15. Store / Food Query
        if re.search(r"\b(?:food\s+store|store\s+in|food\s+menu)\b", t):
            m_station = re.search(r"\b(?:in|at)\s+([A-Za-z\s]+)", action_name)
            st_name = m_station.group(1).strip() if m_station else None
            if not st_name and self.db_state is not None and hasattr(self.db_state, "get_table"):
                st_rows = self.db_state.get_table("station")
                if st_rows:
                    st_name = st_rows[0].get("name")
            if not st_name:
                st_name = "Shanghai"
            store_data = {"id": f"store-{st_name.lower().replace(' ', '')}", "station_name": st_name, "created_at_step": step_index}
            self.record_step_entity(step_index, "store", store_data)
            self.record_step_entity(step_index, "food", {"id": f"food-{st_name.lower().replace(' ', '')}", "created_at_step": step_index})
            return StepMutationResult(step_index, action_name, "SUCCESS", [f"food_store_queried:{st_name}"])

        return StepMutationResult(step_index, action_name, "NOOP", [])

    # -------------------------------------------------------------------------
    # Internal Mutators
    # -------------------------------------------------------------------------

    def _mutate_user_registration(self, step_index: int, action: str, payload: dict[str, Any]) -> StepMutationResult:
        username = payload.get("username", "MRK-reg-430")
        user_id = payload.get("user_id", username)

        self.register_user(user_name=username, account_id=user_id, balance=0.0)
        self.is_new_user = True
        self.orders = []
        self.contacts = []

        user_data = {
            "user_id": user_id,
            "user_name": username,
            "balance": 0.0,
            "created_at_step": step_index,
        }
        self.record_step_entity(step_index, "user", user_data)

        if hasattr(self.db_state, "insert"):
            self.db_state.insert("user", {
                "user_id": user_id, "user_name": username, "password": "password",
                "gender": 1, "document_type": 1, "document_num": "MRK-rdoc", "email": f"{username}@test.com",
            })
            self.db_state.insert("auth_user", {
                "user_id": user_id, "user_name": username, "password": "password",
            })

        return StepMutationResult(
            step_index, action, "SUCCESS",
            [f"user_registered:{username}:{user_id}", "balance_initialized:0.0", "cleared_initial_orders_contacts"],
        )

    def _mutate_login(self, step_index: int, action: str, payload: dict[str, Any]) -> StepMutationResult:
        username = payload.get("username", "")
        if "admin" in action.lower() or username == "admin":
            self.is_admin = True
        else:
            self.is_admin = False
        return StepMutationResult(step_index, action, "SUCCESS", [f"login:admin={self.is_admin}"])

    def _mutate_add_contact(self, step_index: int, action: str, payload: dict[str, Any]) -> StepMutationResult:
        t = action.lower()
        if "companion" in t:
            c_name = payload.get("name", "Companion_One")
        else:
            c_name = payload.get("name", self.user_name)
        cid = payload.get("id", f"contact-{len(self.contacts) + 1}")
        cd = {
            "id": cid,
            "account_id": self.account_id,
            "name": c_name,
            "document_type": 1,
            "document_number": payload.get("document_number", "DocumentNumber_New"),
            "phone_number": "13800000000",
            "created_at_step": step_index,
        }
        self.contacts.append(cd)
        if hasattr(self.db_state, "insert"):
            self.db_state.insert("contacts", cd)
        self.record_step_entity(step_index, "contact", cd)
        return StepMutationResult(step_index, action, "SUCCESS", [f"contact_created:{cid}:{c_name}"], affected_entities={"contact_id": cid})

    def _mutate_booking(self, step_index: int, action: str, payload: dict[str, Any], refs: dict[str, str] | None = None) -> StepMutationResult:
        t = action.lower()
        is_regular = ("regular" in t or "other" in t) and "high-speed" not in t
        train_type = TrainType.Other if is_regular else TrainType.GaoTie

        seat_class = 2 if "second-class" in t else 1
        trip_id = payload.get("tripId") or ("K1235" if is_regular else ("G9101" if ("g9101" in t or "new trip" in t) else "G1234"))
        order_id = payload.get("orderId") or f"order-{self.scenario_id.lower()}-{len(self.orders) + 1}"
        price = float(payload.get("price", 120.0 if is_regular else 100.0))

        c_name = "Contacts_One"
        c_doc = "DocumentNumber_One"
        if refs and "contact" in refs:
            c_ent = self.resolve_ref("contact", refs["contact"])
            if c_ent:
                c_name = c_ent.get("name", c_name)
                c_doc = c_ent.get("document_number", c_doc)

        order = {
            "id": order_id,
            "train_number": trip_id,
            "train_type": train_type,
            "account_id": self.account_id,
            "contacts_name": payload.get("contacts_name", c_name),
            "contacts_document_number": payload.get("contacts_document_number", c_doc),
            "seat_class": seat_class,
            "from": "Shanghai",
            "to": "Nanjing" if is_regular else ("Ning Bo" if "ning bo" in t else "Suzhou"),
            "travel_date": self.travel_date,
            "price": price,
            "status": OrderStatus.NOTPAID,
            "bought_date": self.system_date,
            "created_at_step": step_index,
        }
        self.orders.append(order)
        self.record_step_entity(step_index, "order", order)

        tbl = "orders_other" if is_regular else "orders"
        if hasattr(self.db_state, "insert"):
            db_row = dict(order)
            db_row["status"] = int(OrderStatus.NOTPAID)
            db_row["price"] = str(price)
            # Колонки дампа (Order.from/to — @Column from_station/to_station): по ним читает строки исполнитель M4
            db_row["from_station"], db_row["to_station"] = order["from"], order["to"]
            self.db_state.insert(tbl, db_row)

        mutations = [f"order_created:{order_id}:{tbl}:NOTPAID"]

        # Ancillary items: Food, Assurance, Luggage
        if "food" in t:
            self.has_food = True
            fo = {"id": f"fo-{order_id}", "order_id": order_id, "food_type": 1 if "station" in t else 2, "price": 20.0, "created_at_step": step_index}
            self.food_orders.append(fo)
            if hasattr(self.db_state, "insert"):
                self.db_state.insert("food_order", fo)
            self.record_step_entity(step_index, "food", fo)
            mutations.append(f"food_created:{order_id}")

        if "assurance" in t or "insurance" in t:
            self.has_assurance = True
            ass = {"id": f"ass-{order_id}", "order_id": order_id, "type_index": 1, "type_name": "Traffic Accident Assurance", "price": 20.0, "created_at_step": step_index}
            self.assurances.append(ass)
            if hasattr(self.db_state, "insert"):
                self.db_state.insert("assurance", ass)
            self.record_step_entity(step_index, "assurance", ass)
            mutations.append(f"assurance_created:{order_id}")

        m_weight = re.search(r"(\d+(?:\.\d+)?)\s*kg", t)
        if m_weight:
            self.has_consign = True
            w = float(m_weight.group(1))
            cs = {
                "id": f"consign-{order_id}",
                "order_id": order_id,
                "account_id": self.account_id,
                "weight": w,
                "consignee": "Consignee",
                "phone": "13800000000",
                "price": 16.0,
                "created_at_step": step_index,
            }
            self.consignments.append(cs)
            if hasattr(self.db_state, "insert"):
                # Строка таблицы с колонками дампа (ConsignRecord: @Column consign_record_id, user_id, ...)
                self.db_state.insert("consign_record", {
                    "consign_record_id": cs["id"], "user_id": self.account_id, "order_id": order_id,
                    "consignee": cs["consignee"], "consign_record_phone": cs["phone"],
                    "consign_record_price": cs["price"], "weight": w, "from_place": order["from"],
                    "to_place": order["to"], "handle_date": self.system_date, "target_date": self.travel_date,
                })
            self.record_step_entity(step_index, "consign", cs)
            mutations.append(f"consign_created:{order_id}:{w}kg")

        return StepMutationResult(step_index, action, "SUCCESS", mutations, affected_entities={"order_id": order_id})

    def _mutate_payment(self, step_index: int, action: str, payload: dict[str, Any], refs: dict[str, str] | None = None) -> StepMutationResult:
        target_oid = payload.get("orderId") or payload.get("order_id")
        if not target_oid and refs and "order" in refs:
            target_oid = self.resolve_ref_id("order", refs["order"])

        if target_oid:
            unpaid = [o for o in self.orders if o.get("id") == target_oid and o.get("status") == OrderStatus.NOTPAID]
        else:
            unpaid = [o for o in reversed(self.orders) if o.get("status") == OrderStatus.NOTPAID]

        if not unpaid:
            return StepMutationResult(step_index, action, "NOOP", ["no_unpaid_orders_found"])

        order = unpaid[0]
        mutations = []
        price = float(order.get("price", 0.0))

        if self.balance < price:
            # Fallback to External Payment Channel (e.g. S4)
            self.has_external_payment = True
            if hasattr(self.db_state, "insert"):
                self.db_state.insert("payment", {
                    "id": f"pay-ext-{order['id']}",
                    "order_id": order["id"],
                    "user_id": self.account_id,
                    "price": str(price),
                    "type": "O",
                })
            mutations.append(f"external_payment_triggered:{price}")
        else:
            # Internal Balance Deduction
            self.balance -= price
            self.balances[self.account_id] = self.balance
            if hasattr(self.db_state, "insert"):
                self.db_state.insert("inside_payment", {
                    "id": f"pay-ins-{order['id']}",
                    "order_id": order["id"],
                    "user_id": self.account_id,
                    "price": str(price),
                    "type": "P",
                })
            mutations.append(f"balance_deducted:{price}:remaining_{self.balance}")

        # Update order status to PAID
        order["status"] = OrderStatus.PAID
        tbl = "orders_other" if order.get("train_type") == TrainType.Other else "orders"
        if hasattr(self.db_state, "update"):
            self.db_state.update(tbl, {"status": int(OrderStatus.PAID)}, id=order["id"])
        mutations.append(f"order_status_updated:{order['id']}:PAID")

        return StepMutationResult(step_index, action, "SUCCESS", mutations, affected_entities={"order_id": order["id"], "status": "PAID"})

    def _mutate_collect_ticket(self, step_index: int, action: str, payload: dict[str, Any], refs: dict[str, str] | None = None) -> StepMutationResult:
        target_oid = payload.get("orderId") or payload.get("order_id")
        if not target_oid and refs and "order" in refs:
            target_oid = self.resolve_ref_id("order", refs["order"])

        if target_oid:
            target = [o for o in self.orders if o.get("id") == target_oid and o.get("status") in (OrderStatus.PAID, OrderStatus.CHANGE)]
        else:
            target = [o for o in reversed(self.orders) if o.get("status") in (OrderStatus.PAID, OrderStatus.CHANGE)]

        if not target:
            return StepMutationResult(step_index, action, "REFUSED", refusal_reason="no_paid_order_to_collect")

        order = target[0]
        order["status"] = OrderStatus.COLLECTED
        tbl = "orders_other" if order.get("train_type") == TrainType.Other else "orders"
        if hasattr(self.db_state, "update"):
            self.db_state.update(tbl, {"status": int(OrderStatus.COLLECTED)}, id=order["id"])
        return StepMutationResult(step_index, action, "SUCCESS", [f"order_status_updated:{order['id']}:COLLECTED"])

    def _mutate_enter_station(self, step_index: int, action: str, payload: dict[str, Any], refs: dict[str, str] | None = None) -> StepMutationResult:
        target_oid = payload.get("orderId") or payload.get("order_id")
        if not target_oid and refs and "order" in refs:
            target_oid = self.resolve_ref_id("order", refs["order"])

        if target_oid:
            target = [o for o in self.orders if o.get("id") == target_oid and o.get("status") == OrderStatus.COLLECTED]
        else:
            target = [o for o in reversed(self.orders) if o.get("status") == OrderStatus.COLLECTED]

        if not target:
            return StepMutationResult(step_index, action, "REFUSED", refusal_reason="no_collected_order_to_board")

        order = target[0]
        order["status"] = OrderStatus.USED
        tbl = "orders_other" if order.get("train_type") == TrainType.Other else "orders"
        if hasattr(self.db_state, "update"):
            self.db_state.update(tbl, {"status": int(OrderStatus.USED)}, id=order["id"])
        return StepMutationResult(step_index, action, "SUCCESS", [f"order_status_updated:{order['id']}:USED"])

    def _mutate_cancellation(self, step_index: int, action: str, payload: dict[str, Any], refs: dict[str, str] | None = None) -> StepMutationResult:
        target_oid = payload.get("orderId") or payload.get("order_id")
        if not target_oid and refs and "order" in refs:
            target_oid = self.resolve_ref_id("order", refs["order"])

        if target_oid:
            paid_orders = [o for o in self.orders if o.get("id") == target_oid and o.get("status") in (OrderStatus.PAID, OrderStatus.NOTPAID, OrderStatus.CHANGE)]
            collected_orders = [o for o in self.orders if o.get("id") == target_oid and o.get("status") == OrderStatus.COLLECTED]
        else:
            paid_orders = [o for o in reversed(self.orders) if o.get("status") in (OrderStatus.PAID, OrderStatus.NOTPAID, OrderStatus.CHANGE)]
            collected_orders = [o for o in reversed(self.orders) if o.get("status") == OrderStatus.COLLECTED]

        # Refusal on COLLECTED ticket (S7)
        if not paid_orders and collected_orders:
            order = collected_orders[0]
            self.has_refused_cancel = True
            ref_event = RefusalEvent(
                step_index=step_index,
                action="cancel",
                entity_id=order["id"],
                reason="Order status COLLECTED cannot be cancelled",
                details={"status": int(order["status"])},
            )
            self.refusal_events.append(ref_event)
            self.refusals["cancel"] = "Order Status Cancel Not Permitted"
            self.last_refusal = {"step": step_index, "action": "cancel", "order_id": order["id"], "reason": "status_is_COLLECTED"}
            return StepMutationResult(
                step_index, action, "REFUSED",
                [f"cancellation_refused:{order['id']}:status_is_COLLECTED"],
                refusal_reason="order_already_collected",
                affected_entities={"order_id": order["id"], "status": "COLLECTED (unchanged)"},
            )

        if not paid_orders:
            return StepMutationResult(step_index, action, "NOOP", ["no_cancellable_order_found"])

        order = paid_orders[0]
        price = float(order.get("price", 0.0))
        refund_amount = round(price * 0.8, 2) if order.get("status") == OrderStatus.PAID else 0.0

        order["status"] = OrderStatus.CANCEL
        tbl = "orders_other" if order.get("train_type") == TrainType.Other else "orders"
        if hasattr(self.db_state, "update"):
            self.db_state.update(tbl, {"status": int(OrderStatus.CANCEL)}, id=order["id"])

        if refund_amount > 0:
            self.balance += refund_amount
            self.balances[self.account_id] = self.balance
            if hasattr(self.db_state, "insert"):
                self.db_state.insert("inside_money", {
                    "id": f"drawback-{order['id']}",
                    "user_id": self.account_id,
                    "money": str(refund_amount),
                    "type": "D",
                })

        return StepMutationResult(
            step_index, action, "SUCCESS",
            [f"order_status_updated:{order['id']}:CANCEL", f"refund_credited:{refund_amount}:new_balance_{self.balance}"],
        )

    def _mutate_rebook(self, step_index: int, action: str, payload: dict[str, Any], refs: dict[str, str] | None = None) -> StepMutationResult:
        target_oid = payload.get("orderId") or payload.get("order_id")
        if not target_oid and refs and "order" in refs:
            target_oid = self.resolve_ref_id("order", refs["order"])

        if target_oid:
            paid_orders = [o for o in self.orders if o.get("id") == target_oid and o.get("status") == OrderStatus.PAID]
            collected_orders = [o for o in self.orders if o.get("id") == target_oid and o.get("status") == OrderStatus.COLLECTED]
        else:
            paid_orders = [o for o in reversed(self.orders) if o.get("status") == OrderStatus.PAID]
            collected_orders = [o for o in reversed(self.orders) if o.get("status") == OrderStatus.COLLECTED]

        # Refusal on COLLECTED ticket (S7)
        if not paid_orders and collected_orders:
            order = collected_orders[0]
            self.has_refused_rebook = True
            ref_event = RefusalEvent(
                step_index=step_index,
                action="rebook",
                entity_id=order["id"],
                reason="Order status COLLECTED cannot be rebooked",
                details={"status": int(order["status"])},
            )
            self.refusal_events.append(ref_event)
            self.refusals["rebook"] = "Order status COLLECTED cannot be rebooked"
            self.last_refusal = {"step": step_index, "action": "rebook", "order_id": order["id"], "reason": "status_is_COLLECTED"}
            return StepMutationResult(
                step_index, action, "REFUSED",
                [f"rebooking_refused:{order['id']}:status_is_COLLECTED"],
                refusal_reason="order_already_collected",
                affected_entities={"order_id": order["id"], "status": "COLLECTED (unchanged)"},
            )

        if not paid_orders:
            return StepMutationResult(step_index, action, "NOOP", ["no_rebookable_order_found"])

        order = paid_orders[0]
        orig_price = float(order.get("price", 0.0))
        cheaper_price = round(orig_price * 0.67, 2)
        diff = round(orig_price - cheaper_price, 2)

        order["seat_class"] = 2
        order["price"] = cheaper_price
        order["status"] = OrderStatus.CHANGE
        order["updated_at_step"] = step_index
        self.record_step_entity(step_index, "order", order)

        tbl = "orders_other" if order.get("train_type") == TrainType.Other else "orders"
        if hasattr(self.db_state, "update"):
            self.db_state.update(tbl, {
                "seat_class": 2, "price": str(cheaper_price), "status": int(OrderStatus.CHANGE),
            }, id=order["id"])

        if diff > 0:
            self.balance += diff
            self.balances[self.account_id] = self.balance
            if hasattr(self.db_state, "insert"):
                self.db_state.insert("inside_money", {
                    "id": f"rebook-diff-{order['id']}",
                    "user_id": self.account_id,
                    "money": str(diff),
                    "type": "D",
                })

        return StepMutationResult(
            step_index, action, "SUCCESS",
            [f"order_rebooked:{order['id']}:second_class:{cheaper_price}", f"difference_refunded:{diff}:balance_{self.balance}"],
        )

    # Админские сущности (S6). Параметры — поля DTO запроса от M1 (camelCase), иначе значения S6 по умолчанию.
    # В БД строки пишутся с колонками дампа: по ним их читает исполнитель M4. Имена станций сервисы хранят
    # без пробелов строчными (Station#setName, Trip, StringUtils.String2Lower).

    def _mutate_admin_station(self, step_index: int, action: str, payload: dict[str, Any]) -> StepMutationResult:
        station_name = payload.get("name", "Ning Bo")
        key = _db_name(station_name)
        st_data = {"id": f"station-{key}", "name": station_name, "stay_time": payload.get("stayTime", 5),
                   "created_at_step": step_index}
        self.admin_entities["stations"].append(st_data)
        if hasattr(self.db_state, "insert"):
            # В БД — имя, как его хранит сервис станций (Station#setName); в реестре шагов — как в шаге
            self.db_state.insert("station", {**st_data, "name": key})
        self.record_step_entity(step_index, "station", st_data)
        return StepMutationResult(step_index, action, "SUCCESS", [f"station_created:{station_name}"])

    def _mutate_admin_train(self, step_index: int, action: str, payload: dict[str, Any]) -> StepMutationResult:
        name = payload.get("name", "GaoTieSix")
        tt_data = {"id": f"train-type-{name}", "name": name, "economy_class": payload.get("economyClass", 100),
                   "confort_class": payload.get("confortClass", 30), "average_speed": payload.get("averageSpeed", 300),
                   "created_at_step": step_index}
        self.admin_entities["train_types"].append(tt_data)
        if hasattr(self.db_state, "insert"):
            self.db_state.insert("train_type", tt_data)
        self.record_step_entity(step_index, "train", tt_data)
        return StepMutationResult(step_index, action, "SUCCESS", [f"train_type_created:{name}"])

    def _mutate_admin_route(self, step_index: int, action: str, payload: dict[str, Any]) -> StepMutationResult:
        r_id = payload.get("id") or "route-sh-sz-nb"
        stations = payload.get("stations") or payload.get("stationList") or ["Shanghai", "Suzhou", "Ning Bo"]
        distances = payload.get("distances") or payload.get("distanceList") or [0, 100, 250]
        if isinstance(stations, str):
            stations = [s.strip() for s in stations.split(",") if s.strip()]
        if isinstance(distances, str):
            distances = [int(float(d)) for d in distances.split(",") if d.strip()]
        r_data = {"id": r_id, "start_station_id": stations[0], "terminal_station_id": stations[-1], "stations": stations,
                  "distances": distances, "created_at_step": step_index}
        self.admin_entities["routes"].append(r_data)
        if hasattr(self.db_state, "insert"):
            self.db_state.insert("route", {"id": r_id, "start_station": _db_name(stations[0]),
                                           "end_station": _db_name(stations[-1])})
            for i, s in enumerate(stations):
                self.db_state.insert("route_stations", {"route_id": r_id, "stations": _db_name(s), "stations_order": i})
            for i, d in enumerate(distances):
                self.db_state.insert("route_distances", {"route_id": r_id, "distances": d, "distances_order": i})
        self.record_step_entity(step_index, "route", r_data)
        return StepMutationResult(step_index, action, "SUCCESS", [f"route_created:{r_id}"])

    def _mutate_admin_price(self, step_index: int, action: str, payload: dict[str, Any]) -> StepMutationResult:
        p_id = payload.get("id") or "price-gt6"
        routes = self.admin_entities["routes"]
        p_data = {"id": p_id, "train_type": payload.get("trainType", "GaoTieSix"),
                  "basic_price_rate": payload.get("basicPriceRate", 0.5),
                  "first_class_price_rate": payload.get("firstClassPriceRate", 1.2),
                  "route_id": payload.get("routeId") or (routes[-1]["id"] if routes else "route-sh-sz-nb"),
                  "created_at_step": step_index}
        self.admin_entities["price_configs"].append(p_data)
        if hasattr(self.db_state, "insert"):
            self.db_state.insert("price_config", p_data)
        self.record_step_entity(step_index, "price", p_data)
        return StepMutationResult(step_index, action, "SUCCESS", [f"price_config_created:{p_id}"])

    def _mutate_admin_travel(self, step_index: int, action: str, payload: dict[str, Any]) -> StepMutationResult:
        trip_id = payload.get("tripId") or payload.get("trip_id") or "G9101"
        routes = self.admin_entities["routes"]
        tr_data = {
            # id — номер поезда (реестр шагов M3 разрешает refs по id); type и number — колонки дампа
            "id": trip_id, "trip_id": trip_id, "type": _TRIP_TYPE_ORDINAL.get(trip_id[:1], 0), "number": trip_id[1:],
            "train_type_name": payload.get("trainTypeName", "GaoTieSix"),
            "route_id": payload.get("routeId") or (routes[-1]["id"] if routes else "route-sh-sz-nb"),
            "start_station_name": _db_name(payload.get("startStationName", "Shanghai")),
            "stations_name": _db_name(payload.get("stationsName", "")),
            "terminal_station_name": _db_name(payload.get("terminalStationName", "Ning Bo")),
            "start_time": payload.get("startTime", "09:00"), "end_time": payload.get("endTime", "12:00"),
            "created_at_step": step_index,
        }
        self.admin_entities["trips"].append(tr_data)
        if hasattr(self.db_state, "insert"):
            # Скоростные (G/D) — таблица trip сервиса travel, остальные — trip2 сервиса travel2
            self.db_state.insert("trip" if trip_id[:1] in ("G", "D") else "trip2", tr_data)
        self.record_step_entity(step_index, "trip", tr_data)
        return StepMutationResult(step_index, action, "SUCCESS", [f"trip_created:{trip_id}"])

    def _mutate_update_consignee(self, step_index: int, action: str, payload: dict[str, Any], refs: dict[str, str] | None = None) -> StepMutationResult:
        if not self.consignments:
            return StepMutationResult(step_index, action, "NOOP", ["no_consignments_found"])

        target_cid = payload.get("consignId") or payload.get("consign_id")
        if not target_cid and refs and "consign" in refs:
            target_cid = self.resolve_ref_id("consign", refs["consign"])

        if target_cid:
            matches = [c for c in self.consignments if c.get("id") == target_cid]
            cs = matches[0] if matches else self.consignments[-1]
        else:
            cs = self.consignments[-1]

        new_name = payload.get("consignee", "New Consignee")
        new_phone = payload.get("phone", "13900000000")
        cs["consignee"] = new_name
        cs["phone"] = new_phone
        cs["updated_at_step"] = step_index
        self.record_step_entity(step_index, "consign", cs)

        if hasattr(self.db_state, "update"):
            self.db_state.update("consign_record", {
                "consignee": new_name, "consign_record_phone": new_phone,
            }, consign_record_id=cs.get("id") or cs.get("consign_record_id"))

        return StepMutationResult(
            step_index, action, "SUCCESS",
            [f"consignee_updated:{cs.get('id')}:{new_name}:{new_phone}:weight_unchanged_{cs.get('weight')}"],
        )

    # -------------------------------------------------------------------------
    # Public Mutation Primitives
    # -------------------------------------------------------------------------

    def add_order(self, order: dict[str, Any], step_index: int | None = None) -> dict[str, Any]:
        """Adds an order to state."""
        od = dict(order)
        if step_index is not None:
            od["created_at_step"] = step_index
        if "train_type" not in od and "train_number" in od:
            od["train_type"] = TrainType.from_train_number(od["train_number"])
        if "status" in od:
            od["status"] = OrderStatus.from_value(od["status"])
        else:
            od["status"] = OrderStatus.NOTPAID
        if "price" in od:
            od["price"] = float(od["price"])
        self.orders.append(od)
        if step_index is not None:
            self.record_step_entity(step_index, "order", od)
        return od

    def update_order_status(self, order_id: str, new_status: OrderStatus | int | str) -> bool:
        """Updates status of an existing order."""
        norm_status = OrderStatus.from_value(new_status)
        order = self.get_order_by_id(order_id)
        if order is not None:
            order["status"] = norm_status
            return True
        return False

    def add_contact(self, contact: dict[str, Any], step_index: int | None = None) -> dict[str, Any]:
        """Adds a contact to state."""
        cd = dict(contact)
        if step_index is not None:
            cd["created_at_step"] = step_index
        if "account_id" not in cd:
            cd["account_id"] = self.account_id
        self.contacts.append(cd)
        if step_index is not None:
            self.record_step_entity(step_index, "contact", cd)
        return cd

    def deduct_balance(self, amount: float, account_id: str | None = None) -> bool:
        """Deducts amount from account balance."""
        target_uid = account_id if account_id is not None else self.account_id
        current = self.get_balance(target_uid)
        if current >= amount:
            new_bal = current - amount
            self.balances[target_uid] = new_bal
            if target_uid == self.account_id:
                self.balance = new_bal
            return True
        return False

    def refund_balance(self, amount: float, account_id: str | None = None) -> None:
        """Credits refund amount to account balance."""
        target_uid = account_id if account_id is not None else self.account_id
        new_bal = self.get_balance(target_uid) + amount
        self.balances[target_uid] = new_bal
        if target_uid == self.account_id:
            self.balance = new_bal

    def register_user(
        self,
        user_name: str,
        account_id: str | None = None,
        balance: float = 0.0,
    ) -> str:
        """Registers a new user (for S4 MRK-reg-430), setting initial balance."""
        uid = account_id or f"user-{user_name}"
        user_entry = {
            "user_id": uid,
            "user_name": user_name,
            "document_num": "MRK-rdoc",
            "document_type": 1,
            "email": f"{user_name}@example.com",
            "gender": 1,
        }
        self.users.append(user_entry)
        self.balances[uid] = float(balance)
        self.user_name = user_name
        self.account_id = uid
        self.balance = float(balance)
        return uid

    def add_admin_entity(self, entity_type: str, data: dict[str, Any], step_index: int | None = None) -> None:
        """Records newly created station, train type, route, trip, or price config (S6)."""
        if entity_type not in self.admin_entities:
            self.admin_entities[entity_type] = []
        d = dict(data)
        if step_index is not None:
            d["created_at_step"] = step_index
        self.admin_entities[entity_type].append(d)
        if step_index is not None:
            self.record_step_entity(step_index, entity_type, d)

    def set_refusal(self, action: str, reason: str = "") -> None:
        """Records business refusal (e.g. S7 cancellation/rebooking refusal on COLLECTED order)."""
        self.refusals[action] = reason
