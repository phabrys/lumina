"""Choix du comportement des lumières quand la pièce en compte plusieurs."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import LuminaConfigEntry
from .const import KIND_LIGHTS, LIGHTS_MODES
from .entity import LuminaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuminaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if entry.runtime_data.groups[KIND_LIGHTS].entity_ids:
        async_add_entities([LuminaLightsModeSelect(entry)])


class LuminaLightsModeSelect(LuminaEntity, SelectEntity, RestoreEntity):
    """Toutes les lumières, ou seulement si aucune n'est déjà allumée."""

    _attr_options = LIGHTS_MODES
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: LuminaConfigEntry) -> None:
        super().__init__(entry, "lights_mode")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in LIGHTS_MODES:
            self._controller.set_lights_mode(last_state.state, reevaluate=False)

    @property
    def current_option(self) -> str:
        return self._controller.lights_mode

    async def async_select_option(self, option: str) -> None:
        self._controller.set_lights_mode(option)
