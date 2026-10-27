"""Config flow de Lumina : une entrée de configuration par pièce."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    selector,
)

from .const import (
    CONF_AREA,
    CONF_CLIMATES,
    CONF_FANS,
    CONF_HOLIDAYS,
    CONF_HUMIDITY,
    CONF_ILLUMINANCE,
    CONF_LIGHTS,
    CONF_PRESENCE,
    CONF_PRESENCE_HOLD,
    CONF_PRESENCE_STILL,
    CONF_SLEEP,
    CONF_TEMPERATURE,
    CONF_WORKDAY,
    DOMAIN,
)

PRESENCE_DEVICE_CLASSES = ["motion", "occupancy", "presence"]
SLEEP_DOMAINS = ["binary_sensor", "input_boolean", "switch"]
HOLD_DOMAINS = ["media_player", "binary_sensor", "switch", "input_boolean", "remote", "climate"]


def _area_entities(hass: HomeAssistant, area_id: str) -> list[er.RegistryEntry]:
    """Entités rattachées à la pièce, directement ou via leur appareil."""
    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_area(ent_reg, area_id)
    for device in dr.async_entries_for_area(dr.async_get(hass), area_id):
        # Une entité affectée à une autre pièce que son appareil n'en fait pas partie.
        entries.extend(
            entry
            for entry in er.async_entries_for_device(ent_reg, device.id)
            if entry.area_id is None
        )
    return [
        entry for entry in entries if entry.disabled_by is None and entry.entity_category is None
    ]


def _discover(hass: HomeAssistant, area_id: str) -> dict[str, Any]:
    """Propose des entités par défaut à partir du contenu de la pièce."""
    presence: list[str] = []
    hold: list[str] = []
    lights: list[str] = []
    fans: list[str] = []
    climates: list[str] = []
    illuminance: str | None = None
    temperature: str | None = None
    humidity: str | None = None

    for entry in _area_entities(hass, area_id):
        device_class = entry.device_class or entry.original_device_class
        if entry.domain == "binary_sensor" and device_class in PRESENCE_DEVICE_CLASSES:
            presence.append(entry.entity_id)
        elif entry.domain == "light":
            lights.append(entry.entity_id)
        elif entry.domain == "fan":
            fans.append(entry.entity_id)
        elif entry.domain == "climate":
            climates.append(entry.entity_id)
        elif entry.domain == "sensor" and device_class == "illuminance":
            illuminance = illuminance or entry.entity_id
        elif entry.domain == "sensor" and device_class == "temperature":
            temperature = temperature or entry.entity_id
        elif entry.domain == "sensor" and device_class == "humidity":
            humidity = humidity or entry.entity_id
        elif entry.domain == "media_player":
            hold.append(entry.entity_id)

    defaults: dict[str, Any] = {
        CONF_PRESENCE: presence,
        CONF_PRESENCE_HOLD: hold,
        CONF_LIGHTS: lights,
        CONF_FANS: fans,
        CONF_CLIMATES: climates,
    }
    if illuminance:
        defaults[CONF_ILLUMINANCE] = illuminance
    if temperature:
        defaults[CONF_TEMPERATURE] = temperature
    if humidity:
        defaults[CONF_HUMIDITY] = humidity
    return defaults


def _entities_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Formulaire de choix des entités, prérempli avec les valeurs suggérées."""

    def suggested(key: str) -> dict[str, Any]:
        return {"suggested_value": defaults.get(key)}

    return vol.Schema(
        {
            vol.Required(CONF_PRESENCE, description=suggested(CONF_PRESENCE)): (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        filter=[
                            selector.EntityFilterSelectorConfig(
                                domain="binary_sensor",
                                device_class=PRESENCE_DEVICE_CLASSES,
                            )
                        ],
                        multiple=True,
                    )
                )
            ),
            vol.Optional(CONF_PRESENCE_STILL, description=suggested(CONF_PRESENCE_STILL)): (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        filter=[
                            selector.EntityFilterSelectorConfig(
                                domain="binary_sensor",
                                device_class=PRESENCE_DEVICE_CLASSES,
                            )
                        ],
                        multiple=True,
                    )
                )
            ),
            vol.Optional(CONF_PRESENCE_HOLD, description=suggested(CONF_PRESENCE_HOLD)): (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=HOLD_DOMAINS, multiple=True)
                )
            ),
            vol.Optional(CONF_LIGHTS, description=suggested(CONF_LIGHTS)): (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["light", "switch"], multiple=True)
                )
            ),
            vol.Optional(CONF_ILLUMINANCE, description=suggested(CONF_ILLUMINANCE)): (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="illuminance")
                )
            ),
            vol.Optional(CONF_FANS, description=suggested(CONF_FANS)): (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["fan", "switch"], multiple=True)
                )
            ),
            vol.Optional(CONF_CLIMATES, description=suggested(CONF_CLIMATES)): (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate", multiple=True)
                )
            ),
            vol.Optional(CONF_TEMPERATURE, description=suggested(CONF_TEMPERATURE)): (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                )
            ),
            vol.Optional(CONF_HUMIDITY, description=suggested(CONF_HUMIDITY)): (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
                )
            ),
            vol.Optional(CONF_SLEEP, description=suggested(CONF_SLEEP)): (
                selector.EntitySelector(selector.EntitySelectorConfig(domain=SLEEP_DOMAINS))
            ),
            vol.Optional(CONF_WORKDAY, description=suggested(CONF_WORKDAY)): (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", integration="workday")
                )
            ),
            vol.Optional(CONF_HOLIDAYS, description=suggested(CONF_HOLIDAYS)): (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="calendar", multiple=True)
                )
            ),
        }
    )


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not user_input.get(CONF_PRESENCE):
        errors[CONF_PRESENCE] = "no_presence"
    elif not set(user_input.get(CONF_PRESENCE_STILL) or []) <= set(user_input[CONF_PRESENCE]):
        errors[CONF_PRESENCE_STILL] = "still_not_presence"
    if not any(user_input.get(key) for key in (CONF_LIGHTS, CONF_FANS, CONF_CLIMATES)):
        errors["base"] = "no_actuator"
    # Une clim gérée ne peut pas maintenir la présence : la pièce ne se
    # viderait jamais et la clim ne s'arrêterait jamais.
    elif set(user_input.get(CONF_CLIMATES) or []) & set(user_input.get(CONF_PRESENCE_HOLD) or []):
        errors[CONF_PRESENCE_HOLD] = "climate_in_hold"
    return errors


class LuminaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ajout d'une pièce."""

    VERSION = 1
    # 1.2 : listes normalisées, maintien de présence et humidité (voir __init__)
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._area_id: str | None = None
        self._area_name: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Étape 1 : choix de la pièce."""
        if user_input is not None:
            area_id = user_input[CONF_AREA]
            await self.async_set_unique_id(area_id)
            self._abort_if_unique_id_configured()
            area = ar.async_get(self.hass).async_get_area(area_id)
            self._area_id = area_id
            self._area_name = area.name if area else area_id
            return await self.async_step_entities()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_AREA): selector.AreaSelector()}),
        )

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Étape 2 : entités de la pièce (préremplies par auto-découverte)."""
        assert self._area_id is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(
                    title=self._area_name or self._area_id,
                    data={CONF_AREA: self._area_id, **user_input},
                )
            defaults = user_input
        else:
            defaults = _discover(self.hass, self._area_id)

        return self.async_show_form(
            step_id="entities",
            data_schema=_entities_schema(defaults),
            errors=errors,
            description_placeholders={"area": self._area_name or self._area_id},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LuminaOptionsFlow()


class LuminaOptionsFlow(OptionsFlow):
    """Reconfiguration des entités d'une pièce."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(data=user_input)
            defaults = user_input
        else:
            defaults = dict(self.config_entry.options or self.config_entry.data)

        return self.async_show_form(
            step_id="init",
            data_schema=_entities_schema(defaults),
            errors=errors,
        )
