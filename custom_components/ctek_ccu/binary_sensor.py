"""Connectivity read back from the charger."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CcuCoordinator, dig
from .device import ccu_device_info


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CtekBackendConnected(data["coordinator"], data["runtime"])])


class CtekBackendConnected(CoordinatorEntity[CcuCoordinator], BinarySensorEntity):
    """Whether the charger currently has its OCPP backend connection up —
    i.e. whether the upstream central system is still in charge."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "backend_connected"

    def __init__(self, coordinator: CcuCoordinator, runtime) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{runtime.entry_id}_backend_connected"
        self.entity_id = f"binary_sensor.{runtime.prefix}_backend_connected"
        self._attr_device_info = ccu_device_info(runtime.entry_id)

    @property
    def is_on(self) -> bool | None:
        raw = (self.coordinator.data or {}).get("backend")
        if raw is None:
            return None
        if isinstance(raw, bool):
            return raw
        val = dig(raw, "backendconn", "connected", "hasbackendconnection", "value", "status")
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        if isinstance(val, str):
            return val.strip().lower() in ("true", "1", "connected", "online", "yes")
        return bool(val) if val is not None else None
