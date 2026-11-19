"""The Masterbuilt grill integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .coordinator import MasterbuiltCoordinator
from .device import MasterbuiltGrill

# The number platform (set temperature / timer) is not loaded: the command
# hasn't been confirmed to work. number.py is kept for when it is.
PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

type MasterbuiltConfigEntry = ConfigEntry[MasterbuiltCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: MasterbuiltConfigEntry) -> bool:
    address: str = entry.data[CONF_ADDRESS]
    grill = MasterbuiltGrill(address, entry.title)
    coordinator = MasterbuiltCoordinator(hass, entry, grill)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MasterbuiltConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_stop()
    return unload_ok
