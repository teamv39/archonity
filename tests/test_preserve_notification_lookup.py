"""Тесты флага абляции --preserve-notification-lookup (Гипотеза 2.5)."""
import pytest
from engine.rules import RuntimeRules


def test_preserve_notification_lookup_modes():
    rules_default = RuntimeRules()
    assert rules_default.preserve_notification_lookup == "on"

    rules_other = RuntimeRules(preserve_notification_lookup="other_only")
    assert rules_other.preserve_notification_lookup == "other_only"

    rules_off = RuntimeRules(preserve_notification_lookup="off")
    assert rules_off.preserve_notification_lookup == "off"

    with pytest.raises(ValueError, match="preserve_notification_lookup"):
        RuntimeRules(preserve_notification_lookup="invalid_mode")
