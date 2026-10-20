"""Шаг сценария для исполнителя M4: StepRequest -> аргументы обработчика -> события -> рёбра.

Аргументы обработчика:
- `@RequestBody` — DTO из `params` шага и ссылок `refs` (поля, которых не определил шаг, неизвестны);
  значения по смыслу (ADR-007, решение 6): поле, по которому создающий метод ищет дубликат, — новое значение;
  записанное шагом значение — следующим шагам; при входе — пассажир и пустые поля из `context` скелета;
- `@PathVariable` — по имени из `params`, ссылок или текущего пользователя;
- `@RequestHeader` — неизвестно.

Ссылки `<first|second|new>_of_step_<n>` разрешаются по миру M4: `new` — сущность, сохранённая шагом n,
`first`/`second` — элемент результата обработчика шага n; если не нашли — модель состояния M3. Виды ссылок —
из манифеста `engine/manifest.py`; виды M1 v7 переводятся в них (`--ref-kinds v7`, `_v7_refs`).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from engine.executor.interpreter import Interpreter, Sink
from engine.executor.schema import EntitySchema, simple_name
from engine.executor.values import UNKNOWN, EnumV, ListV, Obj, OptionalV, Wrapper
from engine.executor.world import camel

_REF = re.compile(r"^(first|second|new)_of_step_(\d+)$")
# Виды M1 v7 (кеш m1-v7), которых нет в манифесте: вид манифеста с тем же смыслом. `train` — в StepExecutor._v7_refs
_V7_KINDS = {"contact": "contacts", "price": "priceConfig", "consign": "consignRecord", "store": "stationFoodStore"}
_WORDY = re.compile(r"^[A-Za-z][A-Za-z ,.'-]*$")

_DEFAULT_SCHEMA = EntitySchema()


class StepExecutor:
    """M4 на уровне сценария: мир, реестр результатов шагов, сборка рёбер шага."""

    def __init__(self, index: Any, rules: Any, ir_dir: str | Path, targets_root: str | Path | None,
                 judge: Any = None) -> None:
        self.index = index
        self.schema = EntitySchema(index)
        self.ref_kinds = getattr(rules, "ref_kinds", "v7")  # словарь видов в StepRequest.refs (ADR-007)
        self.judge = judge  # engine.executor.judge.Judge (кеш, бюджет вызовов сервера) или None
        self.it = Interpreter(index, rules, Path(ir_dir), Path(targets_root) if targets_root else None,
                              self._ask_judge if judge is not None else None)
        self.targets_root = Path(targets_root) if targets_root else None
        self._scenario: dict[str, Any] = {}
        self._step_req: Any = None
        self._src: dict[str, list[str]] = {}
        self.results: dict[int, Any] = {}
        self.current_user: str | None = None
        self.written: dict[str, Any] = {}
        self.handlers: dict[int, str] = {}
        self.step_params: dict[int, dict[str, Any]] = {}
        self.step_refs: dict[int, dict[str, str]] = {}
        self.saved: dict[int, list[tuple[str, Obj]]] = {}
        self.unknowns: dict[str, list[dict[str, Any]]] = {}
        self.sid = "S?"
        self._login_ids = _login_principal_ids(index.N)
        self._login_blanks = _context_login_blanks(getattr(index, "sk", {}).get("context"))
        self._reach: dict[str, set[str]] = {}
        self._dedupe: dict[tuple[str, str | None], tuple[str, ...]] = {}

    def begin_scenario(self, sid: str) -> None:
        self.sid = sid
        db = getattr(self.index, "db_state", None)
        self.it.begin_scenario(db.fork() if db is not None and hasattr(db, "fork") else db)
        self.results = {}
        self.current_user = None
        self.written = {}
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
            cands = [(fqn, obj) for fqn, obj in self.saved.get(n, []) if self.schema.is_kind(fqn, kind)]
            if cands:
                top = max(self.schema.kind_rank(fqn, kind) for fqn, _ in cands)
                return [obj for fqn, obj in cands if self.schema.kind_rank(fqn, kind) == top][-1]
        idx = 1 if pick == "second" else 0
        found = _find_kind(_payload(self.results.get(n)), kind, schema=self.schema)
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
        saved_c = [(fqn, o) for fqn, o in self.saved.get(n, []) if self.schema.is_kind(fqn, kind)]
        top = max((self.schema.kind_rank(fqn, kind) for fqn, _ in saved_c), default=0)
        saved = [o for fqn, o in saved_c if self.schema.kind_rank(fqn, kind) == top]
        if saved:
            return saved[-1] if pick == "new" else saved[min(idx, len(saved) - 1)]
        # Шаг n не создавал и не возвращал сущность этого вида: та, на которую ссылался сам шаг n
        # (M1 ссылается на шаг оплаты как на «заказ шага 6» — это заказ, который оплачивали)
        prev = self.step_refs.get(n, {}).get(kind)
        if prev and prev != ref and depth < 4:
            ent = self.resolve_ref(kind, prev, state, depth + 1)
            if ent is not None:
                return ent
        # Модель состояния M3 последним слоем — только в режиме m4_m3_refs=on (до feature/84). Выдачу M3 здесь не
        # меняла (зонд 19.10: при ответе None от M3 sha256 тот же), а держится на перечислениях Train Ticket.
        if getattr(self.it.rules, "m4_m3_refs", "off") == "on" and state is not None and hasattr(state, "resolve_ref"):
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
            if not tid or self.it.types.types[tid].get("module") != module or not self.schema.is_kind(fqn, kind):
                continue
            rows = w.rows(table)
            if rows:
                return w.row_to_obj(fqn, rows[min(idx, len(rows) - 1)], module)
        return None

    def entity_id(self, ent: Any, kind: str, depth: int = 0) -> Any:
        """ID сущности ссылки; у обёрток (TripAllDetail) — ID вложенного объекта того же вида."""
        if not isinstance(ent, Obj) or depth > 2:
            return UNKNOWN
        names = list(self.schema.id_fields(kind)) + ["id"]
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
            if isinstance(v, Obj) and (self.schema.is_kind(v.type, kind) or kind in k.lower()):
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
            if ent is not None and name in self.schema.id_fields(kind):
                v = self.entity_id(ent, kind)
                if v is not UNKNOWN:
                    return v
        if name in self.schema.user_fields and user:
            return user
        if name == "id":
            return UNKNOWN
        for alias in self.schema.field_aliases(name):
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
        self.it.jackson_new(ftype, module, handler)
        obj = Obj(ftype, {}, open=True)
        fields = self.it.types.all_fields(tid)
        names = {f["name"] for f in fields}
        defaults: dict[str, Any] = {}
        own_ids: set[str] = set()
        fresh: set[str] = set()
        hname = self.index.N.get(handler, {}).get("name", "")
        if getattr(self, "_verb", None) == "POST" and re.match(r"(create|add|register|save|insert|new)", hname, re.I):
            # Создание через POST: собственный ID новой сущности клиент не присылает (Jackson оставит null).
            # Это и не ID текущего пользователя: при регистрации UserDto.userId пуст.
            own = [k for k in self.schema.known_kinds if self.schema.kind_rank(ftype, k) >= 2]
            own_ids = {n for n in ["id"] + [f for k in own for f in self.schema.id_fields(k)]
                       if n in names and n not in params}
            defaults.update(dict.fromkeys(own_ids))
            # Поле, по которому создающий метод ищет дубликат (чтение репозитория перед save): значения нет в тексте
            # шага, а новая сущность создаётся — значение, которого нет в мире БД. Следующие шаги его переиспользуют.
            for f in fields:
                name = f["name"]
                if name in self._dedupe_fields(handler, ftype) and name not in params and name not in own_ids \
                        and f.get("type") == "java.lang.String":
                    defaults[name] = f"m4-new-{name}"
                    fresh.add(name)
        if self._is_login(handler):
            # Вход (Spring Security): поля, которых при входе нет по context скелета («no verification code at
            # login»), — пустые; имя (UserDetails.getUsername) — пассажир context, если шаг не регистрировал своего
            for name in names:
                if _norm(name) in self._login_blanks:
                    defaults[name] = ""
                elif _norm(name) == "username" and getattr(self, "_user_name", None):
                    defaults[name] = self._user_name
        if "consigneeName" in names:
            # UI (client_ticket_book.js) шлёт имя, телефон и вес получателя багажа одной группой, только при отмеченном
            # «need consign». Вес 0 в тексте шага — багажа нет, полей группы в запросе нет (null). Имени и телефона в
            # тексте нет: при весе больше 0 они неизвестны. Группу полей каталог UI пока не отдаёт (annotation_rules).
            w = params.get("consigneeWeight")
            if isinstance(w, (int, float)) and not isinstance(w, bool) and w <= 0:
                defaults["consigneeName"] = defaults["consigneePhone"] = None
        for f in fields:
            name = f["name"]
            v = self.field_value(name, params, ents, None if name in own_ids else user, f.get("type"))
            if v is UNKNOWN and name == "id":
                # DTO того же вида, что сущность ссылки (Consign и запись багажа): id — ID этой сущности
                for kind, ent in ents.items():
                    if kind in self.schema.known_kinds and ent is not None and self.schema.kind_rank(ftype, kind) >= 2:
                        v = self.entity_id(ent, kind)
                        if v is not UNKNOWN:
                            break
            if v is UNKNOWN and _norm(name) in self.written:
                # Значение, записанное прежним шагом (имя при регистрации -> вход)
                v = self.written[_norm(name)]
            if v is UNKNOWN and name in defaults:
                v = defaults[name]
                if name in fresh:
                    self.written[_norm(name)] = v
            if v is not UNKNOWN:
                obj.fields[name] = v
        return self.it.jackson_fill(obj, module)

    def _reachable(self, handler: str, depth: int = 4) -> set[str]:
        """Методы проекта, достижимые из обработчика по рёбрам calls скелета (с реализациями интерфейсов)."""
        if handler not in self._reach:
            seen, frontier = {handler}, [handler]
            for _ in range(depth):
                nxt = []
                for m in frontier:
                    for t in self.index.calls.get(m, ()):
                        for x in (t, *self.index.over.get(t, ())):
                            if x not in seen:
                                seen.add(x)
                                nxt.append(x)
                frontier = nxt
            self._reach[handler] = seen
        return self._reach[handler]

    def _is_login(self, handler: str) -> bool:
        """Обработчик входа: из него достижим метод с вызовом AuthenticationManager.authenticate."""
        return not self._reachable(handler).isdisjoint(self._login_ids)

    def _dedupe_fields(self, handler: str, ftype: str | None) -> tuple[str, ...]:
        """Поля DTO, по которым метод, достижимый из обработчика, ищет дубликат: геттеры параметра этого типа в
        аргументах чтения репозитория, после которого тот же метод сохраняет сущность (факты archparse)."""
        key = (handler, ftype)
        if key not in self._dedupe:
            out: list[str] = []
            for m in sorted(self._reachable(handler)):
                saves = [c.line for c in self.index.entities.calls_by_method.get(m, ()) if c.operation == "SAVE"]
                body = self.it.ir.get(m)
                if not saves or not body:
                    continue
                ptypes = {p.get("name"): p.get("type") for p in body.get("params") or ()}
                for call in _call_exprs(body.get("body")):
                    c_str = call.get("call") or ""
                    rc = None
                    if "@" in c_str:
                        pos = c_str.rsplit("@", 1)[1]
                        if ":" in pos:
                            line_s, col_s = pos.split(":", 1)
                            if line_s.isdigit() and col_s.isdigit():
                                rc = self.it.repo_calls.get((m, int(line_s), int(col_s)))
                    if rc is None or rc.operation != "READ" or not any(line > rc.line for line in saves):
                        continue
                    for a in call.get("args") or ():
                        if not isinstance(a, dict):
                            continue
                        recv, getter = a.get("recv") or {}, a.get("callee") or ""
                        if recv.get("ref") == "param" and getter.startswith("get") and len(getter) > 3 \
                                and not a.get("args") and simple_name(ptypes.get(recv.get("name"))) == simple_name(ftype):
                            out.append(getter[3].lower() + getter[4:])
            self._dedupe[key] = tuple(dict.fromkeys(out))
        return self._dedupe[key]

    # --- шаг -----------------------------------------------------------------

    def run_step(self, step_req: Any, state: Any, ledger: Any = None,
                 scenario: dict[str, Any] | None = None) -> tuple[set, set, set, set]:
        n = getattr(step_req, "step", None)
        self._scenario = scenario or {}
        self._step_req = step_req
        handler = step_req.handler
        params = {k: v for k, v in (getattr(step_req, "params", None) or {}).items() if v is not None}
        self._user_name = getattr(state, "user_name", None)
        self._verb = (getattr(step_req, "http", None) or {}).get("method")
        refs = getattr(step_req, "refs", None) or {}
        if self.ref_kinds == "v7":
            refs = self._v7_refs(refs)
        expected = getattr(step_req, "expected_outcome", "success")
        before = len(self.it.world.saved)
        world = self.it.world
        snapshot = world.db.fork() if getattr(self.it.rules, "m4_success_retry", "on") != "off" and world.db is not None             else None
        # Аргументы строятся в sink шага: разбор тела запроса исполняет конструктор DTO (R7)
        sink, ret = self.it.run_handler(handler, lambda: self.handler_args(handler, params, refs, state), expected, n)
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
                sink, ret = self.it.run_handler(
                    handler, lambda r=relaxed: self.handler_args(handler, r, refs, state), expected, n)
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
            # Текущий пассажир — из ответа входа, как его берёт UI (client_id = data.userId)
            uid = self._logged_in_user(sink, ret)
            if uid is not None:
                self.current_user = uid
        for u in sink.unknowns:
            self.unknowns[self.sid].append(dict(u, step=n))
        return self._emit(sink, ledger)

    def _v7_refs(self, refs: dict[str, str]) -> dict[str, str]:
        """Совместимость с видами M1 v7 (кеш m1-v7, до ADR-007): перевод в виды манифеста. Уйдёт с режимом v7.

        `train` в v7 значит то тип поезда (S6: `new_of_step_3` после создания типа), то рейс из поиска (S4.6,
        S7.10): тип поезда, если шаг ссылки сохранил или вернул сущность `trainType`, иначе рейс.
        """
        out: dict[str, str] = {}
        for k, v in refs.items():
            if k != "train":
                out[_V7_KINDS.get(k, k)] = v
        if "train" in refs:
            m = _REF.match(refs["train"] or "")
            n = int(m.group(2)) if m else -1
            is_type = any(self.schema.is_kind(fqn, "trainType") for fqn, _ in self.saved.get(n, [])) \
                or bool(_find_kind(_payload(self.results.get(n)), "trainType", schema=self.schema))
            out.setdefault("trainType" if is_type else "trip", refs["train"])
        return out

    def _logged_in_user(self, sink: Sink, ret: Any) -> str | None:
        """ID пользователя из ответа шага входа или None, если шаг не вход.

        Вход — шаг, в котором исполнился метод с вызовом `AuthenticationManager.authenticate` (Spring Security).
        ID — поле ответа с именем поля `@Id` класса `UserDetails` того же модуля (`User.userId` -> `TokenDto.userId`).
        """
        payload = _payload(ret)
        if not isinstance(payload, Obj):
            return None
        for m in sink.methods:
            for name in self._login_ids.get(m, ()):
                v = payload.fields.get(name)
                if isinstance(v, str):
                    return v
        return None

    # --- судья -----------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Счётчики M4 для run_eval: решения по UNKNOWN и судья."""
        import collections

        decided = collections.Counter(u["decided"].split(":")[0] for us in self.unknowns.values() for u in us)
        out: dict[str, Any] = {"unknown_conditions": dict(sorted(decided.items()))}
        if self.judge is not None:
            out["judge"] = self.judge.stats.to_dict()
        return out

    def _lines(self, file: str) -> list[str]:
        if file not in self._src:
            try:
                self._src[file] = (self.targets_root / file).read_text(encoding="utf-8", errors="replace").splitlines()
            except (OSError, TypeError):
                self._src[file] = []
        return self._src[file]

    def _condition_text(self, file: str, line: int) -> tuple[str, int]:
        """Текст условия `if (...)` из исходника и последняя строка условия (по балансу скобок)."""
        lines = self._lines(file)
        if not 0 < line <= len(lines):
            return "", line
        text, depth, started, end = "", 0, False, line
        for i in range(line - 1, min(len(lines), line + 8)):
            chunk = lines[i] if i > line - 1 else lines[i][lines[i].find("if") if "if" in lines[i] else 0:]
            for ch in chunk:
                if ch == "(":
                    depth += 1
                    started = True
                    if depth == 1:
                        continue
                elif ch == ")":
                    depth -= 1
                    if started and depth == 0:
                        return " ".join(text.split()), i + 1
                if started:
                    text += ch
            text += " "
            end = i + 1
        return " ".join(text.split()), end

    def _state_lines(self) -> tuple[str, ...]:
        """Сводка мира для судьи: пассажир и его заказы (ID, статус, поезд)."""
        user = self.current_user
        out = [f"passenger account id: {user}"] if user else []
        w = self.it.world
        for table in ("orders", "orders_other"):
            for r in w.rows(table):
                if user and r.get("account_id") == user:
                    out.append(f"order {r.get('id')}: status {r.get('status')}, train {r.get('train_number')}, "
                               f"travel date {r.get('travel_date')}")
        return tuple(out[:9])

    def _ask_judge(self, fr: Any, stmt: dict[str, Any]) -> bool | None:
        """Вердикт судьи по условию UNKNOWN; None — ответа нет (режим, бюджет, промах кеша)."""
        from engine.executor.interpreter import facts_lines
        from engine.executor.judge import JudgeQuery

        node = self.index.N.get(fr.method, {})
        file = node.get("file", "")
        line = stmt.get("line") or node.get("line", 1)
        cond, cond_end = self._condition_text(file, line)
        sr = self._step_req
        sc = self._scenario
        q = JudgeQuery(
            scenario_id=sc.get("id", ""), scenario_title=sc.get("title", ""),
            scenario_description=sc.get("description", ""),
            step_n=getattr(sr, "step", 0) or 0, step_action=getattr(sr, "action", ""),
            expected_outcome=getattr(sr, "expected_outcome", "success"),
            step_params={k: v for k, v in (getattr(sr, "params", None) or {}).items() if v is not None},
            step_refs=dict(getattr(sr, "refs", None) or {}),
            method_id=fr.method, file=file, method_line=node.get("line", line), method_end=node.get("end", line),
            cond_line=line, cond_end=cond_end, condition=cond, kind="if",
            path=tuple(f"in {m.split(':', 2)[-1]}" for m in self.it.stack),
            facts=tuple(facts_lines(fr.env)), state=self._state_lines(),
        )
        v = self.judge.ask(q)
        if v is None or v.verdict == "UNKNOWN":
            return None
        return v.verdict == "TRUE"

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


