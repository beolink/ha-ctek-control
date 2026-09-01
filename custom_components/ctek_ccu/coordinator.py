"""Polls the CCU's read-only endpoints.

The exact response shapes differ between CCU firmware versions, so everything
here is defensive: an endpoint that errors simply yields ``None`` for that key
and its entities go unavailable, rather than breaking the whole update.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import CcuApi
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# The CCU's single session is borrowed for each poll, so polling slowly keeps
# the web UI usable for the owner most of the time.
POLL_SECONDS = 120

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
    "meters": "/api/status/getmodbusinfo",
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


def charging_power_w(meters) -> float | None:
    """Live charging power from the CCU's own Modbus meter.

    Measured at the charger, so it is both local and immediate — unlike the
    car's cloud-reported figure, which lags by minutes.
    """
    if not isinstance(meters, dict):
        return None
    total = None
    for m in meters.get("modbusmeters") or []:
        try:
            p = float(m.get("power"))
        except (TypeError, ValueError):
            continue
        total = p if total is None else total + p
    return total


def active_limit_a(profiles) -> float | None:
    """Lowest limit across the returned charging profiles (what actually binds)."""
    if isinstance(profiles, str):
        # The CCU returns this endpoint as text rather than JSON.
        try:
            profiles = json.loads(profiles)
        except (TypeError, ValueError):
            return None
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
        self.errors: dict[str, str] = {}

    async def _async_update_data(self) -> dict:
        self.errors = {}

        async def one(key, path):
            try:
                return await self._api._request("GET", path)
            except Exception as err:  # noqa: BLE001 - per-endpoint tolerance
                # Recorded (never logged with credentials) so the diagnostics
                # sensor can show why an endpoint is blank.
                self.errors[key] = f"{type(err).__name__}: {err}"
                _LOGGER.debug("CCU %s unavailable: %s", path, err)
                return None

        try:
            # Borrow the CCU's single session for this cycle only.
            async with self._api.session():
                # Sequential on purpose: the CCU is a small embedded server.
                return {key: await one(key, path) for key, path in ENDPOINTS.items()}
        except Exception as err:  # noqa: BLE001 - keep the entities alive
            self.errors["login"] = f"{type(err).__name__}: {err}"
            return {key: None for key in ENDPOINTS}
