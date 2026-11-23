"""Pure-Python parser for Masterbuilt grill BLE packets.

This module has no Home Assistant or Bleak dependencies so it can be unit
tested on its own.

Everything below was reverse engineered from Bluetooth captures of a Gravity
Series-style controller, plus the
GATT layout published in particle-iot/ble-gateway-library
(masterbuilt-smoker.cpp) and other implementations of the same protocol.
Each field is tagged:

    [known]       confirmed by capture
    [assumed]     consistent with captures, but only partly observed
    [unconfirmed] taken from another source and not yet seen to work here
    [unknown]     meaning not worked out yet

Multi-byte values are little-endian. All temperatures are in the scale the
grill is configured for (see configuration bit 0).

Advertisement (before connecting)
--------------------------------

    local name         "Masterbuilt Smoker"                   [known]
    service UUIDs      0xFFF0, 0x180A (Device Information)    [known]
    manufacturer data  ID 0x4842, payload = the grill's MAC   [known]
    tx power           -21 dBm                                [known]

No readings are broadcast; a connection is needed for data. [known]

Connection (GATT, service 426f7567-6854-6563-2d57-65694c69fff0)
---------------------------------------------------------------

Handles are from one capture of the official Android app; each
characteristic has one custom 0xFF0n descriptor and none has a CCCD
(0x2902). [known]

    ...fff1  0x002a  read/write  handshake and session messages (below).
                     Writing a handshake hello once after connecting starts
                     the status stream; without it the grill drops the
                     link. [known]
    ...fff2  0x002d  read        handshake replies (below). [known]
    ...fff3  0x0030  read/write  commands (below).
    ...fff4  0x0033  notify      status, probe and power-off packets. No
                     CCCD: the grill notifies without one. [known]
    ...fff5  0x0036  read/write/notify  Wi-Fi setup data: the scanned
                     network list (notify) and the chosen network's
                     credentials (write). [known]

Device Information service (0x180A), as read by the app:

    0x2A24 model number       "C:G:900:1:D"
    0x2A26 firmware revision  "16101401"
    0x2A28 software revision  "3.0.01"

The app negotiates an MTU of 500, so packets don't get split for it.
The grill accepts only one connection at a time. [assumed]

Handshake and session messages (fff1 / fff2)
---------------------------------------------

Messages look like <type> <length> <payload>. [assumed] Sequence seen
from the app: [known]

    write fff1  0E 08 <8-byte nonce>       hello
    read  fff2  0A 08 <8-byte challenge>   grill's challenge
    write fff1  0E 08 <challenge>          the challenge echoed back as-is
    read  fff2  0B 00 00                   accepted (presumably)

The controller validates the hello nonce against its own MAC: five of the
eight nonce bytes must equal a MAC byte XORed with a fixed code (build_hello
derives them; the rest are not checked). An accepted hello starts the
status stream. [known] The challenge equals the nonce XORed with
(0x4842 + MAC), and the client echoes it back verbatim. Whether the full
challenge echo is needed in addition to the hello: [unknown]

    write fff1  0F 00 00    sent before the app disconnects. Session end or
                            reset (likely). [unknown]

Wi-Fi setup (A5 commands on fff3, B5 replies on fff4)
-----------------------------------------------------

Pattern: messages to the grill start with 0xA_, packets from it with 0xB_
(B2 power off, B3 probes, B4 status, B5 Wi-Fi). [assumed] The Particle
set-temperature command (A1) fits this pattern.

A5 <byte 1> <byte 2>. Byte 1 picks the operation, byte 2 steps the data
transfer through fff5 (same bits as B5 byte 2):

    A5 01 00   start a Wi-Fi scan                                 [known]
    A5 00 01   ready to receive (the network list)                [known]
    A5 00 02   data received; send the next part                  [known]
    A5 02 04   about to send Wi-Fi credentials (then fff5 write)  [known]
    A5 02 08   credentials part written                           [known]
    A5 02 10   credentials done; connect                          [known]
    A5 08 00   read the saved network name                        [unconfirmed]
    A5 04 04   about to send cloud credentials                    [unconfirmed]

There is no known command that directly clears the saved network.

The grill answers each with a B5 packet. While the grill is on Wi-Fi it
sends B5 packets (about every 2 s) instead of B4/B3 readings.

Wi-Fi status packet (0xB5, 5 bytes) [known]
-------------------------------------------

    00     packet id 0xB5
    01     connection state bitmap
             bit0  scanning for networks
             bit1  connected to Wi-Fi
             bit2  connected to the internet
             bit3  connected to the cloud service
             bit4  synced with its cloud state
             bit5  about to report its firmware version
             bit6  network list ready to send
             bit7  busy connecting or updating
    02     data transfer bitmap (network list and credentials, via fff5)
             bit0  ready to receive data
             bit1  received data
             bit2  ready to send data
             bit3  sent data
             bit4  finished sending data
    03     error bitmap
             bit0  network not found
             bit1  wrong Wi-Fi password
             bit2  no Wi-Fi networks in range
             bit3  network has no internet access
             bit4  can't reach the cloud service
             bit5  can't sync with the cloud
             bit6  firmware update failed
    04     number of Wi-Fi networks found

Example: during setup byte 1 goes 80 (busy), 86 (Wi-Fi + internet),
8E (+ cloud), 9E (+ synced), then 1E (fully connected, no longer busy).
00 means idle with no connection.

While the grill is on Wi-Fi, temperature and timer changes made from a
phone go through the cloud, not Bluetooth. [known]

A 21-byte status packet can arrive split across two notifications at the
default ATT MTU (20 bytes of payload); PacketAssembler rejoins them.

Status packet (0xB4, 21 bytes)
------------------------------

    00     packet id 0xB4                                     [known]
    01     configuration bitmap: units, timer, and which features the
           controller has
             bit0  1 = Fahrenheit, 0 = Celsius                [known]
             bit1  timer on                                   [known]
             bit2  timer counts up instead of down            [assumed]
             bit3  min/max temperatures present (17-20)       [assumed]
             bit4  has an electric smoker element (06-07)     [unconfirmed]
             bit5  has a fan / charcoal heat source           [assumed]
                   (08-09, 15-16)
             bit6  has a broiler (byte 10, low nibble)        [unconfirmed]
             bit7  has smoke on demand (byte 10, high nibble) [unconfirmed]
           A Gravity Series grill always reports bits 3 and 5 set and
           bits 4, 6 and 7 clear. [known]
    02     operation bitmap
             bit0  powered on                                 [assumed]
             bit1  Bluetooth control enabled                  [unconfirmed]
             bit2  door / lid open                            [unconfirmed]
             bit3  count-up timer running                     [assumed]
             bit4  smoker element on                          [unconfirmed]
             bit5  fan on (heating)                           [known]
             bit6  broiler on                                 [unconfirmed]
             bit7  smoke on demand on                         [unconfirmed]
           A Gravity Series grill never sets bits 2, 4, 6 or 7, so it
           doesn't report the lid state. [known]
    03     error bitmap: one flag per error, bit n = Err n+1
           (Err 1-5)                                          [known]
             Err 2 (meat probe malfunction) is set when any probe
             reports a fault. Err 4 (0x08, charcoal failed to ignite)
             has been seen in a capture.
    04-05  cavity (grill) temperature                         [known]
    06-07  smoker element target temperature; 0 on a grill
           without one                                        [unconfirmed]
    08-09  target (fan) temperature                           [known]
             0 in °F / -17 in °C (0 °F converted) = no target.[assumed]
    10     low nibble broiler level, high nibble smoke-on-
           demand level; 0 on a grill without them            [unconfirmed]
           A Gravity Series grill sends 0 in 06-07 and 10. [known]
    11-12  timer minutes remaining (elapsed when counting up),
           uint16                                             [known]
    13-14  timer minutes set, uint16; 0 when counting up      [known]
    15-16  fan intensity, uint16, 0-100 %                     [known]
             100 while heating up in most captures.
    17-18  maximum settable temperature                       [known]
             700 °F / 371 °C in captures.
    19-20  minimum settable temperature                       [known]
             150 °F / 65 °C in captures.

Temperatures (04-09, 17-20) are read as int16. A Gravity Series controller
sends plain integers: it keeps temperatures in °F and, when set to
Celsius, sends (F - 32) x 5 / 9 rounded toward zero. [known] Other
implementations treat these fields as IEEE 11073 16-bit SFLOATs; for the
values seen so far (exponent 0) the two encodings are the same.

Probe packet (0xB3, 18 bytes)
-----------------------------

    00     packet id 0xB3                                     [known]
    01     connected-probe bitmap, bit n = probe n+1          [known for 1-4]
    02-17  probe 1-8 temperatures, int16 each                 [known for 1-4]
             Probes 5-8 are inferred from the packet length;
             no capture has shown them in use.                [assumed]

Power-off packet
----------------

    B2 00 00 00, or a lone 00: the grill is switched off.     [known]

Control commands (write to ...fff3)
-----------------------------------

The command format depends on the controller type:

    A1 ...   older smokers (the Particle library's command)
    A2 00 00 status request for the oldest controllers (below)
    A3 ...   meat probe target temperatures (below)
    A4 ...   controllers that send the B4 status packet
    A5 ...   Wi-Fi setup (above)

A2 command (3 bytes)                                [experimental, untested]

    A2 00 00

The status request. The official app (Classic) writes it every 1.5 s, but
only to controllers it identifies as MCU version 1, which presumably send a
status packet only when asked. It is the app's only A2 command; the newer
app never sends it.

A3 command (10 bytes)              [untested]

    00     0xA3
    01     which probe targets to set: bit0 = probe 1 ... bit3 = probe 4
    02-03  probe 1 target temperature, int16
    04-05  probe 2 target temperature, int16
    06-07  probe 3 target temperature, int16
    08-09  probe 4 target temperature, int16

Temperatures use the grill's current scale. The controller only changes the
probes whose bit is set; the app sets one probe per command and leaves the
other bytes 0. The controller accepts only a 10-byte A3, so it can set
probes 1-4 only.

    A3 01 A0 00 00 00 00 00 00 00   set the probe 1 target to 160 °F

A4 command (10 bytes)              [untested]

    00     0xA4
    01     what is being set
             bit0  1 = Fahrenheit (always the grill's current unit)
             bit1  timer
             bit2  timer counts up (with bit1)
             bit3  smoker element temperature (05-06)
             bit4  target (fan) temperature (07-08)
             bit5  broiler level (09)
             bit6  smoke-on-demand level (09)
    02     control
             bit0  powered on: always the grill's current power state;
                   clearing it turns the grill off
             bit1  start/stop the timer
    03-04  timer minutes, uint16 (count-down timer only)
    05-06  smoker element temperature, int16
    07-08  target (fan) temperature, int16
    09     broiler level (low nibble) or smoke-on-demand level (high nibble)

One setting is sent per command. Examples, grill on and in °F:

    A4 11 01 00 00 00 00 FA 00 00   set the target to 250 °F
    A4 03 01 9D 01 00 00 00 00 00   set the timer to 413 minutes

A1 command (older smokers)                                     [unconfirmed]

    A1 07 05 <minutes uint16> <temperature uint16>

From the Particle library. It did nothing on a grill reporting model
"C:G:900:1:D", which uses the A4 command instead.
"""

