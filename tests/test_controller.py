"""Tests du comportement d'une pièce."""

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
)

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.lumina.const import (
    CONF_AREA,
    CONF_FANS,
    CONF_HUMIDITY,
    CONF_ILLUMINANCE,
    CONF_LIGHTS,
    CONF_PRESENCE,
    CONF_PRESENCE_HOLD,
    CONF_TEMPERATURE,
    DOMAIN,
)

PIR = "binary_sensor.pir_salon"
LUX = "sensor.lux_salon"
TEMP = "sensor.temp_salon"
HUMIDITY = "sensor.humidite_salon"
LIGHT = "light.salon"
FAN = "fan.salon"
TV = "media_player.tv_salon"

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


# ----------------------------------------------------------------------
# Lumières
# ----------------------------------------------------------------------


async def test_lights_on_when_dark(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    assert _entities(turn_on) == [[LIGHT]]
    assert turn_on[0].data["brightness_pct"] == 100
    assert "color_temp_kelvin" not in turn_on[0].data  # lumière sans teinte réglable
    assert _room(hass, entry).state == "occupied"


async def test_lights_stay_off_when_bright(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    await _setup(hass)

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    assert turn_on == []


async def test_color_temperature_applied(hass: HomeAssistant, daytime) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off", {"supported_color_modes": ["color_temp"]})
    await _setup(hass)

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert turn_on[0].data["color_temp_kelvin"] == 4000


async def test_lights_dim_then_off_after_delay(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()

    # Délai écoulé : les lumières baissent d'abord.
    await _later(hass, seconds=121)
    assert turn_on[-1].data["brightness_pct"] == 20
    assert _room(hass, entry).attributes["lights_warning"] is True
    assert turn_off == []

    # Puis s'éteignent après l'avertissement.
    await _later(hass, seconds=121 + 16)
    assert _entities(turn_off) == [[LIGHT]]


async def test_warning_cancelled_when_presence_returns(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on")
    await _setup(hass)

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=121)
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    assert turn_on[-1].data["brightness_pct"] == 100  # luminosité rétablie
    await _later(hass, seconds=121 + 30)
    assert turn_off == []


async def test_manual_override_blocks_automation(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)

    # Extinction à la main : Lumina doit laisser la main pendant 30 min.
    hass.states.async_set(LIGHT, "off")
    await hass.async_block_till_done()
    assert _room(hass, entry).state == "override"

    hass.states.async_set(LUX, "5")
    await hass.async_block_till_done()
    assert turn_on == []

    # Fin de la reprise manuelle : la règle s'applique de nouveau.
    await _later(hass, minutes=31)
    assert _entities(turn_on) == [[LIGHT]]
    assert _room(hass, entry).state == "occupied"


async def test_disable_switch_stops_automation(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": _eid(hass, entry, "switch", "auto_lights")},
        blocking=True,
    )
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    assert turn_on == []


# ----------------------------------------------------------------------
# Maintien de présence
# ----------------------------------------------------------------------


async def test_presence_hold_keeps_room_occupied(hass: HomeAssistant) -> None:
    async_mock_service(hass, "light", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on")
    hass.states.async_set(TV, "playing")
    entry = await _setup(hass, **{CONF_PRESENCE_HOLD: [TV]})

    # Plus de mouvement, mais la TV joue : la pièce reste occupée.
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    assert _room(hass, entry).state == "occupied"
    await _later(hass, minutes=10)
    assert turn_off == []

    # TV éteinte : la pièce se vide.
    hass.states.async_set(TV, "off")
    await hass.async_block_till_done()
    assert _room(hass, entry).state == "vacant"


async def test_presence_hold_does_not_start_occupancy(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TV, "off")
    entry = await _setup(hass, **{CONF_PRESENCE_HOLD: [TV]})

    hass.states.async_set(TV, "playing")
    await hass.async_block_till_done()

    assert _room(hass, entry).state == "vacant"
    assert turn_on == []


# ----------------------------------------------------------------------
# Ventilateurs
# ----------------------------------------------------------------------


async def test_fans_follow_temperature_with_speed(hass: HomeAssistant) -> None:
    fan_on = async_mock_service(hass, "fan", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TEMP, "25")
    hass.states.async_set(FAN, "off")
    await _setup(hass, **{CONF_FANS: [FAN], CONF_TEMPERATURE: TEMP})

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert fan_on == []  # 25 °C < seuil de 27 °C

    hass.states.async_set(TEMP, "28")
    await hass.async_block_till_done()
    assert _entities(fan_on) == [[FAN]]
    # 1 °C au-dessus du seuil sur une plage de 3 °C : 33 + 67/3 ≈ 55 %
    assert fan_on[0].data["percentage"] == 55

    # Simule l'état réel du ventilateur allumé par Lumina.
    hass.states.async_set(FAN, "on", {"percentage": 55}, context=fan_on[0].context)
    hass.states.async_set(TEMP, "25.5")
    await hass.async_block_till_done()
    assert _entities(turn_off) == [[FAN]]


async def test_fan_speed_follows_heat(hass: HomeAssistant) -> None:
    set_pct = async_mock_service(hass, "fan", "set_percentage")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TEMP, "28")
    hass.states.async_set(FAN, "on", {"percentage": 55, "percentage_step": 1})
    await _setup(hass, **{CONF_FANS: [FAN], CONF_TEMPERATURE: TEMP})

    hass.states.async_set(TEMP, "31")
    await hass.async_block_till_done()
    assert set_pct[-1].data["percentage"] == 100


async def test_manual_fan_speed_is_an_override(hass: HomeAssistant) -> None:
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TEMP, "28")
    hass.states.async_set(FAN, "on", {"percentage": 55})
    entry = await _setup(hass, **{CONF_FANS: [FAN], CONF_TEMPERATURE: TEMP})

    hass.states.async_set(FAN, "on", {"percentage": 100})
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["fans_override_until"] is not None


async def test_apparent_temperature_drives_fans(hass: HomeAssistant) -> None:
    fan_on = async_mock_service(hass, "fan", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TEMP, "26.5")
    hass.states.async_set(HUMIDITY, "85")
    hass.states.async_set(FAN, "off")
    entry = await _setup(
        hass, **{CONF_FANS: [FAN], CONF_TEMPERATURE: TEMP, CONF_HUMIDITY: HUMIDITY}
    )
    apparent = hass.states.get(_eid(hass, entry, "sensor", "apparent_temperature"))
    assert float(apparent.state) > 27  # 26,5 °C humides se ressentent plus chaud

    # Mesuré sous le seuil de 27 °C, mais ressenti au-dessus : on ventile.
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert _entities(fan_on) == [[FAN]]


# ----------------------------------------------------------------------
# Nuit
# ----------------------------------------------------------------------


async def test_night_dims_lights(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)
    assert _room(hass, entry).attributes["period"] == "night"

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
    entry = await _setup(hass)

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": _eid(hass, entry, "number", "night_brightness"), "value": 0},
        blocking=True,
    )
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    assert turn_on == []


async def test_custom_night_window(hass: HomeAssistant) -> None:
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)
    assert _room(hass, entry).attributes["period"] == "day"

    # Nuit de 11 h à 13 h : il est midi, la pièce passe en période de nuit.
    for key, value in (("night_start", "11:00:00"), ("night_end", "13:00:00")):
        await hass.services.async_call(
            "time",
            "set_value",
            {"entity_id": _eid(hass, entry, "time", key), "time": value},
            blocking=True,
        )
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["period"] == "night"


async def test_forced_night_switch(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": _eid(hass, entry, "switch", "forced_night")},
        blocking=True,
    )
    assert _room(hass, entry).attributes["period"] == "night"

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert turn_on[0].data["brightness_pct"] == 30


# ----------------------------------------------------------------------
# Journal
# ----------------------------------------------------------------------


async def test_logbook_explains_actions(hass: HomeAssistant) -> None:
    async_mock_service(hass, "light", "turn_on")
    entries = async_capture_events(hass, "logbook_entry")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    assert entries, "aucune entrée de journal"
    data = entries[-1].data
    assert data["message"].startswith("allume les lumières")
    assert "10 lx" in data["message"]
    assert data["entity_id"] == _eid(hass, entry, "sensor", "room_state")
