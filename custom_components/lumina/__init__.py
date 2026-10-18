"""Lumina : gestion automatique des lumières et ventilateurs par pièce."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .controller import RoomController

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

type LuminaConfigEntry = ConfigEntry[RoomController]


async def async_setup_entry(hass: HomeAssistant, entry: LuminaConfigEntry) -> bool:
    """Crée le contrôleur de la pièce et ses entités."""
    # Les options (si l'utilisateur a reconfiguré la pièce) remplacent les données initiales.
    config = entry.options or entry.data
    controller = RoomController(hass, entry.title, config)
    entry.runtime_data = controller

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    controller.async_start()
    entry.async_on_unload(controller.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LuminaConfigEntry) -> bool:
    """Décharge les entités de la pièce."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: LuminaConfigEntry) -> None:
    """Recharge la pièce après modification des options."""
    await hass.config_entries.async_reload(entry.entry_id)
