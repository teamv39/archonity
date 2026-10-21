"""Ответ-обёртка проекта для M4: класс, поле статуса, значение успеха и поле данных — из кода, без имён проекта.

- Класс — тот, который чаще всего строят в `return new X(<целое>, "<строка>", ...)` (IR тел методов, в т.ч. внутри
  `ok(...)`): код статуса первым аргументом и сообщение вторым. Тот же образ ответа видит M1 (`docs._status_returns`).
- Поле статуса — единственное целое поле класса; поле данных — поле, тип которого — параметр типа класса.
- Значение успеха — литерал, с которым клиент сравнивает поле статуса: UI (`<ответ>.<статус> == <литерал>`), без UI —
  сервисы проекта (`get<Статус>() == / != <литерал>` в IR), по большинству.

Нет класса или значения успеха — `None`: отказ остаётся только у `throw` и `return null`.
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_INT_TYPES = {"int", "long", "short", "java.lang.Integer", "java.lang.Long", "java.lang.Short"}


@dataclass(frozen=True)
class Envelope:
    name: str          # простое имя класса обёртки
    status: str        # поле статуса (первый аргумент конструктора)
    success: Any       # значение статуса при успехе
    data: str | None   # поле данных

    def is_type(self, type_name: str | None) -> bool:
        """`edu.x.Response`, `Response<>`, `Response<List<T>>` — тип обёртки."""
        return bool(type_name) and re.sub(r"<.*>", "", type_name).rsplit(".", 1)[-1] == self.name

    @property
    def setter(self) -> str:
        return "set" + self.status[:1].upper() + self.status[1:]

    @property
    def getter(self) -> str:
        return "get" + self.status[:1].upper() + self.status[1:]


def _walk(x: Any):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)


def _status_ctor(e: Any) -> str | None:
    """`new X(<целое>, "<строка>", ...)`, в т.ч. последним аргументом вызова (`ok(new X(...))`) -> простое имя X."""
    if not isinstance(e, dict):
        return None
    if "new" in e:
        a = e.get("args") or []
        if len(a) >= 2 and isinstance(a[0], dict) and isinstance(a[0].get("lit"), int) \
                and not isinstance(a[0].get("lit"), bool) and isinstance(a[1], dict) and isinstance(a[1].get("lit"), str):
            return re.sub(r"<.*>", "", e["new"]).rsplit(".", 1)[-1]
        return None
    if "call" in e and e.get("args"):
        return _status_ctor(e["args"][-1])
    return None


def _ui_success(status: str, targets_root: Path | None, ix: Any) -> collections.Counter:
    """Литералы, с которыми UI сравнивает `<ответ>.<статус>`."""
    out: collections.Counter = collections.Counter()
    if targets_root is None:
        return out
    from engine.grounding.ui_catalog import find_ui_dir, ui_files

    ui_dir = find_ui_dir(targets_root, ix)
    if ui_dir is None:
        return out
    pat = re.compile(rf"\.{re.escape(status)}\s*===?\s*(-?\d+)\b")
    for p in ui_files(targets_root / ui_dir):
        if p.suffix == ".js":
            out.update(int(m.group(1)) for m in pat.finditer(p.read_text(encoding="utf-8", errors="replace")))
    return out


def _java_success(getter: str, ir: dict[str, dict[str, Any]]) -> collections.Counter:
    """Литералы в сравнениях `x.<getter>() == / != <литерал>` сервисов проекта."""
    out: collections.Counter = collections.Counter()
    for m in ir.values():
        for e in _walk(m.get("body")):
            if e.get("bin") in ("==", "!=") and isinstance(e.get("l"), dict) and e["l"].get("callee") == getter \
                    and isinstance(e.get("r"), dict) and isinstance(e["r"].get("lit"), int):
                out[e["r"]["lit"]] += 1
    return out


def derive(ix: Any, ir: dict[str, dict[str, Any]], targets_root: Path | None) -> Envelope | None:
    """Соглашение об ответе по IR, скелету и UI; None — в проекте его не видно."""
    ctors: collections.Counter = collections.Counter()
    for m in ir.values():
        for s in _walk(m.get("body")):
            if s.get("op") == "return":
                x = _status_ctor(s.get("expr"))
                if x:
                    ctors[x] += 1
    if not ctors:
        return None
    name = ctors.most_common(1)[0][0]
    N = ix.N
    types = {nid: n for nid, n in N.items() if n.get("kind") == "type" and (n.get("fqn") or "").rsplit(".", 1)[-1] == name}
    status = data = None
    for tid, t in sorted(types.items()):
        fields = [n for n in N.values() if n.get("kind") == "field" and n.get("owner") == tid]
        ints = [f["name"] for f in fields if f.get("type") in _INT_TYPES]
        params = set(t.get("type_params") or ())
        generic = [f["name"] for f in fields if f.get("type_raw") in params]
        if len(ints) == 1:
            status = ints[0]
            data = generic[0] if len(generic) == 1 else None
            break
    if status is None:
        return None
    votes = _ui_success(status, targets_root, ix) or _java_success("get" + status[:1].upper() + status[1:], ir)
    top = votes.most_common(2)
    if not top or (len(top) > 1 and top[0][1] == top[1][1]):
        return None
    return Envelope(name=name, status=status, success=top[0][0], data=data)


__all__ = ["Envelope", "derive"]
