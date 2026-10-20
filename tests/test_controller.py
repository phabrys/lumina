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

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
    await _later(hass, seconds=31)  # absence confirmée

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
