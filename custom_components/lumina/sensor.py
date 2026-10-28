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
from .base import parse_datetime
from .const import KIND_CLIMATE, KIND_FANS, KIND_LIGHTS, ROOM_STATES
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
    # Hors de l'historique : les entités choisies, qui ne changent pas, et ce
    # qui change sans cesse (échéances en cours, température). L'état en
    # direct et la restauration au redémarrage les gardent.
    _unrecorded_attributes = frozenset(
        {
            "presence_sensors",
            "presence_still_sensors",
            "presence_hold_entities",
            "illuminance_sensor",
            "temperature_sensor",
            "humidity_sensor",
            "sleep_entity",
            "workday_entity",
            "holiday_calendars",
            "lights",
            "fans",
            "climates",
            "effective_temperature",
            "vacancy_at",
            "lights_off_at",
            "fans_off_at",
            "climate_vacant_at",
            "night_end_at",
        }
    )

    def __init__(self, entry: LuminaConfigEntry) -> None:
        super().__init__(entry, "room_state")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Les entrées du Journal de Lumina sont rattachées à ce capteur.
        self._controller.state_entity_id = self.entity_id
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        attrs = last_state.attributes
        if attrs.get("occupied") is True:
            self._controller.restore_occupied()
        # Réveil en cours (« lights_held_until » en 0.10.1)
        held_until = parse_datetime(attrs.get("wake_hold_until") or attrs.get("lights_held_until"))
        if held_until is not None:
            self._controller.restore_wake_hold(held_until)
        # Contrôles manuels en cours : un redémarrage la nuit ne doit pas
        # rallumer la lumière éteinte au coucher. Ancien nom avant 0.10.0.
        until_wake = attrs.get("overrides_until_wake") or attrs.get("overrides_until_morning") or []
        for kind in (KIND_LIGHTS, KIND_FANS, KIND_CLIMATE):
            until = parse_datetime(attrs.get(f"{kind}_override_until"))
            if until is not None:
                self._controller.restore_override(kind, until, until_wake=kind in until_wake)

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
