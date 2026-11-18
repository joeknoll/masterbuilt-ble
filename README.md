# Masterbuilt Grill for Home Assistant

A custom [Home Assistant](https://www.home-assistant.io/) integration that
connects to Masterbuilt Bluetooth grills and smokers and shows live grill
temperature, meat probe temperatures, the timer and error codes in Home
Assistant.

- **Local only.** It talks to the grill directly over Bluetooth LE, with no cloud account.
- **Automatic discovery.** Home Assistant finds the grill when it is switched on and in range.
- **Push updates.** Readings arrive as soon as the grill sends them.

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
| Probe 1–4 | Sensor | Meat probe temperatures. Show *unknown* when a probe is unplugged. |
| Heating | Binary sensor | On while the grill is heating. |
| Timer | Binary sensor | On while a timer is running. |
| Problem | Binary sensor | On when the grill reports any error. Its attributes list the active errors. |
| Err 1 – Err 5 | Binary sensor | One per grill error code (probe not plugged in, meat probe malfunction, overheated, charcoal failed to ignite, meat probe above 300 °F). |
| Connected | Binary sensor | Whether Home Assistant is connected to the grill. |

Temperatures use the scale the grill is set to (°F or °C). Home Assistant
converts them to the units your system uses.

Some entities are **disabled by default**. You can turn them on from the
device page if you want them:

- **Probe 5–8.** For controllers that support more than four probes.
- **Minimum / maximum settable temperature.**
- **Raw status packet, raw probe packet, status byte 15.** Diagnostic
  entities for people helping to decode the protocol.
- **Set target temperature / Set timer (experimental).** See
  [Controlling the grill](#controlling-the-grill-experimental).

## Controlling the grill (experimental)

> [!WARNING]
> Remote control is untested on most grills. Only try it while you are
> standing next to the grill and can see its display.

The integration includes two number entities that send a "set temperature and
timer" command to the grill. The command comes from Particle's
[ble-gateway-library](https://github.com/particle-iot/ble-gateway-library/blob/main/src/peripherals/masterbuilt-smoker.cpp),
which was written for an older Masterbuilt smoker. It may or may not work on
your grill.

To try it:

1. On the grill's device page, enable **Set target temperature (experimental)**
   and **Set timer (experimental)**.
2. With the grill on, set a new value.
3. Check that the grill's display and the **Target temperature** sensor both
   change.

The grill expects the temperature and timer in the same command. When you
change the temperature, the integration resends the minutes left on the timer
(or 0 if no timer is running). When you change the timer, it resends the
current target temperature.

If nothing happens, turn on debug logging (below) and check whether the
command was sent. Please [open an issue](https://github.com/joeknoll/masterbuilt-ble/issues)
with your grill model and what you saw.

## Troubleshooting

**The grill isn't discovered.**

- Make sure the Masterbuilt phone app is closed and the grill is switched on.
- Check that your Bluetooth adapter or proxy is working and has a free
  connection slot.
- The integration looks for devices that advertise the Bluetooth service
  `0000fff0-0000-1000-8000-00805f9b34fb` together with manufacturer ID
  `18498`, or whose name starts with `Masterbuilt`. To see what your grill
  actually advertises, go to **Settings → Connectivity → Bluetooth** and
  click the **advertisements** link to open the advertisement monitor. If
  your grill doesn't match, please open an issue with what you see there.

**The grill keeps disconnecting.**

- Move the adapter or proxy closer to the grill.
- Make sure nothing else (such as the phone app) is connecting to the grill.

**Turn on debug logging.** Add this to `configuration.yaml` and restart:

```yaml
logger:
  logs:
    custom_components.masterbuilt_ble: debug
```

Every Bluetooth packet is then written to the log as hex.

**Download diagnostics.** On the grill's device page, open the menu (⋮) and
choose **Download diagnostics**. The file contains the most recent status and
probe packets, with the bitmaps written out in binary. Attaching it to an issue
is very helpful.

## Contributing

Bug reports, packet captures from other grill models, and pull requests are
welcome.

### Help decode the protocol

Some fields in the grill's status packet are still unknown. The packet layout
is documented in [`protocol.py`](custom_components/masterbuilt_ble/protocol.py).
Open questions:

- Status bytes 6–7, 10 and 16.
- Byte 15 is `0x64` (100) in most heating captures. It might be the fan speed in percent.
- Operation bitmap bit 0.
- Configuration bits 3 and 5, which are always set in captures so far.
- In one "lid open" capture, the target temperature changes to 700 (`BC 02`).

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
