"""EXPERIMENTAL controls for target temperature and timer.

These send the A4 control command (see protocol.py), which has not yet been
confirmed on a grill. Both entities are disabled by default, and the number
platform is not currently loaded (see PLATFORMS in __init__.py).
"""

from __future__ import annotations

from collections.abc import Awaitable

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
    async def _send(self, command: Awaitable[None]) -> None:
        try:
            await command
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
        await self._send(self.grill.set_target_temp(round(value)))


class MasterbuiltTimer(_MasterbuiltNumber):
    @property
    def native_value(self) -> float | None:
        status = self.grill.status
        return status.set_minutes if status else None

    async def async_set_native_value(self, value: float) -> None:
        await self._send(self.grill.set_timer(round(value)))
