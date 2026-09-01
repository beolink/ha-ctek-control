"""Device registry entry for the CCU."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


def ccu_device_info(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        manufacturer="CTEK",
        model="Charge Control Unit (local API)",
        name="CTEK CCU",
    )
