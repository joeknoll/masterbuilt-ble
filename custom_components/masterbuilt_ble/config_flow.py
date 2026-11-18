"""Config flow for Masterbuilt grills, including Bluetooth auto-discovery."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN, LOCAL_NAME_PREFIXES, SERVICE_UUID


def is_masterbuilt(info: BluetoothServiceInfoBleak) -> bool:
    if SERVICE_UUID in (uuid.lower() for uuid in info.service_uuids):
        return True
    return bool(info.name) and info.name.startswith(LOCAL_NAME_PREFIXES)


def device_title(info: BluetoothServiceInfoBleak) -> str:
    name = (info.name or "").strip()
    # Some stacks report the MAC address as the name when there is none.
    if name and name.replace("-", ":").upper() != info.address.upper():
        # Grills usually advertise "Masterbuilt ..." already; don't double it.
        if name.lower().startswith("masterbuilt"):
            return name
        return f"Masterbuilt {name}"
    return f"Masterbuilt {info.address[-5:].replace(':', '')}"


class MasterbuiltConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """A grill was found automatically through a manifest Bluetooth matcher."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if not is_masterbuilt(discovery_info):
            return self.async_abort(reason="not_supported")
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {"name": device_title(discovery_info)}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery_info is not None
        title = device_title(self._discovery_info)
        if user_input is not None:
            return self.async_create_entry(
                title=title, data={CONF_ADDRESS: self._discovery_info.address}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm", description_placeholders={"name": title}
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual setup: pick from grills currently in range."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            info = self._discovered[address]
            return self.async_create_entry(title=device_title(info), data={CONF_ADDRESS: address})

        configured = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address in configured or info.address in self._discovered:
                continue
            if is_masterbuilt(info):
                self._discovered[info.address] = info

        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            addr: f"{device_title(info)} ({addr})"
                            for addr, info in self._discovered.items()
                        }
                    )
                }
            ),
        )
