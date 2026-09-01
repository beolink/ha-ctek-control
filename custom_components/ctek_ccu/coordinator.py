"""Polls the CCU's read-only endpoints.

The exact response shapes differ between CCU firmware versions, so everything
here is defensive: an endpoint that errors simply yields ``None`` for that key
and its entities go unavailable, rather than breaking the whole update.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import CcuApi
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

POLL_SECONDS = 30

# key -> endpoint. Read-only; nothing here changes charger state.
ENDPOINTS = {
    "outlets": "/api/status/getoutletstates",
    "backend": "/api/status/hasbackendconnection",
    "fw": "/api/status/getfwversion",
    "serial": "/api/status/getserialno",
    "rfid": "/api/status/getrfidstatus",
    "nanogrid": "/api/nanogrid/status",
    "mil": "/api/nanogrid/mil/status",
    "profiles": "/api/config/getChargingProfiles",
}


def dig(data, *names):
    """Depth-first search for the first value under any of ``names``.

    Firmware revisions nest these payloads differently; matching on key name
    rather than a fixed path keeps the sensors working across shapes.
    """
    wanted = {n.lower() for n in names}
    stack = [data]
    while stack:
        cur = stack.pop(0)
        if isinstance(cur, dict):
            for k, v in cur.items():
                if str(k).lower() in wanted and not isinstance(v, (dict, list)):
                    return v
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def active_limit_a(profiles) -> float | None:
    """Lowest limit across the returned charging profiles (what actually binds)."""
    limits: list[float] = []
    stack = [profiles]
    while stack:
        cur = stack.pop(0)
        if isinstance(cur, dict):
            if "limit" in cur:
                try:
                    limits.append(float(cur["limit"]))
                except (TypeError, ValueError):
                    pass
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return min(limits) if limits else None


class CcuCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, api: CcuApi, entry_id: str) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}_{entry_id}",
                         update_interval=timedelta(seconds=POLL_SECONDS))
        self._api = api

    async def _async_update_data(self) -> dict:
        async def one(path):
            try:
                return await self._api._request("GET", path)
            except Exception as err:  # noqa: BLE001 - per-endpoint tolerance
                _LOGGER.debug("CCU %s unavailable: %s", path, err)
                return None

        results = await asyncio.gather(*(one(p) for p in ENDPOINTS.values()))
        return dict(zip(ENDPOINTS.keys(), results))
