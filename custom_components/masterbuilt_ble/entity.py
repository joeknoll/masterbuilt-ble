"""Base entity for Masterbuilt grills."""

from __future__ import annotations

from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .const import DOMAIN, MANUFACTURER
from .coordinator import MasterbuiltCoordinator
from .device import MasterbuiltGrill


class MasterbuiltEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: MasterbuiltCoordinator, description: EntityDescription) -> None:
        self.coordinator = coordinator
        self.entity_description = description
        grill = coordinator.grill
        self._attr_unique_id = f"{grill.address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, grill.address)},
            connections={(CONNECTION_BLUETOOTH, grill.address)},
            manufacturer=MANUFACTURER,
            name=coordinator.entry.title,
        )

    @property
    def grill(self) -> MasterbuiltGrill:
        return self.coordinator.grill

    @property
    def available(self) -> bool:
        return self.grill.connected and self.grill.status is not None

    @property
    def grill_temperature_unit(self) -> str:
        """The unit the grill reports in. Defaults to °F until the first status packet."""
        status = self.grill.status
        if status is not None and not status.fahrenheit:
            return UnitOfTemperature.CELSIUS
        return UnitOfTemperature.FAHRENHEIT

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.grill.add_listener(self.async_write_ha_state))
