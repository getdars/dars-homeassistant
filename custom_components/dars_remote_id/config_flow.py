"""Config flow for D.A.R.S. Drone Remote ID: Bluetooth (discovered or picked),
USB serial, or network (TCP, e.g. RS485 through an RS485-to-Ethernet bridge)."""

from __future__ import annotations

import logging
import os
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_CONNECTION,
    CONF_DEVICE,
    CONF_FAA_LOOKUP,
    CONNECTION_NETWORK,
    CONNECTION_USB,
    DEFAULT_FAA_LOOKUP,
    DEFAULT_NETWORK_PORT,
    DOMAIN,
    NAME_PREFIX,
)
from .stream import async_probe_stream

_LOGGER = logging.getLogger(__name__)


def _list_serial_ports() -> dict[str, str]:
    """Serial ports as {path: label}, preferring stable /dev/serial/by-id
    names (a ttyACM number can change after a reboot or re-plug)."""
    import serial.tools.list_ports  # noqa: PLC0415 - executor-only, optional dep

    by_id: dict[str, str] = {}
    by_id_dir = "/dev/serial/by-id"
    if os.path.isdir(by_id_dir):
        for name in os.listdir(by_id_dir):
            link = os.path.join(by_id_dir, name)
            by_id[os.path.realpath(link)] = link
    ports: dict[str, str] = {}
    for p in serial.tools.list_ports.comports():
        path = by_id.get(os.path.realpath(p.device), p.device)
        desc = p.description if p.description and p.description != "n/a" else ""
        if p.vid == 0x303A:
            desc = (desc + " - Espressif (D.A.R.S. boards)").strip(" -")
        ports[path] = f"{path} ({desc})" if desc else path
    return ports


async def _async_list_ports(hass: HomeAssistant) -> dict[str, str]:
    try:
        return await hass.async_add_executor_job(_list_serial_ports)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("serial port listing failed: %s", err)
        return {}


class DarsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for D.A.R.S. receivers."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options: turn the online FAA make/model lookup on or off."""
        return DarsOptionsFlow(config_entry)

    def __init__(self) -> None:
        self._address: str | None = None
        self._name: str | None = None
        self._discovered: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a device found by the Bluetooth integration."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._name = discovery_info.name or "D.A.R.S."
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered device."""
        assert self._address is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._name, data={CONF_ADDRESS: self._address}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm", description_placeholders={"name": self._name}
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual add: choose how the receiver is connected."""
        return self.async_show_menu(
            step_id="user", menu_options=["pick_bluetooth", "usb", "network"]
        )

    async def async_step_usb(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """USB: the receiver in USB mode, plugged into this machine."""
        errors: dict[str, str] = {}
        if user_input is not None:
            device = user_input[CONF_DEVICE].strip()
            await self.async_set_unique_id(f"usb:{device}")
            self._abort_if_unique_id_configured()
            try:
                ok = await async_probe_stream(CONNECTION_USB, device, None)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("USB probe of %s failed: %s", device, err)
                errors["base"] = "cannot_open"
            else:
                if ok:
                    return self.async_create_entry(
                        title="D.A.R.S. (USB)",
                        data={CONF_CONNECTION: CONNECTION_USB, CONF_DEVICE: device},
                    )
                errors["base"] = "no_data_usb"
        ports = await _async_list_ports(self.hass)
        default = next((p for p in ports if "303a" in p.lower() or "Espressif" in ports[p]), None)
        return self.async_show_form(
            step_id="usb",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEVICE,
                        default=(user_input or {}).get(CONF_DEVICE, default or vol.UNDEFINED),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=k, label=v)
                                for k, v in ports.items()
                            ],
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_network(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Network: TCP stream, e.g. the ToughC5's RS485 port through an
        RS485-to-Ethernet bridge in TCP-server mode."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            await self.async_set_unique_id(f"tcp:{host}:{port}")
            self._abort_if_unique_id_configured()
            try:
                ok = await async_probe_stream(CONNECTION_NETWORK, host, port)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("network probe of %s:%s failed: %s", host, port, err)
                errors["base"] = "cannot_connect"
            else:
                if ok:
                    return self.async_create_entry(
                        title=f"D.A.R.S. ({host})",
                        data={
                            CONF_CONNECTION: CONNECTION_NETWORK,
                            CONF_HOST: host,
                            CONF_PORT: port,
                        },
                    )
                errors["base"] = "no_data_network"
        prev = user_input or {}
        return self.async_show_form(
            step_id="network",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=prev.get(CONF_HOST, vol.UNDEFINED)): str,
                    vol.Required(
                        CONF_PORT, default=prev.get(CONF_PORT, DEFAULT_NETWORK_PORT)
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                }
            ),
            errors=errors,
        )

    async def async_step_pick_bluetooth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Bluetooth: list nearby, unconfigured D.A.R.S. receivers."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._discovered.get(address, "D.A.R.S."),
                data={CONF_ADDRESS: address},
            )

        current_addresses = self._async_current_ids()
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address in current_addresses or info.address in self._discovered:
                continue
            if (info.name or "").upper().startswith(NAME_PREFIX):
                self._discovered[info.address] = info.name

        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="pick_bluetooth",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: f"{name} ({address})"
                            for address, name in self._discovered.items()
                        }
                    )
                }
            ),
        )


class DarsOptionsFlow(OptionsFlow):
    """Integration options (Settings > Devices & services > D.A.R.S. > Configure)."""

    def __init__(self, entry: ConfigEntry) -> None:
        # Kept as our own attribute: works on HA 2024.8 (no built-in
        # config_entry) and avoids the deprecated assignment on newer versions.
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self._entry.options.get(CONF_FAA_LOOKUP, DEFAULT_FAA_LOOKUP)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_FAA_LOOKUP, default=current): bool}
            ),
        )
