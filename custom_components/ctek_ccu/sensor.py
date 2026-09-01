"""Status sensor: what the driver last sent, and whether the CCU is reachable."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import ccu_device_info
from .runtime import CtekRuntime


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    rt: CtekRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CtekStatusSensor(rt)])


class CtekStatusSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:information-outline"
    _attr_translation_key = "control_status"

    def __init__(self, runtime: CtekRuntime) -> None:
        self._rt = runtime
        self._attr_unique_id = f"{runtime.entry_id}_control_status"
        self.entity_id = f"sensor.{runtime.prefix}_control_status"
        self._attr_device_info = ccu_device_info(runtime.entry_id)

    @property
    def native_value(self) -> str:
        if self._rt.last_error:
            return "error"
        if not self._rt.control_enabled:
            return "disabled"
        if self._rt.last_command is None:
            return "idle"
        return "blocked" if self._rt.last_command == 0 else f"limit {self._rt.last_command} A"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "control_enabled": self._rt.control_enabled,
            "charging_allowed": self._rt.charging_allowed,
            "requested_current_a": self._rt.current_a,
            "max_current_a": self._rt.max_current_a,
            "last_limit_sent_a": self._rt.last_command,
            "connectors": self._rt.connectors,
            "last_error": self._rt.last_error,
        }
