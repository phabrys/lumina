"""Constantes et aides partagées par les tests d'une pièce."""

from datetime import timedelta

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache,
)

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.lumina.const import (
    CONF_AREA,
    CONF_ILLUMINANCE,
    CONF_LIGHTS,
    CONF_PRESENCE,
    DOMAIN,
)

PIR = "binary_sensor.pir_salon"
LUX = "sensor.lux_salon"
TEMP = "sensor.temp_salon"
HUMIDITY = "sensor.humidite_salon"
LIGHT = "light.salon"
FAN = "fan.salon"
TV = "media_player.tv_salon"
# Lumière à variateur : seule une lumière qui peut baisser a un avertissement
DIMMABLE = {"supported_color_modes": ["brightness"]}

NOON = "2026-10-18T12:00:00-07:00"  # fuseau des tests : US/Pacific
NIGHT = "2026-10-18T23:30:00-07:00"


def _entry(hass: HomeAssistant, **extra) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Salon",
        unique_id="salon",
        data={
            CONF_AREA: "salon",
            CONF_PRESENCE: [PIR],
            CONF_LIGHTS: [LIGHT],
            CONF_ILLUMINANCE: LUX,
            **extra,
        },
    )
    entry.add_to_hass(hass)
    return entry


async def _start(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _setup(hass: HomeAssistant, **extra) -> MockConfigEntry:
    return await _start(hass, _entry(hass, **extra))


async def _setup_after_restart(
    hass: HomeAssistant, occupied: bool, room_attrs: dict | None = None, **extra
) -> MockConfigEntry:
    """Pièce démarrée avec l'état qu'elle avait avant le redémarrage."""
    entry = _entry(hass, **extra)
    room = er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, f"{entry.entry_id}_room_state", config_entry=entry
    )
    state = "occupied" if occupied else "vacant"
    attrs = {"occupied": occupied, **(room_attrs or {})}
    mock_restore_cache(hass, [State(room.entity_id, state, attrs)])
    return await _start(hass, entry)


def _eid(hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str) -> str:
    """Identifiant d'une entité Lumina, quel que soit son nom généré."""
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id is not None, key
    return entity_id


def _room(hass: HomeAssistant, entry: MockConfigEntry):
    return hass.states.get(_eid(hass, entry, "sensor", "room_state"))


def _entities(calls) -> list[list[str]]:
    return [call.data["entity_id"] for call in calls]


async def _later(hass: HomeAssistant, **delta) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(**delta))
    await hass.async_block_till_done()


async def _switch(hass: HomeAssistant, entry, key: str, on: bool = True) -> None:
    await hass.services.async_call(
        "switch",
        "turn_on" if on else "turn_off",
        {"entity_id": _eid(hass, entry, "switch", key)},
        blocking=True,
    )
    await hass.async_block_till_done()
