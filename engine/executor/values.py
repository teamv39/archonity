"""Абстрактные значения исполнителя M4 и трёхзначная логика (ADR-005, M4).

Известное значение — обычный объект Python: int, float, str, bool, None (Java null) или объекты ниже.
Неизвестное — `Unknown` (лист с происхождением) или `Sym` (выражение над неизвестными). Условие считается TRUE,
FALSE или неизвестным; неизвестное разрешают правила по умолчанию (`default` у листьев), судья или исход шага.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any, Callable


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING: Any = _Missing()  # у листа нет значения по умолчанию


class _NonNull:
    def __repr__(self) -> str:
        return "NONNULL"


NONNULL: Any = _NonNull()  # по умолчанию «не null», в остальном неизвестно

_uids = itertools.count(1)


class Unknown:
    """Неизвестное значение с происхождением.

    kind: object, status, bool, number, string, collection, optional — от вида зависят модели библиотеки
    и значение по умолчанию. src: request, remote, call, repo, library, field, loop, state.
    default — значение на успешном пути (D1–D4); MISSING — правила по умолчанию его не знают.
    """

    __slots__ = ("origin", "kind", "default", "src", "type", "rule", "children", "uid")

    def __init__(self, origin: str, kind: str = "object", default: Any = MISSING, src: str = "library",
                 type: str | None = None, rule: str | None = None) -> None:
        self.origin = origin
        self.kind = kind
        self.default = default
        self.src = src
        self.type = type
        self.rule = rule  # имя правила по умолчанию, которое даёт default (D1…D4)
        self.children: dict[str, Unknown] = {}
        self.uid = next(_uids)

    def child(self, key: str, make: Callable[[], Unknown]) -> Unknown:
        """Одно и то же производное значение для одного ключа: `x.getStatus()` дважды — один лист."""
        if key not in self.children:
            self.children[key] = make()
        return self.children[key]

    def __repr__(self) -> str:
        return f"Unknown({self.kind}: {self.origin})"


@dataclass(frozen=True)
class Sym:
    """Значение, выведенное из неизвестных: операция и аргументы."""

    op: str
    args: tuple[Any, ...]

    def __repr__(self) -> str:
        if len(self.args) == 2:
            return f"({self.args[0]!r} {self.op} {self.args[1]!r})"
        return f"{self.op}({', '.join(repr(a) for a in self.args)})"


def is_unknown(v: Any) -> bool:
    return isinstance(v, (Unknown, Sym))


class Obj:
    """Объект: DTO, сущность, Response, бин. Поля — по имени поля Java."""

    __slots__ = ("type", "fields", "src", "origin", "uid")

    def __init__(self, type: str, fields: dict[str, Any] | None = None, src: str = "new", origin: str = "") -> None:
        self.type = type
        self.fields: dict[str, Any] = fields if fields is not None else {}
        self.src = src  # new, request, state, enum, bean, library
        self.origin = origin
        self.uid = next(_uids)

    @property
    def simple(self) -> str:
        return simple_name(self.type)

    def __repr__(self) -> str:
        return f"Obj({self.simple}, {self.src})"


class Coll:
    """Коллекция: известные элементы или только признак непустоты."""

    __slots__ = ("items", "nonempty", "origin", "src", "elem_type", "uid")

    def __init__(self, items: list[Any] | None = None, nonempty: Any = MISSING, origin: str = "", src: str = "new",
                 elem_type: str | None = None) -> None:
        self.items = items
        if items is not None:
            nonempty = bool(items)
        self.nonempty = nonempty  # bool или Unknown
        self.origin = origin
        self.src = src
        self.elem_type = elem_type
        self.uid = next(_uids)

    def __repr__(self) -> str:
        return f"Coll({len(self.items) if self.items is not None else '?'}, {self.src})"


class Opt:
    """java.util.Optional."""

    __slots__ = ("present", "value", "origin", "src")

    def __init__(self, present: Any, value: Any = None, origin: str = "", src: str = "new") -> None:
        self.present = present  # bool или Unknown
        self.value = value
        self.origin = origin
        self.src = src


class Iter:
    """Итератор по коллекции."""

    __slots__ = ("coll", "pos")

    def __init__(self, coll: Coll) -> None:
        self.coll = coll
        self.pos = 0


@dataclass
class TypeRef:
    """Имя класса как получатель статического вызова или поля."""

    name: str  # FQN, если известен, иначе как написано
    simple: str


@dataclass
class Lambda:
    """Лямбда или ссылка на метод: отложенный блок (R16), исполняется, только когда её вызывают."""

    node: dict[str, Any]
    env: dict[str, Any]
    this: Any
    method_id: str  # объемлющий метод: вызовы внутри лямбды принадлежат ему (R1)
    targets: tuple[str, ...] = field(default=())  # цели ссылки на метод проекта


def simple_name(t: str | None) -> str:
    """`java.util.List<Order>` -> `List`, `a.b.C$D` -> `D`."""
    if not t:
        return ""
    t = t.split("<", 1)[0].strip()
    t = t.rsplit(".", 1)[-1]
    return t.rsplit("$", 1)[-1]


# --- трёхзначная логика -------------------------------------------------------------------------------------------

def truth(v: Any) -> bool | None:
    """Значение условия: True, False или None (неизвестно)."""
    if is_unknown(v):
        return None
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return v != 0
    return True


def not_(v: Any) -> Any:
    t = truth(v)
    return Sym("!", (v,)) if t is None else (not t)


def and_(a: Any, b: Callable[[], Any]) -> Any:
    """`a && b`, b — ленивый: исполняется, только если a не FALSE (вызовы в b дают события)."""
    ta = truth(a)
    if ta is False:
        return False
    bv = b()
    tb = truth(bv)
    if ta is True:
        return bv if tb is None else tb
    if tb is False:
        return False
    return a if tb is True else Sym("&&", (a, bv))


def or_(a: Any, b: Callable[[], Any]) -> Any:
    ta = truth(a)
    if ta is True:
        return True
    bv = b()
    tb = truth(bv)
    if ta is False:
        return bv if tb is None else tb
    if tb is True:
        return True
    return a if tb is False else Sym("||", (a, bv))


_CMP: dict[str, Callable[[Any, Any], bool]] = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}

_ARITH: dict[str, Callable[[Any, Any], Any]] = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a // b if isinstance(a, int) and isinstance(b, int) and not isinstance(a, bool) else a / b,
    "%": lambda a, b: a % b,
    "&": lambda a, b: a & b,
    "|": lambda a, b: a | b,
    "^": lambda a, b: a ^ b,
    "<<": lambda a, b: a << b,
    ">>": lambda a, b: a >> b,
    ">>>": lambda a, b: a >> b,
}


def java_str(v: Any) -> str | None:
    """Строковое представление известного значения для конкатенации; None — не представить."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, str)):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    return None


