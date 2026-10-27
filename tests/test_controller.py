"""Tests du comportement d'une pièce."""

import asyncio
from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
)

from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .common import (
    DIMMABLE,
    FAN,
    HUMIDITY,
    LIGHT,
    LUX,
    NIGHT,
    PIR,
    TEMP,
    TV,
    _eid,
    _entities,
    _later,
    _room,
    _setup,
    _setup_after_restart,
    _switch,
)
from custom_components.lumina.const import (
    CONF_CLIMATES,
    CONF_FANS,
    CONF_HUMIDITY,
    CONF_ILLUMINANCE,
    CONF_LIGHTS,
    CONF_PRESENCE_HOLD,
    CONF_TEMPERATURE,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("daytime")


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
    hass.states.async_set(LIGHT, "on", DIMMABLE)
    entry = await _setup(hass)

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)  # absence confirmée

    # Délai écoulé : les lumières baissent d'abord.
    await _later(hass, seconds=121)
    assert turn_on[-1].data["brightness"] == 51  # 20 %
    assert _room(hass, entry).attributes["lights_warning"] is True
    assert turn_off == []

    # Puis s'éteignent après l'avertissement.
    await _later(hass, seconds=121 + 16)
    assert _entities(turn_off) == [[LIGHT]]


async def test_no_warning_for_on_off_light(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on", {"supported_color_modes": ["onoff"]})
    await _setup(hass)

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    await _later(hass, seconds=121)

    # Rien à baisser : extinction directe, sans attendre l'avertissement.
    assert turn_on == []
    assert _entities(turn_off) == [[LIGHT]]


async def test_warning_cancelled_when_presence_returns(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on", DIMMABLE)
    await _setup(hass)

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)  # absence confirmée
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
    await _later(hass, seconds=31)  # absence confirmée
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


async def test_presence_hold_survives_restart(hass: HomeAssistant) -> None:
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on")
    hass.states.async_set(TV, "playing")
    entry = await _setup_after_restart(hass, True, **{CONF_PRESENCE_HOLD: [TV]})

    assert _room(hass, entry).state == "occupied"
    await _later(hass, minutes=10)
    assert _room(hass, entry).state == "occupied"
    assert turn_off == []


async def test_presence_hold_back_late_after_restart(hass: HomeAssistant) -> None:
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TV, "unavailable")  # intégration pas encore prête
    entry = await _setup_after_restart(hass, True, **{CONF_PRESENCE_HOLD: [TV]})

    await _later(hass, seconds=10)
    hass.states.async_set(TV, "playing")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    assert _room(hass, entry).state == "occupied"


async def test_restored_occupancy_ends_without_hold(hass: HomeAssistant) -> None:
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TV, "off")
    entry = await _setup_after_restart(hass, True, **{CONF_PRESENCE_HOLD: [TV]})

    assert _room(hass, entry).attributes["vacancy_pending"] is True
    await _later(hass, seconds=31)
    assert _room(hass, entry).state == "vacant"


async def test_playing_media_does_not_occupy_after_restart(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TV, "playing")
    entry = await _setup_after_restart(hass, False, **{CONF_PRESENCE_HOLD: [TV]})

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
    # Trop tôt après le démarrage : l'arrêt attend la fin du cycle minimal.
    assert turn_off == []
    await _later(hass, seconds=301)
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
# Soirée
# ----------------------------------------------------------------------

EVENING = "2026-10-18T21:00:00-07:00"


async def _set_time(hass: HomeAssistant, entry, key: str, value: str) -> None:
    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": _eid(hass, entry, "time", key), "time": value},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_no_evening_by_default(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(EVENING)
    hass.states.async_set(PIR, "off")
    entry = await _setup(hass)
    assert _room(hass, entry).attributes["period"] == "day"


async def test_evening_softens_lights(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(EVENING)
    turn_on = async_mock_service(hass, "light", "turn_on")
    entries = async_capture_events(hass, "logbook_entry")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off", {"supported_color_modes": ["color_temp"]})
    entry = await _setup(hass)

    await _set_time(hass, entry, "evening_start", "19:00:00")
    assert _room(hass, entry).attributes["period"] == "evening"

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert turn_on[0].data["brightness_pct"] == 70
    assert turn_on[0].data["color_temp_kelvin"] == 3000
    assert "(soirée, 10 lx)" in entries[-1].data["message"]


async def test_evening_ends_with_night(hass: HomeAssistant, daytime) -> None:
    daytime.move_to("2026-10-18T21:59:30-07:00")
    entries = async_capture_events(hass, "logbook_entry")
    hass.states.async_set(PIR, "off")
    entry = await _setup(hass)
    await _set_time(hass, entry, "evening_start", "19:00:00")
    assert _room(hass, entry).attributes["period"] == "evening"

    daytime.move_to("2026-10-18T22:00:00-07:00")
    await _later(hass, seconds=0)
    assert _room(hass, entry).attributes["period"] == "night"
    assert entries[-1].data["message"] == "passe en mode nuit"


async def test_evening_keeps_day_rules(hass: HomeAssistant, daytime) -> None:
    """Éteindre à la main en soirée n'endort pas la pièce."""
    daytime.move_to(EVENING)
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)
    await _set_time(hass, entry, "evening_start", "19:00:00")

    hass.states.async_set(LIGHT, "off")
    await hass.async_block_till_done()
    assert _room(hass, entry).state == "override"


