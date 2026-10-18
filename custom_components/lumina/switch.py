"""Interrupteurs d'activation de la gestion automatique."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import LuminaConfigEntry
from .const import KIND_FANS, KIND_LIGHTS
from .entity import LuminaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuminaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller = entry.runtime_data
    async_add_entities(
        LuminaAutoSwitch(entry, kind)
        for kind in (KIND_LIGHTS, KIND_FANS)
        if controller.groups[kind].entity_ids
    )


class LuminaAutoSwitch(LuminaEntity, SwitchEntity, RestoreEntity):
    """Active ou suspend la gestion automatique d'un groupe."""

    def __init__(self, entry: LuminaConfigEntry, kind: str) -> None:
        super().__init__(entry, f"auto_{kind}")
        self._kind = kind

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in (STATE_ON, STATE_OFF):
            self._controller.set_enabled(
                self._kind, last_state.state == STATE_ON, reevaluate=False
            )

    @property
    def is_on(self) -> bool:
        return self._controller.groups[self._kind].enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._controller.set_enabled(self._kind, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._controller.set_enabled(self._kind, False)
