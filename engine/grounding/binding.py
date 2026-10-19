"""Обработчик, который Spring MVC не может вызвать (R20, M1).

`@PathVariable` связывается по имени: явному (`@PathVariable("id")`) или имени параметра. Если имени нет среди
переменных шаблона пути, Spring отвечает ошибкой (`MissingPathVariableException`) до вызова контроллера: метод
не исполняется, рёбер нет. В Train Ticket такой обработчик один:

    @GetMapping("/stationfoodstores/{stationId}")
    public HttpEntity getFoodStoresOfStation(@PathVariable String stationName, ...)

Шаг, который M1 заземлил на такой обработчик, в эталоне идёт через рабочий обработчик того же контроллера,
который принимает тот же вход: имя станции → `POST /stationfoodstores` (`getFoodStoresByStationNames(List<String>
stationNameList)`). Подтверждено посылкой 27 (19.10, итог 1.00000).

Замена: обработчик того же класса, который Spring вызвать может, и у которого есть параметр запроса (путь, query,
тело) с тем же корнем имени, что у несвязываемой переменной (`stationName` ↔ `stationNameList`, `stationNames`).
Если такого нет или их несколько — замены нет.
"""
from __future__ import annotations

import re
from typing import Any

from engine.adapters.skeleton import SkeletonIndex
from engine.grounding.docs import HandlerCatalog, HandlerInfo

_NAME_ARG = re.compile(r'(?:^|value\s*=\s*|name\s*=\s*)"(\w+)"')


def _stem(name: str) -> str:
    """Корень имени параметра: `stationNameList`, `stationNames` → `stationname`."""
    s = re.sub(r"(List|Set|Array)$", "", name)
    s = re.sub(r"(?<=[a-z])s$", "", s)
    return s.lower()


_PARAMS: dict[int, dict[str, list[dict[str, Any]]]] = {}


def _params(ix: SkeletonIndex) -> dict[str, list[dict[str, Any]]]:
    if id(ix) not in _PARAMS:
        idx: dict[str, list[dict[str, Any]]] = {}
        for n in ix.N.values():
            if n.get("kind") == "parameter":
                idx.setdefault(n["method"], []).append(n)
        _PARAMS[id(ix)] = idx
    return _PARAMS[id(ix)]


def path_variables(ix: SkeletonIndex, handler: str) -> list[str]:
    """Имена, по которым Spring ищет `@PathVariable` обработчика."""
    out = []
    for n in _params(ix).get(handler, []):
        for a in n.get("annotations") or []:
            if a.get("name") == "PathVariable":
                m = _NAME_ARG.search((a.get("args") or "").strip())
                out.append(m.group(1) if m else n["name"])
    return out


def unbound_path_variables(ix: SkeletonIndex, h: HandlerInfo) -> list[str]:
    """`@PathVariable`, которых нет в шаблоне пути ни одного маршрута обработчика."""
    tpl = {v for _, path in h.routes for v in re.findall(r"\{(\w+)", path)}
    return [v for v in path_variables(ix, h.id) if v not in tpl]


def rebind(ix: SkeletonIndex, cat: HandlerCatalog, handler: str) -> tuple[str, dict[str, Any]] | None:
    """Рабочий обработчик вместо того, который Spring вызвать не может; None — замена не нужна или не найдена."""
    h = cat.handlers.get(handler)
    if h is None:
        return None
    bad = unbound_path_variables(ix, h)
    if not bad:
        return None
    owner = ix.N[handler].get("owner")
    want = {_stem(v) for v in bad}
    alts = [x.id for x in cat.handlers.values()
            if x.id != handler and ix.N[x.id].get("owner") == owner and not unbound_path_variables(ix, x)
            and any(p["source"] in ("path", "query", "body") and _stem(p["name"]) in want for p in x.params)]
    if len(alts) != 1:
        return None
    return alts[0], {"rule": "R20:unbound_path_variable", "from": handler, "path_variables": bad}
