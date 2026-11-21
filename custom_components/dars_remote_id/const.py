"""Constants for the D.A.R.S. Drone Remote ID integration."""

from __future__ import annotations

DOMAIN = "dars_remote_id"

# Bundled Lovelace card that the integration serves + auto-registers on the
# frontend. Bump when dars-map-card.js changes (used as a cache-busting query).
CARD_VERSION = "0.11.1"
CARD_FILENAME = "dars-map-card.js"

# GATT UUIDs — full 128-bit forms of the 16-bit UUIDs the D.A.R.S. firmware exposes.
SVC_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
DATA_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"  # notify: 34-byte detection frames
STATUS_UUID = "0000fff3-0000-1000-8000-00805f9b34fb"  # read: status/licence, write: settings

# Advertised BLE name prefix (e.g. "DARS-C5", "DARS-...").
NAME_PREFIX = "DARS"

# A drone drops off the active list this many seconds after its last frame.
DRONE_EXPIRE_S = 30.0

# Coordinator housekeeping tick: prune stale drones + refresh entity attributes.
TICK_S = 1.0

# Re-read the receiver status (battery, power) this often while connected.
STATUS_REFRESH_S = 60.0

# Delay before retrying a dropped/failed BLE connection.
RECONNECT_S = 10.0

# Option: look up each drone serial's declared make/model in the public FAA UAS
# Declaration of Compliance database (sends the serial to uasdoc.faa.gov).
CONF_FAA_LOOKUP = "faa_lookup"
DEFAULT_FAA_LOOKUP = True

# How the receiver is connected (config entry data "connection"; entries made
# before 0.11 have no key and are Bluetooth).
CONF_CONNECTION = "connection"
CONNECTION_BLUETOOTH = "bluetooth"
CONNECTION_USB = "usb"          # USB serial, receiver in USB mode
CONNECTION_NETWORK = "network"  # TCP, e.g. RS485 via an RS485-to-Ethernet bridge
CONF_DEVICE = "device"          # serial port path (USB)
# CONF_HOST / CONF_PORT from homeassistant.const are used for the network link.

# Wired feed (USB / RS485): MAVLink v2 at this baud rate; HEARTBEAT arrives
# once a second, so this long without a valid frame means the link is dead.
STREAM_BAUD = 115200
STREAM_IDLE_S = 10.0
DEFAULT_NETWORK_PORT = 4196     # Waveshare RS485 TO ETH (B) default TCP port
