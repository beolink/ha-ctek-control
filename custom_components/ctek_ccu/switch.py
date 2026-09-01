"""The control gate and the allow/block-charging switch."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
    async_add_entities([CtekControlEnabledSwitch(rt), CtekChargingAllowedSwitch(rt)])


class _Base(RestoreEntity, SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, runtime: CtekRuntime, key: str, icon: str) -> None:
        self._rt = runtime
        self._key = key
        self._attr_icon = icon
        self._attr_translation_key = key
        self._attr_unique_id = f"{runtime.entry_id}_{key}"
        self.entity_id = f"switch.{runtime.prefix}_{key}"
        self._attr_device_info = ccu_device_info(runtime.entry_id)
        self._is_on = False

    @property
    def is_on(self) -> bool:
        return self._is_on


class CtekControlEnabledSwitch(_Base):
    """Master gate. While OFF the driver never writes to the charger."""

    def __init__(self, runtime: CtekRuntime) -> None:
        super().__init__(runtime, "control_enabled", "mdi:ev-station")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self._is_on = last is not None and last.state == "on"
        self._rt.control_enabled = self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        self._rt.control_enabled = True
        self.async_write_ha_state()
        await self._rt.async_apply()

    async def async_turn_off(self, **kwargs) -> None:
        self._rt.control_enabled = False
        self._is_on = False
        self.async_write_ha_state()
        await self._rt.async_release()


class CtekChargingAllowedSwitch(_Base):
    """EMS binds this as its EV charger entity: on = charging permitted."""

    def __init__(self, runtime: CtekRuntime) -> None:
        super().__init__(runtime, "charging_allowed", "mdi:car-electric")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self._is_on = last is not None and last.state == "on"
        self._rt.charging_allowed = self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        self._rt.charging_allowed = True
        self.async_write_ha_state()
        await self._rt.async_apply()

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        self._rt.charging_allowed = False
        self.async_write_ha_state()
        await self._rt.async_apply()
