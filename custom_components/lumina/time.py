"""Plage de nuit de la pièce, exposée en entités time."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import LuminaConfigEntry
from .const import TIME_NIGHT_END, TIME_NIGHT_START
from .entity import LuminaEntity

TIMES: tuple[TimeEntityDescription, ...] = (
    TimeEntityDescription(
        key=TIME_NIGHT_START,
        translation_key=TIME_NIGHT_START,
        entity_category=EntityCategory.CONFIG,
    ),
    TimeEntityDescription(
        key=TIME_NIGHT_END,
        translation_key=TIME_NIGHT_END,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuminaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(LuminaTime(entry, description) for description in TIMES)


class LuminaTime(LuminaEntity, TimeEntity, RestoreEntity):
    """Début ou fin de la nuit, restauré après redémarrage."""

    def __init__(self, entry: LuminaConfigEntry, description: TimeEntityDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        try:
            value = time.fromisoformat(last_state.state)
        except ValueError:
            return
        self._controller.update_time(self.entity_description.key, value, reevaluate=False)

    @property
    def native_value(self) -> time:
        return self._controller.times[self.entity_description.key]

    async def async_set_value(self, value: time) -> None:
        self._controller.update_time(self.entity_description.key, value)
