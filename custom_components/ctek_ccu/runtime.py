"""Per-entry runtime for the CTEK CCU driver."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
import aiohttp
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import CcuApi
from .const import (
    CONF_CONNECTORS,
    CONF_HOST,
    CONF_MAX_CURRENT,
    CONF_PASSWORD,
    CONF_PREFIX,
    CONF_USERNAME,
    DEFAULT_CONNECTORS,
    DEFAULT_MAX_CURRENT,
    DEFAULT_PREFIX,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class CtekRuntime:
    hass: HomeAssistant
    entry_id: str
    prefix: str
    connectors: int
    max_current_a: int
    api: CcuApi
    # Safety gate: nothing is written to the charger while this is False.
    control_enabled: bool = False
    charging_allowed: bool = False
    current_a: int = 0
    last_command: int | None = None
    last_error: str | None = None

    @classmethod
    def from_entry(cls, hass: HomeAssistant, entry: ConfigEntry) -> "CtekRuntime":
        data = {**entry.data, **entry.options}
        # DummyCookieJar on purpose: aiohttp's real jar re-serialises cookies
        # through SimpleCookie, which quotes the value (session="abc" instead
        # of session=abc) and the CCU then rejects every call with 401. The API
        # client captures the cookie at login and sends it verbatim instead.
        session = async_create_clientsession(
            hass, verify_ssl=False, cookie_jar=aiohttp.DummyCookieJar()
        )
        api = CcuApi(
            session,
            data[CONF_HOST],
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
        )
        max_a = int(data.get(CONF_MAX_CURRENT, DEFAULT_MAX_CURRENT))
        return cls(
            hass=hass,
            entry_id=entry.entry_id,
            prefix=data.get(CONF_PREFIX, DEFAULT_PREFIX),
            connectors=int(data.get(CONF_CONNECTORS, DEFAULT_CONNECTORS)),
            max_current_a=max_a,
            api=api,
            current_a=max_a,
        )

    def _target_limit(self) -> int:
        """0 A blocks charging; otherwise the requested current, capped by the
        configured maximum so we can only ever restrict, never raise."""
        if not self.charging_allowed:
            return 0
        return max(0, min(int(self.current_a), self.max_current_a))

    async def async_apply(self) -> None:
        """Push the current decision to the charger — the single choke point."""
        if not self.control_enabled:
            _LOGGER.debug("CTEK control disabled — command suppressed")
            return
        limit = self._target_limit()
        if limit == self.last_command:
            return  # don't re-send an unchanged limit
        try:
            async with self.api.session():
                await self.api.async_set_limit(limit, self.connectors)
            self.last_command = limit
            self.last_error = None
        except Exception as err:  # noqa: BLE001 - surfaced via the status sensor
            self.last_error = str(err)
            _LOGGER.warning("CTEK CCU write failed: %s", err)

    async def async_release(self) -> None:
        """Hand control back: allow charging up to the configured maximum."""
        if self.last_command is None:
            return
        try:
            async with self.api.session():
                await self.api.async_set_limit(self.max_current_a, self.connectors)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("CTEK CCU release failed: %s", err)
        self.last_command = None