from __future__ import annotations

from dataclasses import dataclass

STATUS_PACKET_ID = 0xB4
PROBE_PACKET_ID = 0xB3
POWER_OFF_PACKET_ID = 0xB2
WIFI_STATUS_PACKET_ID = 0xB5

STATUS_PACKET_LEN = 21
PROBE_PACKET_LEN = 18
WIFI_STATUS_PACKET_LEN = 5

EXPECTED_LENGTHS = {
    STATUS_PACKET_ID: STATUS_PACKET_LEN,
    PROBE_PACKET_ID: PROBE_PACKET_LEN,
    WIFI_STATUS_PACKET_ID: WIFI_STATUS_PACKET_LEN,
}

# Error bitmap bit -> (error number, description)
ERRORS: dict[int, tuple[int, str]] = {
    0: (1, "Temperature probe not fully plugged in"),
    1: (2, "Meat probe malfunction"),
    2: (3, "Grill overheated"),
    3: (4, "Charcoal failed to ignite"),
    4: (5, "Meat probe temperature above 300°F"),
}

# Wi-Fi status (0xB5) byte 1 bits -> description
WIFI_STATES: dict[int, str] = {
    0: "Scanning for networks",
    1: "Connected to Wi-Fi",
    2: "Connected to the internet",
    3: "Connected to the cloud service",
    4: "Synced with its cloud state",
    5: "About to report its firmware version",
    6: "Network list ready to send",
    7: "Busy connecting or updating",
}

