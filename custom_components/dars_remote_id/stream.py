"""Wired feed for D.A.R.S. receivers: USB serial or TCP.

The receiver sends a MAVLink v2 stream (HEARTBEAT once a second plus one
DARS_RID frame per Remote ID message) over:

* USB, when the receiver is in USB mode; Home Assistant opens the serial port.
* RS485 (M5Stack ToughC5), in any mode; an RS485-to-Ethernet bridge such as the
  Waveshare RS485 TO ETH (B) in TCP-server mode turns it into a TCP stream.

This coordinator reuses the Bluetooth coordinator's drone registry, entity
helpers and make/model lookup; only the link is different. The link counts as
up while frames arrive, and is reopened when the port or socket closes or when
nothing valid has arrived for ``STREAM_IDLE_S`` seconds.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONNECTION_NETWORK,
    CONNECTION_USB,
    RECONNECT_S,
    STREAM_BAUD,
    STREAM_IDLE_S,
    TICK_S,
)
from .coordinator import DarsCoordinator
from .decoder import MAV_MSG_DARS_RID, MavlinkParser, parse_dars_rid

_LOGGER = logging.getLogger(__name__)


async def async_open_stream(
    connection: str, target: str, port: int | None
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Open the serial port or TCP socket. Raises on failure."""
    if connection == CONNECTION_NETWORK:
        return await asyncio.wait_for(
            asyncio.open_connection(target, port), timeout=10
        )
    # Imported here so a missing serial package only affects wired entries.
    import serial_asyncio_fast  # noqa: PLC0415

    reader, writer = await asyncio.wait_for(
        serial_asyncio_fast.open_serial_connection(url=target, baudrate=STREAM_BAUD),
        timeout=10,
    )
    # Leave the ESP32's USB-Serial/JTAG reset lines released. RTS first: the
    # chip resets on RTS asserted with DTR released, so never pass that state.
    ser = getattr(writer.transport, "serial", None)
    if ser is not None:
        with contextlib.suppress(Exception):
            ser.rts = False
            ser.dtr = False
    return reader, writer


async def _async_close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(writer.wait_closed(), timeout=2)


async def async_probe_stream(
    connection: str, target: str, port: int | None, timeout: float = 6.0
) -> bool:
    """Config-flow check: does a D.A.R.S. MAVLink stream arrive here?"""
    _LOGGER.debug("probe %s %s:%s: opening", connection, target, port)
    reader, writer = await async_open_stream(connection, target, port)
    _LOGGER.debug("probe %s: opened, waiting for frames", target)
    parser = MavlinkParser()
    got = 0
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while (remaining := deadline - loop.time()) > 0:
            try:
                data = await asyncio.wait_for(reader.read(1024), remaining)
            except asyncio.TimeoutError:
                break
            if not data:
                break
            got += len(data)
            if parser.feed(data):
                _LOGGER.debug("probe %s: D.A.R.S. frames found", target)
                return True
        _LOGGER.debug("probe %s: no frames (%d bytes read)", target, got)
        return False
    finally:
        await _async_close_writer(writer)


class DarsStreamCoordinator(DarsCoordinator):
    """Drone registry fed by a USB-serial or TCP MAVLink stream."""

    def __init__(
        self,
        hass: HomeAssistant,
        connection: str,
        target: str,
        port: int | None,
        name: str,
        *,
        entry_id: str,
        faa_lookup: bool = True,
    ) -> None:
        label = f"{target}:{port}" if connection == CONNECTION_NETWORK else target
        super().__init__(hass, label, name, entry_id=entry_id, faa_lookup=faa_lookup)
        # Keep the original spelling (the base class upper-cases BLE addresses).
        self.address = label
        self.connection = connection
        self._target = target
        self._port = port
        self.model_hint = (
            "D.A.R.S. receiver (USB)"
            if connection == CONNECTION_USB
            else "D.A.R.S. receiver (RS485 / network)"
        )
        # Shown as the drone's "source": the wired feed doesn't say which radio
        # heard it, so say how it reached Home Assistant instead.
        self._via = "USB" if connection == CONNECTION_USB else "RS485 (network)"
        self._task: asyncio.Task | None = None
        self._writer: asyncio.StreamWriter | None = None

    @property
    def device_connections(self) -> set[tuple[str, str]]:
        # No Bluetooth address; the device is identified by its config entry.
        return set()

    # ----- lifecycle ------------------------------------------------------- #
    async def async_start(self) -> None:
        # The 1 s housekeeping tick only (no Bluetooth callback).
        self._cancel_tick = async_track_time_interval(
            self.hass, self._async_tick, timedelta(seconds=TICK_S)
        )
        self._task = self.hass.async_create_background_task(
            self._async_run(), f"dars_remote_id stream {self.address}"
        )

    async def async_stop(self) -> None:
        self._closing = True
        if self._cancel_tick:
            self._cancel_tick()
            self._cancel_tick = None
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        await self._async_close()

    async def _async_close(self) -> None:
        writer, self._writer = self._writer, None
        was = self.connected
        self.connected = False
        if writer is not None:
            await _async_close_writer(writer)
        if was:
            self._async_notify()

    async def _async_run(self) -> None:
        while not self._closing:
            try:
                reader, self._writer = await async_open_stream(
                    self.connection, self._target, self._port
                )
                _LOGGER.debug("%s: stream opened", self.address)
                await self._async_read(reader)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - serial/socket errors vary
                _LOGGER.debug("%s: stream error (%s)", self.address, err)
            await self._async_close()
            if self._closing:
                break
            await asyncio.sleep(RECONNECT_S)

    async def _async_read(self, reader: asyncio.StreamReader) -> None:
        parser = MavlinkParser()
        while not self._closing:
            try:
                data = await asyncio.wait_for(reader.read(1024), STREAM_IDLE_S)
            except asyncio.TimeoutError:
                _LOGGER.debug(
                    "%s: no data for %ss, reopening", self.address, STREAM_IDLE_S
                )
                return
            if not data:
                _LOGGER.debug("%s: stream closed by the other side", self.address)
                return
            frames = parser.feed(data)
            self._frames_bad += parser.bad_frames
            parser.bad_frames = 0
            if not frames:
                continue
            if not self.connected:
                self.connected = True
                _LOGGER.debug("%s: receiving", self.address)
                self._async_notify()
            for msg_id, payload in frames:
                if msg_id != MAV_MSG_DARS_RID:
                    continue  # heartbeat: only keeps the link alive
                parsed = parse_dars_rid(payload)
                if parsed is None:
                    self._frames_bad += 1
                    continue
                self._frames_rx += 1
                self._ingest(*parsed)
                drone = self.drones.get(parsed[0])
                if drone is not None:
                    drone.via = self._via

    # ----- no GATT status on a wired feed --------------------------------- #
    async def _async_refresh_status(self) -> None:
        """The wired stream has no status read; liveness is the idle timeout."""
        return
