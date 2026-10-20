"""Choix du comportement quand la pièce compte plusieurs lumières ou ventilateurs."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import LuminaConfigEntry
from .const import KIND_FANS, KIND_LIGHTS, MODES
from .entity import LuminaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuminaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    groups = entry.runtime_data.groups
    async_add_entities(
        LuminaModeSelect(entry, kind)
        for kind in (KIND_LIGHTS, KIND_FANS)
        if groups[kind].entity_ids
    )


class LuminaModeSelect(LuminaEntity, SelectEntity, RestoreEntity):
    """Tous les actionneurs du groupe, ou seulement si aucun n'est déjà allumé."""

    _attr_options = MODES
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: LuminaConfigEntry, kind: str) -> None:
        super().__init__(entry, f"{kind}_mode")
        self._kind = kind

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in MODES:
            self._controller.set_mode(self._kind, last_state.state, reevaluate=False)

    @property
    def current_option(self) -> str:
        return self._controller.groups[self._kind].mode

    async def async_select_option(self, option: str) -> None:
        self._controller.set_mode(self._kind, option)
