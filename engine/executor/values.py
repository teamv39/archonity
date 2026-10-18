"""Значения исполнителя M4 (ADR-005): конкретные, частично известные и UNKNOWN.

Конкретные значения Java представлены значениями Python: int/float/str/bool/None (null).
Остальное — классы ниже. Всё, чего исполнитель не знает, — UNKNOWN; условие с UNKNOWN решают
правила по умолчанию (успешный путь) или берутся оба плеча.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any


class _Unknown:
    """Неизвестное значение. Одно на весь процесс."""

    _inst: _Unknown | None = None

    def __new__(cls) -> _Unknown:
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self) -> str:
        return "UNKNOWN"

    def __bool__(self) -> bool:  # защита от случайного truthiness
        raise TypeError("UNKNOWN нельзя приводить к bool, используйте tri()")


UNKNOWN: Any = _Unknown()

_ids = itertools.count(1)


def next_uid() -> int:
    """Следующий номер объекта: объекты с номером не меньше созданы позже этого момента."""
    return next(_ids)


def is_unknown(v: Any) -> bool:
    return v is UNKNOWN


@dataclass(eq=False)
class Obj:
    """Объект класса проекта или DTO. Неизвестные поля — UNKNOWN (если объект пришёл извне)."""

    type: str | None
    fields: dict[str, Any] = field(default_factory=dict)
    # open=True: поля, которых нет в fields, неизвестны; False — объект создан через new, отсутствующее поле = null
    open: bool = True
    uid: int = field(default_factory=lambda: next(_ids))

    def get(self, name: str) -> Any:
        if name in self.fields:
            return self.fields[name]
        return UNKNOWN if self.open else None

    def __repr__(self) -> str:
        short = (self.type or "?").rsplit(".", 1)[-1]
        return f"Obj<{short}#{self.uid}>"


@dataclass(eq=False)
class EnumV:
    """Константа enum: тип, имя, порядковый номер, поля из конструктора."""

    type: str
    constant: str
    ordinal: int | None = None
    fields: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str) -> Any:
        return self.fields.get(name, UNKNOWN)

    def __repr__(self) -> str:
        return f"{self.type.rsplit('.', 1)[-1]}.{self.constant}"


@dataclass(eq=False)
class ListV:
    """Список или множество. exact=False — элементы известны не все (размер неизвестен)."""

    items: list[Any] = field(default_factory=list)
    exact: bool = True
    elem_type: str | None = None
    is_set: bool = False
    uid: int = field(default_factory=lambda: next(_ids))

    def __repr__(self) -> str:
        return f"{'Set' if self.is_set else 'List'}[{len(self.items)}{'' if self.exact else '+?'}]"


@dataclass(eq=False)
class MapV:
    data: dict[Any, Any] = field(default_factory=dict)
    exact: bool = True


@dataclass(eq=False)
class OptionalV:
    """Optional: value — значение, None — пусто, UNKNOWN — неизвестно, есть ли значение.

    maybe=True: значение value, если оно есть, но есть ли оно — неизвестно (неточный запрос к БД).
    """

    value: Any
    maybe: bool = False


@dataclass(eq=False)
class Wrapper:
    """HttpEntity / ResponseEntity: тело запроса или ответа."""

    body: Any
    kind: str = "entity"


@dataclass(eq=False)
class Lambda:
    """Отложенный блок (R16): исполняется, только когда его вызывают."""

    params: list[str]
    body: list[dict[str, Any]]
    env: dict[str, Any]
    this: Any
    method: str
    line: int


@dataclass(eq=False)
class MethodRef:
    target: str | None
    call: str | None


@dataclass(eq=False)
class Bean:
    """Поле-зависимость Spring (@Autowired): сервис, репозиторий, RestTemplate."""

    type: str | None
    name: str


@dataclass(eq=False)
class TypeRef:
    """Имя класса в выражении (StringUtils, OrderStatus)."""

    fqn: str


@dataclass(eq=False)
class DateV:
    """java.util.Date / Calendar: момент времени (datetime) или UNKNOWN."""

    value: Any
    calendar: bool = False


@dataclass(eq=False)
class JsonV:
    """Строка JSON с известным исходным значением (toJSONString / writeValueAsString)."""

    value: Any


@dataclass(eq=False)
class Concat:
    """Строка из известных и неизвестных частей (URL запроса)."""

    parts: list[Any]

    def render(self, hole: str = "\x00") -> str:
        return "".join(p if isinstance(p, str) else hole for p in self.parts)


def concat(a: Any, b: Any) -> Any:
    """Конкатенация строк Java: известные части склеиваются, неизвестные сохраняются как дыры."""
    pa = a.parts if isinstance(a, Concat) else [to_jstr(a)]
    pb = b.parts if isinstance(b, Concat) else [to_jstr(b)]
    parts: list[Any] = []
    for p in pa + pb:
        if isinstance(p, str) and parts and isinstance(parts[-1], str):
            parts[-1] += p
        else:
            parts.append(p)
    if all(isinstance(p, str) for p in parts):
        return "".join(parts)
    return Concat(parts)


def to_jstr(v: Any) -> Any:
    """String.valueOf: строка или UNKNOWN."""
    if isinstance(v, str):
        return v
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v) if v != int(v) or abs(v) >= 1e7 else f"{v:.1f}"
    if isinstance(v, EnumV):
        return v.constant
    return UNKNOWN


# --- трёхзначная логика -----------------------------------------------------

TRUE, FALSE = True, False


def tri(v: Any) -> Any:
    """Значение условия: True, False или UNKNOWN."""
    if v is True or v is False:
        return v
    return UNKNOWN


def t_not(a: Any) -> Any:
    return UNKNOWN if a is UNKNOWN else (not a)


def t_and(a: Any, b: Any) -> Any:
    if a is False or b is False:
        return False
    if a is True and b is True:
        return True
    return UNKNOWN


def t_or(a: Any, b: Any) -> Any:
    if a is True or b is True:
        return True
    if a is False and b is False:
        return False
    return UNKNOWN


def join(a: Any, b: Any) -> Any:
    """Слияние значений двух путей: совпадает — значение, иначе UNKNOWN (объекты одного типа — по полям)."""
    if a is b:
        return a
    if a is UNKNOWN or b is UNKNOWN:
        return UNKNOWN
    if type(a) in (int, float, str, bool) and type(a) is type(b) and a == b:
        return a
    if isinstance(a, EnumV) and isinstance(b, EnumV) and a.type == b.type and a.constant == b.constant:
        return a
    if isinstance(a, Obj) and isinstance(b, Obj) and a.type == b.type:
        keys = set(a.fields) | set(b.fields)
        return Obj(a.type, {k: join(a.get(k), b.get(k)) for k in keys}, open=a.open or b.open)
    if isinstance(a, Wrapper) and isinstance(b, Wrapper):
        return Wrapper(join(a.body, b.body), a.kind)
    if isinstance(a, OptionalV) and isinstance(b, OptionalV):
        if a.value is None and b.value is None:
            return a
        if a.value is None or b.value is None:
            return OptionalV(UNKNOWN)
        return OptionalV(join(a.value, b.value))
    if isinstance(a, ListV) and isinstance(b, ListV):
        if a.exact and b.exact and len(a.items) == len(b.items) and all(x is y for x, y in zip(a.items, b.items)):
            return a
        items = list(a.items) + [x for x in b.items if all(x is not y for y in a.items)]
        return ListV(items, exact=False, elem_type=a.elem_type or b.elem_type)
    return UNKNOWN


def same_value(a: Any, b: Any) -> Any:
    """Сравнение == (для объектов — тождество, для строк и чисел — значение)."""
    if a is UNKNOWN or b is UNKNOWN or isinstance(a, Concat) or isinstance(b, Concat):
        return UNKNOWN
    if a is None or b is None:
        if isinstance(a, OptionalV) or isinstance(b, OptionalV):
            return False
        return a is None and b is None
    if isinstance(a, EnumV) and isinstance(b, EnumV):
        return a.type == b.type and a.constant == b.constant
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return a == b
    if isinstance(a, (str, bool)) and isinstance(b, (str, bool)):
        return a == b
    if isinstance(a, (int, float, str, bool)) or isinstance(b, (int, float, str, bool)):
        if isinstance(a, EnumV) or isinstance(b, EnumV):
            return UNKNOWN
        if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
            return UNKNOWN
        return a == b
    return a is b


def equals_value(a: Any, b: Any) -> Any:
    """Object.equals для значений без проектного equals."""
    r = same_value(a, b)
    if r is not False:
        return r
    if isinstance(a, Obj) and isinstance(b, Obj):
        return UNKNOWN
    return r


def num(v: Any) -> Any:
    """Число из значения (BigDecimal, Double.parseDouble, строки с ценой)."""
    if isinstance(v, bool):
        return UNKNOWN
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return int(v) if v.strip().lstrip("-").isdigit() else float(v)
        except ValueError:
            return UNKNOWN
    return UNKNOWN
