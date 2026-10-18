"""Модуль декларативных правил ветвления (Branch Rules) для AST IR движка.

Реализует спецификацию ADR-005 (M2/M4/M5) и план archparse Day 2 (Блок 4):
1. Загрузка и валидация data/branch_rules.json.
2. Декларативное сопоставление предикатов веток (id ветки, регэкспы условия, метод, плечо).
3. Разрешение условий ветвления на основе ScenarioProfile и ScenarioState без хардкода в ir.py.
4. Поддержка абляций: отключение правил по ID (BR_*) или аннотации (R*) для замеров качества.
5. Регистрация обоснования правил для evidence.json v2.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


class BranchRuleValidationError(ValueError):
    """Ошибка валидации структуры или типов в branch_rules.json."""


@dataclass
class RuleMatcher:
    """Критерии сопоставления правила с точкой ветвления."""
    arm_exact: str | None = None
    arm_in: tuple[str, ...] = ()
    branch_type: str | None = None  # "lambda", "foreach", "if", etc.
    branch_id_in: tuple[str, ...] = ()
    method_contains: str | None = None
    method_regex: re.Pattern | None = None
    condition_exact: str | None = None
    condition_contains: str | None = None
    condition_contains_all: tuple[str, ...] = ()
    condition_regex: re.Pattern | None = None
    any_of: list[RuleMatcher] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RuleMatcher:
        method_rx = re.compile(d["method_regex"]) if "method_regex" in d else None
        cond_rx = re.compile(d["condition_regex"]) if "condition_regex" in d else None
        any_of = [cls.from_dict(sub) for sub in d.get("any_of", [])]
        return cls(
            arm_exact=d.get("arm_exact"),
            arm_in=tuple(d.get("arm_in", ())),
            branch_type=d.get("branch_type"),
            branch_id_in=tuple(d.get("branch_id_in", ())),
            method_contains=d.get("method_contains"),
            method_regex=method_rx,
            condition_exact=d.get("condition_exact"),
            condition_contains=d.get("condition_contains"),
            condition_contains_all=tuple(d.get("condition_contains_all", ())),
            condition_regex=cond_rx,
            any_of=any_of,
        )

    def matches(self, method_id: str, bid: str, arm: str, cond: str) -> bool:
        # Проверка arm
        if self.arm_exact is not None and arm != self.arm_exact:
            return False
        if self.arm_in and arm not in self.arm_in:
            return False

        # Проверка типа ветки
        if self.branch_type == "lambda" and not (bid.startswith("l") and bid[1:].isdigit()):
            return False
        if self.branch_type == "foreach" and not (bid.startswith("f") and bid[1:].isdigit()):
            return False

        # Проверка branch_id
        if self.branch_id_in and bid not in self.branch_id_in:
            return False

        # Проверка метода
        if self.method_contains and self.method_contains.lower() not in method_id.lower():
            return False
        if self.method_regex and not self.method_regex.search(method_id):
            return False

        # Проверка условия
        if self.condition_exact is not None and cond.strip() != self.condition_exact.strip():
            return False
        if self.condition_contains and self.condition_contains not in cond:
            return False
        if self.condition_contains_all and not all(sub in cond for sub in self.condition_contains_all):
            return False
        if self.condition_regex and not self.condition_regex.search(cond):
            return False

        # Проверка any_of
        return not (self.any_of and not any(sub.matches(method_id, bid, arm, cond) for sub in self.any_of))


@dataclass
class RuleResolver:
    """Резолвер логического значения условия ветки."""
    type: str  # "constant", "profile_flag", "train_mode"
    value: bool | None = None
    flag: str | None = None
    invert: bool = False
    regular_only: bool = True
    high_speed_only: bool = True
    default: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RuleResolver:
        rtype = d.get("type", "constant")
        if rtype not in ("constant", "profile_flag", "train_mode", "predicate"):
            raise BranchRuleValidationError(f"Неизвестный тип резолвера: {rtype}")
        return cls(
            type=rtype,
            value=d.get("value"),
            flag=d.get("flag"),
            invert=bool(d.get("invert", False)),
            regular_only=bool(d.get("regular_only", True)),
            high_speed_only=bool(d.get("high_speed_only", True)),
            default=bool(d.get("default", True)),
        )

    def resolve(self, profile: Any, state: Any = None) -> bool:
        if self.type == "constant":
            return bool(self.value)

        if self.type in ("profile_flag", "predicate"):
            if profile and self.flag and hasattr(profile, self.flag):
                val = bool(getattr(profile, self.flag))
            else:
                val = bool(self.default)
            return not val if self.invert else val

        if self.type == "train_mode":
            mode = getattr(profile, "train_mode", "both") if profile else "both"
            if mode == "regular_only":
                res = self.regular_only
            elif mode == "high_speed_only":
                res = self.high_speed_only
            else:
                res = self.default
            return not res if self.invert else res

        return bool(self.default)


@dataclass
class BranchRule:
    """Декларативное правило разрешения ветки AST."""
    id: str
    code: str
    description: str
    enabled: bool
    matcher: RuleMatcher
    resolver: RuleResolver

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BranchRule:
        rule_id = d.get("id")
        if not rule_id or not isinstance(rule_id, str):
            raise BranchRuleValidationError(f"Правило должно содержать строковый 'id': {d}")
        code = d.get("code", "R?")
        desc = d.get("description", "")
        enabled = bool(d.get("enabled", True))

        matcher_dict = d.get("matcher")
        if not matcher_dict or not isinstance(matcher_dict, dict):
            raise BranchRuleValidationError(f"Правило {rule_id} должно содержать словарь 'matcher'")
        matcher = RuleMatcher.from_dict(matcher_dict)

        resolver_dict = d.get("resolver")
        if not resolver_dict or not isinstance(resolver_dict, dict):
            raise BranchRuleValidationError(f"Правило {rule_id} должно содержать словарь 'resolver'")
        resolver = RuleResolver.from_dict(resolver_dict)

        return cls(
            id=rule_id,
            code=code,
            description=desc,
            enabled=enabled,
            matcher=matcher,
            resolver=resolver,
        )


class BranchRulesRegistry:
    """Реестр правил разрешения веток IR archparse."""

    def __init__(self, rules: list[BranchRule] | None = None) -> None:
        self.rules: list[BranchRule] = rules or []
        self._disabled_rule_ids: set[str] = set()

    @classmethod
    def load(
        cls,
        path: Path | str | None = None,
        disabled_rules: set[str] | None = None,
        strict: bool = False,
    ) -> BranchRulesRegistry:
        """Загрузка правил из JSON-файла с валидацией схемы."""
        target_path = Path(path) if path else Path(__file__).resolve().parent.parent / "data" / "branch_rules.json"
        if not target_path.is_file():
            LOGGER.warning("Файл branch_rules.json не найден в %s. Используется пустой реестр.", target_path)
            return cls([])

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict) or "rules" not in data or not isinstance(data["rules"], list):
                raise BranchRuleValidationError("Файл branch_rules.json должен быть объектом со списком 'rules'")

            parsed_rules: list[BranchRule] = []
            for r in data["rules"]:
                rule = BranchRule.from_dict(r)
                parsed_rules.append(rule)

            registry = cls(parsed_rules)
            if disabled_rules:
                registry._disabled_rule_ids = set(disabled_rules)
            return registry
        except Exception as e:
            if strict:
                raise
            LOGGER.error("Ошибка загрузки branch_rules.json: %s. Возврат пустого реестра.", e)
            return cls([])

    def disable_rule(self, rule_id: str) -> None:
        self._disabled_rule_ids.add(rule_id)

    def enable_rule(self, rule_id: str) -> None:
        self._disabled_rule_ids.discard(rule_id)

    def is_rule_active(self, rule: BranchRule) -> bool:
        if not rule.enabled:
            return False
        if rule.id in self._disabled_rule_ids:
            return False
        return rule.code not in self._disabled_rule_ids

    def evaluate_branch(
        self,
        method_id: str,
        bid: str,
        arm: str,
        cond: str,
        profile: Any,
        state: Any = None,
    ) -> tuple[bool | None, BranchRule | None]:
        """Оценивает ветку и возвращает (условие_истинно, сработавшее_правило).

        Если ни одно активное правило не сопоставлено, возвращает (None, None).
        """
        for rule in self.rules:
            if not self.is_rule_active(rule):
                continue
            if rule.matcher.matches(method_id, bid, arm, cond):
                val = rule.resolver.resolve(profile, state)
                return val, rule

        return None, None
