"""Tests for billing-period counters."""

from datetime import date

from tests.module_loader import load_integration_module


billing = load_integration_module("billing")


def test_period_start_before_and_after_anniversary():
    assert billing.billing_period_start(date(2026, 10, 9), 5, 1) == date(2026, 5, 1)
    assert billing.billing_period_start(date(2026, 3, 9), 5, 1) == date(2025, 5, 1)
    assert billing.billing_period_start(date(2026, 5, 1), 5, 1) == date(2026, 5, 1)


def test_period_clamps_short_months():
    assert billing.billing_period_start(date(2026, 3, 1), 2, 31) == date(2026, 2, 28)
    assert billing.billing_period_end(date(2026, 5, 1), 5, 1) == date(2027, 4, 30)


def test_accumulates_increase_only():
    state = {}
    billing.apply_readings(state, "2026-05-01", {"import": 1000, "export": 5000})
    assert billing.billing_value(state, "import") == 0
    billing.apply_readings(state, "2026-05-01", {"import": 1500, "export": 7000})
    assert billing.billing_value(state, "import") == 500
    assert billing.billing_value(state, "export") == 2000
    assert billing.billing_value(state, "balance") == 1500
    assert billing.billing_value(state, "balance", 0.8) == 1100


def test_missing_and_zero_readings_are_ignored():
    state = {}
    billing.apply_readings(state, "2026-05-01", {"import": 1000})
    billing.apply_readings(state, "2026-05-01", {"import": None})
    billing.apply_readings(state, "2026-05-01", {"import": 0})
    billing.apply_readings(state, "2026-05-01", {"import": 1200})
    assert billing.billing_value(state, "import") == 200


def test_source_reset_and_glitch():
    state = {}
    billing.apply_readings(state, "2026-05-01", {"import": 400000})
    billing.apply_readings(state, "2026-05-01", {"import": 469500})
    # New calendar year: cloud yearly counter restarts.
    billing.apply_readings(state, "2026-05-01", {"import": 300})
    assert billing.billing_value(state, "import") == 69500 + 300
    # A small drop (e.g. a different source counter) is ignored.
    billing.apply_readings(state, "2026-05-01", {"import": 250})
    billing.apply_readings(state, "2026-05-01", {"import": 400})
    assert billing.billing_value(state, "import") == 69500 + 400


def test_new_period_resets_values():
    state = {}
    billing.apply_readings(state, "2025-05-01", {"import": 1000})
    billing.apply_readings(state, "2025-05-01", {"import": 3000})
    billing.apply_readings(state, "2026-05-01", {"import": 3500})
    assert billing.billing_value(state, "import") == 500


def test_calibration_applies_once():
    state = {}
    billing.apply_readings(state, "2026-05-01", {"import": 1000})
    calibration = {"id": "a", "import": 90900}
    billing.apply_readings(state, "2026-05-01", {"import": 1000}, calibration)
    assert billing.billing_value(state, "import") == 90900
    billing.apply_readings(state, "2026-05-01", {"import": 1100}, calibration)
    assert billing.billing_value(state, "import") == 91000
    assert billing.billing_value(state, "pv") is None
