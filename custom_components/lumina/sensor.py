"""Capteur d'état de la pièce."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import LuminaConfigEntry
from .const import ROOM_STATES
from .entity import LuminaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuminaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller = entry.runtime_data
    entities: list[SensorEntity] = [LuminaRoomStateSensor(entry)]
    if controller.temperature and controller.humidity:
        entities.append(LuminaApparentTemperatureSensor(entry))
    async_add_entities(entities)


class LuminaRoomStateSensor(LuminaEntity, SensorEntity, RestoreEntity):
    """État de la pièce : occupée, vide ou en contrôle manuel."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ROOM_STATES

    def __init__(self, entry: LuminaConfigEntry) -> None:
        super().__init__(entry, "room_state")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Les entrées du Journal de Lumina sont rattachées à ce capteur.
        self._controller.state_entity_id = self.entity_id
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.attributes.get("occupied") is True:
            self._controller.restore_occupied()

    @property
    def native_value(self) -> str:
        return self._controller.room_state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._controller.attributes


class LuminaApparentTemperatureSensor(LuminaEntity, SensorEntity):
    """Température ressentie (indice de chaleur), utilisée pour les ventilateurs."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, entry: LuminaConfigEntry) -> None:
        super().__init__(entry, "apparent_temperature")

    @property
    def native_value(self) -> float | None:
        return self._controller.apparent_temperature
