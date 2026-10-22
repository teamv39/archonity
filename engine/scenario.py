"""Чтение файла сценария (Р2): форма сценария не должна стоить ответа.

Файл организаторов может отличаться от S0–S7 мелочами, из-за которых раньше пропадал весь сценарий. Чтение их
выравнивает, сценарий формата S0–S7 не меняется:

- кодировка: UTF-8 с BOM и без, UTF-16 по BOM;
- нет `id` — имя файла;
- нет `steps` или не список — шагов нет (пустой блок без сбоя);
- шаг-строка — текст шага; `n` не целое (`"1"`, `2.0`, нет) — целое или номер по порядку;
- нет `action` — пустой текст: шаг без заземления, остальные шаги сценария идут дальше.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _step_no(n: Any, pos: int) -> int:
    if isinstance(n, bool):
        return pos
    try:
        f = float(n)
    except (TypeError, ValueError):
        return pos
    return int(f) if f.is_integer() else pos


def load_scenario(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    raw = p.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
    sc = json.loads(text)
    if not isinstance(sc, dict):
        raise ValueError(f"ожидался объект JSON, а не {type(sc).__name__}")
    sc = dict(sc)
    sid = sc.get("id")
    sc["id"] = sid.strip() if isinstance(sid, str) and sid.strip() else str(sid) if isinstance(sid, int) else p.stem
    steps = sc.get("steps") if isinstance(sc.get("steps"), list) else []
    out = []
    for pos, st in enumerate(steps, 1):
        st = {"action": st} if isinstance(st, str) else dict(st) if isinstance(st, dict) else {}
        st["n"] = _step_no(st.get("n"), pos)
        a = st.get("action")
        st["action"] = a if isinstance(a, str) else "" if a is None else str(a)
        out.append(st)
    sc["steps"] = out
    return sc
