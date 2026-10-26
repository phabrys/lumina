"""Réglages de la pièce exposés en entités number."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LuminaConfigEntry
from .const import (
    KIND_CLIMATE,
    KIND_FANS,
    KIND_LIGHTS,
    SETTING_CLIMATE_VACANT_DELAY,
    SETTING_DAY_BRIGHTNESS,
    SETTING_DAY_COLOR_TEMP,
    SETTING_DAYLIGHT_OFF_LUX,
    SETTING_EVENING_BRIGHTNESS,
    SETTING_EVENING_COLOR_TEMP,
    SETTING_FAN_MIN_SPEED,
    SETTING_FAN_MIX_SPEED,
    SETTING_FAN_OFF_DELAY,
    SETTING_FAN_SPEED_RANGE,
    SETTING_LIGHT_OFF_DELAY,
    SETTING_LIGHT_WARNING,
    SETTING_LUX_THRESHOLD,
    SETTING_NIGHT_BRIGHTNESS,
    SETTING_NIGHT_COLOR_TEMP,
    SETTING_NIGHT_FAN_OFF_DELAY,
    SETTING_NIGHT_LIGHT_OFF_DELAY,
    SETTING_NIGHT_TEMP_THRESHOLD,
    SETTING_OVERRIDE_DURATION,
    SETTING_SLEEP_BRIGHTNESS,
    SETTING_SUNRISE_DELAY,
    SETTING_SUNSET_ADVANCE,
    SETTING_TEMP_THRESHOLD,
    SETTING_VACANCY_CONFIRM,
)
from .controller import RoomController
from .entity import LuminaEntity


def _has_lights(controller: RoomController) -> bool:
    return bool(controller.groups[KIND_LIGHTS].entity_ids)


def _has_fans(controller: RoomController) -> bool:
    return bool(controller.groups[KIND_FANS].entity_ids)


def _has_climates(controller: RoomController) -> bool:
    return bool(controller.groups[KIND_CLIMATE].entity_ids)


def _has_climates_and_fans(controller: RoomController) -> bool:
    return _has_climates(controller) and _has_fans(controller)


def _has_illuminance(controller: RoomController) -> bool:
    return controller.illuminance is not None and _has_lights(controller)


def _has_no_illuminance(controller: RoomController) -> bool:
    return controller.illuminance is None and _has_lights(controller)


def _has_temperature(controller: RoomController) -> bool:
    return controller.temperature is not None and _has_fans(controller)


@dataclass(frozen=True, kw_only=True)
class LuminaNumberDescription(NumberEntityDescription):
    """Description d'un réglage, avec sa condition d'existence."""

    requires: Callable[[RoomController], bool] | None = None


def _number(
    key: str,
    min_value: float,
    max_value: float,
    step: float,
    unit: str,
    *,
    slider: bool = False,
    requires: Callable[[RoomController], bool] | None = None,
) -> LuminaNumberDescription:
    """Réglage de configuration : bornes, pas, unité et condition d'existence."""
    return LuminaNumberDescription(
        key=key,
        translation_key=key,
        native_min_value=min_value,
        native_max_value=max_value,
        native_step=step,
        native_unit_of_measurement=unit,
        mode=NumberMode.SLIDER if slider else NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        requires=requires,
    )


