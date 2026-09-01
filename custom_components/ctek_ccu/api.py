"""Minimal async client for the CTEK CCU local REST API.

Auth is a session cookie from ``POST /api/status/login`` with a JSON
``{"username": ..., "password": ...}`` body.

Concurrent sessions are allowed: two logins held at once were both accepted and
both usable (verified 2026-09-01), so an open session does not lock anyone out.
The client still logs out after each burst of work, both to keep the CCU tidy
and because it has a small connection budget.

What the CCU *does* do is answer **HTTP 404 for a request shape it does not
recognise** — ``GET /api/status/logout`` returns 404 where ``POST`` returns 200,
and the login endpoint intermittently answers 404 under load (typically in the
first seconds after a Home Assistant restart, when the poll and the first write
arrive together). A 404 is therefore treated as transient and retried briefly
before the client backs off.

``POST /api/status/logout`` must be sent **without a JSON body**: with ``{}`` the
CCU processes the logout but resets the connection, which surfaces as a spurious
ConnectionResetError.

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
                 username: str, password: str, cookie_store=None) -> None:
        self._session = session
        self._base = f"https://{host}"
        self._username = username
        self._password = password
        # The CCU is a small embedded server, so logins and the requests
        # themselves are serialised, and a login is only redone once per burst
        # of 401s.
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
        self._backoff = 30.0
        # Optional durable store for the session cookie, as
        # ``(async load() -> str | None, async save(str | None))``. Home
        # Assistant can be restarted or the integration reloaded while a session
        # is open — the logout in :meth:`session` then never runs, the CCU keeps
        # the slot, and every later login is refused (HTTP 404/500) until the
        # box is power-cycled. Persisting the cookie lets the next run close
        # that orphan instead.
        self._cookie_store = cookie_store

    async def _saved_cookie(self) -> str | None:
        if not self._cookie_store:
            return None
        with contextlib.suppress(Exception):
            return await self._cookie_store[0]()
        return None

    async def _persist_cookie(self, cookie: str | None) -> None:
        if not self._cookie_store:
            return
        with contextlib.suppress(Exception):
            await self._cookie_store[1](cookie)

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
            await self._login_with_retries()
        except Exception:
            self._cookie = None   # a failed login leaves nothing usable
            stale = await self._saved_cookie()
            if stale:
                # One session slot, and it is still held by a previous run of
                # this integration. Close it with the cookie we kept, then try
                # once more before giving up and backing off.
                _LOGGER.warning(
                    "CCU refused the login; closing the session left open by a "
                    "previous run and retrying"
                )
                self._cookie = stale
                await self._logout()
                with contextlib.suppress(Exception):
                    await self._login_request()
            if self._cookie:
                self._backoff = 30.0
                self._cooldown_until = 0.0
                await self._persist_cookie(self._cookie)
                return
            self._cooldown_until = time.monotonic() + self._backoff
            self._backoff = min(self._backoff * 2, 900.0)
            raise
        self._backoff = 30.0
        self._cooldown_until = 0.0
        await self._persist_cookie(self._cookie)

    async def _login_with_retries(self, attempts: int = 3) -> None:
        """Log in, treating the CCU's transient 404s as worth another try.

        The box answers 404 for requests it cannot place, including a login
        that arrives while it is busy. Those clear within seconds, so a couple
        of short retries beat dropping into a minutes-long backoff.
        """
        for attempt in range(attempts):
            try:
                await self._login_request()
                return
            except Exception:
                if attempt == attempts - 1:
                    raise
                await asyncio.sleep(1.5 * (attempt + 1))

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
                f"{self._base}/api/status/logout",
                headers=headers, ssl=False
            ):
                pass
        self._cookie = None
        await self._persist_cookie(None)

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