_AUTH_MANAGER = "org.springframework.security.authentication.AuthenticationManager"


def _norm(name: str) -> str:
    """Имя поля без регистра и разделителей: userName, username, user_name -> username."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _context_login_blanks(context: Any) -> frozenset[str]:
    """Поля, которых при входе нет, по тексту context скелета: «no verification code at login» -> verificationcode."""
    texts = context.values() if isinstance(context, dict) else ()
    return frozenset(_norm(m.group(1)) for t in texts if isinstance(t, str)
                     for m in re.finditer(r"\bno ([A-Za-z][A-Za-z ]*?) at login", t))


def _call_exprs(x: Any):
    """Выражения вызова в IR тела метода, в порядке обхода."""
    if isinstance(x, dict):
        if isinstance(x.get("call"), str) and x["call"].startswith("call:") and "callee" in x:
            yield x
        for v in x.values():
            if isinstance(v, (dict, list)):
                yield from _call_exprs(v)
    elif isinstance(x, list):
        for v in x:
            yield from _call_exprs(v)


def _login_principal_ids(nodes: dict[str, dict[str, Any]]) -> dict[str, tuple[str, ...]]:
    """Методы входа (call_site `authenticate` у `AuthenticationManager`) -> поля `@Id` классов `UserDetails` модуля."""
    entries = {n.get("method") for n in nodes.values() if n.get("kind") == "call_site"
               and n.get("callee") == "authenticate" and n.get("receiver_type") == _AUTH_MANAGER}
    principals: dict[str, set[str]] = {}
    users = {nid: n.get("module") for nid, n in nodes.items()
             if n.get("kind") == "type" and "UserDetails" in (n.get("implements_raw") or [])}
    for n in nodes.values():
        if n.get("kind") == "field" and n.get("owner") in users \
                and any((a.get("name") if isinstance(a, dict) else a) in ("Id", "EmbeddedId")
                        for a in n.get("annotations") or ()):
            principals.setdefault(users[n["owner"]], set()).add(n.get("name", ""))
    return {m: tuple(sorted(principals.get(nodes.get(m, {}).get("module"), ()))) for m in sorted(e for e in entries if e)}


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
    return simple_name(fqn)


def _kind_rank(fqn: str | None, kind: str, schema: EntitySchema | None = None) -> int:
    """Насколько тип похож на вид сущности: 3 — имя совпадает, 2 — начинается с вида, 1 — содержит, 0 — нет."""
    return (schema or _DEFAULT_SCHEMA).kind_rank(fqn, kind)


def _is_kind(fqn: str | None, kind: str, schema: EntitySchema | None = None) -> bool:
    return (schema or _DEFAULT_SCHEMA).is_kind(fqn, kind)


def _obj_is_kind(o: Obj, kind: str, schema: EntitySchema | None = None) -> bool:
    """Объект вида kind: по имени типа или по известному ID-полю вида (TravelAdvanceResultUnit.tripId)."""
    sch = schema or _DEFAULT_SCHEMA
    if sch.is_kind(o.type, kind):
        return True
    primary = sch.primary_id_field(kind)
    return bool(primary and isinstance(o.fields.get(primary), str))


def _find_kind(v: Any, kind: str, depth: int = 0, schema: EntitySchema | None = None) -> list[Any]:
    """Объекты вида kind в результате шага: сам объект, элементы списка или поля (на 2 уровня)."""
    sch = schema or _DEFAULT_SCHEMA
    if depth > 2 or v is None or v is UNKNOWN:
        return []
    if isinstance(v, ListV):
        direct = [x for x in v.items if isinstance(x, Obj) and _obj_is_kind(x, kind, sch)]
        if direct:
            return direct
        out: list[Any] = []
        for x in v.items:
            out.extend(_find_kind(x, kind, depth + 1, sch)[:1])
        return out
    if isinstance(v, Obj):
        if sch.is_kind(v.type, kind):
            return [v]
        for k, x in v.fields.items():
            if isinstance(x, (Obj, ListV)):
                if isinstance(x, Obj) and (sch.is_kind(x.type, kind) or kind in k.lower()):
                    return [x]
                r = _find_kind(x, kind, depth + 1, sch)
                if r:
                    return r
    return []


__all__ = ["StepExecutor", "EnumV"]
