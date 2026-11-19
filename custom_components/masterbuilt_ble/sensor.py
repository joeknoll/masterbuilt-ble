"""Sensors for Masterbuilt grills."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import MasterbuiltConfigEntry
from .const import NUM_PROBES, NUM_PROBES_ENABLED_DEFAULT
from .device import MasterbuiltGrill
from .entity import MasterbuiltEntity


@dataclass(frozen=True, kw_only=True)
class MasterbuiltSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[MasterbuiltGrill], StateType]
    is_temperature: bool = False
    needs_probes: bool = False


def _status(fn: Callable) -> Callable[[MasterbuiltGrill], StateType]:
    return lambda grill: fn(grill.status) if grill.status is not None else None


def _probe(number: int) -> Callable[[MasterbuiltGrill], StateType]:
    return lambda grill: grill.probes.temperature(number) if grill.probes is not None else None


SENSORS: tuple[MasterbuiltSensorEntityDescription, ...] = (
    MasterbuiltSensorEntityDescription(
        key="cavity_temperature",
        translation_key="cavity_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        is_temperature=True,
        value_fn=_status(lambda s: s.cavity_temp),
    ),
    MasterbuiltSensorEntityDescription(
        key="target_temperature",
        translation_key="target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        is_temperature=True,
        value_fn=_status(lambda s: s.target_temp),
    ),
    MasterbuiltSensorEntityDescription(
        key="timer_remaining",
        translation_key="timer_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=_status(lambda s: s.remaining_minutes),
    ),
    MasterbuiltSensorEntityDescription(
        key="timer_set",
        translation_key="timer_set",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=_status(lambda s: s.set_minutes),
    ),
    MasterbuiltSensorEntityDescription(
        key="max_temperature",
        translation_key="max_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_temperature=True,
        value_fn=_status(lambda s: s.max_temp),
    ),
    MasterbuiltSensorEntityDescription(
        key="min_temperature",
        translation_key="min_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_temperature=True,
        value_fn=_status(lambda s: s.min_temp),
    ),
    MasterbuiltSensorEntityDescription(
        key="fan_intensity",
        translation_key="fan_intensity",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fan",
        value_fn=_status(lambda s: s.fan_intensity),
    ),
    # Raw values to help with further reverse engineering.
    MasterbuiltSensorEntityDescription(
        key="raw_status",
        translation_key="raw_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_status(lambda s: s.raw.hex(" ").upper()),
    ),
    MasterbuiltSensorEntityDescription(
        key="raw_probes",
        translation_key="raw_probes",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        needs_probes=True,
        value_fn=lambda g: g.probes.raw.hex(" ").upper() if g.probes else None,
    ),
) + tuple(
    MasterbuiltSensorEntityDescription(
        key=f"probe_{n}",
        translation_key="probe_temperature",
        translation_placeholders={"probe": str(n)},
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=n <= NUM_PROBES_ENABLED_DEFAULT,
        is_temperature=True,
        needs_probes=True,
        value_fn=_probe(n),
    )
    for n in range(1, NUM_PROBES + 1)
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MasterbuiltConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(MasterbuiltSensor(entry.runtime_data, d) for d in SENSORS)


class MasterbuiltSensor(MasterbuiltEntity, SensorEntity):
    entity_description: MasterbuiltSensorEntityDescription

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return not self.entity_description.needs_probes or self.grill.probes is not None

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.grill)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.is_temperature:
            return self.grill_temperature_unit
        return self.entity_description.native_unit_of_measurement