def binop(op: str, a: Any, b: Any) -> Any:
    """Бинарная операция без `&&`/`||` (их считают and_/or_)."""
    if is_unknown(a) or is_unknown(b):
        return Sym(op, (a, b))
    if op in ("==", "!="):
        eq = _equal(a, b)
        if eq is None:
            return Sym(op, (a, b))
        return eq if op == "==" else not eq
    if op == "+" and (isinstance(a, str) or isinstance(b, str)):
        sa, sb = java_str(a), java_str(b)
        if sa is None or sb is None:
            return Sym(op, (a, b))
        return sa + sb
    fn = _CMP.get(op) or _ARITH.get(op)
    if fn is None:
        return Sym(op, (a, b))
    try:
        return fn(a, b)
    except (TypeError, ZeroDivisionError, ValueError):
        return Sym(op, (a, b))


def _equal(a: Any, b: Any) -> bool | None:
    """`==` Java: примитивы по значению, объекты по ссылке; None — не определить."""
    if a is None or b is None:
        return a is b
    if isinstance(a, (Obj, Coll, Opt)) or isinstance(b, (Obj, Coll, Opt)):
        return a is b
    if isinstance(a, (bool, int, float, str)) and isinstance(b, (bool, int, float, str)):
        if isinstance(a, str) != isinstance(b, str):
            return None
        return a == b
    return None


def unop(op: str, v: Any) -> Any:
    if op == "!":
        return not_(v)
    if is_unknown(v):
        return Sym(op, (v,))
    if op == "-" and isinstance(v, (int, float)):
        return -v
    if op == "+" and isinstance(v, (int, float)):
        return v
    if op == "~" and isinstance(v, int):
        return ~v
    return Sym(op, (v,))


# --- правила по умолчанию: подстановка значений листьев ----------------------------------------------------------

def resolve(v: Any, leaf: Callable[[Unknown], Any], used: list[Unknown] | None = None) -> Any:
    """Пересчёт выражения над неизвестными, где лист заменяет `leaf(u)` (MISSING — лист остаётся неизвестным).

    `used` собирает листья, значения которых повлияли на результат.
    """
    if isinstance(v, Unknown):
        x = leaf(v)
        if x is MISSING:
            return v
        if used is not None:
            used.append(v)
        return x
    if not isinstance(v, Sym):
        return v
    op, args = v.op, v.args
    if op == "!":
        return not_(resolve(args[0], leaf, used))
    if op in ("&&", "||"):
        a = resolve(args[0], leaf, used)
        b = resolve(args[1], leaf, used)
        return and_(a, lambda: b) if op == "&&" else or_(a, lambda: b)
    if len(args) == 2:
        a = resolve(args[0], leaf, used)
        b = resolve(args[1], leaf, used)
        if op in ("==", "!=") and (a is NONNULL or b is NONNULL):
            other = b if a is NONNULL else a
            if other is None:
                return op == "!="
            return Sym(op, (args[0], args[1]))
        if a is NONNULL or b is NONNULL:
            return Sym(op, (args[0], args[1]))
        return binop(op, a, b)
    if len(args) == 1:
        a = resolve(args[0], leaf, used)
        return Sym(op, (args[0],)) if a is NONNULL else unop(op, a)
    return v


def leaves(v: Any, out: list[Unknown] | None = None) -> list[Unknown]:
    """Листья-неизвестные выражения в порядке появления, без повторов."""
    out = [] if out is None else out
    if isinstance(v, Unknown):
        if all(u is not v for u in out):
            out.append(v)
    elif isinstance(v, Sym):
        for a in v.args:
            leaves(a, out)
    return out
