# D.A.R.S. Drone Remote ID — Home Assistant integration

Bring live drone **Remote ID** detections from a [D.A.R.S.](https://getdars.com)
receiver into Home Assistant over Bluetooth. The receiver passively picks up the
Remote ID that nearby drones broadcast (2.4 GHz / 5 GHz Wi‑Fi and Bluetooth) and
streams each detection to HA, where it becomes entities you can put on a
dashboard, a map, and into automations.

> **Local push.** The receiver talks to Home Assistant over a local Bluetooth
> link, with no D.A.R.S. cloud account or server involved. Two optional features
> do use the internet; both are described under
> [Privacy and network access](#privacy-and-network-access), and the FAA lookup
> can be turned off.

## What you get

Per receiver (one device in HA):

| Entity | Type | What it is |
| --- | --- | --- |
| **Drone detected** | binary_sensor (occupancy) | On while ≥ 1 drone is being detected. Attribute: `count`. |
| **Active drones** | sensor | Number of drones right now. Attribute `drones`: full list (id, source, RSSI, lat/lon, altitude, height, speed, heading, operator lat/lon). |
| **Nearest drone ID** | sensor | Serial/ID of the strongest‑signal drone. Attributes: that drone's telemetry. |
| **Nearest drone signal** | sensor (dBm) | RSSI of the strongest drone. |
| **Nearest drone** | device_tracker | Map marker following the strongest drone (with operator location in attributes). |
| **Drone *serial*** | device_tracker (one per drone) | Added automatically for each drone that broadcasts a serial number; shows that drone's position while it is being detected. |
| **Receiver connected** | binary_sensor (connectivity, diagnostic) | BLE link status. Attributes: `licensed`, `model` (detected board), `dual_band`, and `sd_card` (`logging` / `present` / `none`) on boards with a microSD slot. |
| **Receiver battery** | sensor (%, diagnostic) | Only on boards that report a battery (Waveshare ESP32‑C5 kit, M5Stack ToughC5). Unknown while on external power, because the charger then holds the cell full. Attribute: `voltage`. |
| **External power** | binary_sensor (plug, diagnostic) | Only on the same boards. On while the receiver runs from USB or DC. |

The device page shows which board is connected: M5Stack Unit C6L, Seeed XIAO
ESP32‑C5 (with or without the Expansion Board), Waveshare ESP32‑C5‑WIFI6‑KIT or
M5Stack ToughC5. Battery and power are re-read once a minute.

Automation ideas: announce on a speaker when *Drone detected* turns on, flash a
light, push a phone notification with the nearest drone's ID and distance, or log
the `drones` attribute to history.

## Integration icon

The icon and logo ship with the integration in
[`custom_components/dars_remote_id/brand/`](custom_components/dars_remote_id/brand/).

## Requirements

- Home Assistant **2024.8** or newer, and one way to reach the receiver:
  - **Bluetooth**: a working adapter in range of the receiver, either local or
    an [ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy/)
    (needs an *active‑connection* capable proxy);
  - **USB**: the receiver plugged into the Home Assistant machine and switched
    to **USB mode** in the D.A.R.S. app; or
  - **Network (RS485)**: an M5Stack ToughC5 wired from its RS485 port to an
    RS485‑to‑Ethernet bridge (see [Wired connections](#wired-connections-usb-and-rs485)).
- A genuine, **activated** D.A.R.S. receiver running current firmware: the
  2.4 GHz M5Stack Unit C6L, or a dual‑band (2.4 + 5 GHz) board — Seeed XIAO
  ESP32‑C5, Waveshare ESP32‑C5‑WIFI6‑KIT or M5Stack ToughC5. Get at
  [getdars.com](https://getdars.com/).

## Install (HACS)

1. HACS → ⋮ → **Custom repositories** → add this repo's URL, category
   **Integration**.
2. Install **D.A.R.S. Drone Remote ID**, then restart Home Assistant.
3. Over Bluetooth the receiver is usually **auto‑discovered** (Settings →
   Devices & Services → *Discovered*). Otherwise **+ Add Integration → D.A.R.S.
   Drone Remote ID** and choose **Bluetooth**, **USB cable** or **Network**.

Manual install: copy `custom_components/dars_remote_id/` into your HA
`config/custom_components/` and restart.

## Wired connections (USB and RS485)

Besides Bluetooth, the integration can read the receiver's wired feed: the same
MAVLink stream the D.A.R.S. Windows viewer and ATAK use (a heartbeat once a
second plus one frame per Remote ID message). Detections, the map card and the
drone trackers work the same way. The wired feed carries no battery or board
status, so those entities don't appear for a wired receiver.

**USB.** Plug the receiver into the Home Assistant machine, switch it to **USB
mode** in the D.A.R.S. app, then **+ Add Integration → D.A.R.S. Drone Remote ID
→ USB cable** and pick its serial port (D.A.R.S. boards show as *Espressif*;
`/dev/serial/by-id/…` names are kept so the port survives a re‑plug).

**RS485 over the network (M5Stack ToughC5).** The ToughC5 sends the same feed on
its RS485 port in every mode, 115200 baud 8N1. Wire it to an RS485‑to‑Ethernet
bridge, for example the Waveshare *RS485 TO ETH (B)*, set the bridge to **TCP
server**, 115200 8N1, then **+ Add Integration → D.A.R.S. Drone Remote ID →
Network** with the bridge's IP address and port (default 4196). ToughC5 RS485
port: GND (black), 6–24 V in (red), A (yellow), B (white); the bridge doesn't
supply power, so feed 12 V to both, for example from a PoE splitter.

The setup checks that D.A.R.S. data actually arrives before it saves. A wired
link counts as connected while frames arrive, and reconnects on its own when
the port or socket closes or nothing arrives for 10 seconds.

## Map card — bundled, no separate install

The integration **ships and auto-loads** a D.A.R.S.-styled map card
(`dars-map-card.js`) that plots every detected drone (marker per drone + operator,
tether line, popups, and a detection list) from `sensor.dars_active_drones`. It's
a **viewer** — the integration is what connects to the receiver and supplies the
data.

Nothing to install for the card: after the integration is set up (HACS or manual)
and Home Assistant is restarted, just add it to a dashboard:

```yaml
type: custom:dars-map-card
entity: sensor.dars_active_drones   # optional (auto-detected if omitted)
title: Drone Map                    # optional
map_style: Fiord                    # optional: Fiord | Dark Matter | Positron | Liberty | Bright
units: metric                       # optional: metric (m, m/s) | imperial (ft, mph)
show_takeoff: true                  # optional
show_replay: true                   # optional: show the Live/Replay controls
```

**Units.** `units` sets the default; each viewer can also flip metric ⇄ imperial
with the **m / ft** button in the card header (their choice is remembered on that
device). Matches the D.A.R.S. app (m→ft, m/s→mph).

**Map styles** use free‑for‑commercial [OpenFreeMap](https://openfreemap.org)
vector tiles (same styles as the D.A.R.S. app). The on‑map switcher remembers the
viewer's choice. See `ATTRIBUTIONS.md` for data/library licences.

**Live / History.** The card has a **Live** and a **History** mode. History reads
this receiver's past detections straight from Home Assistant's **Recorder** (no
extra storage) and lists them newest first, one row per detection, going back up
to 14 days. Pick a detection to replay it on the map with the **timeline
scrubber, play/pause and speed** controls, breadcrumb trail included. History
depends on Recorder retention (default ~10 days) and needs the drones sensor to
be recorded; a single history sample whose attributes exceed 16 KiB (≈ 60+
simultaneous drones) is dropped by HA. Set `show_replay: false` to hide the
controls.

The integration serves the card at `/dars_remote_id/dars-map-card.js` and
registers it as a frontend module automatically — no `www/` copy, no Lovelace
resource entry needed. (Hard-refresh the browser once after updating so the new
card JS is fetched.)

The map libraries (Leaflet, MapLibre GL JS, maplibre-gl-leaflet) are bundled
with the integration in `custom_components/dars_remote_id/lib/` and served by
Home Assistant at `/dars_remote_id/lib/`; nothing is loaded from a public CDN.
The base-map **tiles** do come from OpenFreeMap (see below), so without internet
on the viewing browser the map background stays empty and the card falls back
to the detection list (which always works). Drones without a GPS fix are listed
but not placed on the map.

## Privacy and network access

Detections travel from the receiver to Home Assistant over Bluetooth and stay in
your Home Assistant. Two optional features make requests to the internet:

- **FAA make/model lookup (Home Assistant server, on by default).** The first
  time the receiver picks up a drone that broadcasts a serial number, the
  integration sends that **serial number** to the public FAA UAS Declaration of
  Compliance database (`https://uasdoc.faa.gov`) to show the drone's declared
  make and model. One request per new serial, cached afterwards. Nothing else is
  sent (no location, no receiver or user data). Turn it off in **Settings →
  Devices & services → D.A.R.S. Drone Remote ID → Configure** → *Look up drone
  make and model online*.
- **Map tiles (viewing browser).** The map card fetches the base-map style and
  tiles from OpenFreeMap (`https://tiles.openfreemap.org`), like any web map.
  Those requests carry the map area being viewed and the browser's IP address,
  not drone data. Without the map card on a dashboard, no tile requests are
  made.

## How it works

Over Bluetooth, the receiver exposes a GATT service `0xFFF1` with a notify characteristic
`0xFFF2` that streams fixed 34‑byte frames (`mac`, `rssi`, `channel`, 25‑byte
ASTM F3411 message). The integration keeps a long‑lived connection, decodes each
frame (`decoder.py`, a faithful port of the D.A.R.S. web viewer's decoder, unit
tested for parity), maintains a registry of drones (dropped 30 s after their last
frame), and pushes entity updates. On connect, and then once a minute, it reads
the `0xFFF3` status for the licence flag, the board model and, where the board
reports them, battery and power.

## Notes & limits

- **Foreground live view.** The Android app remains the full product (background
  scanning, widget, EFB output, USB, PRO). This integration is the live feed for
  a Home Assistant dashboard.
- One receiver drives one BLE connection. Keep it in good range of the HA adapter
  or a Bluetooth proxy.
- Besides the *Nearest drone* tracker, each drone that broadcasts a serial
  number gets its own tracker, available while that drone is being detected.

## Dashboard & automation examples

> Entity IDs are built from the **device name** you gave the receiver, e.g. a
> device named *DARS C6L* yields `sensor.dars_c6l_active_drones`. The examples
> below use the slug `dars` — replace it with yours (Developer Tools → States).

**Map — nearest drone** (Lovelace, add as a Manual card):

```yaml
type: map
title: Drones
default_zoom: 12
hours_to_show: 0
entities:
  - entity: device_tracker.dars_nearest_drone
```

**Status panel:**

```yaml
type: entities
title: D.A.R.S.
entities:
  - entity: binary_sensor.dars_drone_detected
  - entity: sensor.dars_active_drones
  - entity: sensor.dars_nearest_drone_id
  - entity: sensor.dars_nearest_drone_signal
  - entity: binary_sensor.dars_receiver_connected
```

**Live drone table** (renders the full `drones` attribute):

```yaml
type: markdown
title: Detected drones
content: >
  {% set drones = state_attr('sensor.dars_active_drones', 'drones') %}
  {% if drones %}
  | ID | Source | RSSI | Alt m | Speed m/s | Heading |
  | --- | --- | ---: | ---: | ---: | ---: |
  {% for d in drones -%}
  | {{ d.id or d.mac }} | {{ d.source }} | {{ d.rssi }} | {{ d.altitude_m }} | {{ d.speed_mps }} | {{ d.heading }} |
  {% endfor %}
  {% else %}
  _No drones detected._
  {% endif %}
```

**Automation — notify on a new drone** (Settings → Automations → Edit in YAML):

```yaml
alias: Drone detected alert
triggers:
  - trigger: state
    entity_id: binary_sensor.dars_drone_detected
    from: "off"
    to: "on"
actions:
  - action: notify.notify
    data:
      title: Drone detected
      message: >
        {{ states('sensor.dars_active_drones') }} drone(s) nearby. Nearest:
        {{ states('sensor.dars_nearest_drone_id') }}
        ({{ states('sensor.dars_nearest_drone_signal') }} dBm).
```

Swap `notify.notify` for your mobile app service (e.g. `notify.mobile_app_phone`)
to get a push notification, or add a `light.turn_on` / `media_player` action to
flash a light or announce on a speaker.

## Development

`decoder.py` is Home Assistant independent and unit‑testable in isolation. The
byte layout and ODID math match the firmware and the web viewer exactly.

## License & attributions

Licensed under the **[MIT License](LICENSE)** (© getdars.com). Third‑party map
data and libraries remain under their own licences — see
**[ATTRIBUTIONS.md](ATTRIBUTIONS.md)** (OpenStreetMap / OpenFreeMap / OpenMapTiles,
Leaflet, MapLibre GL JS, maplibre‑gl‑leaflet, and the FAA UAS Declaration of
Compliance data).

---

*Not affiliated with Home Assistant or the Open Home Foundation. D.A.R.S. is
independent firmware; see [getdars.com/terms](https://getdars.com/terms).*
