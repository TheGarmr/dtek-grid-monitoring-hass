"""Config flow for DTEK Grid Monitoring."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.config_entries import ConfigFlow
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.config_entries import OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import EntitySelector
from homeassistant.helpers.selector import EntitySelectorConfig
from homeassistant.helpers.selector import NumberSelector
from homeassistant.helpers.selector import NumberSelectorConfig
from homeassistant.helpers.selector import NumberSelectorMode
from homeassistant.helpers.selector import TextSelector

from .const import CONF_BASE_URL
from .const import CONF_CITY
from .const import CONF_HOUSES
from .const import CONF_INITIAL_INTERVAL
from .const import CONF_INTERVAL
from .const import CONF_NAME
from .const import CONF_POWER_OFF_STATE
from .const import CONF_SOURCE_ENTITY
from .const import CONF_STREET
from .const import DEFAULT_BASE_URL
from .const import DEFAULT_INITIAL_INTERVAL
from .const import DEFAULT_INTERVAL
from .const import DEFAULT_POWER_OFF_STATE
from .const import DEFAULT_SOURCE_ENTITY
from .const import DOMAIN
from .dtek import DtekClient
from .dtek import DtekError

_LOGGER = logging.getLogger(__name__)


def _parse_houses(raw: str) -> list[str]:
    """Split a comma-separated house string into a clean list."""
    return [h.strip() for h in raw.split(",") if h.strip()]


def _user_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the user-step schema pre-filled with defaults."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
            vol.Required(
                CONF_BASE_URL, default=defaults.get(CONF_BASE_URL, DEFAULT_BASE_URL)
            ): str,
            vol.Required(CONF_CITY, default=defaults.get(CONF_CITY, "")): str,
            vol.Required(CONF_STREET, default=defaults.get(CONF_STREET, "")): str,
            vol.Required(
                CONF_HOUSES, default=defaults.get(CONF_HOUSES, "")
            ): TextSelector(),
            vol.Required(
                CONF_SOURCE_ENTITY,
                default=defaults.get(CONF_SOURCE_ENTITY, DEFAULT_SOURCE_ENTITY),
            ): EntitySelector(
                EntitySelectorConfig(
                    domain=["binary_sensor", "sensor", "input_boolean"]
                )
            ),
            vol.Required(
                CONF_POWER_OFF_STATE,
                default=defaults.get(CONF_POWER_OFF_STATE, DEFAULT_POWER_OFF_STATE),
            ): str,
        }
    )


class DtekConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DTEK Grid Monitoring."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial configuration step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            houses = _parse_houses(user_input[CONF_HOUSES])
            if not houses:
                errors[CONF_HOUSES] = "no_houses"
            else:
                validation_error = await self._async_validate_address(
                    user_input[CONF_BASE_URL],
                    user_input[CONF_CITY],
                    user_input[CONF_STREET],
                )
                if validation_error:
                    errors["base"] = validation_error

            if not errors:
                await self.async_set_unique_id(
                    f"{user_input[CONF_CITY]}|{user_input[CONF_STREET]}|"
                    f"{','.join(houses)}|{user_input[CONF_SOURCE_ENTITY]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_BASE_URL: user_input[CONF_BASE_URL].strip(),
                        CONF_CITY: user_input[CONF_CITY].strip(),
                        CONF_STREET: user_input[CONF_STREET].strip(),
                        CONF_HOUSES: houses,
                        CONF_SOURCE_ENTITY: user_input[CONF_SOURCE_ENTITY],
                        CONF_POWER_OFF_STATE: user_input[CONF_POWER_OFF_STATE].strip(),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input or {}),
            errors=errors,
        )

    async def _async_validate_address(
        self, base_url: str, city: str, street: str
    ) -> str | None:
        """Return an error key if DTEK cannot be reached for the address."""
        session = async_get_clientsession(self.hass)
        client = DtekClient(session, base_url.strip())
        try:
            await client.async_get_info(city.strip(), street.strip())
        except DtekError as err:
            _LOGGER.debug("Address validation failed: %s", err)
            return "cannot_connect"
        return None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return DtekOptionsFlow()


class DtekOptionsFlow(OptionsFlow):
    """Handle DTEK options (polling intervals)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the polling interval options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_INITIAL_INTERVAL: int(user_input[CONF_INITIAL_INTERVAL]),
                    CONF_INTERVAL: int(user_input[CONF_INTERVAL]),
                }
            )

        options = self.config_entry.options
        interval_selector = NumberSelector(
            NumberSelectorConfig(min=1, max=120, step=1, mode=NumberSelectorMode.BOX)
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_INITIAL_INTERVAL,
                    default=options.get(
                        CONF_INITIAL_INTERVAL, DEFAULT_INITIAL_INTERVAL
                    ),
                ): interval_selector,
                vol.Required(
                    CONF_INTERVAL,
                    default=options.get(CONF_INTERVAL, DEFAULT_INTERVAL),
                ): interval_selector,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
