"""Diagnostics support: dumps raw packets to help decode unknown bytes."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import MasterbuiltConfigEntry


def _hexify(data: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.hex(" ").upper() if isinstance(v, bytes) else v) for k, v in data.items()}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MasterbuiltConfigEntry
) -> dict[str, Any]:
    grill = entry.runtime_data.grill
    status = grill.status
    return {
        "address": grill.address,
        "connected": grill.connected,
        "powered_off": grill.powered_off,
        "status": _hexify(asdict(status)) | {
            "fahrenheit": status.fahrenheit,
            "timer_active": status.timer_active,
            "heating": status.heating,
            "target_temp": status.target_temp,
            "active_errors": status.active_errors,
            "config_flags_bin": f"{status.config_flags:08b}",
            "operation_flags_bin": f"{status.operation_flags:08b}",
            "error_flags_bin": f"{status.error_flags:08b}",
        }
        if status
        else None,
        "probes": _hexify(asdict(grill.probes)) if grill.probes else None,
        "last_unknown_packet": grill.last_unknown_packet.hex(" ").upper()
        if grill.last_unknown_packet
        else None,
    }
