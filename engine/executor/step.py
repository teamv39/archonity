"""Шаг сценария для исполнителя M4: StepRequest -> аргументы обработчика -> события -> рёбра.

Аргументы обработчика:
- `@RequestBody` — DTO из `params` шага и ссылок `refs` (поля, которых не определил шаг, неизвестны);
- `@PathVariable` — по имени из `params`, ссылок или текущего пользователя;
- `@RequestHeader` — неизвестно.

Ссылки `<first|second|new>_of_step_<n>` разрешаются по миру M4: `new` — сущность, сохранённая шагом n,
`first`/`second` — элемент результата обработчика шага n; если не нашли — модель состояния M3.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from engine.executor.interpreter import Interpreter, Sink
from engine.executor.values import UNKNOWN, EnumV, ListV, Obj, OptionalV, Wrapper
from engine.executor.world import camel

_REF = re.compile(r"^(first|second|new)_of_step_(\d+)$")
_WORDY = re.compile(r"^[A-Za-z][A-Za-z ,.'-]*$")

# Признаки вида сущности в простом имени типа
_KIND_HINTS = {
    "order": ("order",),
    "trip": ("trip",),
    "contact": ("contact",),
    "user": ("user", "token", "account"),
    "food": ("food",),
    "store": ("store",),
    "station": ("station",),
    "route": ("route",),
    "train": ("traintype", "train"),
    "price": ("price",),
    "consign": ("consign",),
    "assurance": ("assurance",),
}

# Поля DTO и path-параметры, в которые идёт ID сущности ссылки
_ID_FIELDS = {
    "order": ("orderId", "id"),
    "trip": ("tripId",),
    "contact": ("contactsId", "contactId"),
    "user": ("accountId", "userId", "loginId"),
    "food": ("foodId",),
    "store": ("storeId",),
    "station": ("stationId",),
    "route": ("routeId",),
    "train": ("trainTypeId",),
    "price": ("priceId",),
    "consign": ("consignId",),
    "assurance": ("assuranceId",),
}
_USER_FIELDS = ("accountId", "userId", "loginId")

# Поле DTO -> поля сущности ссылки с тем же смыслом (как UI переносит их из ответа предыдущего шага)
_FIELD_ALIASES = {
    "from": ("from", "startStation", "startPlace", "startStationName", "fromStation"),
    "to": ("to", "terminalStation", "endPlace", "terminalStationName", "toStation"),
    "date": ("date", "travelDate", "departureTime"),
    "tripId": ("tripId", "trainNumber"),
    "oldTripId": ("trainNumber",),
}


class StepExecutor:
    """M4 на уровне сценария: мир, реестр результатов шагов, сборка рёбер шага."""

    def __init__(self, index: Any, rules: Any, ir_dir: str | Path, targets_root: str | Path | None,
                 judge: Any = None) -> None:
        self.index = index
        self.it = Interpreter(index, rules, Path(ir_dir), Path(targets_root) if targets_root else None, judge)
        self.results: dict[int, Any] = {}
        self.current_user: str | None = None
        self.registered_username: str | None = None
        self.handlers: dict[int, str] = {}
        self.step_params: dict[int, dict[str, Any]] = {}
        self.step_refs: dict[int, dict[str, str]] = {}
        self.saved: dict[int, list[tuple[str, Obj]]] = {}
        self.unknowns: dict[str, list[dict[str, Any]]] = {}
        self.sid = "S?"

    def begin_scenario(self, sid: str) -> None:
        self.sid = sid
        db = getattr(self.index, "db_state", None)
        self.it.begin_scenario(db.fork() if db is not None and hasattr(db, "fork") else db)
        self.results = {}
        self.current_user = None
        self.registered_username = None
        self.handlers = {}
        self.step_params = {}
        self.step_refs = {}
        self.saved = {}
        self.unknowns[sid] = []

    # --- ссылки --------------------------------------------------------------

    def resolve_ref(self, kind: str, ref: str, state: Any, depth: int = 0) -> Any:
        m = _REF.match(ref or "")
        if not m:
            return None
        pick, n = m.group(1), int(m.group(2))
        if pick == "new":
            cands = [(fqn, obj) for fqn, obj in self.saved.get(n, []) if _is_kind(fqn, kind)]
            if cands:
                top = max(_kind_rank(fqn, kind) for fqn, _ in cands)
                return [obj for fqn, obj in cands if _kind_rank(fqn, kind) == top][-1]
        idx = 1 if pick == "second" else 0
        found = _find_kind(_payload(self.results.get(n)), kind)
        if found:
            ent = found[idx] if idx < len(found) else found[0]
            if self.entity_id(ent, kind) is not UNKNOWN:
                return ent
            # Контекст скелета (context.choices): выбор «первого» рейса/контакта/блюда не меняет исполненный код,
            # поэтому при неизвестном ID берём строку таблицы сущности этого вида в сервисе шага
            row_ent = self._table_entity(n, kind, idx)
            if row_ent is not None:
                # поля ответа шага (станции, дата поиска) + ID из строки таблицы
                merged = Obj(ent.type, dict(row_ent.fields), open=True)
                merged.fields.update({k: v for k, v in ent.fields.items() if v is not UNKNOWN and v is not None})
                return merged
            return ent
        saved_c = [(fqn, o) for fqn, o in self.saved.get(n, []) if _is_kind(fqn, kind)]
        top = max((_kind_rank(fqn, kind) for fqn, _ in saved_c), default=0)
        saved = [o for fqn, o in saved_c if _kind_rank(fqn, kind) == top]
        if saved:
            return saved[-1] if pick == "new" else saved[min(idx, len(saved) - 1)]
        # Шаг n не создавал и не возвращал сущность этого вида: та, на которую ссылался сам шаг n
        # (M1 ссылается на шаг оплаты как на «заказ шага 6» — это заказ, который оплачивали)
        prev = self.step_refs.get(n, {}).get(kind)
        if prev and prev != ref and depth < 4:
            ent = self.resolve_ref(kind, prev, state, depth + 1)
            if ent is not None:
                return ent
        if state is not None and hasattr(state, "resolve_ref"):
            d = state.resolve_ref(kind, ref)
            if isinstance(d, dict):
                return Obj(None, {camel(k): (v.value if hasattr(v, "value") else v) for k, v in d.items()
                                  if isinstance(k, str)}, open=True)
        return None

    def _table_entity(self, n: int, kind: str, idx: int) -> Obj | None:
        handler = self.handlers.get(n)
        module = self.index.N.get(handler or "", {}).get("module")
        w = self.it.world
        for fqn, table in sorted(w.table_of.items()):
            tid = self.it.types.resolve(fqn, module)
            if not tid or self.it.types.types[tid].get("module") != module or not _is_kind(fqn, kind):
                continue
            rows = w.rows(table)
            if rows:
                return w.row_to_obj(fqn, rows[min(idx, len(rows) - 1)], module)
        return None

    def entity_id(self, ent: Any, kind: str, depth: int = 0) -> Any:
        """ID сущности ссылки; у обёрток (TripAllDetail) — ID вложенного объекта того же вида."""
        if not isinstance(ent, Obj) or depth > 2:
            return UNKNOWN
        names = list(_ID_FIELDS.get(kind, ())) + ["id"]
        if kind == "user":
            names = ["userId", "accountId", "id"]
        for name in names:
            v = ent.fields.get(name, UNKNOWN)
            if v is UNKNOWN or v is None:
                continue
            if isinstance(v, Obj):
                return self.to_string(v)
            return v
        for k, v in ent.fields.items():
            if isinstance(v, Obj) and (_is_kind(v.type, kind) or kind in k.lower()):
                r = self.entity_id(v, kind, depth + 1)
                if r is not UNKNOWN:
                    return r
        return UNKNOWN

    def to_string(self, obj: Obj) -> Any:
        """toString() проекта без событий (TripId -> "G1234")."""
        tid = self.it.types.resolve(obj.type, None)
        mid = self.it.types.method_of(tid, "toString", 0)
        if not mid or mid not in self.it.ir:
            return UNKNOWN
        self.it.sink.muted += 1
        try:
            r = self.it._run_body(mid, obj, [], self.index.unit_of(mid), ("SKELETON", "to_string"))
        finally:
            self.it.sink.muted -= 1
        return r if isinstance(r, str) else UNKNOWN

    # --- аргументы обработчика ------------------------------------------------

    def handler_args(self, handler: str, params: dict[str, Any], refs: dict[str, Any], state: Any) -> list[Any]:
        ents: dict[str, Any] = {k: self.resolve_ref(k, v, state) for k, v in (refs or {}).items()}
        # Последний слой: параметры запросов шагов, на которые ссылается шаг (UI переносит дату и станции поиска)
        for v in (refs or {}).values():
            m = _REF.match(v or "")
            if m and self.step_params.get(int(m.group(2))):
                ents.setdefault(f"#params{m.group(2)}", Obj(None, dict(self.step_params[int(m.group(2))]), open=True))
        user = self.current_user or getattr(state, "account_id", None)
        out: list[Any] = []
        for p in self.it.params.get(handler, []):
            anns = {a.get("name"): a.get("args", "") for a in p.get("annotations") or []}
            if "RequestBody" in anns:
                out.append(self.build_dto(p.get("type"), params, ents, user, handler))
            elif "RequestHeader" in anns:
                out.append(UNKNOWN)
            else:
                m = re.search(r'"([^"]+)"', anns.get("PathVariable") or "")
                name = m.group(1) if m else p["name"]
                out.append(self.field_value(name, params, ents, user, p.get("type")))
        return out

    def field_value(self, name: str, params: dict[str, Any], ents: dict[str, Any], user: Any,
                    ftype: str | None = None) -> Any:
        if name in params and params[name] is not None:
            return self._typed(params[name], ftype)
        for kind, ent in ents.items():
            if ent is not None and name in _ID_FIELDS.get(kind, ()):
                v = self.entity_id(ent, kind)
                if v is not UNKNOWN:
                    return v
        if name in _USER_FIELDS and user:
            return user
        if name == "id":
            return UNKNOWN
        for alias in _FIELD_ALIASES.get(name, (name,)):
            for kind, ent in ents.items():
                # сама сущность, затем вложенные объекты (TripAllDetail -> tripResponse)
                layers = [ent] + ([x for x in ent.fields.values() if isinstance(x, Obj)] if isinstance(ent, Obj) else [])
                for layer in layers:
                    if not isinstance(layer, Obj) or alias not in layer.fields:
                        continue
                    v = layer.fields[alias]
                    if v is UNKNOWN or v is None:
                        continue
                    if isinstance(v, Obj) and ftype == "java.lang.String":
                        v = self.to_string(v)
                    return v
        return UNKNOWN

    def _typed(self, v: Any, ftype: str | None) -> Any:
        if ftype in ("double", "float", "java.lang.Double", "java.lang.Float") and isinstance(v, int) \
                and not isinstance(v, bool):
            return float(v)
        tid = self.it.types.resolve(ftype, None) if ftype else None
        if tid and self.it.types.is_enum(tid) and isinstance(v, (int, str)):
            return self.it.enum_value(tid, v) if isinstance(v, str) else UNKNOWN
        return v

    def build_dto(self, ftype: str | None, params: dict[str, Any], ents: dict[str, Any], user: Any,
                  handler: str) -> Any:
        module = self.index.N.get(handler, {}).get("module")
        tid = self.it.types.resolve(ftype, module)
        obj = Obj(ftype, {}, open=True)
        fields = self.it.types.all_fields(tid)
        names = {f["name"] for f in fields}
        defaults: dict[str, Any] = {}
        hname = self.index.N.get(handler, {}).get("name", "")
        if getattr(self, "_verb", None) == "POST" and re.match(r"(create|add|register|save|insert|new)", hname, re.I):
            # Создание через POST: собственный ID новой сущности клиент не присылает (Jackson оставит null)
            own = [k for k in _ID_FIELDS if _kind_rank(ftype, k) >= 2]
            for name in ["id"] + [f for k in own for f in _ID_FIELDS[k]]:
                if name in names and name not in params:
                    defaults[name] = None
        is_user_dto = _kind_rank(ftype, "user") >= 2 and "password" in names
        if is_user_dto:
            # Регистрация: DTO самого пользователя — ID текущего пассажира в него не подставляем. Имени нового
            # пользователя в тексте шага нет; синтетическое имя нужно, чтобы следующий логин нашёл ту же строку.
            user = None
            if params.get("userName") is None and "userName" in names:
                defaults["userName"] = self.registered_username = "m4-new-user"
        if {"password", "verificationCode"} <= names:
            # Логин: контекст скелета (context.account) — пассажир сценария (или зарегистрированный в сценарии),
            # кода подтверждения нет
            defaults = {"verificationCode": ""}
            login = self.registered_username or getattr(self, "_user_name", None)
            if login:
                defaults["username"] = login
        if "consigneeName" in names:
            # UI (client_ticket_book.js): имя, телефон и вес получателя багажа ставятся только при отмеченном
            # «need consign»; без багажа полей в запросе нет (null). Имени нет в тексте шага, вес есть.
            w = params.get("consigneeWeight")
            if isinstance(w, (int, float)) and not isinstance(w, bool):
                defaults["consigneeName"] = "consignee" if w > 0 else None
                defaults["consigneePhone"] = "consignee-phone" if w > 0 else None
        for f in fields:
            v = self.field_value(f["name"], params, ents, user, f.get("type"))
            if v is UNKNOWN and f["name"] == "id":
                # DTO того же вида, что сущность ссылки (Consign и запись багажа): id — ID этой сущности
                for kind, ent in ents.items():
                    if kind in _ID_FIELDS and ent is not None and _kind_rank(ftype, kind) >= 2:
                        v = self.entity_id(ent, kind)
                        if v is not UNKNOWN:
                            break
            if v is UNKNOWN and f["name"] in defaults:
                v = defaults[f["name"]]
            if v is not UNKNOWN:
                obj.fields[f["name"]] = v
        return self.it.jackson_fill(obj, module)

    # --- шаг -----------------------------------------------------------------

    def run_step(self, step_req: Any, state: Any, ledger: Any = None) -> tuple[set, set, set, set]:
        n = getattr(step_req, "step", None)
        handler = step_req.handler
        params = {k: v for k, v in (getattr(step_req, "params", None) or {}).items() if v is not None}
        self._user_name = getattr(state, "user_name", None)
        self._verb = (getattr(step_req, "http", None) or {}).get("method")
        refs = getattr(step_req, "refs", None) or {}
        expected = getattr(step_req, "expected_outcome", "success")
        args = self.handler_args(handler, params, refs, state)
        before = len(self.it.world.saved)
        world = self.it.world
        snapshot = world.db.fork() if getattr(self.it.rules, "m4_success_retry", "on") != "off" and world.db is not None             else None
        sink, ret = self.it.run_handler(handler, args, expected, n)
        if snapshot is not None and expected != "refused" and _is_failure(ret)                 and any(isinstance(v, str) for v in params.values()):
            # Шаг по тексту успешен, а по конкретным значениям отказал: значения строковых параметров M1
            # (восстановлены LLM из английского текста: регистр, пробелы) не совпали с тем, что принял бэкенд.
            # Откат мира и повтор шага со строковыми параметрами UNKNOWN.
            # Ступень 1: названия станций и мест в форме, в которой их хранит Train Ticket
            #   (Station.setName, StringUtils.String2Lower: без пробелов, строчными).
            # Ступень 2: неизвестны словесные строки (станции, типы поездов); ID и время остаются.
            # Ступень 3: неизвестны все строки.
            ladder = (
                (1, {k: (_station_norm(v) if _is_place_param(k, v) else v) for k, v in params.items()}),
                (2, {k: v for k, v in params.items() if not (isinstance(v, str) and _WORDY.match(v))}),
                (3, {k: v for k, v in params.items() if not isinstance(v, str)}),
            )
            for level, relaxed in ladder:
                if relaxed == params:
                    continue
                world.db = snapshot.fork()
                del world.saved[before:]
                dropped = sorted(k for k in params if relaxed.get(k, UNKNOWN) != params[k])
                args = self.handler_args(handler, relaxed, refs, state)
                sink, ret = self.it.run_handler(handler, args, expected, n)
                sink.unknowns.append({"method": handler, "branch": "step", "line": None,
                                      "decided": f"success_retry{level}:changed_params={','.join(dropped)}"})
                if not _is_failure(ret):
                    break
        if n is not None:
            self.results[n] = ret
            self.handlers[n] = handler
            self.step_params[n] = params
            self.step_refs[n] = dict(refs)
            self.saved[n] = list(self.it.world.saved[before:])
            # Текущий пассажир — из ответа логина (TokenDto.userId), как его берёт UI
            payload = _payload(ret)
            if isinstance(payload, Obj) and _kind_rank(payload.type, "user") >= 2:
                uid = payload.fields.get("userId")
                if isinstance(uid, str):
                    self.current_user = uid
        for u in sink.unknowns:
            self.unknowns[self.sid].append(dict(u, step=n))
        return self._emit(sink, ledger)

    def _emit(self, sink: Sink, ledger: Any) -> tuple[set, set, set, set]:
        methods = set(sink.methods)
        calls = set(sink.calls)
        remote = set(sink.remote)
        data = set(sink.data)
        if ledger is not None:
            for rel, s, t, st, rule in sink.prunes:
                if rel == "executes":
                    s = f"scenario:{ledger.scenario_id}"
                ledger.prune(rel, s, t, st, rule)
            for rel, edges in (("calls", sink.calls), ("remote", sink.remote), ("data", sink.data)):
                for (s, t), (st, rule) in sorted(edges.items()):
                    ledger.include(rel, s, t, st, rule)
            for m, (st, rule, via) in sorted(sink.methods.items()):
                ledger.execute(m, st, rule, via=via)
        return methods, calls, remote, data


def _is_place_param(name: str, v: Any) -> bool:
    n = name.lower()
    return isinstance(v, str) and bool(_WORDY.match(v)) and any(h in n for h in ("station", "place", "from", "to"))


def _station_norm(v: str) -> str:
    return ",".join(p.replace(" ", "").lower() for p in v.split(","))


def _is_failure(ret: Any) -> bool:
    """Ответ обработчика — отказ: Response со статусом, известным и не равным 1."""
    v = ret
    for _ in range(3):
        if isinstance(v, Wrapper):
            v = v.body
    if isinstance(v, Obj) and (v.type or "").endswith(".Response"):
        st = v.fields.get("status")
        return isinstance(st, int) and not isinstance(st, bool) and st != 1
    return False


def _payload(v: Any) -> Any:
    """Данные ответа обработчика: ResponseEntity -> Response -> data."""
    for _ in range(4):
        if isinstance(v, Wrapper):
            v = v.body
        elif isinstance(v, Obj) and (v.type or "").endswith(".Response"):
            v = v.get("data")
        elif isinstance(v, OptionalV):
            v = v.value
        else:
            break
    return v


def _simple(fqn: str | None) -> str:
    return (fqn or "").rsplit(".", 1)[-1].split("$")[-1].lower()


def _kind_rank(fqn: str | None, kind: str) -> int:
    """Насколько тип похож на вид сущности: 3 — имя совпадает, 2 — начинается с вида, 1 — содержит, 0 — нет."""
    s = _simple(fqn)
    best = 0
    for h in _KIND_HINTS.get(kind, (kind,)):
        if s in (h, h + "s"):
            best = max(best, 3)
        elif s.startswith(h):
            best = max(best, 2)
        elif h in s:
            best = max(best, 1)
    return best


def _is_kind(fqn: str | None, kind: str) -> bool:
    return _kind_rank(fqn, kind) > 0


def _obj_is_kind(o: Obj, kind: str) -> bool:
    """Объект вида kind: по имени типа или по известному ID-полю вида (TravelAdvanceResultUnit.tripId)."""
    if _is_kind(o.type, kind):
        return True
    return any(isinstance(o.fields.get(f), str) for f in _ID_FIELDS.get(kind, ())[:1])


def _find_kind(v: Any, kind: str, depth: int = 0) -> list[Any]:
    """Объекты вида kind в результате шага: сам объект, элементы списка или поля (на 2 уровня)."""
    if depth > 2 or v is None or v is UNKNOWN:
        return []
    if isinstance(v, ListV):
        direct = [x for x in v.items if isinstance(x, Obj) and _obj_is_kind(x, kind)]
        if direct:
            return direct
        out: list[Any] = []
        for x in v.items:
            out.extend(_find_kind(x, kind, depth + 1)[:1])
        return out
    if isinstance(v, Obj):
        if _is_kind(v.type, kind):
            return [v]
        for k, x in v.fields.items():
            if isinstance(x, (Obj, ListV)):
                if isinstance(x, Obj) and (_is_kind(x.type, kind) or kind in k.lower()):
                    return [x]
                r = _find_kind(x, kind, depth + 1)
                if r:
                    return r
    return []


__all__ = ["StepExecutor", "EnumV"]
