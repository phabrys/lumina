"""Lumina : gestion automatique des lumières et ventilateurs par pièce."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_FANS, CONF_LIGHTS, CONF_PRESENCE, CONF_PRESENCE_HOLD
from .controller import RoomController

_LOGGER = logging.getLogger(__name__)

# Champs de configuration qui contiennent une liste d'entités
_LIST_FIELDS = (CONF_PRESENCE, CONF_PRESENCE_HOLD, CONF_LIGHTS, CONF_FANS)

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.SELECT,
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


def _normalize(config: dict) -> dict:
    """Garantit des listes pour tous les champs d'entités multiples."""
    result = dict(config)
    for field in _LIST_FIELDS:
        value = result.get(field)
        if value is None:
            result[field] = []
        elif isinstance(value, str):
            result[field] = [value]
        else:
            result[field] = list(value)
    return result


async def async_migrate_entry(hass: HomeAssistant, entry: LuminaConfigEntry) -> bool:
    """Met à jour la configuration d'une pièce créée par une version antérieure."""
    if entry.version > 1:
        # Configuration créée par une version plus récente de Lumina.
        return False

    if entry.minor_version < 2:
        hass.config_entries.async_update_entry(
            entry,
            data=_normalize(dict(entry.data)),
            options=_normalize(dict(entry.options)) if entry.options else {},
            minor_version=2,
        )

    _LOGGER.debug(
        "Pièce %s migrée en version %s.%s", entry.title, entry.version, entry.minor_version
    )
    return True
