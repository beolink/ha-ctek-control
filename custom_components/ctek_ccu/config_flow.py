"""Config flow: host + credentials are entered by the user and stored by HA."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
import aiohttp
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import CcuApi, CcuAuthError
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
    DOMAIN,
)
from .stats import OPTION_KEY as CONF_SEND_STATISTICS, async_forget_install


def _num(lo: int, hi: int, unit: str) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=lo, max=hi, step=1, mode=NumberSelectorMode.BOX,
                             unit_of_measurement=unit)
    )


def _schema(cur: dict) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_HOST, default=cur.get(CONF_HOST, "")): str,
        vol.Required(CONF_USERNAME, default=cur.get(CONF_USERNAME, "")): str,
        vol.Required(CONF_PASSWORD, default=""): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_PREFIX, default=cur.get(CONF_PREFIX, DEFAULT_PREFIX)): str,
        vol.Required(CONF_CONNECTORS,
                     default=cur.get(CONF_CONNECTORS, DEFAULT_CONNECTORS)): _num(1, 4, ""),
        vol.Required(CONF_MAX_CURRENT,
                     default=cur.get(CONF_MAX_CURRENT, DEFAULT_MAX_CURRENT)): _num(6, 32, "A"),
        vol.Optional(CONF_SEND_STATISTICS,
                     default=cur.get(CONF_SEND_STATISTICS, True)): bool,
    })


async def _validate(hass, user_input: dict) -> dict[str, str]:
    """Verify the credentials against the CCU before creating the entry."""
    session = async_create_clientsession(
        hass, verify_ssl=False, cookie_jar=aiohttp.DummyCookieJar()
    )
    api = CcuApi(session, user_input[CONF_HOST],
                 user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
    try:
        await api.async_login()
    except CcuAuthError:
        return {"base": "invalid_auth"}
    except Exception:  # noqa: BLE001
        return {"base": "cannot_connect"}
    return {}


class CtekCcuConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_CONNECTORS] = int(user_input[CONF_CONNECTORS])
            user_input[CONF_MAX_CURRENT] = int(user_input[CONF_MAX_CURRENT])
            errors = await _validate(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(f"{DOMAIN}_{user_input[CONF_HOST]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="CTEK CCU", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema(user_input or {}),
                                    errors=errors)

    @staticmethod
    def async_get_options_flow(entry):
        return CtekCcuOptionsFlow(entry)


class CtekCcuOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        cur = {**self._entry.data, **self._entry.options}
        if user_input is not None:
            user_input[CONF_CONNECTORS] = int(user_input[CONF_CONNECTORS])
            user_input[CONF_MAX_CURRENT] = int(user_input[CONF_MAX_CURRENT])
            errors = await _validate(self.hass, user_input)
            if not errors:
                if cur.get(CONF_SEND_STATISTICS, True) and not user_input.get(
                        CONF_SEND_STATISTICS, True):
                    # Switching it off erases what has already been sent,
                    # rather than merely going quiet.
                    await async_forget_install(self.hass, self._entry, DOMAIN)
                return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(step_id="init", data_schema=_schema(cur), errors=errors)