async def test_forced_night_wins_over_evening(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(EVENING)
    turn_on = async_mock_service(hass, "light", "turn_on")
    entries = async_capture_events(hass, "logbook_entry")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)
    await _set_time(hass, entry, "evening_start", "19:00:00")

    await _switch(hass, entry, "forced_night")
    assert _room(hass, entry).attributes["period"] == "night"
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert turn_on[0].data["brightness_pct"] == 30

    await _switch(hass, entry, "forced_night", on=False)
    assert _room(hass, entry).attributes["period"] == "evening"
    assert "repasse en mode soirée" in [e.data["message"] for e in entries]


async def test_evening_start_inside_night_disables_evening(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(EVENING)
    hass.states.async_set(PIR, "off")
    entry = await _setup(hass)

    # 23:00 tombe dans la nuit (22:00 → 07:00) : pas de soirée de 23 h à 22 h.
    await _set_time(hass, entry, "evening_start", "23:00:00")
    assert _room(hass, entry).attributes["period"] == "day"


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


# ----------------------------------------------------------------------
# v0.4.0 : lumière du jour, plusieurs lumières, journal, nuit forcée
# ----------------------------------------------------------------------

LIGHT2 = "light.salon_lampadaire"


async def _set_number(hass, entry, key, value) -> None:
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": _eid(hass, entry, "number", key), "value": value},
        blocking=True,
    )


async def test_daylight_turns_lights_off_then_relocks(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)
    await _set_number(hass, entry, "daylight_off_lux", 300)

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 1

    # Le jour se lève : 400 lx pendant 5 min → extinction.
    hass.states.async_set(LIGHT, "on", context=turn_on[0].context)
    hass.states.async_set(LUX, "400")
    await hass.async_block_till_done()
    assert turn_off == []
    await _later(hass, seconds=301)
    assert _entities(turn_off) == [[LIGHT]]
    assert _room(hass, entry).attributes["daylight_locked"] is True

    # Lampe éteinte : la mesure retombe, mais pas de rallumage immédiat.
    hass.states.async_set(LIGHT, "off", context=turn_off[0].context)
    hass.states.async_set(LUX, "20")
    await hass.async_block_till_done()
    assert len(turn_on) == 1

    # Sombre pendant 10 min (le soir) : l'allumage automatique reprend.
    await _later(hass, seconds=301 + 601)
    assert len(turn_on) == 2
    assert _room(hass, entry).attributes["daylight_locked"] is False


async def test_lights_mode_all_turns_on_remaining(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on")
    hass.states.async_set(LIGHT2, "off")
    await _setup(hass, **{CONF_LIGHTS: [LIGHT, LIGHT2]})

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert _entities(turn_on) == [[LIGHT2]]


async def test_lights_mode_any_leaves_others(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on")
    hass.states.async_set(LIGHT2, "off")
    entry = await _setup(hass, **{CONF_LIGHTS: [LIGHT, LIGHT2]})
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": _eid(hass, entry, "select", "lights_mode"), "option": "any"},
        blocking=True,
    )

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert turn_on == []


async def test_small_fan_speed_changes_are_ignored(hass: HomeAssistant) -> None:
    set_pct = async_mock_service(hass, "fan", "set_percentage")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TEMP, "28")
    hass.states.async_set(FAN, "on", {"percentage": 55, "percentage_step": 1})
    await _setup(hass, **{CONF_FANS: [FAN], CONF_TEMPERATURE: TEMP})

    hass.states.async_set(TEMP, "28.3")  # ≈ 62 % visés, écart < 10 points
    await hass.async_block_till_done()
    assert set_pct == []


