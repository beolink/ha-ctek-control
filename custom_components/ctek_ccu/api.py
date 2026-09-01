"""Minimal async client for the CTEK CCU local REST API.

Auth is a session cookie obtained from ``POST /api/status/login`` with a JSON
``{"username": ..., "password": ...}`` body; every other call rides that cookie
and we transparently re-login on a 401. The CCU serves HTTPS with a self-signed
certificate, so verification is disabled for this local host by design.
"""

from __future__ import annotations

import logging

import aiohttp

from .const import PROFILE_KIND, PROFILE_PURPOSE, RATE_UNIT

_LOGGER = logging.getLogger(__name__)


class CcuAuthError(Exception):
    """Raised when the CCU rejects the configured credentials."""


class CcuApi:
    def __init__(self, session: aiohttp.ClientSession, host: str,
                 username: str, password: str) -> None:
        self._session = session
        self._base = f"https://{host}"
        self._username = username
        self._password = password

    async def _login(self) -> None:
        async with self._session.post(
            f"{self._base}/api/status/login",
            json={"username": self._username, "password": self._password},
            ssl=False,
        ) as resp:
            if resp.status != 200:
                raise CcuAuthError(f"CCU login failed: HTTP {resp.status}")

    async def _request(self, method: str, path: str, json_body=None, _retry: bool = True):
        async with self._session.request(
            method, f"{self._base}{path}", json=json_body, ssl=False
        ) as resp:
            if resp.status == 401 and _retry:
                await self._login()
                return await self._request(method, path, json_body, _retry=False)
            if resp.status == 401:
                raise CcuAuthError("CCU rejected the session after re-login")
            resp.raise_for_status()
            if resp.content_type == "application/json":
                return await resp.json()
            return await resp.text()

    async def async_login(self) -> None:
        await self._login()

    async def async_is_alive(self) -> bool:
        try:
            await self._request("GET", "/api/status/isalive")
            return True
        except Exception:  # noqa: BLE001 - availability probe
            return False

    async def async_get_profiles(self):
        return await self._request("GET", "/api/config/getChargingProfiles")

    async def async_get_outlet_states(self):
        return await self._request("GET", "/api/status/getoutletstates")

    @staticmethod
    def build_profiles(limit_a: int, connectors: int, phases: int = 3) -> list[dict]:
        """One TxDefaultProfile per connector at ``limit_a`` amps."""
        return [
            {
                "chargingProfilePurpose": PROFILE_PURPOSE,
                "chargingSchedule": {
                    "chargingRateUnit": RATE_UNIT,
                    "chargingSchedulePeriod": [
                        {"limit": int(limit_a), "numberPhases": phases, "startPeriod": 0}
                    ],
                },
                "chargingProfileId": c,
                "chargingProfileKind": PROFILE_KIND,
                "stackLevel": c - 1,
                "connectorId": c,
            }
            for c in range(1, connectors + 1)
        ]

    async def async_set_limit(self, limit_a: int, connectors: int) -> None:
        await self._request(
            "POST", "/api/config/setChargingProfiles",
            self.build_profiles(limit_a, connectors),
        )
        _LOGGER.debug("CCU charging limit set to %s A on %s connector(s)", limit_a, connectors)
