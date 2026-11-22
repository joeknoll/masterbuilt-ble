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

### Option 1: HACS (recommended)

1. In Home Assistant, open **HACS**.
2. Open the menu (⋮) in the top-right corner and choose **Custom repositories**.
3. Add `https://github.com/joeknoll/masterbuilt-ble` with the type **Integration**.
4. Search for **Masterbuilt Grill**, open it, and click **Download**.
5. Restart Home Assistant.

### Option 2: Manual

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
- **Minimum / maximum settable temperature.**
- **Raw status packet, raw probe packet.** Diagnostic
  entities for people helping to decode the protocol.

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

When this happens, the integration automatically makes a one-time attempt to
switch the grill back to sending readings: it briefly reconnects to complete a
handshake the controller requires before it will stream readings again. This
runs once per connection session; if it succeeds the **Bluetooth readings**
sensor turns on and the readings entities come back, and the change persists so
later connections work straight away. Watch the debug log for
`attempting the one-time latch to enable Bluetooth readings` followed by
`packet B4 ...`.

If it does not help (for example the grill is actively connected to Wi-Fi and
the cloud), clearing the grill's saved Wi-Fi network also restores Bluetooth
readings. Check your grill's manual or ask Masterbuilt support how to do this
for your controller. Making the saved network unreachable, for example by
blocking the grill on your router, is not enough.

The Wi-Fi status packet is 5 bytes:

| Byte | Contents |
|---|---|
| 0 | `B5`, the packet type |
| 1 | Connection state (bitmap below) |
| 2 | Data transfer state during Wi-Fi setup (bitmap below) |
| 3 | Setup errors (bitmap below) |
| 4 | Number of Wi-Fi networks found in the last scan |

Each bit in bytes 1–3 is a separate flag:

| Bit | Value | Byte 1: connection state | Byte 2: data transfer | Byte 3: errors |
|---|---|---|---|---|
| 0 | `01` | Scanning for networks | Ready to receive data | Network not found |
| 1 | `02` | Connected to Wi-Fi | Received data | Wrong Wi-Fi password |
| 2 | `04` | Connected to the internet | Ready to send data | No Wi-Fi networks in range |
| 3 | `08` | Connected to the cloud service | Sent data | Network has no internet access |
| 4 | `10` | Synced with its cloud state | Finished sending data | Can't reach the cloud service |
| 5 | `20` | About to report its firmware version | — | Can't sync with the cloud |
| 6 | `40` | Network list ready to send | — | Firmware update failed |
| 7 | `80` | Busy connecting or updating | — | — |

Add the values together to read a byte. For example, byte 1 = `1E` is
`02 + 04 + 08 + 10`: connected to Wi-Fi, the internet and the cloud, and
synced. `00` means not connected.

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

### Help decode the protocol

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

| Bit | Value | Byte 1: configuration | Byte 2: operation |
|---|---|---|---|
| 0 | `01` | °F (clear = °C) | Powered on |
| 1 | `02` | Timer on | Bluetooth control enabled |
| 2 | `04` | Timer counts up | Door or lid open |
| 3 | `08` | Min/max temperatures present | Count-up timer running |
| 4 | `10` | Has a smoker element | Smoker element on |
| 5 | `20` | Has a fan (charcoal) | Fan on (heating) |
| 6 | `40` | Has a broiler | Broiler on |
| 7 | `80` | Has smoke on demand | Smoke on demand on |

Numbers are little-endian. A Gravity Series grill always reports
configuration bits 3 and 5, never configuration bits 4, 6 or 7, and never
operation bits 2, 4, 6 or 7, so it doesn't report the lid state. It sends 0
in bytes 6–7 and 10, and sends temperatures as whole numbers: it keeps them
in °F and, when set to °C, sends (°F − 32) × 5 / 9 rounded toward zero.
Err 2 (meat probe malfunction) is set when any probe reports a fault.

Open questions:

- The smoker element, broiler and smoke-on-demand fields haven't been seen
  in a capture; captures from grills that have them would confirm them.
- What operation bit 1 means, and whether operation bit 0 is the power
  state. Captures with the grill switched off or a count-up timer would
  help.
- Only Err 4 has been seen in a capture. Captures of other errors would
  confirm them.

To help, enable the raw packet sensors or debug logging, change one thing on
the grill at a time, and note which bytes change.

### Running the tests

The packet parser doesn't depend on Home Assistant, so the tests run with
plain `pytest` on Python 3.12 or newer:

```sh
pip install pytest
python -m pytest tests/
```

## Credits

The Bluetooth service, characteristics and control command were first
documented in Particle's
[ble-gateway-library](https://github.com/particle-iot/ble-gateway-library).

## License

Released under the [MIT License](LICENSE).