NUMBERS: tuple[LuminaNumberDescription, ...] = (
    _number(SETTING_LUX_THRESHOLD, 0, 2000, 5, LIGHT_LUX, requires=_has_illuminance),
    _number(SETTING_LIGHT_OFF_DELAY, 0, 3600, 10, UnitOfTime.SECONDS, requires=_has_lights),
    _number(SETTING_FAN_OFF_DELAY, 0, 3600, 10, UnitOfTime.SECONDS, requires=_has_fans),
    _number(
        SETTING_TEMP_THRESHOLD, 18, 35, 0.5, UnitOfTemperature.CELSIUS,
        requires=_has_temperature,
    ),
    _number(SETTING_OVERRIDE_DURATION, 0, 240, 5, UnitOfTime.MINUTES),
    _number(SETTING_DAY_BRIGHTNESS, 1, 100, 1, PERCENTAGE, slider=True, requires=_has_lights),
    # --- Soirée ---
    _number(
        SETTING_EVENING_BRIGHTNESS, 1, 100, 1, PERCENTAGE, slider=True, requires=_has_lights
    ),
    # --- Nuit ---
    _number(SETTING_NIGHT_BRIGHTNESS, 0, 100, 1, PERCENTAGE, slider=True, requires=_has_lights),
    _number(SETTING_NIGHT_LIGHT_OFF_DELAY, 0, 3600, 10, UnitOfTime.SECONDS, requires=_has_lights),
    _number(SETTING_NIGHT_FAN_OFF_DELAY, 0, 14400, 60, UnitOfTime.SECONDS, requires=_has_fans),
    _number(
        SETTING_NIGHT_TEMP_THRESHOLD, 18, 35, 0.5, UnitOfTemperature.CELSIUS,
        requires=_has_temperature,
    ),
    # --- Sommeil ---
    _number(SETTING_SLEEP_BRIGHTNESS, 0, 100, 1, PERCENTAGE, slider=True, requires=_has_lights),
    _number(SETTING_VACANCY_CONFIRM, 0, 600, 5, UnitOfTime.SECONDS),
    _number(SETTING_DAYLIGHT_OFF_LUX, 0, 5000, 10, LIGHT_LUX, requires=_has_illuminance),
    _number(SETTING_SUNSET_ADVANCE, 0, 180, 5, UnitOfTime.MINUTES, requires=_has_no_illuminance),
    _number(SETTING_SUNRISE_DELAY, 0, 180, 5, UnitOfTime.MINUTES, requires=_has_no_illuminance),
    # --- Confort ---
    _number(SETTING_FAN_MIN_SPEED, 0, 100, 1, PERCENTAGE, slider=True, requires=_has_temperature),
    _number(
        SETTING_FAN_SPEED_RANGE, 0.5, 10, 0.5, UnitOfTemperature.CELSIUS,
        requires=_has_temperature,
    ),
    _number(SETTING_LIGHT_WARNING, 0, 120, 5, UnitOfTime.SECONDS, requires=_has_lights),
    _number(SETTING_DAY_COLOR_TEMP, 0, 6500, 100, UnitOfTemperature.KELVIN, requires=_has_lights),
    _number(
        SETTING_EVENING_COLOR_TEMP, 0, 6500, 100, UnitOfTemperature.KELVIN,
        requires=_has_lights,
    ),
    _number(SETTING_NIGHT_COLOR_TEMP, 0, 6500, 100, UnitOfTemperature.KELVIN, requires=_has_lights),
    # --- Clim ---
    _number(SETTING_CLIMATE_VACANT_DELAY, 0, 7200, 60, UnitOfTime.SECONDS, requires=_has_climates),
    _number(
        SETTING_FAN_MIX_SPEED, 10, 100, 1, PERCENTAGE,
        slider=True, requires=_has_climates_and_fans,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuminaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller = entry.runtime_data
    async_add_entities(
        LuminaNumber(entry, description)
        for description in NUMBERS
        if description.requires is None or description.requires(controller)
    )


class LuminaNumber(LuminaEntity, RestoreNumber):
    """Réglage de la pièce, restauré après redémarrage."""

    entity_description: LuminaNumberDescription

    def __init__(self, entry: LuminaConfigEntry, description: LuminaNumberDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._controller.update_setting(
                self.entity_description.key, last.native_value, reevaluate=False
            )

    @property
    def native_value(self) -> float:
        return self._controller.settings[self.entity_description.key]

    async def async_set_native_value(self, value: float) -> None:
        self._controller.update_setting(self.entity_description.key, value)
