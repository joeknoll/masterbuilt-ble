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

# Text of the bleak-esphome error raised when a characteristic has no CCCD.
_CCCD_MISSING = "does not have a characteristic client config descriptor"
_NOTIFY_TIMEOUT = 30.0


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
            step = "sending init payload"
            try:
                _LOGGER.debug("%s: connected, %s", self.address, step)
                await self._write(client, START_CHAR_UUID, INIT_PAYLOAD)
                step = "subscribing to notifications"
                _LOGGER.debug("%s: %s", self.address, step)
                await self._start_notify(client)
            except Exception as err:
                _LOGGER.debug(
                    "%s: failed while %s; services seen: %s",
                    self.address,
                    step,
                    self._describe_services(client),
                )
                try:
                    await client.disconnect()
                except BleakError:
                    pass
                raise BleakError(f"failed while {step}: {err!r}") from err

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

    async def _start_notify(self, client: BleakClient) -> None:
        char = client.services.get_characteristic(NOTIFY_CHAR_UUID)
        if char is None:
            raise BleakError(f"Characteristic {NOTIFY_CHAR_UUID} not found on {self.address}")
        try:
            await client.start_notify(char, self._handle_notification)
            return
        except BleakError as err:
            if _CCCD_MISSING not in str(err):
                raise
        _LOGGER.debug(
            "%s: %s has no CCCD descriptor, subscribing without it", self.address, char.uuid
        )
        await self._start_notify_without_cccd(client, char)

    async def _start_notify_without_cccd(
        self, client: BleakClient, char: BleakGATTCharacteristic
    ) -> None:
        """Subscribe on an ESPHome proxy without writing a CCCD.

        The grill's notify characteristic has no Client Characteristic
        Configuration Descriptor; it sends notifications as soon as the init
        payload is written. bleak-esphome refuses to subscribe without a CCCD
        when the proxy supports remote caching, so this calls the proxy API
        directly, the same way bleak-esphome does before its CCCD step.

        This relies on bleak-esphome internals (_backend, _client,
        _address_as_int, _notify_cancels) and only works through an ESPHome
        proxy. Registering in _notify_cancels lets stop_notify and disconnect
        clean up normally.
        """
        backend = getattr(client, "_backend", None)
        api = getattr(backend, "_client", None)
        address = getattr(backend, "_address_as_int", None)
        cancels = getattr(backend, "_notify_cancels", None)
        if (
            address is None
            or not isinstance(cancels, dict)
            or not hasattr(api, "bluetooth_gatt_start_notify")
        ):
            raise BleakError(
                f"{char.uuid} has no CCCD descriptor and the Bluetooth backend "
                f"({type(backend).__name__}) can't subscribe without one"
            )

        def _on_notify(_handle: int, data: bytearray) -> None:
            self._handle_notification(char, bytearray(data))

        cancels[char.handle] = await api.bluetooth_gatt_start_notify(
            address, char.handle, _on_notify, _NOTIFY_TIMEOUT
        )

    @staticmethod
    def _describe_services(client: BleakClient) -> str:
        """List characteristics, properties and descriptors, for debugging."""
        try:
            return ", ".join(
                f"{char.uuid}[{'/'.join(char.properties)}]"
                f"{{{','.join(d.uuid[4:8] for d in char.descriptors)}}}"
                for service in client.services
                for char in service.characteristics
            )
        except Exception as err:  # noqa: BLE001 - best effort, debug only
            return f"unavailable ({err!r})"

    async def _write(self, client: BleakClient, uuid: str, data: bytes) -> None:
        char = client.services.get_characteristic(uuid)
        if char is None:
            raise BleakError(f"Characteristic {uuid} not found on {self.address}")
        response = "write" in char.properties
        await client.write_gatt_char(char, data, response=response)