async def test_fan_speed_log_is_throttled(hass: HomeAssistant) -> None:
    set_pct = async_mock_service(hass, "fan", "set_percentage")
    entries = async_capture_events(hass, "logbook_entry")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TEMP, "28")
    hass.states.async_set(FAN, "on", {"percentage": 55, "percentage_step": 1})
    await _setup(hass, **{CONF_FANS: [FAN], CONF_TEMPERATURE: TEMP})

    hass.states.async_set(TEMP, "30")
    await hass.async_block_till_done()
    hass.states.async_set(FAN, "on", {"percentage": 100}, context=set_pct[0].context)
    hass.states.async_set(TEMP, "28")
    await hass.async_block_till_done()

    assert len(set_pct) == 2  # la vitesse suit bien
    speed_logs = [e for e in entries if e.data["message"].startswith("règle")]
    assert len(speed_logs) == 1  # mais une seule entrée de journal


async def test_forced_night_ends_without_night_window(hass: HomeAssistant, daytime) -> None:
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)
    # Pas de plage de nuit : début = fin = 07:00.
    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": _eid(hass, entry, "time", "night_start"), "time": "07:00:00"},
        blocking=True,
    )
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": _eid(hass, entry, "switch", "forced_night")},
        blocking=True,
    )
    assert _room(hass, entry).attributes["period"] == "night"

    # Le lendemain à 07:01, le forçage s'arrête de lui-même.
    daytime.move_to("2026-10-19T07:01:00-07:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["period"] == "day"
    assert hass.states.get(_eid(hass, entry, "switch", "forced_night")).state == "off"


# ----------------------------------------------------------------------
# v0.5.0 : absence confirmée, repli sur le soleil, reprises dédoublonnées
# ----------------------------------------------------------------------


async def test_vacancy_needs_confirmation(hass: HomeAssistant) -> None:
    async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    room = _room(hass, entry)
    assert room.state == "occupied"
    assert room.attributes["vacancy_pending"] is True

    await _later(hass, seconds=31)
    assert _room(hass, entry).state == "vacant"


async def test_brief_dropout_keeps_manual_override(hass: HomeAssistant) -> None:
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)

    hass.states.async_set(LIGHT, "off")  # extinction à la main
    await hass.async_block_till_done()
    assert _room(hass, entry).state == "override"

    # Micro-coupure du détecteur : 10 s sans présence, puis retour.
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=10)
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)

    room = _room(hass, entry)
    assert room.state == "override"
    assert room.attributes["vacancy_pending"] is False


@pytest.mark.parametrize(("sun", "expected_calls"), [("above_horizon", 0), ("below_horizon", 1)])
async def test_unavailable_lux_falls_back_to_sun(
    hass: HomeAssistant, sun: str, expected_calls: int
) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set("sun.sun", sun)
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "unavailable")
    hass.states.async_set(LIGHT, "off")
    await _setup(hass)

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == expected_calls


@pytest.mark.parametrize(("sun", "expected_calls"), [("above_horizon", 0), ("below_horizon", 1)])
async def test_no_lux_sensor_follows_sun(
    hass: HomeAssistant, sun: str, expected_calls: int
) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set("sun.sun", sun)
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LIGHT, "off")
    await _setup(hass, **{CONF_ILLUMINANCE: None})

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == expected_calls


def _sun(hass: HomeAssistant, state: str, *, rising: timedelta, setting: timedelta) -> None:
    """Soleil avec ses prochains lever et coucher, comptés depuis maintenant."""
    now = dt_util.utcnow()
    hass.states.async_set(
        "sun.sun",
        state,
        {"next_rising": (now + rising).isoformat(), "next_setting": (now + setting).isoformat()},
    )


async def _next_minute(hass: HomeAssistant, freezer, minutes: int) -> None:
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def test_no_lux_sensor_turns_on_before_sunset(hass: HomeAssistant, daytime) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    _sun(hass, "above_horizon", rising=timedelta(hours=13), setting=timedelta(minutes=40))
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass, **{CONF_ILLUMINANCE: None})

    # Coucher dans 40 min : encore assez de jour.
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert turn_on == []

    # 30 min avant le coucher : la marge du soir allume sans attendre un mouvement.
    await _next_minute(hass, daytime, 11)
    assert _entities(turn_on) == [[LIGHT]]

    # Marge réglée à 0 : rien ne s'allume avant le coucher lui-même.
    hass.states.async_set(LIGHT, "off")
    await _set_number(hass, entry, "sunset_advance", 0)
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 1


