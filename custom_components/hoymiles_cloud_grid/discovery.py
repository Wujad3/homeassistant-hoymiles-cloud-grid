"""Idempotent entity discovery on coordinator updates."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Iterable


try:
    from homeassistant.helpers import device_registry as dr
except ImportError:  # unit tests run without Home Assistant
    dr = None


def _device_registry(coordinator: Any) -> Any:
    """Return the device registry, or None outside Home Assistant."""
    hass = getattr(coordinator, "hass", None)
    if dr is None or hass is None:
        return None
    return dr.async_get(hass)


def _parent_device(registry: Any, identifier: tuple[str, str], entry_id: str) -> Any:
    """Look up a device of this entry (`async_get_device` is deprecated since 2026.9)."""
    if hasattr(registry, "async_get_device_by_identifier"):
        return registry.async_get_device_by_identifier(identifier, entry_id)
    return registry.async_get_device(identifiers={identifier})


def link_via_devices(registry: Any, entry_id: str, entities: Iterable[Any]) -> None:
    """Replace `via_device` in the entities' device info with `via_device_id`.

    Home Assistant 2026.8 deprecated `via_device` (it stops working in 2027.8);
    older cores do not accept `via_device_id` and keep `via_device`. Parent
    devices (the station) come without `via_device` and are registered first,
    so the child devices (DTU, inverter, battery, meter) link to them by id.
    """
    if registry is None or (
        "via_device_id" not in inspect.signature(registry.async_get_or_create).parameters
    ):
        return
    entities = [
        entity
        for entity in entities
        if isinstance(getattr(entity, "_attr_device_info", None), dict)
    ]
    for entity in entities:
        info = entity._attr_device_info  # noqa: SLF001
        if "via_device" not in info:
            registry.async_get_or_create(config_entry_id=entry_id, **info)
    for entity in entities:
        info = entity._attr_device_info  # noqa: SLF001
        via = info.get("via_device")
        if via is None:
            continue
        fields = {key: value for key, value in info.items() if key != "via_device"}
        parent = _parent_device(registry, via, entry_id)
        if parent is not None:
            fields["via_device_id"] = parent.id
        entity._attr_device_info = fields  # noqa: SLF001


def register_discovery(
    coordinator: Any,
    entry: Any,
    add_entities: Callable[[list[Any]], None],
    build_entities: Callable[[], Iterable[Any]],
) -> None:
    """Add new unique IDs now and after future successful refreshes."""
    seen_ids: set[str] = set()

    def discover() -> None:
        new_entities = []
        pending_ids: set[str] = set()
        for entity in build_entities():
            unique_id = entity.unique_id
            if unique_id in seen_ids or unique_id in pending_ids:
                continue
            pending_ids.add(unique_id)
            new_entities.append(entity)
        if new_entities:
            link_via_devices(
                _device_registry(coordinator), getattr(entry, "entry_id", ""), new_entities
            )
            add_entities(new_entities)
            seen_ids.update(pending_ids)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


def invalidate_control_cache(coordinator: Any, station_id: str) -> None:
    """Force the next coordinator refresh to re-read device settings."""
    callback = getattr(coordinator, "invalidate_control_cache", None)
    if callback is not None:
        callback(station_id)
