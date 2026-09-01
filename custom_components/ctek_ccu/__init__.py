"""CTEK CCU Control — local-API driver for a CTEK charge control unit.

Implements the "allow / block / throttle charging" surface EMS needs, using the
CCU's own REST API. It writes an OCPP TxDefaultProfile, which composes with any
profile an upstream central system (e.g. a Ferroamp EnergyHub doing load
balancing) already applies: OCPP takes the lowest limit, so this driver can only
restrict further — the upstream fuse protection stays intact.

Safety model: a per-entry "control enabled" switch defaults OFF, so installing
and configuring the driver writes nothing to the charger.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import CcuCoordinator
from .runtime import CtekRuntime

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    runtime = CtekRuntime.from_entry(hass, entry)
    coordinator = CcuCoordinator(hass, runtime.api, entry.entry_id, runtime)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "runtime": runtime,
        "coordinator": coordinator,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
