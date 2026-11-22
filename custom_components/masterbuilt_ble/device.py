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

from .const import (
    AUTH_CHAR_UUID,
    CONTROL_CHAR_UUID,
    INIT_PAYLOAD,
    NOTIFY_CHAR_UUID,
    START_CHAR_UUID,
)
from .protocol import (
    GrillStatus,
    PacketAssembler,
    PowerOff,
    ProbeStatus,
    WifiStatus,
    build_handshake,
    build_set_target_temp,
    build_set_timer,
    is_handshake_accepted,
    parse_handshake_challenge,
    parse_packet,
)

_LOGGER = logging.getLogger(__name__)

# Text of the bleak-esphome error raised when a characteristic has no CCCD.
_CCCD_MISSING = "does not have a characteristic client config descriptor"
_NOTIFY_TIMEOUT = 30.0

# EXPERIMENTAL. Writing the init payload (the hello) is enough to start the
# status stream on a grill that is sending Bluetooth readings. A grill that
# has been set up on Wi-Fi sends only Wi-Fi status (B5) instead. The
# controller firmware only marks a Bluetooth session as "validated" after the
# full fff1/fff2 handshake completes, and the status (B4) stream is gated
# behind that validated state, so completing the handshake right after
# connecting -- not just before sending a command -- may be what switches a
# Wi-Fi-mode grill back to sending readings. This is unproven; set it to True
# to test on a grill that is stuck sending B5, and watch the debug log for
# "packet B4". It is off by default because on a grill that already streams
# readings the extra handshake is unnecessary.
HANDSHAKE_ON_CONNECT = True


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
        self.wifi_status: WifiStatus | None = None
        # True while the grill sends readings over Bluetooth, False once it
        # sends Wi-Fi status packets instead, None until the first packet.
        self.bluetooth_readings: bool | None = None

        self._ble_device: BLEDevice | None = None
        self._client: BleakClient | None = None
        self._connect_lock = asyncio.Lock()
        self._handshake_done = False
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
            self._handshake_done = False
            step = "sending init payload"
            try:
                _LOGGER.debug("%s: connected, %s", self.address, step)
                await self._write(client, START_CHAR_UUID, INIT_PAYLOAD)
                step = "subscribing to notifications"
                _LOGGER.debug("%s: %s", self.address, step)
                await self._start_notify(client)
                if HANDSHAKE_ON_CONNECT:
                    step = "completing handshake"
                    _LOGGER.debug("%s: %s", self.address, step)
                    await self._complete_handshake(client)
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
                self.bluetooth_readings = True
            elif isinstance(packet, ProbeStatus):
                self.probes = packet
                self.bluetooth_readings = True
            elif isinstance(packet, WifiStatus):
                if self.bluetooth_readings is not False:
                    _LOGGER.warning(
                        "%s: the grill is in Wi-Fi mode and is not sending readings "
                        "over Bluetooth (Wi-Fi state: %s)",
                        self.address,
                        ", ".join(packet.states) or "not connected",
                    )
                self.wifi_status = packet
                self.bluetooth_readings = False
                # Earlier readings are no longer updated; don't show them as live.
                self.status = None
                self.probes = None
            elif isinstance(packet, PowerOff):
                self.powered_off = True
            else:
                self.last_unknown_packet = packet_bytes
        self._notify_listeners()

    # -- commands (experimental) ------------------------------------------

    async def set_target_temp(self, temp: int) -> None:
        """Set the target temperature (A4 command). Untested on real hardware."""
        status = self._require_status()
        await self._send_command(
            "set target temperature",
            build_set_target_temp(
                temp, fahrenheit=status.fahrenheit, powered_on=status.powered_on
            ),
        )

    async def set_timer(self, minutes: int) -> None:
        """Set a count-down timer (A4 command). Untested on real hardware."""
        status = self._require_status()
        await self._send_command(
            "set timer",
            build_set_timer(
                minutes, fahrenheit=status.fahrenheit, powered_on=status.powered_on
            ),
        )

    def _require_status(self) -> GrillStatus:
        # Commands carry the grill's unit and power state; sending a guess
        # could switch the grill off.
        if self.status is None:
            raise BleakError("the grill's current state isn't known yet")
        return self.status

    async def _send_command(self, what: str, payload: bytes) -> None:
        if not self.connected:
            await self.connect()
        assert self._client is not None
        if not self._handshake_done:
            await self._complete_handshake(self._client)
        _LOGGER.debug("%s: sending %s (%s)", self.address, what, payload.hex(" ").upper())
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

    async def _complete_handshake(self, client: BleakClient) -> None:
        """Finish the handshake the official app does, before sending commands.

        connect() only writes the hello (INIT_PAYLOAD), which is enough for
        the status stream. The app then reads a challenge from fff2, writes
        it back to fff1, and reads 0B 00 00. Whether commands need this is
        not known yet, so failures are logged and the command is sent anyway.
        Done once per connection, only when a command is sent, so a plain
        read-only connection stays exactly as before.
        """
        try:
            reply = bytes(await client.read_gatt_char(AUTH_CHAR_UUID))
            _LOGGER.debug("%s: handshake reply %s", self.address, reply.hex(" ").upper())
            challenge = parse_handshake_challenge(reply)
            if challenge is None:
                _LOGGER.warning(
                    "%s: unexpected handshake reply %s; sending command anyway",
                    self.address,
                    reply.hex(" ").upper(),
                )
                return
            await self._write(client, START_CHAR_UUID, build_handshake(challenge))
            result = bytes(await client.read_gatt_char(AUTH_CHAR_UUID))
            _LOGGER.debug("%s: handshake result %s", self.address, result.hex(" ").upper())
            if is_handshake_accepted(result):
                self._handshake_done = True
            else:
                _LOGGER.warning(
                    "%s: handshake not accepted (%s); sending command anyway",
                    self.address,
                    result.hex(" ").upper(),
                )
        except (BleakError, TimeoutError) as err:
            _LOGGER.warning("%s: handshake failed (%r); sending command anyway", self.address, err)

    async def _write(self, client: BleakClient, uuid: str, data: bytes) -> None:
        char = client.services.get_characteristic(uuid)
        if char is None:
            raise BleakError(f"Characteristic {uuid} not found on {self.address}")
        response = "write" in char.properties
        await client.write_gatt_char(char, data, response=response)
