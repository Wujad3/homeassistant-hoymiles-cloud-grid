"""HA-free regression tests for late entity discovery."""

from types import SimpleNamespace

from tests.module_loader import load_integration_module


def test_register_discovery_adds_late_entities_once_and_unloads() -> None:
    discovery = load_integration_module("discovery")
    listeners = []
    unloads = []
    added = []
    entities = [SimpleNamespace(unique_id="station_pv1")]
    coordinator = SimpleNamespace(async_add_listener=lambda callback: listeners.append(callback) or listeners.clear)
    entry = SimpleNamespace(async_on_unload=unloads.append)

    discovery.register_discovery(coordinator, entry, added.append, lambda: entities)
    assert [[item.unique_id for item in batch] for batch in added] == [["station_pv1"]]
    entities.append(SimpleNamespace(unique_id="station_pv2"))
    listeners[0]()
    listeners[0]()
    assert [[item.unique_id for item in batch] for batch in added] == [["station_pv1"], ["station_pv2"]]
    unloads[0]()
    assert listeners == []


def test_register_discovery_deduplicates_batch_and_retries_failed_add() -> None:
    discovery = load_integration_module("discovery")
    listeners = []
    calls = []
    entities = [SimpleNamespace(unique_id="initial")]
    coordinator = SimpleNamespace(async_add_listener=lambda callback: listeners.append(callback) or (lambda: None))
    entry = SimpleNamespace(async_on_unload=lambda callback: None)

    def add(batch):
        calls.append([entity.unique_id for entity in batch])
        if len(calls) == 2:
            raise RuntimeError("setup failed")

    discovery.register_discovery(coordinator, entry, add, lambda: entities)
    entities.extend([SimpleNamespace(unique_id="same"), SimpleNamespace(unique_id="same")])
    try:
        listeners[0]()
    except RuntimeError:
        pass
    else:
        raise AssertionError("first late setup should fail")
    listeners[0]()
    assert calls == [["initial"], ["same"], ["same"]]


class FakeDeviceRegistry:
    """Device registry of Home Assistant 2026.9+ (`via_device_id`, lookup by identifier)."""

    def __init__(self) -> None:
        self.devices: dict[tuple[str, str], SimpleNamespace] = {}

    def async_get_or_create(self, *, config_entry_id, via_device_id=None, **kwargs):
        (identifier,) = kwargs["identifiers"]
        device = self.devices.setdefault(
            identifier, SimpleNamespace(id=f"dev-{identifier[1]}", entry=config_entry_id)
        )
        return device

    def async_get_device_by_identifier(self, identifier, config_entry_id):
        device = self.devices.get(identifier)
        return device if device is not None and device.entry == config_entry_id else None


class LegacyDeviceRegistry:
    """Device registry before Home Assistant 2026.8 (only `via_device`)."""

    def async_get_or_create(self, *, config_entry_id, **kwargs):
        raise AssertionError("not called on old cores")


def test_link_via_devices_uses_parent_device_id() -> None:
    discovery = load_integration_module("discovery")
    registry = FakeDeviceRegistry()
    station = SimpleNamespace(
        _attr_device_info={"identifiers": {("hoymiles_cloud_grid", "123")}, "name": "Station"}
    )
    battery = SimpleNamespace(
        _attr_device_info={
            "identifiers": {("hoymiles_cloud_grid", "battery_1")},
            "name": "Battery",
            "via_device": ("hoymiles_cloud_grid", "123"),
        }
    )
    orphan = SimpleNamespace(
        _attr_device_info={
            "identifiers": {("hoymiles_cloud_grid", "meter_1")},
            "via_device": ("hoymiles_cloud_grid", "999"),
        }
    )

    # The child comes first in the batch: the station must still be registered first.
    discovery.link_via_devices(registry, "entry1", [battery, station, orphan])

    assert battery._attr_device_info == {
        "identifiers": {("hoymiles_cloud_grid", "battery_1")},
        "name": "Battery",
        "via_device_id": "dev-123",
    }
    assert "via_device" not in orphan._attr_device_info
    assert "via_device_id" not in orphan._attr_device_info
    assert station._attr_device_info == {
        "identifiers": {("hoymiles_cloud_grid", "123")},
        "name": "Station",
    }


def test_link_via_devices_keeps_via_device_on_old_cores() -> None:
    discovery = load_integration_module("discovery")
    info = {"identifiers": {("hoymiles_cloud_grid", "battery_1")}, "via_device": ("hoymiles_cloud_grid", "123")}
    battery = SimpleNamespace(_attr_device_info=dict(info))

    discovery.link_via_devices(LegacyDeviceRegistry(), "entry1", [battery])
    discovery.link_via_devices(None, "entry1", [battery])

    assert battery._attr_device_info == info
