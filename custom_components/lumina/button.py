"""Bouton de reprise immédiate de l'automatisme."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LuminaConfigEntry
from .entity import LuminaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuminaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LuminaResumeButton(entry)])


class LuminaResumeButton(LuminaEntity, ButtonEntity):
    """Met fin au contrôle manuel sans attendre la fin du délai."""

    def __init__(self, entry: LuminaConfigEntry) -> None:
        super().__init__(entry, "resume")

    async def async_press(self) -> None:
        self._controller.async_resume()
