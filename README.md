# Masterbuilt Grill for Home Assistant

A custom [Home Assistant](https://www.home-assistant.io/) integration that
connects to Masterbuilt Bluetooth grills and smokers and shows live grill
temperature, meat probe temperatures, the timer and error codes in Home
Assistant.

- **Local only.** It talks to the grill directly over Bluetooth LE, with no cloud account.
- **Automatic discovery.** Home Assistant finds the grill when it is switched on and in range.
- **Push updates.** Readings arrive as soon as the grill sends them.

> [!IMPORTANT]
> **The grill only sends readings over Bluetooth while it is not set up on
> Wi-Fi.** Once a grill has been set up on Wi-Fi, it sends only Wi-Fi
> status over Bluetooth, and this integration has no temperatures to show.
> The **Bluetooth readings** diagnostic sensor tells you which mode the grill
> is in. See [Only "Connected" has a value](#only-connected-has-a-value).

> [!NOTE]
> This is an unofficial, community project. It is not affiliated with or
> endorsed by Masterbuilt. The protocol was worked out from Bluetooth packet
> captures of a Gravity Series–style controller, so other models may behave
> differently.

## Requirements

- Home Assistant **2024.8** or newer.
- A Bluetooth adapter that Home Assistant can use, **or** an
  [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html)
  with `active: true`. The integration keeps a connection open, so the adapter
  or proxy needs a free connection slot.
- The grill must be within Bluetooth range of that adapter or proxy.

## Installation

### Option 1: Marketplace (recommended)

In Home Assistant **2026.11** or newer, Marketplace replaces HACS.

1. In Home Assistant, open **Marketplace**.
2. Click **Add from link** in the upper-right corner.
3. Paste `https://github.com/joeknoll/masterbuilt-ble` and add it.
4. Open **Masterbuilt Grill** and click **Download**.
5. Restart Home Assistant.

### Option 2: HACS (older Home Assistant versions)

1. In Home Assistant, open **HACS**.
2. Open the menu (⋮) in the top-right corner and choose **Custom repositories**.
3. Add `https://github.com/joeknoll/masterbuilt-ble` with the type **Integration**.
4. Search for **Masterbuilt Grill**, open it, and click **Download**.
5. Restart Home Assistant.

Marketplace and HACS both install the latest
[release](https://github.com/joeknoll/masterbuilt-ble/releases) and show its
version number.

### Option 3: Manual

1. Download this repository.
2. Copy the `custom_components/masterbuilt_ble` folder into your Home Assistant
   `config/custom_components/` folder. Create `custom_components` first if
   it doesn't exist.
3. Restart Home Assistant.

## Setup

1. **Close the Masterbuilt app on your phone.** The grill accepts only one
   Bluetooth connection at a time, so the integration can't connect while the
   app is connected.
2. Switch the grill on.
3. In Home Assistant, go to **Settings → Devices & services**. The grill
   should appear under **Discovered**. Click **Add** to set it up.
4. If it doesn't appear, click **Add integration**, search for
   **Masterbuilt Grill**, and pick your grill from the list.

If the grill still isn't found, see [Troubleshooting](#troubleshooting).

## What you get

| Entity | Type | Description |
|---|---|---|
| Grill temperature | Sensor | Temperature inside the grill. |
| Target temperature | Sensor | The temperature the grill is heating to. Shows *unknown* when no target is set. |
| Timer remaining | Sensor | Minutes left on the timer. |
| Timer set | Sensor | Total minutes the timer was set to. |
| Fan intensity | Sensor | How hard the fan is running, 0–100 %. |
| Probe 1–4 | Sensor | Meat probe temperatures. Show *unknown* when a probe is unplugged. |
| Heating | Binary sensor | On while the grill is heating. |
| Timer | Binary sensor | On while a timer is running. |
| Problem | Binary sensor | On when the grill reports any error. Its attributes list the active errors. |
| Err 1 – Err 5 | Binary sensor | One per grill error code (probe not plugged in, meat probe malfunction, overheated, charcoal failed to ignite, meat probe above 300 °F). |
| Connected | Binary sensor | Whether Home Assistant is connected to the grill. |
| Bluetooth readings | Binary sensor | On while the grill sends readings over Bluetooth. Off when the grill is in Wi-Fi mode and sends only Wi-Fi status; its attributes then show the Wi-Fi state, any Wi-Fi errors and the number of networks found. |

Temperatures use the scale the grill is set to (°F or °C). Home Assistant
converts them to the units your system uses.

Some entities are **disabled by default**. You can turn them on from the
device page if you want them:

- **Probe 5–8.** For controllers that support more than four probes.

## Controlling the grill (work in progress)

Setting the target temperature and timer from Home Assistant is a goal, but
it isn't available yet.

The command for this kind of controller has now been identified: a 10-byte
`A4` command written to the grill's settings characteristic (see
[`protocol.py`](custom_components/masterbuilt_ble/protocol.py)). An older
`A1` command, documented in Particle's
[ble-gateway-library](https://github.com/particle-iot/ble-gateway-library/blob/main/src/peripherals/masterbuilt-smoker.cpp)
for an earlier Masterbuilt smoker, had no effect on a Gravity Series grill.

The `A4` command is implemented, but the entities stay switched off until it
has been tested on a grill that is sending readings over Bluetooth. The
command carries the grill's current units and power state, so it can only
be sent once a status packet has arrived.

**Power off.** A **Power off** button turns the grill off.
It sends the `A4` command with the power bit clear (`A4 01 00 …` in °F).
This has been tested on a grill: afterwards the status packet reports the
power bit (operation bit 0) clear. The button is disabled by default; turn it
on from the device page. It is unavailable while the grill is off.
There is no power-on button: switching a charcoal grill on remotely with no
ignition source doesn't make sense.

Two more commands are implemented as experimental, with no entities yet:

- **`A3`, meat probe targets.** Sets the target temperature of probe 1–4.
  The format is confirmed in the controller firmware but hasn't been tested
  on a grill.
- **`A2`, status request (`A2 00 00`).** The official app sends this only to
  the oldest controllers. A Gravity Series grill ignores it and sends status
  on its own.

If you have a grill where control works, or a packet capture of it, please
[open an issue](https://github.com/joeknoll/masterbuilt-ble/issues).

## Troubleshooting

### The grill isn't discovered

- Make sure the Masterbuilt phone app is closed and the grill is switched on.
- Check that your Bluetooth adapter or proxy is working and has a free
  connection slot.
- The integration looks for devices that advertise the Bluetooth service
  `0000fff0-0000-1000-8000-00805f9b34fb` together with manufacturer ID
  `18498`, or whose name starts with `Masterbuilt`. To see what your grill
  actually advertises, go to **Settings → Connectivity → Bluetooth** and
  click the **advertisements** link to open the advertisement monitor. If
  your grill doesn't match, please open an issue with what you see there.

### The grill keeps disconnecting

- Move the adapter or proxy closer to the grill.
- Make sure nothing else (such as the phone app) is connecting to the grill.

### Only "Connected" has a value

Once a grill has been set up on Wi-Fi, it stops sending readings over
Bluetooth. The **Bluetooth readings** sensor turns off, and the other
entities show as unavailable. The grill sends Wi-Fi status packets
instead, which look like `packet B5 1E 00 00 00` in the debug log.

When this happens, the integration tries to switch the grill back to sending
readings by disconnecting and reconnecting once. The grill remembers the
setting, so later connections get readings straight away. Watch the debug log
for `reconnecting to switch on Bluetooth readings` followed by
`packet B4 ...`. A grill that is in Wi-Fi mode also sends Wi-Fi status
alongside its readings; that is normal.

If it does not help (for example the grill is actively connected to Wi-Fi and
the cloud), clearing the grill's saved Wi-Fi network also restores Bluetooth
readings. Check your grill's manual or ask Masterbuilt support how to do this
for your controller. Making the saved network unreachable, for example by
blocking the grill on your router, is not enough.

### Turn on debug logging

Add this to `configuration.yaml` and restart:

```yaml
logger:
  logs:
    custom_components.masterbuilt_ble: debug
```

Every Bluetooth packet is then written to the log as hex.

### Download diagnostics

On the grill's device page, open the menu (⋮) and
choose **Download diagnostics**. The file contains the most recent status and
probe packets (or the latest Wi-Fi status packet), with the bitmaps written
out in binary. Attaching it to an issue
is very helpful.

## Contributing

Bug reports, packet captures from other grill models, and pull requests are
welcome.

### Running the tests

The packet parser doesn't depend on Home Assistant, so the tests run with
plain `pytest` on Python 3.12 or newer:

```sh
pip install pytest
python -m pytest tests/
```

### Releasing (maintainers)

Create a GitHub release with a tag like `v0.2.0`. The release workflow
writes that version into `manifest.json` and attaches `masterbuilt_ble.zip`,
which Marketplace and HACS install.

## Packet Information

### Status Packet
The full packet layout is documented in
[`protocol.py`](custom_components/masterbuilt_ble/protocol.py), with each
field marked as confirmed or not. The status packet (`B4`, 21 bytes) looks
like this:

| Byte | Contents |
|---|---|
| 0 | `B4`, the packet type |
| 1 | Configuration bitmap (below) |
| 2 | Operation bitmap (below) |
| 3 | Errors: bit 0 = Err 1 … bit 4 = Err 5 |
| 4–5 | Grill temperature |
| 6–7 | Smoker element target temperature (0 without one) |
| 8–9 | Target temperature |
| 10 | Broiler level (low 4 bits), smoke-on-demand level (high 4 bits) |
| 11–12 | Timer minutes remaining (elapsed when counting up) |
| 13–14 | Timer minutes set (0 when counting up) |
| 15–16 | Fan intensity, 0–100 % |
| 17–18 | Maximum settable temperature |
| 19–20 | Minimum settable temperature |

| Bit | Byte 1: configuration | Byte 2: operation |
|---|---|---|
| 0 | °F (clear = °C) | Powered on |
| 1 | Timer on | Bluetooth control enabled |
| 2 | Timer counts up | Door or lid open |
| 3 | Min/max temperatures present | Count-up timer running |
| 4 | Has a smoker element | Smoker element on |
| 5 | Has a fan (charcoal) | Fan on (heating) |
| 6 | Has a broiler | Broiler on |
| 7 | Has smoke on demand | Smoke on demand on |

Numbers are little-endian. A Gravity Series grill always reports
configuration bits 3 and 5, never configuration bits 4, 6 or 7, and never
operation bits 2, 4, 6 or 7, so it doesn't report the lid state. It sends 0
in bytes 6–7 and 10, and sends temperatures as whole numbers.
Err 2 (meat probe malfunction) is set when any probe reports a fault.

### Wi-Fi Status Packet

The Wi-Fi status packet is 5 bytes:

| Byte | Contents |
|---|---|
| 0 | `B5`, the packet type |
| 1 | Connection state (bitmap below) |
| 2 | Data transfer state during Wi-Fi setup (bitmap below) |
| 3 | Setup errors (bitmap below) |
| 4 | Number of Wi-Fi networks found in the last scan |

Each bit in bytes 1–3 is a separate flag:

| Bit | Byte 1: connection state | Byte 2: data transfer | Byte 3: errors |
|---|---|---|---|
| 0 | Scanning for networks | Ready to receive data | Network not found |
| 1 | Connected to Wi-Fi | Received data | Wrong Wi-Fi password |
| 2 | Connected to the internet | Ready to send data | No Wi-Fi networks in range |
| 3 | Connected to the cloud service | Sent data | Network has no internet access |
| 4 | Synced with its cloud state | Finished sending data | Can't reach the cloud service |
| 5 | About to report its firmware version | — | Can't sync with the cloud |
| 6 | Network list ready to send | — | Firmware update failed |
| 7 | Busy connecting or updating | — | — |

For example, byte 1 = `1E` is connected to Wi-Fi, the internet and the cloud, and
synced. `00` means not connected.

## Credits

The Bluetooth service, characteristics and control command were first
documented in Particle's
[ble-gateway-library](https://github.com/particle-iot/ble-gateway-library).

## License

Released under the [MIT License](LICENSE).
