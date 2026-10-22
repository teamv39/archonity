"""Режимы правил исполнения M4 и проекции M5 (флаги абляций run_eval.py).

Значения по умолчанию дают рекорд (eval/records). Остальные режимы — откат правила для проверки гипотез.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import ClassVar


@dataclass(frozen=True)
class RuntimeRules:
    """Режимы правил, которые читают M4 (`engine/executor`) и M5 (`engine/projection.py`)."""

    # R7, ADR-006: caller_only — конструктор в ответе, только если из него исполнился вызов метода проекта, рёбер calls
    # в конструктор нет; all — как до ADR-006 (new — всегда, загрузка Hibernate — с вызовом проекта в теле);
    # off — конструкторов нет (отладка)
    constructors: str = "caller_only"
    # R10: loaded — таблица ленивой коллекции, только если метод загрузил коллекцию сам; all — все таблицы data_access
    collection_tables_on_read: str = "loaded"
    # equals сущности из list.contains(x) на результате чтения
    element_callbacks: str = "on"
    # R13: доставка сообщения RabbitMQ потребителю
    rabbitmq_delivery: str = "on"
    # R7: Jackson создаёт тело запроса рукописным конструктором без аргументов
    jackson_ctor: str = "on"
    # R5: аргумент SLF4J по шаблону с {} форматируется Lombok-toString, рукописные геттеры полей исполняются
    lombok_tostring: str = "on"
    # R20: обработчик, который Spring вызвать не может, — шаг через рабочий обработчик того же контроллера (rebind)
    # или как выбрал M1 (keep)
    unbound_handlers: str = "rebind"
    # Метод проекта на получателе известного типа без ребра в скелете (TripId#toString): emit — рёбра, mute — только
    # значение
    unresolved_receiver_calls: str = "emit"
    # Шаг ожидает успех, а по значениям M1 отказал: повтор с нормализованными, затем неизвестными строками
    m4_success_retry: str = "on"
    # Ссылка first/second_of_step_N, а в параметрах шага — строковый ID сущности того же вида: из результатов шага N
    # берётся сущность с этим ID (шаг называет объект явно), а не первая по порядку
    ref_explicit_id: str = "on"
    # Ссылка на шаг, чей ответ — объект нужного вида без ID (сводка «доплатите разницу»): сущность — та, на которую
    # ссылался сам этот шаг
    ref_idless_result: str = "on"
    # Группа полей, которую UI шлёт только под общим условием (каталог UI): шаг не дал ни поля группы, ни литерала
    # условия со значением не по умолчанию — полей в запросе нет, у DTO умолчания полей
    ui_optional_groups: str = "on"
    # Ссылка first/second_of_step_N без слова позиции в тексте шага, а запись этого вида создал шаг раньше, чем читался
    # список N: ссылка на созданную запись (R22). Rust — StepCore::prefer_created
    ref_unpositioned: str = "on"

    MODES: ClassVar[dict[str, tuple[str, ...]]] = {
        "constructors": ("caller_only", "all", "off"),
        "collection_tables_on_read": ("loaded", "all"),
        "element_callbacks": ("on", "off"),
        "rabbitmq_delivery": ("on", "off"),
        "jackson_ctor": ("on", "off"),
        "lombok_tostring": ("on", "off"),
        "unbound_handlers": ("rebind", "keep"),
        "unresolved_receiver_calls": ("emit", "mute"),
        "m4_success_retry": ("on", "off"),
        "ref_explicit_id": ("on", "off"),
        "ref_idless_result": ("on", "off"),
        "ui_optional_groups": ("on", "off"),
        "ref_unpositioned": ("on", "off"),
    }

    def __post_init__(self) -> None:
        for f in fields(self):
            val = getattr(self, f.name)
            if val not in self.MODES[f.name]:
                raise ValueError(f"{f.name}: {val!r}, ожидается одно из {self.MODES[f.name]}")
