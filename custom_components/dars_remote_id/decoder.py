"""ASTM F3411 Remote ID frame decoder for D.A.R.S. receivers.

This module is intentionally Home Assistant independent (pure Python, no HA
imports) so it can be unit-tested on its own. It is a faithful port of the
decoder in the D.A.R.S. Web Bluetooth viewer.

The receiver streams fixed 34-byte frames on GATT characteristic 0xFFF2::

    byte  [0:6]   source MAC (of the transmitting drone)
    byte  [6]     RSSI (int8, dBm)
    byte  [7]     firmware frame counter
    byte  [8:33]  25-byte ASTM F3411 / ASD-STAN Remote ID message
    byte  [33]    radio channel (0 = BLE, >14 = WiFi 5 GHz, else WiFi 2.4 GHz)
"""

from __future__ import annotations

from dataclasses import dataclass, field

FRAME_LEN = 34
_MSG_OFF = 8  # offset of the 25-byte ODID message inside a frame


# --------------------------------------------------------------------------- #
#  Little-endian byte helpers (match the viewer's i16/i32/int8 semantics)
# --------------------------------------------------------------------------- #
def _u16(b: bytes, o: int) -> int:
    return b[o] | (b[o + 1] << 8)


def _s32(b: bytes, o: int) -> int:
    v = b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)
    return v - 0x100000000 if v & 0x80000000 else v


def _s8(v: int) -> int:
    return v - 0x100 if v & 0x80 else v


def _ascii(b: bytes, o: int, n: int) -> str:
    """Printable-ASCII string, terminated at the first NUL (ODID strings are
    NUL-padded), then stripped."""
    out: list[str] = []
    for i in range(n):
        c = b[o + i]
        if c == 0:
            break
        if 32 <= c < 127:
            out.append(chr(c))
    return "".join(out).strip()


def mac_str(b: bytes, o: int = 0) -> str:
    return ":".join(f"{b[o + i]:02X}" for i in range(6))


# --------------------------------------------------------------------------- #
#  Drone model
# --------------------------------------------------------------------------- #
@dataclass
class DarsDrone:
    """Accumulated state for one detected drone (keyed by transmitter MAC)."""

    mac: str
    first: float  # monotonic time of first frame
    last: float = 0.0  # monotonic time of most recent frame
    rssi: int | None = None
    channel: int | None = None
    # Basic ID (message type 0)
    uas_id: str | None = None
    id_type: int | None = None
    ua_type: int | None = None
    # Location / Vector (message type 1)
    lat: float | None = None
    lon: float | None = None
    alt: float | None = None  # geodetic altitude, metres MSL
    height: float | None = None  # height above take-off, metres
    speed: float | None = None  # ground speed, m/s
    vspeed: float | None = None  # vertical speed, m/s
    heading: float | None = None  # track direction, degrees
    # System (message type 4)
    op_lat: float | None = None  # operator latitude
    op_lon: float | None = None  # operator longitude

    @property
    def source(self) -> str:
        if self.channel is None:
            return "unknown"
        if self.channel == 0:
            return "BLE"
        if self.channel > 14:
            return "WiFi 5 GHz"
        return "WiFi 2.4 GHz"

    def as_dict(self) -> dict:
        """Compact, JSON-friendly view for entity attributes."""
        return {
            "mac": self.mac,
            "id": self.uas_id,
            "source": self.source,
            "rssi": self.rssi,
            "lat": round(self.lat, 6) if self.lat is not None else None,
            "lon": round(self.lon, 6) if self.lon is not None else None,
            "altitude_m": round(self.alt) if self.alt is not None else None,
            "height_m": round(self.height) if self.height is not None else None,
            "speed_mps": round(self.speed, 1) if self.speed is not None else None,
            "heading": round(self.heading) if self.heading is not None else None,
            "takeoff_lat": round(self.op_lat, 6) if self.op_lat is not None else None,
            "takeoff_lon": round(self.op_lon, 6) if self.op_lon is not None else None,
        }


# --------------------------------------------------------------------------- #
#  Decode
# --------------------------------------------------------------------------- #
def parse_frame(data: bytes | bytearray) -> tuple[str, int, int, bytes] | None:
    """Split a raw 34-byte frame into (mac, rssi, channel, message). Returns
    None if the frame is too short."""
    if len(data) < FRAME_LEN:
        return None
    b = bytes(data)
    return mac_str(b, 0), _s8(b[6]), b[33], b[_MSG_OFF:_MSG_OFF + 25]


