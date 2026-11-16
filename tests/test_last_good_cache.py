"""Tests for LastGoodCache (serving last good optional payloads through failures)."""
from tests.module_loader import load_integration_module

data_module = load_integration_module("data")
LastGoodCache = data_module.LastGoodCache


def readable(value):
    return bool(value and value.get("readable"))


def test_good_value_is_stored_and_fresh():
    cache = LastGoodCache(max_age=60)
    value, fresh = cache.resolve("k", {"list": [1]}, now=100.0)
    assert value == {"list": [1]}
    assert fresh is True
    assert cache.has_recent("k", now=150.0)


def test_failure_serves_last_good_within_max_age():
    cache = LastGoodCache(max_age=60)
    cache.resolve("k", {"list": [1]}, now=100.0)
    value, fresh = cache.resolve("k", None, now=150.0)
    assert value == {"list": [1]}
    assert fresh is False


def test_failure_after_max_age_returns_failed_value():
    cache = LastGoodCache(max_age=60)
    cache.resolve("k", {"list": [1]}, now=100.0)
    value, fresh = cache.resolve("k", {}, now=161.0)
    assert value == {}
    assert fresh is False
    assert not cache.has_recent("k", now=161.0)


def test_failure_without_history_returns_failed_value():
    cache = LastGoodCache(max_age=60)
    value, fresh = cache.resolve("k", None, now=100.0)
    assert value is None
    assert fresh is False
    assert not cache.has_recent("k", now=100.0)


def test_custom_predicate_keeps_readable_settings():
    cache = LastGoodCache(max_age=1800)
    good = {"readable": True, "data": {"mode": 1}}
    unreadable = {"readable": False, "error_message": "Unable to read battery settings"}
    cache.resolve(("s", "battery_settings"), good, now=0.0, is_good=readable)
    value, fresh = cache.resolve(("s", "battery_settings"), unreadable, now=30.0, is_good=readable)
    assert value is good
    assert fresh is False


def test_keys_are_independent():
    cache = LastGoodCache(max_age=60)
    cache.resolve(("s1", "grid_indicators"), {"list": [1]}, now=0.0)
    value, _ = cache.resolve(("s2", "grid_indicators"), None, now=10.0)
    assert value is None
