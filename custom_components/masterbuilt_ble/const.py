"""Constants for the Masterbuilt grill integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "masterbuilt_ble"
MANUFACTURER: Final = "Masterbuilt"

# --- BLE GATT layout -------------------------------------------------------
# Taken from particle-iot/ble-gateway-library (masterbuilt-smoker.cpp).
SERVICE_UUID: Final = "426f7567-6854-6563-2d57-65694c69fff0"
# Written once right after connecting; the grill drops the link otherwise.
START_CHAR_UUID: Final = "426f7567-6854-6563-2d57-65694c69fff1"
# Commands (set temperature / timer).
CONTROL_CHAR_UUID: Final = "426f7567-6854-6563-2d57-65694c69fff3"
# Status / probe notifications.
NOTIFY_CHAR_UUID: Final = "426f7567-6854-6563-2d57-65694c69fff4"

INIT_PAYLOAD: Final = bytes(
    [0x0E, 0x08, 0x0E, 0x1C, 0x9B, 0x02, 0x7E, 0x09, 0xBA, 0x3B]
)

# --- Advertisement (discovery) ---------------------------------------------
# What the grill broadcasts before any connection. It does NOT advertise the
# 426f7567-... GATT service above; that only appears after connecting.
# Keep these in sync with the "bluetooth" matchers in manifest.json.
#
# Generic 16-bit 0xFFF0 service, used by many cheap BLE devices, so it is
# only trusted together with the manufacturer ID below.
ADVERTISED_SERVICE_UUID: Final = "0000fff0-0000-1000-8000-00805f9b34fb"
# Manufacturer data key 0x4842 ("BH"); its payload is the grill's MAC address.
ADVERTISED_MANUFACTURER_ID: Final = 0x4842  # 18498
# Fallback: advertised local names, e.g. "Masterbuilt Smoker".
LOCAL_NAME_PREFIXES: Final = ("Masterbuilt",)

# --- Connection management -------------------------------------------------
# How often the connection watchdog runs.
WATCHDOG_INTERVAL: Final = timedelta(seconds=30)
# Minimum delay between failed connection attempts.
RECONNECT_BACKOFF_SECONDS: Final = 30.0
# Drop and re-establish the link if no packet has arrived for this long.
STALE_DATA_SECONDS: Final = 90.0

NUM_PROBES: Final = 8
# Probes enabled by default (Gravity Series grills have 4 probe ports).
NUM_PROBES_ENABLED_DEFAULT: Final = 4

# Timer limits for the experimental timer control (minutes).
TIMER_MIN_MINUTES: Final = 0
TIMER_MAX_MINUTES: Final = 1440
