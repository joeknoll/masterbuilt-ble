"""Pure-Python parser for Masterbuilt grill BLE packets.

This module has no Home Assistant or Bleak dependencies so it can be unit
tested on its own.

Everything below was reverse engineered from Bluetooth captures of a Gravity
Series-style controller, plus the GATT layout and control command published
in particle-iot/ble-gateway-library (masterbuilt-smoker.cpp). Each field is
tagged:

    [known]       matches every capture so far
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

    ...fff1  write    INIT_PAYLOAD once after connecting, or the grill drops
                      the link. [known] Meaning of the payload bytes: [unknown]
    ...fff3  write    control commands (see below). [unconfirmed]
    ...fff4  notify   status, probe and power-off packets. [known]
                      Has no CCCD descriptor; the grill notifies without
                      one once INIT_PAYLOAD is written. [assumed]

The grill accepts only one connection at a time. [assumed]

A 21-byte status packet can arrive split across two notifications at the
default ATT MTU (20 bytes of payload); PacketAssembler rejoins them.

Status packet (0xB4, 21 bytes)
------------------------------

    00     packet id 0xB4                                     [known]
    01     configuration bitmap
             bit0  1 = Fahrenheit, 0 = Celsius                [known]
             bit1  timer active                               [known]
             bit3  always set in captures                     [unknown]
             bit5  always set in captures                     [unknown]
             bits 2, 4, 6, 7  never seen set                  [unknown]
    02     operation bitmap
             bit5  heating / running                          [known]
             bit1  set in Fahrenheit captures                 [assumed]
             bit0  set in all Celsius and one Fahrenheit      [unknown]
                   capture
    03     error bitmap, bit n = Err n+1 (Err 1-5)            [assumed]
             Only 0x08 (Err 4) has been seen in a capture.
    04-05  cavity (grill) temperature, int16                  [known]
    06-07  always 0 in captures                               [unknown]
    08-09  target temperature, int16                          [known]
             0 in °F / -17 in °C (0 °F converted) = no target.
             Reads 700 (BC 02) in one "lid open" capture.     [unknown]
    10     always 0 in captures                               [unknown]
    11-12  remaining timer minutes, uint16                    [known]
    13-14  set timer minutes, uint16                          [known]
    15     0x64 (100) in most heating captures, 0 otherwise.  [unknown]
             Possibly fan speed %, or related to the timer.
    16     always 0 in captures                               [unknown]
    17-18  maximum settable temperature, int16                [known]
             700 °F / 371 °C in captures.
    19-20  minimum settable temperature, int16                [known]
             150 °F / 65 °C in captures.

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

Set temperature and timer command (write to ...fff3)
----------------------------------------------------

    A1 07 05 <minutes uint16> <temperature uint16>            [unconfirmed]

From the Particle library, which targets an older smoker with a different
status layout. Both values are always sent together.
"""

from __future__ import annotations

from dataclasses import dataclass

STATUS_PACKET_ID = 0xB4
PROBE_PACKET_ID = 0xB3
POWER_OFF_PACKET_ID = 0xB2

STATUS_PACKET_LEN = 21
PROBE_PACKET_LEN = 18

EXPECTED_LENGTHS = {
    STATUS_PACKET_ID: STATUS_PACKET_LEN,
    PROBE_PACKET_ID: PROBE_PACKET_LEN,
}

# Error bitmap bit -> (error number, description)
ERRORS: dict[int, tuple[int, str]] = {
    0: (1, "Temperature probe not fully plugged in"),
    1: (2, "Meat probe malfunction"),
    2: (3, "Grill overheated"),
    3: (4, "Charcoal failed to ignite"),
    4: (5, "Meat probe temperature above 300°F"),
}

# Control command header: A1 07 05 <minutes u16 LE> <temp u16 LE>
SET_TEMP_TIME_HEADER = bytes([0xA1, 0x07, 0x05])


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
    unknown_byte_15: int
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
            unknown_byte_15=data[15],
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


Packet = GrillStatus | ProbeStatus | PowerOff


def parse_packet(data: bytes) -> Packet | None:
    """Parse one complete packet. Returns None for unknown packets."""
    if not data:
        return None
    packet_id = data[0]
    if packet_id == STATUS_PACKET_ID and len(data) >= STATUS_PACKET_LEN:
        return GrillStatus.from_bytes(data)
    if packet_id == PROBE_PACKET_ID and len(data) >= PROBE_PACKET_LEN:
        return ProbeStatus.from_bytes(data)
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
