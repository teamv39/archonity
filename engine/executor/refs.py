"""Привязка запроса шага к аргументам обработчика (M4): params и refs из StepRequest (ADR-005, M1 -> M4).

params M1 — поля DTO тела и path/query-параметры, которые определил текст шага или UI. refs — ссылки на результаты
прошлых шагов (`new_of_step_4`): из них берутся идентификаторы и связанные поля (заказ, рейс, контакт, багаж,
пользователь). Не заданное ни тем, ни другим поле запроса — `Unknown` с происхождением «запрос шага».
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from engine.executor.program import ann_value
from engine.executor.repo import convert
from engine.executor.values import Obj, simple_name

if TYPE_CHECKING:
    from engine.executor.interp import StepRun
    from engine.executor.program import Program
    from engine.grounding.request import StepRequest

TRIP_TYPES = ("G", "D", "Z", "T", "K")  # edu.fudan.common.entity.Type, порядок констант = ordinal в БД
REF = re.compile(r"^(first|second|new)_of_step_(\d+)$")
USER_FIELDS = ("accountId", "loginId", "userId")


class RefResolver:
    """Сущности прошлых шагов сценария и их поля для запроса текущего шага."""

    def __init__(self, program: Program) -> None:
        self.program = program
        self.steps: dict[int, StepRequest] = {}
        self.created: dict[int, dict[str, Any]] = {}

    def begin(self) -> None:
        self.steps.clear()
        self.created.clear()

    def remember_step(self, step_req: StepRequest) -> None:
        self.steps[step_req.step] = step_req

    def remember_mutation(self, step_n: int, affected: dict[str, Any] | None) -> None:
        if affected:
            self.created[step_n] = dict(affected)

    # --- сущности --------------------------------------------------------------------------------------------------

    def entity(self, kind: str, ref: str, state: Any) -> dict[str, Any]:
        """Поля сущности по ссылке: имя поля Java -> значение. Пусто — не разрешить."""
        m = REF.match(ref or "")
        if not m:
            return {}
        pick, n = m.group(1), int(m.group(2))
        if kind == "order":
            return self._order(pick, n, state)
        if kind in ("trip", "train"):
            return self._trip(pick, n, state)
        if kind == "contact":
            return self._contact(pick, n, state)
        if kind == "consign":
            return self._consign(state)
        if kind == "user":
            return {"accountId": getattr(state, "account_id", None), "userName": getattr(state, "user_name", None)}
        return {}

    def _order(self, pick: str, n: int, state: Any) -> dict[str, Any]:
        oid = self.created.get(n, {}).get("order_id")
        order = state.get_order_by_id(oid) if oid and hasattr(state, "get_order_by_id") else None
        if order is None:
            # Заказ, с которым работает сценарий: последний созданный в сценарии, иначе первый у пользователя
            created = [c.get("order_id") for _, c in sorted(self.created.items()) if c.get("order_id")]
            if created:
                order = state.get_order_by_id(created[-1])
            elif hasattr(state, "get_orders"):
                mine = state.get_orders(account_id=state.account_id)
                order = mine[1] if pick == "second" and len(mine) > 1 else (mine[0] if mine else None)
        if order is None:
            return {}
        tn = order.get("train_number")
        return {"orderId": order.get("id"), "id": order.get("id"), "tripId": tn, "trainNumber": tn, "oldTripId": tn,
                "accountId": order.get("account_id"), "travelDate": order.get("travel_date"),
                "from": order.get("from_station") or order.get("from"), "to": order.get("to_station") or order.get("to")}

    def _trip(self, pick: str, n: int, state: Any) -> dict[str, Any]:
        step = self.steps.get(n)
        if step is None:
            return {}
        params = step.params or {}
        start = str(params.get("startPlace") or params.get("startingPlace") or "").lower()
        end = str(params.get("endPlace") or "").lower()
        module = self.program.module_of(step.handler)
        table = "trip2" if "travel2" in module or "other" in module else "trip"
        db = getattr(state, "db_state", None)
        if db is None:
            return {}
        stations: dict[str, list[str]] = {}
        for r in sorted(db.get_table("route_stations"), key=lambda r: int(r.get("stations_order") or 0)):
            stations.setdefault(r.get("route_id"), []).append(str(r.get("stations", "")).lower())
        hits = []
        for row in db.get_table(table):
            st = stations.get(row.get("route_id"), [])
            if start and end and (start not in st or end not in st or st.index(start) >= st.index(end)):
                continue
            hits.append(row)
        idx = 1 if pick == "second" else 0
        if len(hits) <= idx:
            return {}
        row = hits[idx]
        try:
            letter = TRIP_TYPES[int(row.get("type"))]
        except (TypeError, ValueError, IndexError):
            return {}
        trip_id = f"{letter}{row.get('number')}"
        out = {"tripId": trip_id, "trainNumber": trip_id, "trainTypeName": row.get("train_type_name")}
        if start:
            out["from"], out["startPlace"], out["startStation"] = params.get("startPlace"), params.get(
                "startPlace"), params.get("startPlace")
        if end:
            out["to"], out["endPlace"], out["endStation"] = params.get("endPlace"), params.get(
                "endPlace"), params.get("endPlace")
        date = params.get("departureTime") or params.get("travelDate")
        if date:
            out["date"] = out["departureTime"] = date
        return out

    def _contact(self, pick: str, n: int, state: Any) -> dict[str, Any]:
        contacts = state.get_contacts() if hasattr(state, "get_contacts") else []
        if not contacts:
            return {}
        if pick == "new":
            c = contacts[-1]
        else:
            c = contacts[1] if pick == "second" and len(contacts) > 1 else contacts[0]
        return {"contactsId": c.get("id"), "contactId": c.get("id"), "contactsName": c.get("name")}

    def _consign(self, state: Any) -> dict[str, Any]:
        created = [c.get("order_id") for _, c in sorted(self.created.items()) if c.get("order_id")]
        records = [c for c in getattr(state, "consignments", []) if not created or c.get("order_id") in created]
        if not records:
            return {}
        r = records[-1]
        return {"id": r.get("id") or r.get("consign_record_id"), "orderId": r.get("order_id")}

    # --- привязка входа шага ---------------------------------------------------------------------------------------

    def bind_entry(self, run: StepRun, handler: str, step_req: StepRequest) -> list[Any]:
        """Аргументы обработчика шага: тело, path/query-параметры, заголовки."""
        from engine.executor.interp import unknown_of

        params = {k: v for k, v in (step_req.params or {}).items() if v is not None}
        refs = step_req.refs or {}
        state = run.state
        ref_fields: dict[str, dict[str, Any]] = {}
        for kind, ref in refs.items():
            ent = self.entity(kind, ref, state)
            if ent:
                ref_fields[kind] = ent
        user = {"accountId": getattr(state, "account_id", None)}
        out: list[Any] = []
        for p in self.program.params_by_method.get(handler, []):
            ann = p.annotations
            if "RequestBody" in ann:
                out.append(self.body(run, p.type, params, ref_fields, user, step_req))
                continue
            if "RequestHeader" in ann or simple_name(p.type) == "HttpHeaders":
                # Клиент после входа шлёт токен в заголовке Authorization (JWTFilter)
                out.append(Obj("org.springframework.http.HttpHeaders", {"__map__": {
                    "Authorization": "Bearer <token>", "Content-Type": "application/json"}}, src="request"))
                continue
            name = ann_value(ann.get("PathVariable") or ann.get("RequestParam") or "") or p.name
            value = self.value_for(name, simple_name(handler.split("#", 1)[0]), params, ref_fields, user)
            if value is None:
                out.append(unknown_of(f"parameter {name} of the step request (not set by the step)", p.type,
                                      "request", success_defaults=False))
            else:
                out.append(convert(value, p.type))
        return out

    def body(self, run: StepRun, type_fqn: str, params: dict[str, Any], ref_fields: dict[str, dict[str, Any]],
             user: dict[str, Any], step_req: StepRequest) -> Obj:
        p = self.program
        tn = p.type_node(type_fqn, p.module_of(step_req.handler))
        obj = Obj(type_fqn, src="request", origin=f"request body of step {step_req.step}")
        for f in p.instance_fields(tn):
            v = self.value_for(f.name, simple_name(type_fqn), params, ref_fields, user)
            if v is not None:
                obj.fields[f.name] = convert(v, f.type)
        return obj

    @staticmethod
    def value_for(name: str, owner: str, params: dict[str, Any], ref_fields: dict[str, dict[str, Any]],
                  user: dict[str, Any]) -> Any:
        """Значение поля запроса: params шага, затем поля сущностей refs, затем пользователь сценария."""
        if name in params:
            return params[name]
        low = name.lower()
        if low == "id":
            # id — сущности, о которой запрос (Consign -> consign); иначе единственной сущности refs с id
            for kind, ent in ref_fields.items():
                if kind in owner.lower() and ent.get("id") is not None:
                    return ent["id"]
            with_id = [ent for ent in ref_fields.values() if ent.get("id") is not None]
            return with_id[0]["id"] if len(with_id) == 1 else None
        order = ("trip", "train", "order", "contact", "consign", "user") if low in ("tripid", "trainnumber") else (
            "order", "consign", "contact", "trip", "train", "user")
        for kind in order:
            ent = ref_fields.get(kind) or {}
            for k, v in ent.items():
                if k.lower() == low and v is not None and k != "id":
                    return v
        if name in USER_FIELDS and user.get("accountId"):
            return user["accountId"]
        return None
