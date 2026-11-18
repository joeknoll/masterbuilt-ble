"""EXPERIMENTAL controls for target temperature and timer.

The command format comes from particle-iot/ble-gateway-library and has not
been tested against this packet format. Both entities are disabled by default.
"""

from __future__ import annotations

from bleak.exc import BleakError

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MasterbuiltConfigEntry
from .const import TIMER_MAX_MINUTES, TIMER_MIN_MINUTES
from .entity import MasterbuiltEntity

TARGET_TEMP = NumberEntityDescription(
    key="set_target_temperature",
    translation_key="set_target_temperature",
    device_class=NumberDeviceClass.TEMPERATURE,
    mode=NumberMode.BOX,
    entity_registry_enabled_default=False,
)
TIMER = NumberEntityDescription(
    key="set_timer",
    translation_key="set_timer",
    device_class=NumberDeviceClass.DURATION,
    native_unit_of_measurement=UnitOfTime.MINUTES,
    native_min_value=TIMER_MIN_MINUTES,
    native_max_value=TIMER_MAX_MINUTES,
    native_step=1,
    mode=NumberMode.BOX,
    entity_registry_enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MasterbuiltConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            MasterbuiltTargetTemperature(coordinator, TARGET_TEMP),
            MasterbuiltTimer(coordinator, TIMER),
        ]
    )


class _MasterbuiltNumber(MasterbuiltEntity, NumberEntity):
    async def _send(self, temp: int, minutes: int) -> None:
        try:
            await self.grill.set_temp_and_time(temp, minutes)
        except (BleakError, TimeoutError, ValueError) as err:
            raise HomeAssistantError(f"Failed to send command to grill: {err}") from err


class MasterbuiltTargetTemperature(_MasterbuiltNumber):
    @property
    def native_unit_of_measurement(self) -> str:
        return self.grill_temperature_unit

    @property
    def native_step(self) -> float:
        return 5 if self.grill_temperature_unit == UnitOfTemperature.FAHRENHEIT else 1

    @property
    def native_min_value(self) -> float:
        status = self.grill.status
        return status.min_temp if status else 150

    @property
    def native_max_value(self) -> float:
        status = self.grill.status
        return status.max_temp if status else 700

    @property
    def native_value(self) -> float | None:
        status = self.grill.status
        return status.target_temp if status else None

    async def async_set_native_value(self, value: float) -> None:
        status = self.grill.status
        if status is None:
            raise HomeAssistantError("Grill status not yet known")
        # Keep any running timer by passing the remaining minutes, as the
        # reference implementation does.
        minutes = status.remaining_minutes if status.timer_active else 0
        await self._send(round(value), minutes)


class MasterbuiltTimer(_MasterbuiltNumber):
    @property
    def native_value(self) -> float | None:
        status = self.grill.status
        return status.set_minutes if status else None

    async def async_set_native_value(self, value: float) -> None:
        status = self.grill.status
        if status is None or status.target_temp is None:
            raise HomeAssistantError("Set a target temperature before setting the timer")
        await self._send(status.target_temp, round(value))
