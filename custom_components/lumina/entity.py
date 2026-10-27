"""Entité de base partagée par les plateformes Lumina."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.loader import async_get_loaded_integration

from . import LuminaConfigEntry
from .const import DOMAIN


class LuminaEntity(Entity):
    """Entité rattachée à l'appareil virtuel d'une pièce."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: LuminaConfigEntry, key: str) -> None:
        self._controller = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Lumina",
            manufacturer="Lumina",
            entry_type=DeviceEntryType.SERVICE,
            sw_version=str(async_get_loaded_integration(self._controller.hass, DOMAIN).version),
            suggested_area=entry.title,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._controller.async_add_listener(self.async_write_ha_state))
