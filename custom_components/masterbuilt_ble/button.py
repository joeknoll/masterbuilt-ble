"""Power-off button.

Sends the A4 control command with the power bit clear (see protocol.py).
Tested on a grill: the next status packet reports the power bit clear. The
entity is still disabled by default. There is deliberately no
power-on button: switching a charcoal grill on remotely is untested and
lights it with nobody there.
"""

from __future__ import annotations

from bleak.exc import BleakError

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MasterbuiltConfigEntry
from .entity import MasterbuiltEntity

POWER_OFF = ButtonEntityDescription(
    key="power_off",
    translation_key="power_off",
    # Fallback for when Home Assistant's cached translations predate this
    # entity (they load only at startup); otherwise the entity shows only the
    # device name.
    name="Power off",
    icon="mdi:power",
    entity_registry_enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MasterbuiltConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([MasterbuiltPowerOffButton(entry.runtime_data, POWER_OFF)])


class MasterbuiltPowerOffButton(MasterbuiltEntity, ButtonEntity):
    @property
    def available(self) -> bool:
        # Offered only while the grill reports that it is on: status byte 2,
        # bit 0 (confirmed by a capture after powering off), and no B2
        # power-off packet since the last status.
        return (
            super().available
            and self.grill.status.powered_on
            and not self.grill.powered_off
        )

    async def async_press(self) -> None:
        try:
            await self.grill.power_off()
        except (BleakError, TimeoutError) as err:
            raise HomeAssistantError(f"Failed to turn the grill off: {err}") from err
