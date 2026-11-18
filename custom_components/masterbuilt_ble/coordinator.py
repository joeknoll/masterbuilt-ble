"""Connection manager tying a MasterbuiltGrill to Home Assistant's Bluetooth stack."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import time

from bleak.exc import BleakError

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .const import RECONNECT_BACKOFF_SECONDS, STALE_DATA_SECONDS, WATCHDOG_INTERVAL
from .device import MasterbuiltGrill

_LOGGER = logging.getLogger(__name__)


class MasterbuiltCoordinator:
    """Keeps the grill connected whenever it is in range.

    Grills are often switched off or out of range. Setup never fails because
    of that. The coordinator connects when an advertisement is seen and
    reconnects after a drop.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, grill: MasterbuiltGrill) -> None:
        self.hass = hass
        self.entry = entry
        self.grill = grill
        self._connect_task: asyncio.Task[None] | None = None
        self._next_attempt = 0.0
        self._stopping = False
        self._warned_connect_failure = False

    @callback
    def async_start(self) -> None:
        entry = self.entry
        entry.async_on_unload(
            bluetooth.async_register_callback(
                self.hass,
                self._async_handle_advertisement,
                bluetooth.BluetoothCallbackMatcher(address=self.grill.address, connectable=True),
                bluetooth.BluetoothScanningMode.ACTIVE,
            )
        )
        entry.async_on_unload(
            async_track_time_interval(self.hass, self._async_watchdog, WATCHDOG_INTERVAL)
        )
        if ble_device := bluetooth.async_ble_device_from_address(
            self.hass, self.grill.address, connectable=True
        ):
            self.grill.set_ble_device(ble_device)
            self._async_schedule_connect()

    async def async_stop(self) -> None:
        self._stopping = True
        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()
        await self.grill.disconnect()

    @callback
    def _async_handle_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        _change: bluetooth.BluetoothChange,
    ) -> None:
        self.grill.set_ble_device(service_info.device)
        self._async_schedule_connect()

    @callback
    def _async_schedule_connect(self) -> None:
        if self._stopping or self.grill.connected:
            return
        if self._connect_task and not self._connect_task.done():
            return
        if time.monotonic() < self._next_attempt:
            return
        self._connect_task = self.entry.async_create_background_task(
            self.hass, self._async_connect(), f"masterbuilt connect {self.grill.address}"
        )

    async def _async_connect(self) -> None:
        try:
            await self.grill.connect()
        except Exception as err:
            self._next_attempt = time.monotonic() + RECONNECT_BACKOFF_SECONDS
            # Warn once per failure streak; repeat attempts go to debug so a
            # grill that is simply off doesn't flood the log.
            log = _LOGGER.debug if self._warned_connect_failure else _LOGGER.warning
            log(
                "%s: connection failed, retrying in %ss: %r",
                self.grill.address,
                RECONNECT_BACKOFF_SECONDS,
                err,
                # Full traceback only for unexpected errors (likely our bug).
                exc_info=not isinstance(err.__cause__ or err, (BleakError, TimeoutError)),
            )
            self._warned_connect_failure = True
        else:
            self._warned_connect_failure = False

    async def _async_watchdog(self, _now: datetime) -> None:
        grill = self.grill
        if grill.connected:
            last = grill.last_packet_monotonic
            if last is not None and time.monotonic() - last > STALE_DATA_SECONDS:
                _LOGGER.debug("%s: no data for %ss, reconnecting", grill.address, STALE_DATA_SECONDS)
                await grill.disconnect()
                self._async_schedule_connect()
            return

        if ble_device := bluetooth.async_ble_device_from_address(
            self.hass, grill.address, connectable=True
        ):
            grill.set_ble_device(ble_device)
            self._async_schedule_connect()
