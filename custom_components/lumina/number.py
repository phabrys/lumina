"""Réglages de la pièce exposés en entités number."""

from __future__ import annotations

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
    KIND_FANS,
    KIND_LIGHTS,
    SETTING_DAY_BRIGHTNESS,
    SETTING_DAY_COLOR_TEMP,
    SETTING_DAYLIGHT_OFF_LUX,
    SETTING_FAN_MIN_SPEED,
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
    SETTING_TEMP_THRESHOLD,
    SETTING_VACANCY_CONFIRM,
)
from .controller import RoomController
from .entity import LuminaEntity


@dataclass(frozen=True, kw_only=True)
class LuminaNumberDescription(NumberEntityDescription):
    """Description d'un réglage, avec sa condition d'existence."""

    requires: str | None = None


NUMBERS: tuple[LuminaNumberDescription, ...] = (
    LuminaNumberDescription(
        key=SETTING_LUX_THRESHOLD,
        translation_key=SETTING_LUX_THRESHOLD,
        native_min_value=0,
        native_max_value=2000,
        native_step=5,
        native_unit_of_measurement=LIGHT_LUX,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        requires="illuminance",
    ),
    LuminaNumberDescription(
        key=SETTING_LIGHT_OFF_DELAY,
        translation_key=SETTING_LIGHT_OFF_DELAY,
        native_min_value=0,
        native_max_value=3600,
        native_step=10,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        requires=KIND_LIGHTS,
    ),
    LuminaNumberDescription(
        key=SETTING_FAN_OFF_DELAY,
        translation_key=SETTING_FAN_OFF_DELAY,
        native_min_value=0,
        native_max_value=3600,
        native_step=10,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        requires=KIND_FANS,
    ),
    LuminaNumberDescription(
        key=SETTING_TEMP_THRESHOLD,
        translation_key=SETTING_TEMP_THRESHOLD,
        native_min_value=18,
        native_max_value=35,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        requires="temperature",
    ),
    LuminaNumberDescription(
        key=SETTING_OVERRIDE_DURATION,
        translation_key=SETTING_OVERRIDE_DURATION,
        native_min_value=0,
        native_max_value=240,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    LuminaNumberDescription(
        key=SETTING_DAY_BRIGHTNESS,
        translation_key=SETTING_DAY_BRIGHTNESS,
        native_min_value=1,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        requires=KIND_LIGHTS,
    ),
    # --- Nuit ---
    LuminaNumberDescription(
        key=SETTING_NIGHT_BRIGHTNESS,
        translation_key=SETTING_NIGHT_BRIGHTNESS,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        requires=KIND_LIGHTS,
    ),
    LuminaNumberDescription(
        key=SETTING_NIGHT_LIGHT_OFF_DELAY,
        translation_key=SETTING_NIGHT_LIGHT_OFF_DELAY,
        native_min_value=0,
        native_max_value=3600,
        native_step=10,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        requires=KIND_LIGHTS,
    ),
    LuminaNumberDescription(
        key=SETTING_NIGHT_FAN_OFF_DELAY,
        translation_key=SETTING_NIGHT_FAN_OFF_DELAY,
        native_min_value=0,
        native_max_value=14400,
        native_step=60,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        requires=KIND_FANS,
    ),
    LuminaNumberDescription(
        key=SETTING_NIGHT_TEMP_THRESHOLD,
        translation_key=SETTING_NIGHT_TEMP_THRESHOLD,
        native_min_value=18,
        native_max_value=35,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        requires="temperature",
    ),
    LuminaNumberDescription(
        key=SETTING_VACANCY_CONFIRM,
        translation_key=SETTING_VACANCY_CONFIRM,
        native_min_value=0,
        native_max_value=600,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    LuminaNumberDescription(
        key=SETTING_DAYLIGHT_OFF_LUX,
        translation_key=SETTING_DAYLIGHT_OFF_LUX,
        native_min_value=0,
        native_max_value=5000,
        native_step=10,
        native_unit_of_measurement=LIGHT_LUX,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        requires="illuminance",
    ),
    # --- Confort ---
    LuminaNumberDescription(
        key=SETTING_FAN_MIN_SPEED,
        translation_key=SETTING_FAN_MIN_SPEED,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        requires="temperature",
    ),
    LuminaNumberDescription(
        key=SETTING_FAN_SPEED_RANGE,
        translation_key=SETTING_FAN_SPEED_RANGE,
        native_min_value=0.5,
        native_max_value=10,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        requires="temperature",
    ),
    LuminaNumberDescription(
        key=SETTING_LIGHT_WARNING,
        translation_key=SETTING_LIGHT_WARNING,
        native_min_value=0,
        native_max_value=120,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        requires=KIND_LIGHTS,
    ),
    LuminaNumberDescription(
        key=SETTING_DAY_COLOR_TEMP,
        translation_key=SETTING_DAY_COLOR_TEMP,
        native_min_value=0,
        native_max_value=6500,
        native_step=100,
        native_unit_of_measurement=UnitOfTemperature.KELVIN,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        requires=KIND_LIGHTS,
    ),
    LuminaNumberDescription(
        key=SETTING_NIGHT_COLOR_TEMP,
        translation_key=SETTING_NIGHT_COLOR_TEMP,
        native_min_value=0,
        native_max_value=6500,
        native_step=100,
        native_unit_of_measurement=UnitOfTemperature.KELVIN,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        requires=KIND_LIGHTS,
    ),
)


def _is_relevant(controller: RoomController, requires: str | None) -> bool:
    if requires is None:
        return True
    if requires == "illuminance":
        return controller.illuminance is not None and bool(
            controller.groups[KIND_LIGHTS].entity_ids
        )
    if requires == "temperature":
        return controller.temperature is not None and bool(
            controller.groups[KIND_FANS].entity_ids
        )
    return bool(controller.groups[requires].entity_ids)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuminaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller = entry.runtime_data
    async_add_entities(
        LuminaNumber(entry, description)
        for description in NUMBERS
        if _is_relevant(controller, description.requires)
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
