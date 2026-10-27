"""Interrupteurs d'activation de la gestion automatique."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import LuminaConfigEntry
from .const import KIND_CLIMATE, KIND_FANS, KIND_LIGHTS, SLEEP_MANUAL
from .entity import LuminaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuminaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller = entry.runtime_data
    entities: list[SwitchEntity] = [
        LuminaAutoSwitch(entry, kind)
        for kind in (KIND_LIGHTS, KIND_FANS, KIND_CLIMATE)
        if controller.groups[kind].entity_ids
    ]
    entities.append(LuminaForcedNightSwitch(entry))
    entities.append(LuminaSleepSwitch(entry))
    async_add_entities(entities)


class LuminaAutoSwitch(LuminaEntity, SwitchEntity, RestoreEntity):
    """Active ou suspend la gestion automatique d'un groupe."""

    def __init__(self, entry: LuminaConfigEntry, kind: str) -> None:
        super().__init__(entry, f"auto_{kind}")
        self._kind = kind

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in (STATE_ON, STATE_OFF):
            self._controller.set_enabled(self._kind, last_state.state == STATE_ON, reevaluate=False)

    @property
    def is_on(self) -> bool:
        return self._controller.groups[self._kind].enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._controller.set_enabled(self._kind, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._controller.set_enabled(self._kind, False)


class LuminaForcedNightSwitch(LuminaEntity, SwitchEntity, RestoreEntity):
    """Force le mode nuit jusqu'à la fin de la prochaine nuit."""

    def __init__(self, entry: LuminaConfigEntry) -> None:
        super().__init__(entry, "forced_night")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == STATE_ON:
            until = last_state.attributes.get("until")
            parsed = dt_util.parse_datetime(until) if isinstance(until, str) else None
            self._controller.set_forced_night(True, until=parsed, reevaluate=False)

    @property
    def is_on(self) -> bool:
        return self._controller.forced_night

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"until": self._controller.forced_night_until}

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._controller.set_forced_night(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._controller.set_forced_night(False)


class LuminaSleepSwitch(LuminaEntity, SwitchEntity, RestoreEntity):
    """Met la pièce en sommeil, jusqu'à la prochaine heure de fin de nuit au plus tard."""

    def __init__(self, entry: LuminaConfigEntry) -> None:
        super().__init__(entry, "sleeping")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == STATE_ON:
            until = last_state.attributes.get("until")
            parsed = dt_util.parse_datetime(until) if isinstance(until, str) else None
            attrs = last_state.attributes
            self._controller.start_sleep(
                source=attrs.get("source") or SLEEP_MANUAL,
                until=parsed,
                presence_seen=bool(attrs.get("presence_seen")),
                restored=True,
                reevaluate=False,
            )

    @property
    def is_on(self) -> bool:
        return self._controller.sleeping

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "until": self._controller.sleeping_until,
            "source": self._controller.sleep_source,
            "presence_seen": self._controller.sleep_presence_seen,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._controller.start_sleep()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._controller.wake()