async def test_no_lux_sensor_turns_off_after_sunrise(hass: HomeAssistant, daytime) -> None:
    entries = async_capture_events(hass, "logbook_entry")
    turn_on = async_mock_service(hass, "light", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    # Levé depuis 10 min : encore dans la marge du matin, la pièce reste sombre.
    _sun(hass, "above_horizon", rising=timedelta(minutes=24 * 60 - 10), setting=timedelta(hours=12))
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass, **{CONF_ILLUMINANCE: None})

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 1
    assert "soleil couché" in entries[-1].data["message"]
    hass.states.async_set(LIGHT, "on", context=turn_on[0].context)
    await hass.async_block_till_done()

    # 30 min après le lever : extinction aussitôt.
    await _next_minute(hass, daytime, 19)
    assert turn_off == []
    await _next_minute(hass, daytime, 1)
    assert _entities(turn_off) == [[LIGHT]]
    assert _room(hass, entry).attributes["daylight_locked"] is True
    assert entries[-1].data["message"] == "éteint les lumières, soleil levé"

    # Toujours jour : pas de rallumage au mouvement suivant.
    hass.states.async_set(LIGHT, "off", context=turn_off[0].context)
    hass.states.async_set(PIR, "off")
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 1

    # Le soir, dans la marge du coucher : l'allumage reprend aussitôt.
    _sun(hass, "above_horizon", rising=timedelta(hours=13), setting=timedelta(minutes=20))
    await hass.async_block_till_done()
    assert len(turn_on) == 2
    assert _room(hass, entry).attributes["daylight_locked"] is False


async def test_simultaneous_changes_make_one_override(hass: HomeAssistant) -> None:
    entries = async_capture_events(hass, "logbook_entry")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "on")
    hass.states.async_set(LIGHT2, "on")
    await _setup(hass, **{CONF_LIGHTS: [LIGHT, LIGHT2]})

    # Un script ou un interrupteur coupe les deux lampes à la suite.
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(LIGHT2, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=6)  # entrée écrite une fois le geste terminé

    overrides = [e for e in entries if e.data["message"].startswith("laisse la main")]
    assert len(overrides) == 1


# ----------------------------------------------------------------------
# v0.6.0 : informations pour la carte, bouton de reprise
# ----------------------------------------------------------------------


async def test_room_state_exposes_entities_and_deadlines(hass: HomeAssistant) -> None:
    async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)

    attrs = _room(hass, entry).attributes
    assert attrs["lights"] == [LIGHT]
    assert attrs["presence_sensors"] == [PIR]
    assert attrs["illuminance_sensor"] == LUX
    assert attrs["fans"] == []

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["vacancy_at"] is not None

    await _later(hass, seconds=31)
    attrs = _room(hass, entry).attributes
    assert attrs["vacancy_at"] is None
    assert attrs["lights_off_at"] is not None


async def test_resume_button_ends_override(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)

    hass.states.async_set(LIGHT, "off")  # à la main
    await hass.async_block_till_done()
    assert _room(hass, entry).state == "override"

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _eid(hass, entry, "button", "resume")},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert _room(hass, entry).state == "occupied"
    assert _entities(turn_on) == [[LIGHT]]  # pièce sombre : lumière rallumée


async def test_failed_service_call_is_logged(hass: HomeAssistant) -> None:
    async def _broken(call) -> None:
        raise HomeAssistantError("Action script.maj_ventilateur not found")

    hass.services.async_register("fan", "turn_on", _broken)
    entries = async_capture_events(hass, "logbook_entry")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TEMP, "28")
    hass.states.async_set(FAN, "off")
    await _setup(hass, **{CONF_FANS: [FAN], CONF_TEMPERATURE: TEMP})

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    failures = [e for e in entries if e.data["message"].startswith("échec")]
    assert len(failures) == 1
    assert "fan.turn_on" in failures[0].data["message"]
    assert FAN in failures[0].data["message"]
    assert "not found" in failures[0].data["message"]


async def test_logbook_follows_language(hass: HomeAssistant) -> None:
    hass.config.language = "en"
    async_mock_service(hass, "light", "turn_on")
    entries = async_capture_events(hass, "logbook_entry")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    await _setup(hass)

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    assert entries[-1].data["message"] == "turns on the lights at 100 % (day, 10 lx)"


async def test_no_logbook_after_unload(hass: HomeAssistant) -> None:
    release = asyncio.Event()

    async def _slow_failure(call) -> None:
        await release.wait()
        raise HomeAssistantError("appareil muet")

    hass.services.async_register("light", "turn_on", _slow_failure)
    entries = async_capture_events(hass, "logbook_entry")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)

    hass.states.async_set(PIR, "on")
    await asyncio.sleep(0)  # l'appel est en cours, bloqué sur l'appareil
    assert await hass.config_entries.async_unload(entry.entry_id)
    release.set()
    await hass.async_block_till_done()

    assert not [e for e in entries if e.data["message"].startswith("échec")]


