"""Config flow for Water Meter integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_HOST, CONF_SCAN_INTERVAL, DEFAULT_HOST, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            int, vol.Range(min=1, max=3600)
        ),
    }
)


async def _validate_connection(host: str) -> None:
    """Validate that the water meter is reachable and returns Prometheus metrics."""
    url = f"http://{host}/"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            response.raise_for_status()
            text = await response.text()

    if "water_today_litres" not in text and "water_flowrate_lpm" not in text:
        raise ValueError("Response does not appear to contain water meter metrics")


def _build_schema(current_host: str, current_interval: int) -> vol.Schema:
    """Build a schema pre-filled with current values."""
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=current_host): str,
            vol.Optional(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                int, vol.Range(min=1, max=3600)
            ),
        }
    )


class WaterMeterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Water Meter."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip().rstrip("/")

            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            try:
                await _validate_connection(host)
            except (aiohttp.ClientResponseError, aiohttp.ClientConnectionError, TimeoutError):
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "invalid_response"
            except Exception:
                _LOGGER.exception("Unexpected error connecting to water meter")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Water Meter ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration via the ··· menu on the integration card."""
        errors: dict[str, str] = {}
        current = self._get_reconfigure_entry()

        if user_input is not None:
            host = user_input[CONF_HOST].strip().rstrip("/")

            if host != current.data.get(CONF_HOST):
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()

            try:
                await _validate_connection(host)
            except (aiohttp.ClientResponseError, aiohttp.ClientConnectionError, TimeoutError):
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "invalid_response"
            except Exception:
                _LOGGER.exception("Unexpected error connecting to water meter")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    current,
                    title=f"Water Meter ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_schema(
                current.data.get(CONF_HOST, DEFAULT_HOST),
                current.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "WaterMeterOptionsFlow":
        """Return the options flow handler."""
        return WaterMeterOptionsFlow(config_entry)


class WaterMeterOptionsFlow(config_entries.OptionsFlow):
    """Handle the Configure button on the integration card."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialise options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip().rstrip("/")

            try:
                await _validate_connection(host)
            except (aiohttp.ClientResponseError, aiohttp.ClientConnectionError, TimeoutError):
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "invalid_response"
            except Exception:
                _LOGGER.exception("Unexpected error connecting to water meter")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=f"Water Meter ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                    },
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(
                self.config_entry.data.get(CONF_HOST, DEFAULT_HOST),
                self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ),
            errors=errors,
        )