# Wi-Fi status (0xB5) byte 3 bits -> description
WIFI_ERRORS: dict[int, str] = {
    0: "Network not found",
    1: "Wrong Wi-Fi password",
    2: "No Wi-Fi networks in range",
    3: "Network has no internet access",
    4: "Can't reach the cloud service",
    5: "Can't sync with the cloud",
    6: "Firmware update failed",
}

# Control command header: A1 07 05 <minutes u16 LE> <temp u16 LE> (older smokers)
SET_TEMP_TIME_HEADER = bytes([0xA1, 0x07, 0x05])

# A2 status request (oldest controllers; experimental).
STATUS_REQUEST = bytes([0xA2, 0x00, 0x00])

# A3 meat probe target command (experimental).
PROBE_TARGET_COMMAND_ID = 0xA3
PROBE_TARGET_COMMAND_LEN = 10
PROBE_TARGET_MAX_PROBES = 4

# A4 control command (controllers that send B4 status packets).
CONTROL_COMMAND_ID = 0xA4
CONTROL_COMMAND_LEN = 10
# Byte 1: what is being set.
CONTROL_SET_FAHRENHEIT = 0x01
CONTROL_SET_TIMER = 0x02
CONTROL_SET_TARGET_TEMP = 0x10
# Byte 2: control.
CONTROL_POWER_ON = 0x01
CONTROL_START_STOP_TIMER = 0x02

