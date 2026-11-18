"""BLE connection handling for a Masterbuilt grill."""

from __future__ import annotations

from collections.abc import Callable
import asyncio
import logging
import time

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import CONTROL_CHAR_UUID, INIT_PAYLOAD, NOTIFY_CHAR_UUID, START_CHAR_UUID
from .protocol import (
    GrillStatus,
    PacketAssembler,
    PowerOff,
    ProbeStatus,
    build_set_temp_and_time,
    parse_packet,
)

_LOGGER = logging.getLogger(__name__)


class MasterbuiltGrill:
    """Keeps a live notification connection to one grill and holds its state."""

    def __init__(self, address: str, name: str) -> None:
        self.address = address
        self.name = name
        self.status: GrillStatus | None = None
        self.probes: ProbeStatus | None = None
        self.powered_off = False
        self.last_packet_monotonic: float | None = None
        self.last_unknown_packet: bytes | None = None

        self._ble_device: BLEDevice | None = None
        self._client: BleakClient | None = None
        self._connect_lock = asyncio.Lock()
        self._assembler = PacketAssembler()
        self._listeners: list[Callable[[], None]] = []

    # -- state / listeners -------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        self._ble_device = ble_device

    @property
    def has_ble_device(self) -> bool:
        return self._ble_device is not None

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a callback for state changes; returns an unsubscribe function."""
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    def _notify_listeners(self) -> None:
        for listener in list(self._listeners):
            listener()

    # -- connection --------------------------------------------------------

    async def connect(self) -> None:
        """Connect, send the init payload, and subscribe to notifications."""
        async with self._connect_lock:
            if self.connected:
                return
            if self._ble_device is None:
                raise BleakError(f"{self.address} has not been seen by any Bluetooth adapter")

            _LOGGER.debug("%s: connecting", self.address)
            client = await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self.name,
                disconnected_callback=self._handle_disconnect,
                ble_device_callback=lambda: self._ble_device,
                max_attempts=3,
            )
            try:
                await self._write(client, START_CHAR_UUID, INIT_PAYLOAD)
                await client.start_notify(NOTIFY_CHAR_UUID, self._handle_notification)
            except (BleakError, TimeoutError):
                await client.disconnect()
                raise

            self._client = client
            self._assembler = PacketAssembler()
            self.last_packet_monotonic = time.monotonic()
            _LOGGER.info("%s: connected", self.address)
            self._notify_listeners()

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except BleakError as err:
                _LOGGER.debug("%s: error while disconnecting: %s", self.address, err)
        self._notify_listeners()

    def _handle_disconnect(self, client: BleakClient) -> None:
        if client is not self._client:
            return
        _LOGGER.info("%s: disconnected", self.address)
        self._client = None
        self._notify_listeners()

    # -- data --------------------------------------------------------------

    def _handle_notification(self, _char: BleakGATTCharacteristic, data: bytearray) -> None:
        self.last_packet_monotonic = time.monotonic()
        for packet_bytes in self._assembler.feed(bytes(data)):
            _LOGGER.debug("%s: packet %s", self.address, packet_bytes.hex(" ").upper())
            try:
                packet = parse_packet(packet_bytes)
            except ValueError as err:
                _LOGGER.debug("%s: failed to parse packet: %s", self.address, err)
                continue

            if isinstance(packet, GrillStatus):
                self.status = packet
                self.powered_off = False
            elif isinstance(packet, ProbeStatus):
                self.probes = packet
            elif isinstance(packet, PowerOff):
                self.powered_off = True
            else:
                self.last_unknown_packet = packet_bytes
        self._notify_listeners()

    # -- commands (experimental) ------------------------------------------

    async def set_temp_and_time(self, temp: int, minutes: int) -> None:
        """Send the set-temperature/timer command. Untested on real hardware."""
        payload = build_set_temp_and_time(temp, minutes)
        if not self.connected:
            await self.connect()
        assert self._client is not None
        _LOGGER.debug(
            "%s: sending set temp=%s minutes=%s (%s)",
            self.address,
            temp,
            minutes,
            payload.hex(" ").upper(),
        )
        await self._write(self._client, CONTROL_CHAR_UUID, payload)

    async def _write(self, client: BleakClient, uuid: str, data: bytes) -> None:
        char = client.services.get_characteristic(uuid)
        if char is None:
            raise BleakError(f"Characteristic {uuid} not found on {self.address}")
        response = "write" in char.properties
        await client.write_gatt_char(char, data, response=response)
