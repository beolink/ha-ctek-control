"""Minimal async client for the CTEK CCU local REST API.

Auth is a session cookie from ``POST /api/status/login`` with a JSON
``{"username": ..., "password": ...}`` body.

**The CCU allows only one session at a time.** A second login while a session is
open — including the installer's own browser session — is answered with HTTP
500, and a session that is never closed keeps the slot indefinitely (it does not
appear to time out quickly). So this client borrows the slot for as short a time
as possible: :meth:`session` logs in, runs the work and always logs out again,
leaving the web UI usable between polls.

The CCU serves HTTPS with a self-signed certificate, so verification is disabled
for this local host by design.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

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
        # The CCU is a small embedded server: concurrent logins make it answer
        # HTTP 500, so both the login and the requests themselves are
        # serialised, and a login is only redone once per burst of 401s.
        self._login_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()
        # The CCU has exactly one session, so a poll and a write must never
        # overlap: the one that finishes first logs out and clears the cookie,
        # leaving the other unauthenticated mid-flight.
        self._session_lock = asyncio.Lock()
        self._session_generation = 0
        # The CCU sets its cookie for a bare IP host, which aiohttp's jar
        # handles inconsistently — so we capture the value at login and send it
        # back as an explicit header instead of relying on the jar at all.
        self._cookie: str | None = None
        # Back off after a failed login. A small embedded controller can run out
        # of session slots or rate-limit, and retrying every poll would keep it
        # pinned there — so failures cool down instead of hammering.
        self._cooldown_until = 0.0
        self._backoff = 60.0

    async def _login(self, seen_generation: int | None = None) -> None:
        async with self._login_lock:
            # Another coroutine may have refreshed the session while we waited.
            if seen_generation is not None and seen_generation != self._session_generation:
                return
            await self._login_locked()
            self._session_generation += 1

    async def _login_locked(self) -> None:
        now = time.monotonic()
        if now < self._cooldown_until:
            raise CcuAuthError(
                f"login backing off for {int(self._cooldown_until - now)}s "
                "after a previous failure"
            )
        try:
            await self._login_request()
        except Exception:
            self._cooldown_until = time.monotonic() + self._backoff
            self._backoff = min(self._backoff * 2, 900.0)
            raise
        self._backoff = 60.0
        self._cooldown_until = 0.0

    async def _login_request(self) -> None:
        async with self._session.post(
            f"{self._base}/api/status/login",
            json={"username": self._username, "password": self._password},
            ssl=False,
        ) as resp:
            if resp.status != 200:
                raise CcuAuthError(f"CCU login failed: HTTP {resp.status}")
            self._cookie = None
            for raw in resp.headers.getall("Set-Cookie", []):
                # e.g. "session=abc123; Path=/" -> keep just "session=abc123"
                self._cookie = raw.split(";", 1)[0].strip()
                break
            if not self._cookie:
                raise CcuAuthError("CCU login returned no session cookie")

    async def _request(self, method: str, path: str, json_body=None):
        """Issue one call on an already-open session (see :meth:`session`)."""
        async with self._request_lock:  # one call at a time; the CCU is small
            headers = {"Cookie": self._cookie} if self._cookie else {}
            async with self._session.request(
                method, f"{self._base}{path}", json=json_body,
                headers=headers, ssl=False
            ) as resp:
                if resp.status == 401:
                    # Diagnostic: which headers actually went out, and did our
                    # Cookie survive? Values are never logged, only shapes.
                    sent = dict(resp.request_info.headers)
                    cookie_sent = sent.get("Cookie")
                    _LOGGER.debug(
                        "CCU 401 on %s | cookie_header=%s len=%s | our_cookie=%s len=%s | "
                        "other_headers=%s | body=%s",
                        path,
                        "yes" if cookie_sent else "NO",
                        len(cookie_sent) if cookie_sent else 0,
                        "yes" if self._cookie else "NO",
                        len(self._cookie) if self._cookie else 0,
                        sorted(k for k in sent if k != "Cookie"),
                        (await resp.text())[:120],
                    )
                    raise CcuAuthError(f"CCU session not accepted for {path}")
                resp.raise_for_status()
                if resp.content_type == "application/json":
                    return await resp.json()
                return await resp.text()

    async def _logout(self) -> None:
        with contextlib.suppress(Exception):
            headers = {"Cookie": self._cookie} if self._cookie else {}
            async with self._session.post(
                f"{self._base}/api/status/logout", json={},
                headers=headers, ssl=False
            ):
                pass
        self._cookie = None

    @contextlib.asynccontextmanager
    async def session(self):
        """Hold the CCU's single session for the duration of the block only.

        Serialised: only one session context runs at a time, so a poll can't
        log out from under a concurrent write. Always logs out afterwards —
        leaving it open would lock everyone else, including the owner's
        browser, out of the charger.
        """
        async with self._session_lock:
            await self._login()
            try:
                yield self
            finally:
                await self._logout()

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
