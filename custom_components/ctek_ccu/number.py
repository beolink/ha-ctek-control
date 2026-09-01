"""Charging current (A). EMS binds this as its EV current entity."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .device import ccu_device_info
from .runtime import CtekRuntime


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    rt: CtekRuntime = data["runtime"]
    async_add_entities([CtekChargingCurrentNumber(rt)])


class CtekChargingCurrentNumber(RestoreEntity, NumberEntity):
    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "A"
    _attr_icon = "mdi:current-ac"
    _attr_translation_key = "charging_current"

    def __init__(self, runtime: CtekRuntime) -> None:
        self._rt = runtime
        self._attr_unique_id = f"{runtime.entry_id}_charging_current"
        self.entity_id = f"number.{runtime.prefix}_charging_current"
        self._attr_device_info = ccu_device_info(runtime.entry_id)
        # Never offer more than the configured ceiling.
        self._attr_native_max_value = runtime.max_current_a

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state not in (None, "unknown", "unavailable"):
            try:
                self._rt.current_a = int(float(last.state))
            except (TypeError, ValueError):
                pass

    @property
    def native_value(self) -> float:
        return float(self._rt.current_a)

    async def async_set_native_value(self, value: float) -> None:
        self._rt.current_a = int(value)
        self.async_write_ha_state()
        await self._rt.async_apply()
