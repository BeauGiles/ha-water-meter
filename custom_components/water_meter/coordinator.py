"""Data coordinator for Water Meter integration."""
from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_HOST, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class WaterMeterCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch water meter data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the coordinator."""
        self.host = entry.data[CONF_HOST]
        self.url = f"http://{self.host}/"
        scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    @staticmethod
    def _parse_prometheus(text: str) -> dict[str, float | None]:
        """Parse Prometheus exposition format into a dict of metric name -> float value.

        Lines beginning with # are comments/metadata and are skipped.
        Data lines are: <metric_name> <value>
        """
        result: dict[str, float | None] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                name, raw_value = parts[0], parts[1]
                try:
                    result[name] = float(raw_value)
                except ValueError:
                    _LOGGER.warning(
                        "Could not parse value for metric '%s': %s", name, raw_value
                    )
                    result[name] = None
        return result

    async def _async_update_data(self) -> dict:
        """Fetch and parse Prometheus metrics from the water meter."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.url,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    response.raise_for_status()
                    text = await response.text()

            metrics = self._parse_prometheus(text)

            return {
                "water_today_litres": metrics.get("water_today_litres"),
                "water_flowrate_lpm": metrics.get("water_flowrate_lpm"),
            }
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(
                f"Error communicating with water meter at {self.url}: {err}"
            ) from err
        except Exception as err:
            raise UpdateFailed(
                f"Unexpected error fetching water meter data: {err}"
            ) from err
