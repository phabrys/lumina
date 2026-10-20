"""Choix de comportement : plusieurs appareils, clim en pièce vide, ventilateurs."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import LuminaConfigEntry
from .const import (
    CLIMATE_ACTIONS,
    FANS_WITH_CLIMATE_MODES,
    KIND_CLIMATE,
    KIND_FANS,
    KIND_LIGHTS,
    MODES,
    SELECT_CLIMATE_VACANT_DAY,
    SELECT_CLIMATE_VACANT_NIGHT,
)
from .entity import LuminaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuminaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    groups = entry.runtime_data.groups
    entities: list[SelectEntity] = [
        LuminaModeSelect(entry, kind)
        for kind in (KIND_LIGHTS, KIND_FANS)
        if groups[kind].entity_ids
    ]
    if groups[KIND_CLIMATE].entity_ids:
        entities.extend(
            LuminaClimateActionSelect(entry, key)
            for key in (SELECT_CLIMATE_VACANT_DAY, SELECT_CLIMATE_VACANT_NIGHT)
        )
        if groups[KIND_FANS].entity_ids:
            entities.append(LuminaFansWithClimateSelect(entry))
    async_add_entities(entities)


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


class LuminaClimateActionSelect(LuminaEntity, SelectEntity, RestoreEntity):
    """Action sur les clims quand la pièce est vide, le jour ou la nuit."""

    _attr_options = CLIMATE_ACTIONS
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: LuminaConfigEntry, key: str) -> None:
        super().__init__(entry, key)
        self._key = key

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in CLIMATE_ACTIONS:
            self._controller.set_climate_action(
                self._key, last_state.state, reevaluate=False
            )

    @property
    def current_option(self) -> str:
        return self._controller.climate_actions[self._key]

    async def async_select_option(self, option: str) -> None:
        self._controller.set_climate_action(self._key, option)


class LuminaFansWithClimateSelect(LuminaEntity, SelectEntity, RestoreEntity):
    """Ventilateurs pendant que la clim tourne : normaux, en brassage ou arrêtés."""

    _attr_options = FANS_WITH_CLIMATE_MODES
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: LuminaConfigEntry) -> None:
        super().__init__(entry, "fans_with_climate")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in FANS_WITH_CLIMATE_MODES:
            self._controller.set_fans_with_climate(last_state.state, reevaluate=False)

    @property
    def current_option(self) -> str:
        return self._controller.fans_with_climate

    async def async_select_option(self, option: str) -> None:
        self._controller.set_fans_with_climate(option)
