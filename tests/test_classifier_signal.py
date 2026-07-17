"""Unit tests for classify_alert_signal() and its env-driven configuration."""

import importlib

import pytest

from backend.services.classifier import classify_alert_signal

ACTIONABLE = {"red", "yellow"}


def test_red_is_actionable():
    assert classify_alert_signal("red", False, ACTIONABLE, True) == "actionable"


def test_yellow_is_actionable():
    assert classify_alert_signal("yellow", False, ACTIONABLE, True) == "actionable"


def test_uppercase_and_mixed_case_colors_are_normalized():
    assert classify_alert_signal("RED", False, ACTIONABLE, True) == "actionable"
    assert classify_alert_signal("YeLLoW", False, ACTIONABLE, True) == "actionable"


def test_whitespace_around_color_is_ignored():
    assert classify_alert_signal("  red  ", False, ACTIONABLE, True) == "actionable"


def test_black_is_noise():
    assert classify_alert_signal("black", False, ACTIONABLE, True) == "noise"


def test_green_is_noise():
    assert classify_alert_signal("green", False, ACTIONABLE, True) == "noise"


def test_gray_is_noise():
    assert classify_alert_signal("gray", False, ACTIONABLE, True) == "noise"


def test_blank_color_is_noise():
    assert classify_alert_signal("", False, ACTIONABLE, True) == "noise"
    assert classify_alert_signal("   ", False, ACTIONABLE, True) == "noise"


def test_none_color_is_noise():
    assert classify_alert_signal(None, False, ACTIONABLE, True) == "noise"


def test_unrecognized_color_is_noise():
    assert classify_alert_signal("purple", False, ACTIONABLE, True) == "noise"


def test_known_error_is_suppressed_when_suppression_enabled():
    assert classify_alert_signal("red", True, ACTIONABLE, True) == "suppressed"


def test_known_red_error_is_actionable_when_suppression_disabled():
    assert classify_alert_signal("red", True, ACTIONABLE, False) == "actionable"


def test_known_error_with_non_actionable_color_stays_noise_regardless_of_suppression():
    assert classify_alert_signal("black", True, ACTIONABLE, False) == "noise"
    assert classify_alert_signal("black", True, ACTIONABLE, True) == "suppressed"  # suppression wins


def test_custom_actionable_color_configuration():
    custom = {"orange"}
    assert classify_alert_signal("orange", False, custom, True) == "actionable"
    assert classify_alert_signal("red", False, custom, True) == "noise"


# ─── Config parsing ────────────────────────────────────────────────────────────

@pytest.fixture
def config_module():
    import backend.services.config as config
    yield config
    # Restore true env-based state so later tests/imports aren't affected by reloads.
    importlib.reload(config)


def test_actionable_colors_env_parsing_case_insensitive_and_trims_whitespace(monkeypatch, config_module):
    monkeypatch.setenv("SCANFOR_ACTIONABLE_COLORS", " Red , YELLOW ,, orange ")
    importlib.reload(config_module)
    assert config_module.ACTIONABLE_COLORS == {"red", "yellow", "orange"}


def test_actionable_colors_blank_value_falls_back_to_default(monkeypatch, config_module):
    monkeypatch.setenv("SCANFOR_ACTIONABLE_COLORS", "   ")
    importlib.reload(config_module)
    assert config_module.ACTIONABLE_COLORS == {"red", "yellow"}


def test_actionable_colors_default_when_unset(monkeypatch, config_module):
    monkeypatch.delenv("SCANFOR_ACTIONABLE_COLORS", raising=False)
    importlib.reload(config_module)
    assert config_module.ACTIONABLE_COLORS == {"red", "yellow"}


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", "TRUE", "Yes", "ON"])
def test_suppress_known_errors_true_values(monkeypatch, config_module, value):
    monkeypatch.setenv("SCANFOR_SUPPRESS_KNOWN_ERRORS", value)
    importlib.reload(config_module)
    assert config_module.SUPPRESS_KNOWN_ERRORS is True


def test_suppress_known_errors_false_value(monkeypatch, config_module):
    monkeypatch.setenv("SCANFOR_SUPPRESS_KNOWN_ERRORS", "false")
    importlib.reload(config_module)
    assert config_module.SUPPRESS_KNOWN_ERRORS is False


def test_suppress_known_errors_defaults_true_when_unset(monkeypatch, config_module):
    monkeypatch.delenv("SCANFOR_SUPPRESS_KNOWN_ERRORS", raising=False)
    importlib.reload(config_module)
    assert config_module.SUPPRESS_KNOWN_ERRORS is True