FAN2 = "fan.salon_plafond"


async def test_fans_mode_all_turns_on_remaining(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "fan", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TEMP, "28")
    hass.states.async_set(FAN, "on", {"percentage": 55})
    hass.states.async_set(FAN2, "off")
    await _setup(hass, **{CONF_FANS: [FAN, FAN2], CONF_TEMPERATURE: TEMP})

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert _entities(turn_on) == [[FAN2]]


async def test_fans_mode_any_leaves_others(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "fan", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TEMP, "28")
    hass.states.async_set(FAN, "on", {"percentage": 55})
    hass.states.async_set(FAN2, "off")
    entry = await _setup(hass, **{CONF_FANS: [FAN, FAN2], CONF_TEMPERATURE: TEMP})
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": _eid(hass, entry, "select", "fans_mode"), "option": "any"},
        blocking=True,
    )

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert turn_on == []


# ----------------------------------------------------------------------
# Clims
# ----------------------------------------------------------------------

CLIMATE = "climate.salon"
CLIMATE_ATTRS = {
    "temperature": 24,
    "preset_mode": "none",
    "preset_modes": ["none", "eco", "sleep"],
    "min_temp": 16,
    "max_temp": 30,
}


async def _setup_with_climate(hass: HomeAssistant, **extra) -> MockConfigEntry:
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(CLIMATE, "cool", CLIMATE_ATTRS)
    return await _setup(hass, **{CONF_CLIMATES: [CLIMATE], **extra})


async def _select(hass: HomeAssistant, entry, key: str, option: str) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": _eid(hass, entry, "select", key), "option": option},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_climate_turned_off_then_restored(hass: HomeAssistant) -> None:
    turn_off = async_mock_service(hass, "climate", "turn_off")
    set_mode = async_mock_service(hass, "climate", "set_hvac_mode")
    entry = await _setup_with_climate(hass)

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)  # absence confirmée
    assert turn_off == []
    await _later(hass, seconds=31 + 900)
    assert _entities(turn_off) == [[CLIMATE]]
    assert _room(hass, entry).attributes["climate_vacant_applied"] == "off"

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert _entities(set_mode) == [[CLIMATE]]
    assert set_mode[0].data["hvac_mode"] == "cool"


async def test_climate_eco_then_restored(hass: HomeAssistant) -> None:
    set_preset = async_mock_service(hass, "climate", "set_preset_mode")
    entry = await _setup_with_climate(hass)
    await _select(hass, entry, "climate_vacant_day", "eco")

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)  # absence confirmée
    await _later(hass, seconds=31 + 900)
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert [c.data["preset_mode"] for c in set_preset] == ["eco", "none"]


async def test_climate_setback_then_restored(hass: HomeAssistant) -> None:
    set_temp = async_mock_service(hass, "climate", "set_temperature")
    entry = await _setup_with_climate(hass)
    await _select(hass, entry, "climate_vacant_day", "setback")

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)  # absence confirmée
    await _later(hass, seconds=31 + 900)
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert [c.data["temperature"] for c in set_temp] == [26, 24]


async def test_climate_left_alone_at_night(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_off = async_mock_service(hass, "climate", "turn_off")
    await _setup_with_climate(hass)

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)  # absence confirmée
    await _later(hass, seconds=31 + 900)
    assert turn_off == []


async def test_climate_not_restored_after_long_absence(hass: HomeAssistant, daytime) -> None:
    async_mock_service(hass, "climate", "turn_off")
    set_mode = async_mock_service(hass, "climate", "set_hvac_mode")
    await _setup_with_climate(hass)

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)  # absence confirmée
    await _later(hass, seconds=31 + 900)
    daytime.tick(timedelta(hours=3))
    await _later(hass, seconds=1)
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert set_mode == []