# Handshake message types (fff1 writes, fff2 reads).
HANDSHAKE_HELLO = 0x0E
HANDSHAKE_CHALLENGE = 0x0A
HANDSHAKE_ACCEPTED = 0x0B
HANDSHAKE_NONCE_LEN = 8
# Written by the app before it disconnects.
SESSION_END = bytes([0x0F, 0x00, 0x00])


def _s16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little", signed=True)


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little", signed=False)


@dataclass(frozen=True)
class GrillStatus:
    """Decoded 0xB4 status packet."""

    raw: bytes
    config_flags: int
    operation_flags: int
    error_flags: int
    cavity_temp: int
    target_temp_raw: int
    remaining_minutes: int
    set_minutes: int
    fan_intensity: int
    max_temp: int
    min_temp: int

    @classmethod
    def from_bytes(cls, data: bytes) -> GrillStatus:
        if len(data) < STATUS_PACKET_LEN or data[0] != STATUS_PACKET_ID:
            raise ValueError(f"Not a status packet: {data.hex()}")
        return cls(
            raw=bytes(data[:STATUS_PACKET_LEN]),
            config_flags=data[1],
            operation_flags=data[2],
            error_flags=data[3],
            cavity_temp=_s16(data, 4),
            target_temp_raw=_s16(data, 8),
            remaining_minutes=_u16(data, 11),
            set_minutes=_u16(data, 13),
            fan_intensity=_u16(data, 15),
            max_temp=_s16(data, 17),
            min_temp=_s16(data, 19),
        )

    @property
    def fahrenheit(self) -> bool:
        """True if the grill is configured for °F."""
        return bool(self.config_flags & 0x01)

    @property
    def timer_active(self) -> bool:
        return bool(self.config_flags & 0x02)

    @property
    def heating(self) -> bool:
        return bool(self.operation_flags & 0x20)

    @property
    def powered_on(self) -> bool:
        return bool(self.operation_flags & 0x01)

    @property
    def target_temp(self) -> int | None:
        """Target temperature, or None if no target is set.

        With no target set, the grill reports 0 in °F mode. In °C mode it
        reports -17, which is 0 °F converted.
        """
        if self.fahrenheit:
            return None if self.target_temp_raw <= 0 else self.target_temp_raw
        return None if self.target_temp_raw <= -17 else self.target_temp_raw

    @property
    def active_errors(self) -> list[int]:
        """Grill error numbers (1-5) that are currently set."""
        return [num for bit, (num, _) in ERRORS.items() if self.error_flags & (1 << bit)]

    def has_error(self, number: int) -> bool:
        return number in self.active_errors


@dataclass(frozen=True)
class ProbeStatus:
    """Decoded 0xB3 probe packet."""

    raw: bytes
    connected_flags: int
    temps: tuple[int, ...]

    @classmethod
    def from_bytes(cls, data: bytes) -> ProbeStatus:
        if len(data) < PROBE_PACKET_LEN or data[0] != PROBE_PACKET_ID:
            raise ValueError(f"Not a probe packet: {data.hex()}")
        temps = tuple(_s16(data, 2 + i * 2) for i in range(8))
        return cls(raw=bytes(data[:PROBE_PACKET_LEN]), connected_flags=data[1], temps=temps)

    def is_connected(self, probe: int) -> bool:
        """Probe numbers are 1-based."""
        return bool(self.connected_flags & (1 << (probe - 1)))

    def temperature(self, probe: int) -> int | None:
        if not self.is_connected(probe):
            return None
        return self.temps[probe - 1]


