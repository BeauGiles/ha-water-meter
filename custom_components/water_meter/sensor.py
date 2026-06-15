"""Sensor platform for Water Meter integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_HOST, DOMAIN
from .coordinator import WaterMeterCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class WaterMeterSensorDescription(SensorEntityDescription):
    """Describe a Water Meter sensor."""

    data_key: str
    legacy_entity_id: str | None = None


SENSOR_DESCRIPTIONS: tuple[WaterMeterSensorDescription, ...] = (
    WaterMeterSensorDescription(
        key="water_flowrate_lpm",
        data_key="water_flowrate_lpm",
        name="Water Flow Rate",
        native_unit_of_measurement="L/min",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water",
        legacy_entity_id="sensor.water_flow_rate",
    ),
)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Water Meter",
        manufacturer="Custom",
        model="REST Water Meter",
        configuration_url=f"http://{entry.data[CONF_HOST]}/",
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Water Meter sensors from a config entry."""
    coordinator: WaterMeterCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        WaterMeterSensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    ]
    entities.append(WaterMeterTodaySensor(coordinator, entry))
    entities.append(WaterMeterLifetimeSensor(coordinator, entry))

    async_add_entities(entities)


class WaterMeterSensor(CoordinatorEntity[WaterMeterCoordinator], SensorEntity):
    """Simple pass-through sensor (used for flow rate)."""

    entity_description: WaterMeterSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WaterMeterCoordinator,
        entry: ConfigEntry,
        description: WaterMeterSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(entry)
        if description.legacy_entity_id:
            self.entity_id = description.legacy_entity_id

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.data_key)


class _AccumulatorSensor(
    CoordinatorEntity[WaterMeterCoordinator], RestoreEntity, SensorEntity
):
    """Base class for sensors that accumulate a running total and survive reloads."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _STORAGE_KEY: str = "total"

    def __init__(self, coordinator: WaterMeterCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_device_info = _device_info(entry)
        self._total: float = 0.0
        self._last_device_value: float | None = None
        self._restored: bool = False

    async def async_added_to_hass(self) -> None:
        """Restore persisted totals before allowing coordinator updates."""
        await super().async_added_to_hass()
        await self._restore()
        self._restored = True
        if self.coordinator.data is not None:
            self._process_update()
            self.async_write_ha_state()

    async def _restore(self) -> None:
        """Restore total and last device value from extra data, falling back to state."""
        if (extra := await self.async_get_last_extra_data()) is not None:
            data = extra.as_dict()
            if (val := data.get(self._STORAGE_KEY)) is not None:
                try:
                    self._total = float(val)
                    _LOGGER.debug(
                        "%s: restored total %.2f L from extra data",
                        self.entity_id, self._total,
                    )
                except (ValueError, TypeError):
                    pass
            if (ldv := data.get("last_device_value")) is not None:
                try:
                    self._last_device_value = float(ldv)
                except (ValueError, TypeError):
                    pass
            return

        # Fallback for first boot after upgrade
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._total = float(last_state.state)
                _LOGGER.debug(
                    "%s: restored total %.2f L from last state",
                    self.entity_id, self._total,
                )
            except (ValueError, TypeError):
                pass

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            self._STORAGE_KEY: self._total,
            "last_device_value": self._last_device_value,
        }

    def _handle_coordinator_update(self) -> None:
        if not self._restored or self.coordinator.data is None:
            return
        self._process_update()
        self.async_write_ha_state()

    def _process_update(self) -> None:
        raise NotImplementedError

    @property
    def native_value(self) -> float:
        return round(self._total, 2)


class WaterMeterTodaySensor(_AccumulatorSensor):
    """Water usage today — resets at midnight, survives device reboots at any time.

    Only a date change (in HA's configured timezone) triggers a midnight reset.
    Any drop in the device value on the same calendar day — including a drop to
    zero — is always treated as a device reboot and accumulated on top of the
    existing total.
    """

    _attr_name = "Water Usage Today"
    _attr_icon = "mdi:faucet"
    _STORAGE_KEY = "today_total"
    entity_id = "sensor.water_usage_today"

    def __init__(self, coordinator: WaterMeterCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_water_today_litres"
        self._last_date: date | None = None

    async def _restore(self) -> None:
        """Restore today total, last device value, and last date."""
        await super()._restore()

        last_date: date | None = None

        # Primary: get last_date from extra data
        if (extra := await self.async_get_last_extra_data()) is not None:
            if (ds := extra.as_dict().get("last_date")):
                try:
                    last_date = date.fromisoformat(ds)
                except ValueError:
                    pass

        # Fallback: derive last_date from last_changed timestamp on the state
        if last_date is None:
            if (last_state := await self.async_get_last_state()) is not None:
                if last_state.last_changed is not None:
                    last_date = dt_util.as_local(last_state.last_changed).date()
                    _LOGGER.debug(
                        "%s: derived last_date %s from last_changed timestamp",
                        self.entity_id, last_date,
                    )

        self._last_date = last_date
        _LOGGER.debug("%s: restored last_date=%s", self.entity_id, self._last_date)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        attrs["last_date"] = self._last_date.isoformat() if self._last_date else None
        return attrs

    def _process_update(self) -> None:
        current: float | None = self.coordinator.data.get("water_today_litres")
        if current is None:
            return

        today = dt_util.now().date()

        if self._last_device_value is None or self._last_date is None:
            # First ever reading — trust the device value
            _LOGGER.debug(
                "%s: first reading, seeding today total to %.2f L",
                self.entity_id, current,
            )
            self._total = current

        elif today != self._last_date:
            # Date changed in HA's timezone — genuine midnight reset
            _LOGGER.debug(
                "%s: midnight reset (%s -> %s), starting fresh at %.2f L",
                self.entity_id, self._last_date, today, current,
            )
            self._total = current

        else:
            # Same calendar day — date is the ONLY reset signal.
            # Any drop (including to zero) means the device rebooted; accumulate.
            delta = current - self._last_device_value
            if delta >= 0:
                self._total += delta
            else:
                _LOGGER.debug(
                    "%s: device reboot on same day (%.2f -> %.2f), "
                    "adding %.2f L to accumulated %.2f L",
                    self.entity_id, self._last_device_value,
                    current, current, self._total,
                )
                self._total += current

        self._last_device_value = current
        self._last_date = today


class WaterMeterLifetimeSensor(_AccumulatorSensor):
    """Cumulative lifetime total — never resets. Use this for the Energy Dashboard."""

    _attr_name = "Water Lifetime Total"
    _attr_icon = "mdi:water-plus"
    _STORAGE_KEY = "lifetime_total"
    entity_id = "sensor.water_lifetime_total"

    def __init__(self, coordinator: WaterMeterCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_water_lifetime_total"

    def _process_update(self) -> None:
        current: float | None = self.coordinator.data.get("water_today_litres")
        if current is None:
            return

        if self._last_device_value is None:
            # First reading — anchor only, don't add to total
            pass
        else:
            delta = current - self._last_device_value
            if delta > 0:
                self._total += delta
            elif delta < 0:
                _LOGGER.debug(
                    "%s: counter reset (%.2f -> %.2f), adding %.2f L",
                    self.entity_id, self._last_device_value, current, current,
                )
                self._total += current

        self._last_device_value = current
