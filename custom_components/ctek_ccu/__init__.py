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

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import CONF_CONNECTORS, CONF_MAX_CURRENT, DEFAULT_CONNECTORS, DOMAIN
from .coordinator import CcuCoordinator, dig
from .runtime import CtekRuntime
from .stats import async_setup_stats, async_stop_stats
from .stats_extra import build_extra

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


def _stats_extra_for(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """The driver's part of the anonymous daily report.

    Resolved when the report is built, not when it is armed: a CCU that is
    unreachable makes the set-up raise ConfigEntryNotReady, and this has to
    report the charger as installed and unreachable rather than not at all.
    Reads what the coordinator already fetched and never opens a session of
    its own, since the CCU has a single session slot. What goes in it:
    stats_extra.py, and why: https://stats.rnet.se/integritet
    """
    stored = (hass.data.get(DOMAIN) or {}).get(entry.entry_id) or {}
    runtime = stored.get("runtime")
    coordinator = stored.get("coordinator")
    if runtime is None:
        # Set-up has not finished. Everything the config knows, and an error
        # flag, so an unreachable charger counts as installed and broken.
        config = {**entry.data, **entry.options}
        return build_extra(
            connectors=int(config.get(CONF_CONNECTORS, DEFAULT_CONNECTORS) or 0),
            max_current_a=int(config.get(CONF_MAX_CURRENT, 0) or 0),
            control_enabled=False,
            charging_allowed=False,
            had_error=True,
        )
    data = getattr(coordinator, "data", None) or {}
    return build_extra(
        connectors=runtime.connectors,
        max_current_a=runtime.max_current_a,
        control_enabled=runtime.control_enabled,
        charging_allowed=runtime.charging_allowed,
        backend_connected=dig(data.get("backend"), "backendconn", "connected",
                              "hasbackendconnection", "value", "status"),
        nanogrid=dig(data.get("nanogrid"), "enabled", "active", "status", "value"),
        rfid=dig(data.get("rfid"), "enabled", "active", "status", "value"),
        firmware=dig(data.get("fw"), "version", "fwversion", "value"),
        had_error=runtime.last_error is not None,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Armed before the first refresh: a CCU that is away makes that refresh
    # raise ConfigEntryNotReady, and Home Assistant then retries the set-up
    # for as long as the charger stays away. A reporter armed afterwards, or
    # stopped by an on-unload callback, would go quiet exactly then. Stopped
    # only from async_unload_entry, which a failed attempt never reaches.
    try:
        integration = await async_get_integration(hass, DOMAIN)
        await async_setup_stats(
            hass, entry, DOMAIN, str(integration.version),
            extra=lambda: _stats_extra_for(hass, entry),
        )
    except Exception:  # noqa: BLE001 - statistics must never break a set-up
        _LOGGER.debug("Could not arm the statistics reporter", exc_info=True)

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
        # Only here, never from an on-unload callback: those also run when a
        # set-up attempt fails, and the report has to survive that.
        await async_stop_stats(hass, entry, DOMAIN)
    return unload_ok


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