def apply_message(drone: DarsDrone, msg: bytes) -> None:
    """Merge a 25-byte ODID message into ``drone`` (mutates in place)."""
    t = (msg[0] >> 4) & 0x0F

    if t == 0:  # Basic ID
        id_type = (msg[1] >> 4) & 0x0F
        ua_type = msg[1] & 0x0F
        uas = _ascii(msg, 2, 20)
        # Keep an already-known serial (id_type 1) rather than letting a later
        # non-serial or empty Basic ID overwrite it.
        keep = drone.id_type == 1 and bool(drone.uas_id) and not (id_type == 1 and uas)
        if not keep:
            drone.id_type = id_type
            drone.ua_type = ua_type
            drone.uas_id = uas
    elif t == 1:  # Location / Vector
        b1 = msg[1]
        ew = (b1 >> 1) & 1  # E/W direction segment (adds 180° to track)
        mult = b1 & 1  # speed multiplier flag
        drone.lat = _s32(msg, 5) / 1e7
        drone.lon = _s32(msg, 9) / 1e7
        drone.alt = _u16(msg, 15) * 0.5 - 1000
        drone.height = _u16(msg, 17) * 0.5 - 1000
        drone.speed = msg[3] * 0.75 + 63.75 if mult else msg[3] * 0.25
        drone.vspeed = _s8(msg[4]) * 0.5
        drone.heading = msg[2] + (180 if ew else 0)
    elif t == 4:  # System (operator location)
        drone.op_lat = _s32(msg, 2) / 1e7
        drone.op_lon = _s32(msg, 6) / 1e7


def is_licensed(status: bytes | bytearray) -> bool:
    """Licence gate: the receiver's 0xFFF3 status read carries the VALID flag in
    bit 0 of byte 21. A genuine, activated D.A.R.S. unit sets it."""
    b = bytes(status)
    return len(b) >= 22 and (b[21] & 0x01) != 0


# --------------------------------------------------------------------------- #
#  Receiver status (0xFFF3 read) -> board model, battery, power
# --------------------------------------------------------------------------- #
# Same layout the D.A.R.S. Android app reads:
#   [0] audio  [1] mode  [2] LoRa region (0xFF on the ESP32-C5 boards, which have no LoRa)
#   [21] bit0 licence valid
#   C5 boards only:
#   [121] caps: 0x01 display, 0x02 buzzer, 0x04 SD card, 0x08 SD logging,
#               0x10 display on, 0x20 external power / charging, 0x40 battery fields valid
#   [122:124] battery mV (LE)   [124] battery %   (when caps & 0x40)
#   [125] board flags: 0x01 touch screen (M5Stack ToughC5), 0x02 touch enabled
MODEL_C6L = "M5Stack Unit C6L"
MODEL_XIAO = "Seeed XIAO ESP32-C5 (dual-band)"
MODEL_XIAO_EXP = "Seeed XIAO ESP32-C5 + Expansion Board (dual-band)"
MODEL_WAVESHARE = "Waveshare ESP32-C5-WIFI6-KIT (dual-band)"
MODEL_TOUGHC5 = "M5Stack ToughC5 (dual-band)"


@dataclass
class DarsStatus:
    """Decoded receiver status. ``battery_mv``/``battery_pct`` are None when the
    board reports no battery."""

    model: str = "Drone Remote ID receiver"
    dual_band: bool = False
    battery_mv: int | None = None
    battery_pct: int | None = None
    external_power: bool | None = None
    sd_card: str | None = None  # "logging" | "present" | "none"; None = no SD slot info

    @property
    def has_battery(self) -> bool:
        return self.battery_mv is not None


