"""Capteur d'état de la pièce."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LuminaConfigEntry
from .const import ROOM_STATES
from .entity import LuminaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuminaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LuminaRoomStateSensor(entry)])


class LuminaRoomStateSensor(LuminaEntity, SensorEntity):
    """État de la pièce : occupée, vide ou en contrôle manuel."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ROOM_STATES

    def __init__(self, entry: LuminaConfigEntry) -> None:
        super().__init__(entry, "room_state")

    @property
    def native_value(self) -> str:
        return self._controller.room_state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._controller.attributes
