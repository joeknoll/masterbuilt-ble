"""Tests for the packet parser, using real packets captured from a grill.

The packet layout, including which fields are still unknown, is documented
at the top of custom_components/masterbuilt_ble/protocol.py.

Run with:  python -m pytest tests/
protocol.py has no Home Assistant dependency, so it is loaded straight from
its file path.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

_PATH = pathlib.Path(__file__).parents[1] / "custom_components" / "masterbuilt_ble" / "protocol.py"
_spec = importlib.util.spec_from_file_location("masterbuilt_protocol", _PATH)
protocol = importlib.util.module_from_spec(_spec)
sys.modules["masterbuilt_protocol"] = protocol
_spec.loader.exec_module(protocol)


def status(hexstr: str):
    pkt = protocol.parse_packet(bytes.fromhex(hexstr))
    assert isinstance(pkt, protocol.GrillStatus)
    return pkt


def test_fresh_start_fahrenheit():
    s = status("B429020048000000E10000000000000000BC029600")
    assert s.fahrenheit
    assert not s.heating
    assert not s.timer_active
    assert s.cavity_temp == 72
    assert s.target_temp == 225
    assert s.max_temp == 700
    assert s.min_temp == 150
    assert s.active_errors == []


def test_heat_to_420_no_timer():
    s = status("B4292300A2010000A40100000000000000BC029600")
    assert s.heating
    assert s.cavity_temp == 418
    assert s.target_temp == 420


def test_heat_with_timer_fahrenheit():
    s = status("B42B23004A000000E10000720078006400BC029600")
    assert s.fahrenheit and s.heating and s.timer_active
    assert s.remaining_minutes == 114
    assert s.set_minutes == 120
    assert s.fan_intensity == 100


def test_celsius_heat_and_timer():
    s = status("B42A210016000000C9000077007800640073014100")
    assert not s.fahrenheit
    assert s.heating and s.timer_active
    assert s.cavity_temp == 22
    assert s.target_temp == 201
    assert s.remaining_minutes == 119
    assert s.max_temp == 371
    assert s.min_temp == 65


def test_celsius_no_target_is_none():
    # EF FF = -17, i.e. 0 °F converted to °C
    s = status("B42801001E000000EFFF0000000000000073014100")
    assert s.target_temp_raw == -17
    assert s.target_temp is None


def test_fahrenheit_no_target_is_none():
    s = status("B42903004C000000000000000000000000BC029600")
    assert s.target_temp is None


def test_error_bitmap():
    s = status("B42A210816000000C900006F007800640073014100")
    assert s.active_errors == [4]
    assert s.has_error(4)


def test_probes():
    p = protocol.parse_packet(bytes.fromhex("B30119000000000000000000000000000000"))
    assert isinstance(p, protocol.ProbeStatus)
    assert p.temperature(1) == 25
    assert p.temperature(2) is None

    p = protocol.parse_packet(bytes.fromhex("B30200004700000000000000000000000000"))
    assert p.temperature(2) == 71
    p = protocol.parse_packet(bytes.fromhex("B304000000004A0000000000000000000000"))
    assert p.temperature(3) == 74
    p = protocol.parse_packet(bytes.fromhex("B30800000000000017000000000000000000"))
    assert p.temperature(4) == 23


def test_power_off():
    assert isinstance(protocol.parse_packet(bytes.fromhex("B2000000")), protocol.PowerOff)
    assert isinstance(protocol.parse_packet(b"\x00"), protocol.PowerOff)


def test_assembler_split_packet():
    raw = bytes.fromhex("B42B23004A000000E10000720078006400BC029600")
    a = protocol.PacketAssembler()
    assert a.feed(raw[:20]) == []
    assert a.feed(raw[20:]) == [raw]
    assert a.feed(raw) == [raw]


def test_build_command():
    cmd = protocol.build_set_temp_and_time(225, 120)
    assert cmd == bytes([0xA1, 0x07, 0x05, 0x78, 0x00, 0xE1, 0x00])


# Handshake values from a capture of the official Android app.
def test_handshake_from_app_capture():
    hello = protocol.build_handshake(bytes.fromhex("8FF56A77A4BD040D"))
    assert hello == bytes.fromhex("0E088FF56A77A4BD040D")

    challenge = protocol.parse_handshake_challenge(bytes.fromhex("0A08CDBDB2CB9CE424AB"))
    assert challenge == bytes.fromhex("CDBDB2CB9CE424AB")
    assert protocol.build_handshake(challenge) == bytes.fromhex("0E08CDBDB2CB9CE424AB")

    assert protocol.is_handshake_accepted(bytes.fromhex("0B0000"))
    assert protocol.parse_handshake_challenge(bytes.fromhex("0B0000")) is None
    assert not protocol.is_handshake_accepted(bytes.fromhex("0A08CDBDB2CB9CE424AB"))


def test_build_hello_matches_app_on_validated_bytes():
    # From a capture of the official app talking to grill D8:BC:38:59:20:A6.
    mac = protocol.mac_to_bytes("D8:BC:38:59:20:A6")
    app_hello = bytes.fromhex("0E088FF56A77A4BD040D")
    hello = protocol.build_hello(mac)
    # The derived hello reproduces the app's nonce on every byte the
    # controller validates; the unchecked bytes are left zero.
    for index in protocol.HELLO_NONCE_MAC_MAP:
        assert hello[2 + index] == app_hello[2 + index]
    assert hello == bytes.fromhex("0E0800006A77A4BD000D")


def test_mac_to_bytes():
    assert protocol.mac_to_bytes("D8:BC:38:59:20:A6") == bytes.fromhex("D8BC385920A6")


def test_wifi_status_connected():
    pkt = protocol.parse_packet(bytes.fromhex("B51E000000"))
    assert isinstance(pkt, protocol.WifiStatus)
    assert pkt.wifi_connected
    assert pkt.states == [
        "Connected to Wi-Fi",
        "Connected to the internet",
        "Connected to the cloud service",
        "Synced with its cloud state",
    ]
    assert pkt.errors == []


def test_wifi_status_scan_reports_network_count():
    pkt = protocol.parse_packet(bytes.fromhex("B54004000C"))
    assert isinstance(pkt, protocol.WifiStatus)
    assert not pkt.wifi_connected
    assert pkt.states == ["Network list ready to send"]
    assert pkt.transfer_flags == 0x04
    assert pkt.networks_found == 12


def test_wifi_status_idle():
    pkt = protocol.parse_packet(bytes.fromhex("B500000000"))
    assert isinstance(pkt, protocol.WifiStatus)
    assert pkt.states == [] and pkt.errors == []


def test_set_target_temp_command():
    cmd = protocol.build_set_target_temp(250, fahrenheit=True, powered_on=True)
    assert cmd.hex(" ").upper() == "A4 11 01 00 00 00 00 FA 00 00"


def test_set_target_temp_command_celsius():
    cmd = protocol.build_set_target_temp(121, fahrenheit=False, powered_on=True)
    assert cmd.hex(" ").upper() == "A4 10 01 00 00 00 00 79 00 00"


def test_set_timer_command():
    cmd = protocol.build_set_timer(413, fahrenheit=True, powered_on=True)
    assert cmd.hex(" ").upper() == "A4 03 01 9D 01 00 00 00 00 00"


def test_status_request_command():
    assert protocol.build_status_request().hex(" ").upper() == "A2 00 00"


def test_set_probe_target_command():
    cmd = protocol.build_set_probe_target(1, 160)
    assert cmd.hex(" ").upper() == "A3 01 A0 00 00 00 00 00 00 00"


def test_set_probe_target_command_probe_4():
    cmd = protocol.build_set_probe_target(4, 300)
    assert cmd.hex(" ").upper() == "A3 08 00 00 00 00 00 00 2C 01"


def test_set_probe_target_rejects_probe_5():
    import pytest

    with pytest.raises(ValueError):
        protocol.build_set_probe_target(5, 160)


def test_command_keeps_power_bit_clear_when_off():
    cmd = protocol.build_set_timer(10, fahrenheit=True, powered_on=False)
    assert cmd[2] == 0


def test_powered_on_flag():
    assert status("B4292300A2010000A40100000000000000BC029600").powered_on
    assert not status("B429020048000000E10000000000000000BC029600").powered_on