def parse_status(status: bytes | bytearray) -> DarsStatus:
    """Identify the board and read its battery/power state from a status read.
    Short or older payloads degrade to the generic model with no battery."""
    b = bytes(status)
    st = DarsStatus()
    if len(b) < 7:
        return st  # older firmware: too short to tell the board apart
    # The C6L fills the LoRa fields; the C5 boards send region 0xFF.
    if b[2] != 0xFF:
        st.model = MODEL_C6L
        return st
    st.dual_band = True
    caps = b[121] if len(b) >= 122 else 0
    flags = b[125] if len(b) >= 126 else 0
    if caps & 0x40 and len(b) >= 125:
        mv = _u16(b, 122)
        if mv > 0:
            st.battery_mv = mv
            st.battery_pct = min(100, b[124])
    if len(b) >= 122:
        st.external_power = bool(caps & 0x20)
    if flags & 0x01:
        st.model = MODEL_TOUGHC5
    elif st.has_battery:
        st.model = MODEL_WAVESHARE
    elif caps & 0x1F:
        st.model = MODEL_XIAO_EXP
    else:
        st.model = MODEL_XIAO
    if caps & 0x1F or flags & 0x01:
        st.sd_card = "logging" if caps & 0x08 else "present" if caps & 0x04 else "none"
    return st


# ---------------------------------------------------------------------------
# Wired feed: MAVLink v2 over USB serial or RS485 (via a serial-to-TCP bridge).
#
# The receiver's USB mode and its RS485 port send the same stream:
#   HEARTBEAT (msg 0, crc_extra 50) once a second, and
#   DARS_RID  (msg 12920, crc_extra 0x42) per ODID message, payload
#     mac[6] + rssi(int8) + counter(uint8) + data[25]  (33 bytes).
# The stream may carry other bytes too (a text banner, boot log); the parser
# resynchronises on the 0xFD start byte and drops any frame whose CRC fails.
# ---------------------------------------------------------------------------

MAV_STX_V2 = 0xFD
MAV_MSG_HEARTBEAT = 0
MAV_MSG_DARS_RID = 12920
_MAV_CRC_EXTRA = {MAV_MSG_HEARTBEAT: 50, MAV_MSG_DARS_RID: 0x42}
_MAV_HDR = 10        # STX..msgid
_MAV_SIG_LEN = 13    # present when incompat_flags & 0x01
_DARS_RID_LEN = 33


def _mav_crc(data: bytes, extra: int) -> int:
    crc = 0xFFFF
    for byte in (*data, extra):
        tmp = byte ^ (crc & 0xFF)
        tmp = (tmp ^ (tmp << 4)) & 0xFF
        crc = ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF
    return crc


class MavlinkParser:
    """Incremental MAVLink v2 reader. ``feed()`` returns the complete, CRC-valid
    frames of known message types as (msg_id, payload) pairs; partial data is
    kept for the next call. Bytes that are not a valid frame are skipped."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self.bad_frames = 0

    def feed(self, data: bytes | bytearray) -> list[tuple[int, bytes]]:
        buf = self._buf
        buf.extend(data)
        out: list[tuple[int, bytes]] = []
        while True:
            start = buf.find(MAV_STX_V2)
            if start < 0:
                buf.clear()
                break
            if start:
                del buf[:start]
            if len(buf) < _MAV_HDR:
                break
            plen = buf[1]
            total = _MAV_HDR + plen + 2 + (_MAV_SIG_LEN if buf[2] & 0x01 else 0)
            if len(buf) < total:
                break
            msg_id = buf[7] | (buf[8] << 8) | (buf[9] << 16)
            extra = _MAV_CRC_EXTRA.get(msg_id)
            crc_rx = buf[_MAV_HDR + plen] | (buf[_MAV_HDR + plen + 1] << 8)
            if extra is None or _mav_crc(bytes(buf[1:_MAV_HDR + plen]), extra) != crc_rx:
                # Not ours or corrupt: drop just this start byte and resync, so
                # a real frame starting inside the junk is not lost.
                if extra is not None:
                    self.bad_frames += 1
                del buf[0]
                continue
            out.append((msg_id, bytes(buf[_MAV_HDR:_MAV_HDR + plen])))
            del buf[:total]
        # Never let unparseable junk grow without bound.
        if len(buf) > 4096:
            del buf[:-512]
        return out


def parse_dars_rid(payload: bytes) -> tuple[str, int, int | None, bytes] | None:
    """DARS_RID payload -> (mac, rssi, channel, message) like ``parse_frame``.
    MAVLink v2 trims trailing zero bytes, so pad back to full length. The wired
    feed doesn't say which radio heard the drone, so the channel is None and the
    drone's source reads "unknown" (not "BLE")."""
    if len(payload) < 8:
        return None
    p = payload.ljust(_DARS_RID_LEN, b"\x00")
    return mac_str(p, 0), _s8(p[6]), None, p[8:33]
