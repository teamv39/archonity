"""Константы enum в M4: конструктор константы не пишет в журнал плеч, кеш констант — свой у каждого сценария.

До 22.10 первое обращение к константе внутри плеча с неизвестным условием журналировало поля её конструктора
(у `EnumV` нет `uid`, журнал считал её старым объектом), откат плеча стирал их, а слияние плеч давало UNKNOWN
(`Type.G.name`). Кеш констант жил весь прогон: испорченная константа переходила в следующие сценарии — на
перефразированных S1 и S7 без LLM балл S7 с верными запросами падал с 1.0 до 0.67.
"""
from __future__ import annotations

from engine.executor.values import UNKNOWN, next_uid


def _enum_with_ctor(it):
    """Первое enum проекта, у константы которого конструктор с аргументами и телом в IR."""
    for tid in sorted(it.types.types):
        if not it.types.is_enum(tid):
            continue
        consts = it.types.enum_constants(tid)
        if consts and consts[0][1] and any(it.N[m].get("name") == "<init>" and m in it.ir
                                           for m in it.types.methods.get(tid, ())):
            return tid, consts[0][0]
    return None


def test_enum_init_inside_arm_keeps_fields(shared_pipeline) -> None:
    it = shared_pipeline.m4.it
    found = _enum_with_ctor(it)
    assert found is not None
    tid, name = found
    it.begin_scenario(shared_pipeline.index.db_state.fork())
    it.journal.append({})
    it.journal_start.append(next_uid())
    try:
        ev = it.enum_const(tid, name)
    finally:
        arm = it.journal.pop()
        it.journal_start.pop()
    assert arm == {}, "поля конструктора константы попали в журнал плеча"
    assert ev.fields and all(v is not UNKNOWN for v in ev.fields.values())


def test_enum_cache_is_per_scenario(shared_pipeline) -> None:
    it = shared_pipeline.m4.it
    tid, name = _enum_with_ctor(it)
    it.begin_scenario(shared_pipeline.index.db_state.fork())
    it.enum_const(tid, name)
    assert (tid, name) in it._enum_cache
    it.begin_scenario(shared_pipeline.index.db_state.fork())
    assert (tid, name) not in it._enum_cache
