"""Billing-period energy counters (e.g. 1 May -> 30 April).

The pure helpers at the top are importable without Home Assistant so they can
be unit tested; the tracker at the bottom wires them to a Store and the
coordinator.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any, Callable

BILLING_KINDS = ("import", "export", "pv")


def _clamped_date(year: int, month: int, day: int) -> date:
    """Return the date, moving e.g. 31 Feb to the last day of February."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def billing_period_start(today: date, month: int, day: int) -> date:
    """Return the start of the billing period that contains ``today``."""
    start = _clamped_date(today.year, month, day)
    if today < start:
        start = _clamped_date(today.year - 1, month, day)
    return start


def billing_period_end(start: date, month: int, day: int) -> date:
    """Return the last day of the billing period starting at ``start``."""
    return date.fromordinal(_clamped_date(start.year + 1, month, day).toordinal() - 1)


def apply_readings(
    state: dict[str, Any],
    period_start: str,
    readings: dict[str, int | None],
    calibration: dict[str, Any] | None = None,
) -> bool:
    """Fold new cumulative readings into the billing counters; return True if changed.

    ``readings`` are lifetime-style counters in Wh. Only their increase is
    accumulated, so a counter that resets (e.g. yearly in the cloud) keeps
    working. ``calibration`` holds user-entered values in Wh and is applied once
    per ``calibration["id"]``.
    """
    changed = False
    counters = state.setdefault("counters", {})

    if state.get("period_start") != period_start:
        for counter in counters.values():
            counter["value"] = 0
        state["period_start"] = period_start
        changed = True

    for kind, reading in readings.items():
        # 0 / missing usually means the cloud returned an empty payload.
        if not reading:
            continue
        counter = counters.setdefault(kind, {"value": 0, "last": None})
        last = counter["last"]
        if last is None:
            counter["last"] = reading
            changed = True
            continue
        if reading >= last:
            delta = reading - last
        elif reading < last / 2:
            # Source counter was reset (e.g. new calendar year).
            delta = reading
        else:
            # Small drop: a glitch or a switch to another source counter.
            # Ignore it and keep the previous reference point.
            continue
        if delta:
            counter["value"] += delta
            changed = True
        counter["last"] = reading

    if calibration and calibration.get("id") != state.get("calibration_id"):
        for kind in BILLING_KINDS:
            value = calibration.get(kind)
            if value is not None:
                counters.setdefault(kind, {"value": 0, "last": None})["value"] = int(value)
        state["calibration_id"] = calibration.get("id")
        changed = True

    return changed


def billing_value(state: dict[str, Any], kind: str, export_factor: float = 1.0) -> int | None:
    """Return a counter value in Wh, or the balance (export * factor - import)."""
    counters = state.get("counters", {})
    if kind == "balance":
        if "import" not in counters or "export" not in counters:
            return None
        return round(counters["export"]["value"] * export_factor - counters["import"]["value"])
    counter = counters.get(kind)
    return None if counter is None else counter["value"]


class BillingPeriodTracker:
    """Per-station billing counters persisted in a Home Assistant Store."""

    def __init__(
        self,
        hass: Any,
        store: Any,
        readings_fn: Callable[[], dict[str, int | None]],
    ) -> None:
        """Initialize the tracker."""
        self._hass = hass
        self._store = store
        self._readings_fn = readings_fn
        self.state: dict[str, Any] = {}
        self.month = 1
        self.day = 1
        self.export_factor = 1.0
        self.calibration: dict[str, Any] | None = None

    async def async_load(self) -> None:
        """Load the persisted counters."""
        self.state = await self._store.async_load() or {}

    def configure(
        self,
        month: int,
        day: int,
        export_factor: float,
        calibration: dict[str, Any] | None,
        readings_fn: Callable[[], dict[str, int | None]],
    ) -> None:
        """Apply (possibly changed) options after an entry (re)load."""
        self.month = month
        self.day = day
        self.export_factor = export_factor
        self.calibration = calibration
        self._readings_fn = readings_fn

    def period(self) -> tuple[date, date]:
        """Return the current billing period as (first day, last day)."""
        from homeassistant.util import dt as dt_util

        start = billing_period_start(dt_util.now().date(), self.month, self.day)
        return start, billing_period_end(start, self.month, self.day)

    def update(self) -> None:
        """Process the latest coordinator data."""
        start, _ = self.period()
        if apply_readings(self.state, start.isoformat(), self._readings_fn(), self.calibration):
            self._store.async_delay_save(lambda: self.state, 30)

    def value(self, kind: str) -> int | None:
        """Return a billing counter value in Wh."""
        return billing_value(self.state, kind, self.export_factor)