async def _setup_evening_climate(
    hass: HomeAssistant, daytime, temperature: float = 25, mode: str = "off"
) -> MockConfigEntry:
    """Chambre en soirée, clim arrêtée, consigne de soirée réglée, personne."""
    daytime.move_to(EVENING)
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(
        CLIMATE, mode, {**CLIMATE_ATTRS, "hvac_modes": ["off", "cool", "fan_only"]}
    )
    entry = await _setup(hass, **{CONF_CLIMATES: [CLIMATE]})
    await _set_time(hass, entry, "evening_start", "19:00:00")
    await hass.services.async_call(
        "number",
        "set_value",
        {
            "entity_id": _eid(hass, entry, "number", "evening_climate_temperature"),
            "value": temperature,
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    return entry


async def test_evening_climate_on_with_presence(hass: HomeAssistant, daytime) -> None:
    set_temp = async_mock_service(hass, "climate", "set_temperature")
    entries = async_capture_events(hass, "logbook_entry")
    await _setup_evening_climate(hass, daytime)
    assert set_temp == []

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert _entities(set_temp) == [[CLIMATE]]
    assert set_temp[0].data["hvac_mode"] == "cool"
    assert set_temp[0].data["temperature"] == 25
    assert entries[-1].data["message"] == "allume la clim à 25 °C, présence en soirée"


async def test_evening_climate_off_when_vacant_then_on_again(hass: HomeAssistant, daytime) -> None:
    set_temp = async_mock_service(hass, "climate", "set_temperature")
    turn_off = async_mock_service(hass, "climate", "turn_off")
    set_mode = async_mock_service(hass, "climate", "set_hvac_mode")
    entry = await _setup_evening_climate(hass, daytime)
    # Arrêt en pièce vide, même si le jour est réglé sur « ne rien faire »
    await _select(hass, entry, "climate_vacant_day", "none")
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    hass.states.async_set(
        CLIMATE, "cool", {**CLIMATE_ATTRS, "temperature": 25, "hvac_modes": ["off", "cool"]}
    )
    await hass.async_block_till_done()
    assert _room(hass, entry).state == "occupied"  # confirmation, pas un geste

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)  # absence confirmée
    await _later(hass, seconds=31 + 900)
    assert _entities(turn_off) == [[CLIMATE]]

    hass.states.async_set(
        CLIMATE, "off", {**CLIMATE_ATTRS, "temperature": 25, "hvac_modes": ["off", "cool"]}
    )
    await hass.async_block_till_done()
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    # Retour : l'état d'avant (froid) est rétabli, sans second allumage.
    assert set_mode[0].data["hvac_mode"] == "cool"
    assert len(set_temp) == 1


async def test_evening_climate_disabled_by_default(hass: HomeAssistant, daytime) -> None:
    set_temp = async_mock_service(hass, "climate", "set_temperature")
    await _setup_evening_climate(hass, daytime, temperature=0)

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert set_temp == []


async def test_evening_climate_starts_with_the_evening(hass: HomeAssistant, daytime) -> None:
    set_temp = async_mock_service(hass, "climate", "set_temperature")
    daytime.move_to("2026-10-18T18:59:30-07:00")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(CLIMATE, "off", {**CLIMATE_ATTRS, "hvac_modes": ["off", "cool"]})
    entry = await _setup(hass, **{CONF_CLIMATES: [CLIMATE]})
    await _set_time(hass, entry, "evening_start", "19:00:00")
    await hass.services.async_call(
        "number",
        "set_value",
        {
            "entity_id": _eid(hass, entry, "number", "evening_climate_temperature"),
            "value": 24,
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    assert set_temp == []

    daytime.move_to("2026-10-18T19:00:00-07:00")
    await _later(hass, seconds=0)
    assert set_temp[0].data["temperature"] == 24


async def test_evening_climate_respects_manual_off(hass: HomeAssistant, daytime) -> None:
    set_temp = async_mock_service(hass, "climate", "set_temperature")
    entry = await _setup_evening_climate(hass, daytime)
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    hass.states.async_set(CLIMATE, "cool", {**CLIMATE_ATTRS, "hvac_modes": ["off", "cool"]})
    await hass.async_block_till_done()

    # Arrêtée à la main : contrôle manuel, pas de relance.
    hass.states.async_set(CLIMATE, "off", {**CLIMATE_ATTRS, "hvac_modes": ["off", "cool"]})
    await hass.async_block_till_done()
    assert _room(hass, entry).state == "override"
    assert len(set_temp) == 1


async def test_evening_climate_not_at_night_or_asleep(hass: HomeAssistant, daytime) -> None:
    set_temp = async_mock_service(hass, "climate", "set_temperature")
    entry = await _setup_evening_climate(hass, daytime)
    await _switch(hass, entry, "sleeping")

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert set_temp == []


async def test_evening_climate_leaves_other_modes(hass: HomeAssistant, daytime) -> None:
    set_temp = async_mock_service(hass, "climate", "set_temperature")
    entry = await _setup_evening_climate(hass, daytime, mode="fan_only")

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert _room(hass, entry).state == "occupied"
    assert set_temp == []


async def test_manual_climate_change_is_an_override(hass: HomeAssistant) -> None:
    entry = await _setup_with_climate(hass)

    hass.states.async_set(CLIMATE, "cool", {**CLIMATE_ATTRS, "temperature": 22})
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["climate_override_until"] is not None


async def test_fans_circulate_while_climate_runs(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "fan", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(TEMP, "22")  # sous le seuil : arrêt selon la température
    hass.states.async_set(FAN, "off")
    entry = await _setup_with_climate(hass, **{CONF_FANS: [FAN], CONF_TEMPERATURE: TEMP})
    assert turn_on == []

    await _select(hass, entry, "fans_with_climate", "mix")
    assert _entities(turn_on) == [[FAN]]
    assert turn_on[0].data["percentage"] == 33

    # Clim arrêtée : retour à la règle de température (pièce fraîche).
    # Le ventilateur démarre avec le contexte de la commande de Lumina.
    hass.states.async_set(FAN, "on", {"percentage": 33}, context=turn_on[0].context)
    hass.states.async_set(CLIMATE, "off", CLIMATE_ATTRS)
    await hass.async_block_till_done()
    assert _entities(turn_off) == [[FAN]]


async def test_fans_stop_while_climate_runs(hass: HomeAssistant) -> None:
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(TEMP, "30")
    hass.states.async_set(FAN, "on", {"percentage": 100})
    entry = await _setup_with_climate(hass, **{CONF_FANS: [FAN], CONF_TEMPERATURE: TEMP})

    await _select(hass, entry, "fans_with_climate", "off")
    assert _entities(turn_off) == [[FAN]]


# ----------------------------------------------------------------------
# v0.9.0 : luminosité rétablie, détecteurs muets, confirmations tardives
# ----------------------------------------------------------------------


async def _vacate_until_warning(hass: HomeAssistant, off_delay: int = 121) -> None:
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)  # absence confirmée
    await _later(hass, seconds=off_delay)


async def test_warning_return_restores_previous_brightness(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on", {**DIMMABLE, "brightness": 153})  # 60 %
    await _setup(hass)

    await _vacate_until_warning(hass)
    assert turn_on[-1].data["brightness"] == 51  # 20 %
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    assert _entities(turn_on[-1:]) == [[LIGHT]]
    assert turn_on[-1].data["brightness"] == 153  # pas la luminosité réglée (100 %)


async def test_warning_return_at_night_without_auto_lights(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on", DIMMABLE)  # luminosité inconnue
    entry = await _setup(hass)
    await _set_number(hass, entry, "night_brightness", 0)

    await _vacate_until_warning(hass, off_delay=61)
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    # Allumage automatique coupé la nuit : pleine luminosité, pas 1 %.
    assert turn_on[-1].data["brightness_pct"] == 100


async def test_unavailable_presence_sensor_keeps_room_occupied(
    hass: HomeAssistant,
) -> None:
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)

    # Zigbee2MQTT redémarre : le détecteur ne répond plus un moment.
    hass.states.async_set(PIR, "unavailable")
    await hass.async_block_till_done()
    await _later(hass, minutes=10)
    assert _room(hass, entry).state == "occupied"
    assert turn_off == []

    # De retour, il dit que la pièce est vide : on le croit.
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["vacancy_pending"] is True


async def test_unavailable_presence_sensor_after_restart(hass: HomeAssistant) -> None:
    hass.states.async_set(PIR, "unavailable")
    hass.states.async_set(LUX, "10")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup_after_restart(hass, True)

    await _later(hass, minutes=10)
    assert _room(hass, entry).state == "occupied"

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    assert _room(hass, entry).state == "vacant"


async def test_dead_presence_sensor_turns_nothing_off(hass: HomeAssistant) -> None:
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    clim_off = async_mock_service(hass, "climate", "turn_off")
    hass.states.async_set(PIR, "unavailable")  # piles mortes, pièce vue vide
    hass.states.async_set(LIGHT, "on")
    hass.states.async_set(FAN, "on")
    hass.states.async_set("climate.salon", "cool")
    entry = await _setup(hass, **{CONF_FANS: [FAN], CONF_CLIMATES: ["climate.salon"]})

    room = _room(hass, entry)
    assert room.attributes["presence_unknown"] is True
    assert room.attributes["presence_unavailable"] == [PIR]
    await _later(hass, hours=2)
    assert turn_off == clim_off == []


async def test_presence_sensor_dying_during_confirmation_keeps_room(
    hass: HomeAssistant,
) -> None:
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    hass.states.async_set(PIR, "unavailable")
    await hass.async_block_till_done()

    await _later(hass, minutes=10)
    assert _room(hass, entry).state == "occupied"
    assert turn_off == []


async def test_dead_presence_sensor_raises_repair_issue(hass: HomeAssistant) -> None:
    hass.states.async_set(PIR, "on")
    hass.states.async_set("binary_sensor.pir_2", "unavailable")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass, presence_sensors=[PIR, "binary_sensor.pir_2"])
    issue_id = f"presence_unavailable_{entry.entry_id}"
    registry = ir.async_get(hass)

    await _later(hass, minutes=30)  # redémarrage de Zigbee2MQTT : pas encore
    assert registry.async_get_issue(DOMAIN, issue_id) is None
    await _later(hass, hours=1, minutes=1)  # l'horloge des tests ne bouge pas
    issue = registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders["room"] == "Salon"

    hass.states.async_set("binary_sensor.pir_2", "off")  # piles changées
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def _fan_started_by_lumina(hass: HomeAssistant):
    fan_on = async_mock_service(hass, "fan", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TEMP, "28")
    hass.states.async_set(FAN, "off")
    entry = await _setup(hass, **{CONF_FANS: [FAN], CONF_TEMPERATURE: TEMP})
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert fan_on[0].data["percentage"] == 55
    return entry


async def test_late_fan_confirmation_is_not_an_override(hass: HomeAssistant) -> None:
    entry = await _fan_started_by_lumina(hass)

    # Appareil cloud : l'état arrive tard, sous un autre contexte, arrondi au cran.
    await _later(hass, seconds=10)
    hass.states.async_set(FAN, "on", {"percentage": 50, "percentage_step": 25})
    await hass.async_block_till_done()

    assert _room(hass, entry).state == "occupied"


async def test_different_fan_speed_is_still_an_override(hass: HomeAssistant) -> None:
    entry = await _fan_started_by_lumina(hass)

    await _later(hass, seconds=10)
    hass.states.async_set(FAN, "on", {"percentage": 100})
    await hass.async_block_till_done()

    assert _room(hass, entry).state == "override"


async def test_late_change_after_window_is_an_override(hass: HomeAssistant, daytime) -> None:
    entry = await _fan_started_by_lumina(hass)

    daytime.tick(timedelta(minutes=2))
    await _later(hass, seconds=1)
    hass.states.async_set(FAN, "on", {"percentage": 55})
    await hass.async_block_till_done()

    assert _room(hass, entry).state == "override"


async def test_late_climate_confirmation_is_not_an_override(hass: HomeAssistant) -> None:
    set_temp = async_mock_service(hass, "climate", "set_temperature")
    entry = await _setup_with_climate(hass)
    await _select(hass, entry, "climate_vacant_day", "setback")

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)  # absence confirmée
    await _later(hass, seconds=31 + 900)
    assert set_temp[-1].data["temperature"] == 26

    await _later(hass, seconds=20)
    hass.states.async_set(CLIMATE, "cool", {**CLIMATE_ATTRS, "temperature": 26})
    await hass.async_block_till_done()
    attributes = _room(hass, entry).attributes
    assert attributes["climate_override_until"] is None
    assert attributes["climate_vacant_applied"] == "setback"  # toujours à rétablir


async def test_fan_speed_follows_during_min_cycle(hass: HomeAssistant) -> None:
    fan_on = async_mock_service(hass, "fan", "turn_on")
    set_pct = async_mock_service(hass, "fan", "set_percentage")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "500")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(TEMP, "28")
    hass.states.async_set(FAN, "off")
    hass.states.async_set(FAN2, "off")
    await _setup(hass, **{CONF_FANS: [FAN, FAN2], CONF_TEMPERATURE: TEMP})
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert _entities(fan_on) == [[FAN, FAN2]]

    # Seul le premier a démarré ; la chaleur monte pendant le cycle minimal.
    hass.states.async_set(FAN, "on", {"percentage": 55}, context=fan_on[0].context)
    hass.states.async_set(TEMP, "31")
    await hass.async_block_till_done()

    assert len(fan_on) == 1  # le second attend la fin du cycle
    assert _entities(set_pct) == [[FAN]]
    assert set_pct[0].data["percentage"] == 100


async def test_fan_only_climate_left_alone(hass: HomeAssistant) -> None:
    turn_off = async_mock_service(hass, "climate", "turn_off")
    entry = await _setup_with_climate(hass)
    hass.states.async_set(CLIMATE, "fan_only", CLIMATE_ATTRS, context=Context(user_id=None))
    await hass.async_block_till_done()
    await _select(hass, entry, "climate_vacant_day", "off")
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _eid(hass, entry, "button", "resume")},
        blocking=True,
    )

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)  # absence confirmée
    await _later(hass, seconds=31 + 900)

    assert turn_off == []
    assert _room(hass, entry).attributes["climate_vacant_at"] is None