@dataclass(frozen=True)
class PowerOff:
    """Grill reported it is powered off (0xB2 00 00 00, or a lone 0x00)."""

    raw: bytes


@dataclass(frozen=True)
class WifiStatus:
    """Decoded 0xB5 Wi-Fi status packet.

    A grill that has been set up on Wi-Fi sends these instead of status and
    probe packets.
    """

    raw: bytes
    state_flags: int
    transfer_flags: int
    error_flags: int
    networks_found: int

    @classmethod
    def from_bytes(cls, data: bytes) -> WifiStatus:
        if len(data) < WIFI_STATUS_PACKET_LEN or data[0] != WIFI_STATUS_PACKET_ID:
            raise ValueError(f"Not a Wi-Fi status packet: {data.hex()}")
        return cls(
            raw=bytes(data[:WIFI_STATUS_PACKET_LEN]),
            state_flags=data[1],
            transfer_flags=data[2],
            error_flags=data[3],
            networks_found=data[4],
        )

    @property
    def wifi_connected(self) -> bool:
        return bool(self.state_flags & 0x02)

    @property
    def states(self) -> list[str]:
        return [desc for bit, desc in WIFI_STATES.items() if self.state_flags & (1 << bit)]

    @property
    def errors(self) -> list[str]:
        return [desc for bit, desc in WIFI_ERRORS.items() if self.error_flags & (1 << bit)]


Packet = GrillStatus | ProbeStatus | PowerOff | WifiStatus


def parse_packet(data: bytes) -> Packet | None:
    """Parse one complete packet. Returns None for unknown packets."""
    if not data:
        return None
    packet_id = data[0]
    if packet_id == STATUS_PACKET_ID and len(data) >= STATUS_PACKET_LEN:
        return GrillStatus.from_bytes(data)
    if packet_id == PROBE_PACKET_ID and len(data) >= PROBE_PACKET_LEN:
        return ProbeStatus.from_bytes(data)
    if packet_id == WIFI_STATUS_PACKET_ID and len(data) >= WIFI_STATUS_PACKET_LEN:
        return WifiStatus.from_bytes(data)
    if packet_id == POWER_OFF_PACKET_ID and data[1:4] == b"\x00\x00\x00":
        return PowerOff(bytes(data))
    if data == b"\x00":
        return PowerOff(bytes(data))
    return None


