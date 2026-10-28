"""Choix de comportement : plusieurs appareils, clim en pièce vide, ventilateurs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import LuminaConfigEntry
from .const import (
    BEDTIME_MODES,
    CLIMATE_ACTIONS,
    FANS_WITH_CLIMATE_MODES,
    KIND_CLIMATE,
    KIND_FANS,
    KIND_LIGHTS,
    MODES,
    SELECT_BEDTIME,
    SELECT_CLIMATE_VACANT_DAY,
    SELECT_CLIMATE_VACANT_NIGHT,
)
from .controller import RoomController
from .entity import LuminaEntity


def _has(*kinds: str) -> Callable[[RoomController], bool]:
    """Condition d'existence : la pièce a des appareils de chacun de ces groupes."""
    return lambda controller: all(controller.groups[kind].entity_ids for kind in kinds)


@dataclass(frozen=True, kw_only=True)
class LuminaSelectDescription(SelectEntityDescription):
    """Description d'un choix : lecture, écriture et condition d'existence."""

    current: Callable[[RoomController], str]
    # (contrôleur, option, réévaluer)
    select: Callable[[RoomController, str, bool], None]
    requires: Callable[[RoomController], bool] | None = None


def _mode(kind: str) -> LuminaSelectDescription:
    """Tous les actionneurs du groupe, ou seulement si aucun n'est déjà allumé."""
    return LuminaSelectDescription(
        key=f"{kind}_mode",
        options=MODES,
        current=lambda c: c.groups[kind].mode,
        select=lambda c, option, reevaluate: c.set_mode(kind, option, reevaluate=reevaluate),
        requires=_has(kind),
    )


def _climate_action(key: str) -> LuminaSelectDescription:
    """Action sur les clims quand la pièce est vide, le jour ou la nuit."""
    return LuminaSelectDescription(
        key=key,
        options=CLIMATE_ACTIONS,
        current=lambda c: c.climate_actions[key],
        select=lambda c, option, reevaluate: c.set_climate_action(
            key, option, reevaluate=reevaluate
        ),
        requires=_has(KIND_CLIMATE),
    )


SELECTS: tuple[LuminaSelectDescription, ...] = (
    _mode(KIND_LIGHTS),
    _mode(KIND_FANS),
    _climate_action(SELECT_CLIMATE_VACANT_DAY),
    _climate_action(SELECT_CLIMATE_VACANT_NIGHT),
    # Ventilateurs pendant que la clim tourne : normaux, en brassage ou arrêtés
    LuminaSelectDescription(
        key="fans_with_climate",
        options=FANS_WITH_CLIMATE_MODES,
        current=lambda c: c.fans_with_climate,
        select=lambda c, option, reevaluate: c.set_fans_with_climate(option, reevaluate=reevaluate),
        requires=_has(KIND_CLIMATE, KIND_FANS),
    ),
    # Lumières éteintes à la main la nuit : contrôle manuel, ou sommeil
    LuminaSelectDescription(
        key=SELECT_BEDTIME,
        options=BEDTIME_MODES,
        current=lambda c: c.bedtime_gesture,
        select=lambda c, option, reevaluate: c.set_bedtime_gesture(option, reevaluate=reevaluate),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuminaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller = entry.runtime_data
    async_add_entities(
        LuminaSelect(entry, description)
        for description in SELECTS
        if description.requires is None or description.requires(controller)
    )


class LuminaSelect(LuminaEntity, SelectEntity, RestoreEntity):
    """Choix de comportement de la pièce, restauré après redémarrage."""

    _attr_entity_category = EntityCategory.CONFIG
    entity_description: LuminaSelectDescription

    def __init__(self, entry: LuminaConfigEntry, description: LuminaSelectDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self.options:
            self.entity_description.select(self._controller, last_state.state, False)

    @property
    def current_option(self) -> str:
        return self.entity_description.current(self._controller)

    async def async_select_option(self, option: str) -> None:
        self.entity_description.select(self._controller, option, True)
