"""Binary sensors for Masterbuilt grills."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MasterbuiltConfigEntry
from .device import MasterbuiltGrill
from .entity import MasterbuiltEntity
from .protocol import ERRORS


@dataclass(frozen=True, kw_only=True)
class MasterbuiltBinarySensorEntityDescription(BinarySensorEntityDescription):
    is_on_fn: Callable[[MasterbuiltGrill], bool | None]
    always_available: bool = False


def _status(fn: Callable) -> Callable[[MasterbuiltGrill], bool | None]:
    return lambda grill: fn(grill.status) if grill.status is not None else None


def _error(number: int) -> Callable[[MasterbuiltGrill], bool | None]:
    return _status(lambda s: s.has_error(number))


BINARY_SENSORS: tuple[MasterbuiltBinarySensorEntityDescription, ...] = (
    MasterbuiltBinarySensorEntityDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        is_on_fn=lambda grill: grill.connected,
    ),
    MasterbuiltBinarySensorEntityDescription(
        key="heating",
        translation_key="heating",
        device_class=BinarySensorDeviceClass.HEAT,
        is_on_fn=_status(lambda s: s.heating),
    ),
    MasterbuiltBinarySensorEntityDescription(
        key="timer_active",
        translation_key="timer_active",
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on_fn=_status(lambda s: s.timer_active),
    ),
    MasterbuiltBinarySensorEntityDescription(
        key="problem",
        translation_key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=_status(lambda s: bool(s.active_errors)),
    ),
) + tuple(
    MasterbuiltBinarySensorEntityDescription(
        key=f"error_{number}",
        translation_key=f"error_{number}",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_error(number),
    )
    for number, _ in ERRORS.values()
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MasterbuiltConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(MasterbuiltBinarySensor(entry.runtime_data, d) for d in BINARY_SENSORS)


class MasterbuiltBinarySensor(MasterbuiltEntity, BinarySensorEntity):
    entity_description: MasterbuiltBinarySensorEntityDescription

    @property
    def available(self) -> bool:
        return self.entity_description.always_available or super().available

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on_fn(self.grill)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "problem" or self.grill.status is None:
            return None
        errors = self.grill.status.active_errors
        descriptions = {num: desc for num, desc in ERRORS.values()}
        return {
            "error_codes": [f"Err {n}" for n in errors],
            "errors": [descriptions[n] for n in errors],
        }
