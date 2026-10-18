"""Tests du comportement d'une pièce."""

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.lumina.const import (
    CONF_AREA,
    CONF_FANS,
    CONF_ILLUMINANCE,
    CONF_LIGHTS,
    CONF_PRESENCE,
    CONF_TEMPERATURE,
    DOMAIN,
)

PIR = "binary_sensor.pir_salon"
LUX = "sensor.lux_salon"
TEMP = "sensor.temp_salon"
LIGHT = "light.salon"
FAN = "fan.salon"
ROOM_STATE = "sensor.lumina_salon_room_state"

NOON = "2026-10-18T12:00:00-07:00"  # fuseau des tests : US/Pacific
NIGHT = "2026-10-18T23:30:00-07:00"


@pytest.fixture(autouse=True)
def daytime(freezer):
    """Fige l'horloge en journée, sauf si un test la déplace."""
    freezer.move_to(NOON)
    return freezer


async def _setup(hass: HomeAssistant, **extra) -> MockConfigEntry:
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
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entities(calls) -> list[list[str]]:
    return [call.data["entity_id"] for call in calls]


async def test_lights_on_when_dark(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    await _setup(hass)

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    assert _entities(turn_on) == [[LIGHT]]
    assert turn_on[0].data["brightness_pct"] == 100
    assert hass.states.get(ROOM_STATE).state == "occupied"


async def test_lights_stay_off_when_bright(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    await _setup(hass)

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    assert turn_on == []


async def test_lights_off_after_delay(hass: HomeAssistant) -> None:
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on")
    await _setup(hass)

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    assert turn_off == []

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=121))
    await hass.async_block_till_done()
    assert _entities(turn_off) == [[LIGHT]]


async def test_manual_override_blocks_automation(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "on")
    await _setup(hass)

    # Extinction à la main : Lumina doit laisser la main pendant 30 min.
    hass.states.async_set(LIGHT, "off")
    await hass.async_block_till_done()
    assert hass.states.get(ROOM_STATE).state == "override"

    hass.states.async_set(LUX, "5")
    await hass.async_block_till_done()
    assert turn_on == []

    # Fin de la reprise manuelle : la règle s'applique de nouveau.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=31))
    await hass.async_block_till_done()
    assert _entities(turn_on) == [[LIGHT]]
    assert hass.states.get(ROOM_STATE).state == "occupied"


async def test_fans_follow_temperature(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "homeassistant", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TEMP, "25")
    hass.states.async_set(FAN, "off")
    await _setup(hass, **{CONF_FANS: [FAN], CONF_TEMPERATURE: TEMP})

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert turn_on == []  # 25 °C < seuil de 27 °C

    hass.states.async_set(TEMP, "28")
    await hass.async_block_till_done()
    assert _entities(turn_on) == [[FAN]]

    # Simule l'état réel du ventilateur allumé par Lumina.
    hass.states.async_set(FAN, "on", context=turn_on[0].context)
    hass.states.async_set(TEMP, "25.5")
    await hass.async_block_till_done()
    assert _entities(turn_off) == [[FAN]]


async def test_disable_switch_stops_automation(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    await _setup(hass)

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.lumina_salon_automatic_lights"},
        blocking=True,
    )
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    assert turn_on == []


async def test_night_dims_lights(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    await _setup(hass)
    assert hass.states.get(ROOM_STATE).attributes["period"] == "night"

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    assert _entities(turn_on) == [[LIGHT]]
    assert turn_on[0].data["brightness_pct"] == 30


async def test_night_brightness_zero_disables_lights(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    await _setup(hass)

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.lumina_salon_lights_brightness_night", "value": 0},
        blocking=True,
    )
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    assert turn_on == []


async def test_custom_night_window(hass: HomeAssistant) -> None:
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LIGHT, "off")
    await _setup(hass)
    assert hass.states.get(ROOM_STATE).attributes["period"] == "day"

    # Nuit de 11 h à 13 h : il est midi, la pièce passe en période de nuit.
    for entity_id, value in (
        ("time.lumina_salon_night_start", "11:00:00"),
        ("time.lumina_salon_night_end", "13:00:00"),
    ):
        await hass.services.async_call(
            "time", "set_value", {"entity_id": entity_id, "time": value}, blocking=True
        )
    await hass.async_block_till_done()
    assert hass.states.get(ROOM_STATE).attributes["period"] == "night"