class PacketAssembler:
    """Joins packets that arrive split across notifications.

    A 21-byte status packet does not fit in one notification at the default
    ATT MTU (20 bytes of payload). Many stacks negotiate a larger MTU, but
    this handles the split case too.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        """Add a notification payload; return any complete packets."""
        out: list[bytes] = []
        if chunk and chunk[0] in EXPECTED_LENGTHS:
            # A new packet starts here; drop any incomplete leftover.
            self._buffer = bytearray(chunk)
        elif self._buffer:
            self._buffer.extend(chunk)
        else:
            out.append(bytes(chunk))
            return out

        expected = EXPECTED_LENGTHS[self._buffer[0]]
        if len(self._buffer) >= expected:
            out.append(bytes(self._buffer))
            self._buffer.clear()
        return out


def build_set_temp_and_time(temp: int, minutes: int) -> bytes:
    """Build the (unconfirmed) command that sets target temperature and timer.

    temp uses the grill's configured scale.
    """
    if not 0 <= temp <= 0xFFFF:
        raise ValueError(f"temperature out of range: {temp}")
    if not 0 <= minutes <= 0xFFFF:
        raise ValueError(f"minutes out of range: {minutes}")
    return SET_TEMP_TIME_HEADER + minutes.to_bytes(2, "little") + temp.to_bytes(2, "little")


def _control_command(
    set_flags: int, fahrenheit: bool, powered_on: bool, control: int = 0
) -> bytearray:
    cmd = bytearray(CONTROL_COMMAND_LEN)
    cmd[0] = CONTROL_COMMAND_ID
    cmd[1] = set_flags | (CONTROL_SET_FAHRENHEIT if fahrenheit else 0)
    cmd[2] = control | (CONTROL_POWER_ON if powered_on else 0)
    return cmd


def build_set_target_temp(temp: int, *, fahrenheit: bool, powered_on: bool) -> bytes:
    """Build the (unconfirmed) A4 command that sets the target temperature.

    temp uses the grill's configured scale. fahrenheit and powered_on must
    match the grill's current state; a cleared power bit turns it off.
    """
    if not -0x8000 <= temp <= 0x7FFF:
        raise ValueError(f"temperature out of range: {temp}")
    cmd = _control_command(CONTROL_SET_TARGET_TEMP, fahrenheit, powered_on)
    cmd[7:9] = temp.to_bytes(2, "little", signed=True)
    return bytes(cmd)


def build_set_timer(
    minutes: int, *, fahrenheit: bool, powered_on: bool, start_stop: bool = False
) -> bytes:
    """Build the (unconfirmed) A4 command that sets a count-down timer.

    start_stop also toggles the timer between running and stopped.
    """
    if not 0 <= minutes <= 0xFFFF:
        raise ValueError(f"minutes out of range: {minutes}")
    control = CONTROL_START_STOP_TIMER if start_stop else 0
    cmd = _control_command(CONTROL_SET_TIMER, fahrenheit, powered_on, control)
    cmd[3:5] = minutes.to_bytes(2, "little")
    return bytes(cmd)


def build_status_request() -> bytes:
    """Build the (experimental) A2 status request: A2 00 00.

    The official app polls the oldest controllers with this; a Gravity Series
    controller ignores it.
    """
    return STATUS_REQUEST


def build_set_probe_target(probe: int, temp: int) -> bytes:
    """Build the (experimental) A3 command that sets one meat probe's target.

    probe is 1-4; temp uses the grill's configured scale.
    """
    if not 1 <= probe <= PROBE_TARGET_MAX_PROBES:
        raise ValueError(f"probe must be 1-{PROBE_TARGET_MAX_PROBES}, got {probe}")
    if not -0x8000 <= temp <= 0x7FFF:
        raise ValueError(f"temperature out of range: {temp}")
    cmd = bytearray(PROBE_TARGET_COMMAND_LEN)
    cmd[0] = PROBE_TARGET_COMMAND_ID
    cmd[1] = 1 << (probe - 1)
    offset = 2 + (probe - 1) * 2
    cmd[offset : offset + 2] = temp.to_bytes(2, "little", signed=True)
    return bytes(cmd)


def build_handshake(nonce: bytes) -> bytes:
    """Build a handshake message (0E 08 <8 bytes>) to write to fff1."""
    if len(nonce) != HANDSHAKE_NONCE_LEN:
        raise ValueError(f"nonce must be {HANDSHAKE_NONCE_LEN} bytes, got {len(nonce)}")
    return bytes([HANDSHAKE_HELLO, HANDSHAKE_NONCE_LEN]) + nonce


# The controller validates the hello nonce against its own MAC: five of the
# eight nonce bytes must equal a MAC byte XOR a fixed code (the other three are
# not checked). Deriving the nonce from the grill's MAC produces a hello the
# controller accepts, which starts the readings session and enables B4/B3.
#   nonce index -> (MAC index, XOR code)
HELLO_NONCE_MAC_MAP: dict[int, tuple[int, int]] = {
    2: (0, 0xB2),
    3: (1, 0xCB),
    4: (2, 0x9C),
    5: (3, 0xE4),
    7: (5, 0xAB),
}


def build_hello(mac: bytes) -> bytes:
    """Build the hello (0E 08 <8 bytes>) for a grill with the given MAC.

    The nonce is derived from the MAC so the controller accepts it; nonce
    bytes it doesn't check are left zero.
    """
    if len(mac) != 6:
        raise ValueError(f"mac must be 6 bytes, got {len(mac)}")
    nonce = bytearray(HANDSHAKE_NONCE_LEN)
    for index, (mac_index, code) in HELLO_NONCE_MAC_MAP.items():
        nonce[index] = mac[mac_index] ^ code
    return build_handshake(bytes(nonce))


def mac_to_bytes(address: str) -> bytes:
    """Parse a BLE address string like 'D8:BC:38:59:20:A6' into 6 bytes."""
    return bytes.fromhex(address.replace(":", ""))


def parse_handshake_challenge(data: bytes) -> bytes | None:
    """Return the 8-byte challenge from an fff2 reply (0A 08 ...), else None."""
    if (
        len(data) >= 2 + HANDSHAKE_NONCE_LEN
        and data[0] == HANDSHAKE_CHALLENGE
        and data[1] == HANDSHAKE_NONCE_LEN
    ):
        return bytes(data[2 : 2 + HANDSHAKE_NONCE_LEN])
    return None


def is_handshake_accepted(data: bytes) -> bool:
    """True for the fff2 reply seen after a successful handshake (0B 00 00)."""
    return bytes(data[:3]) == bytes([HANDSHAKE_ACCEPTED, 0x00, 0x00])
