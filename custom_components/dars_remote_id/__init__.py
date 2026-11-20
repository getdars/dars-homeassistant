"""The D.A.R.S. Drone Remote ID integration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .const import (
    CARD_FILENAME,
    CARD_VERSION,
    CONF_CONNECTION,
    CONF_DEVICE,
    CONF_FAA_LOOKUP,
    CONNECTION_BLUETOOTH,
    CONNECTION_NETWORK,
    CONNECTION_USB,
    DEFAULT_FAA_LOOKUP,
    DOMAIN,
)
from .coordinator import DarsCoordinator
from .stream import DarsStreamCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
]

_CARD_URL = f"/{DOMAIN}/{CARD_FILENAME}"
# Map libraries the card uses (Leaflet, MapLibre GL, maplibre-gl-leaflet), bundled
# in lib/ so the frontend never loads third-party code from a public CDN.
_LIB_URL = f"/{DOMAIN}/lib"
_CARD_REGISTERED = f"{DOMAIN}_card_registered"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up D.A.R.S. from a config entry."""
    await _async_register_card(hass)

    faa_lookup: bool = entry.options.get(CONF_FAA_LOOKUP, DEFAULT_FAA_LOOKUP)
    connection = entry.data.get(CONF_CONNECTION, CONNECTION_BLUETOOTH)
    coordinator: DarsCoordinator
    if connection == CONNECTION_USB:
        coordinator = DarsStreamCoordinator(
            hass, CONNECTION_USB, entry.data[CONF_DEVICE], None, entry.title,
            entry_id=entry.entry_id, faa_lookup=faa_lookup,
        )
    elif connection == CONNECTION_NETWORK:
        coordinator = DarsStreamCoordinator(
            hass, CONNECTION_NETWORK, entry.data[CONF_HOST], entry.data[CONF_PORT],
            entry.title, entry_id=entry.entry_id, faa_lookup=faa_lookup,
        )
    else:
        coordinator = DarsCoordinator(
            hass, entry.data[CONF_ADDRESS], entry.title,
            entry_id=entry.entry_id, faa_lookup=faa_lookup,
        )
    await coordinator.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload so a changed option (e.g. the FAA lookup) takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: DarsCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_stop()
    return unload_ok


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the bundled Lovelace map card and auto-load it on the frontend.

    This makes ``type: custom:dars-map-card`` available with no manual `www/`
    copy and no Lovelace resource entry — for both HACS and manual installs.
    It is best-effort: a failure here never blocks the integration setup.
    """
    if hass.data.get(_CARD_REGISTERED):
        return
    hass.data[_CARD_REGISTERED] = True
    try:
        # Imported lazily so an API change only disables the card, not the whole
        # integration.
        from homeassistant.components.frontend import add_extra_js_url
        from homeassistant.components.http import StaticPathConfig

        base = Path(__file__).parent
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(_CARD_URL, str(base / CARD_FILENAME), False),
                StaticPathConfig(_LIB_URL, str(base / "lib"), True),
            ]
        )
        add_extra_js_url(hass, f"{_CARD_URL}?v={CARD_VERSION}")
        _LOGGER.debug("Registered D.A.R.S. map card at %s", _CARD_URL)
    except Exception as err:  # noqa: BLE001 - card is optional cosmetic frontend
        hass.data[_CARD_REGISTERED] = False
        _LOGGER.warning("Could not register the D.A.R.S. map card: %s", err)
