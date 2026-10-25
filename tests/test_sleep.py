"""Tests du sommeil : entrée, réveil, et protection du dormeur."""

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
    mock_restore_cache,
)

from homeassistant.core import Context, HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .common import (
    DIMMABLE,
    FAN,
    LIGHT,
    LUX,
    NIGHT,
    PIR,
    TEMP,
    _eid,
    _entities,
    _entry,
    _later,
    _room,
    _setup,
    _setup_after_restart,
    _start,
    _switch,
)
from custom_components.lumina.const import (
    CONF_CLIMATES,
    CONF_FANS,
    CONF_LIGHTS,
    CONF_PRESENCE_STILL,
    CONF_SLEEP,
    CONF_TEMPERATURE,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("daytime")


# ----------------------------------------------------------------------
# Nuit : extinction au coucher (sommeil deviné)
# ----------------------------------------------------------------------


async def test_night_override_lasts_until_morning(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)
    turn_on.clear()

    hass.states.async_set(LIGHT, "off")  # extinction au coucher
    await hass.async_block_till_done()
    until = dt_util.parse_datetime(str(_room(hass, entry).attributes["sleeping_until"]))
    assert dt_util.as_local(until).strftime("%H:%M") == "07:00"

    await _later(hass, minutes=31)
    assert turn_on == []  # la lumière ne se rallume pas au milieu de la nuit


async def test_night_override_can_be_limited(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)
    await _bedtime(hass, entry, "override")
    turn_on.clear()

    hass.states.async_set(LIGHT, "off")
    await hass.async_block_till_done()
    await _later(hass, minutes=31)
    assert _entities(turn_on) == [[LIGHT]]


async def test_night_override_survives_restart(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "off")  # éteinte au coucher, avant le redémarrage
    until = dt_util.utcnow() + timedelta(hours=7, minutes=30)  # 07:00
    entry = await _setup_after_restart(
        hass,
        True,
        room_attrs={
            "lights_override_until": until.isoformat(),
            "overrides_until_morning": ["lights"],
        },
    )

    room = _room(hass, entry)
    assert room.state == "override"
    assert room.attributes["overrides_until_morning"] == ["lights"]
    await _later(hass, minutes=31)
    assert turn_on == []  # pas de rallumage au redémarrage

    # Le matin, la reprise manuelle prend fin comme prévu.
    await _later(hass, hours=7, minutes=31)
    assert _entities(turn_on) == [[LIGHT]]


async def test_expired_override_not_restored(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "off")
    past = dt_util.utcnow() - timedelta(minutes=5)
    entry = await _setup_after_restart(
        hass, True, room_attrs={"lights_override_until": past.isoformat()}
    )

    assert _room(hass, entry).state == "occupied"
    assert _entities(turn_on) == [[LIGHT]]


async def test_night_override_survives_sleeper_dropout(
    hass: HomeAssistant, daytime
) -> None:
    daytime.move_to(NIGHT)
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)
    await _bedtime(hass, entry, "until_wake")  # chambre
    turn_on.clear()
    hass.states.async_set(LIGHT, "off")  # extinction au coucher
    await hass.async_block_till_done()

    # Le détecteur ne voit plus le dormeur : la pièce se vide...
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    assert _room(hass, entry).attributes["occupied"] is False

    # ... mais son prochain mouvement ne rallume pas la lumière.
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert turn_on == []
    assert _room(hass, entry).state == "sleeping"


async def test_night_override_lifted_when_lights_left_on(
    hass: HomeAssistant, daytime
) -> None:
    daytime.move_to(NIGHT)
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on")
    hass.states.async_set("light.salon_2", "on")
    await _setup(hass, **{CONF_LIGHTS: [LIGHT, "light.salon_2"]})
    hass.states.async_set(LIGHT, "off")  # l'autre lampe reste allumée
    await hass.async_block_till_done()

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    await _later(hass, seconds=61)  # délai de nuit

    assert _entities(turn_off) == [[LIGHT, "light.salon_2"]]


async def test_night_manual_turn_on_keeps_set_duration(
    hass: HomeAssistant, daytime
) -> None:
    daytime.move_to(NIGHT)
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)

    # Lumière allumée à la main dans une pièce vide : 30 min, pas jusqu'au matin.
    hass.states.async_set(LIGHT, "on")
    await hass.async_block_till_done()
    until = dt_util.parse_datetime(
        str(_room(hass, entry).attributes["lights_override_until"])
    )
    assert until - dt_util.utcnow() == timedelta(minutes=30)

    await _later(hass, minutes=31)
    await _later(hass, minutes=31, seconds=61)
    assert _entities(turn_off) == [[LIGHT]]


# ----------------------------------------------------------------------
# Sommeil
# ----------------------------------------------------------------------

BED = "input_boolean.lit"


async def _bedtime(hass: HomeAssistant, entry, option: str) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": _eid(hass, entry, "select", "bedtime_gesture"), "option": option},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_sleep_switch_blocks_auto_lights(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)

    # Sieste en journée : autorisée, jusqu'à la prochaine fin de nuit.
    await _switch(hass, entry, "sleeping")
    room = _room(hass, entry)
    assert room.state == "sleeping"
    assert room.attributes["sleep_source"] == "manual"
    # Pièce vide : rien n'est présumé tant que personne n'y a été vu.
    assert room.attributes["presumed_occupied"] is False
    until = dt_util.parse_datetime(str(room.attributes["sleeping_until"]))
    assert dt_util.as_local(until).strftime("%H:%M") == "07:00"

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert turn_on == []
    assert _room(hass, entry).attributes["presumed_occupied"] is True

    await _switch(hass, entry, "sleeping", on=False)
    assert _room(hass, entry).state == "occupied"
    assert _entities(turn_on) == [[LIGHT]]


async def test_sleep_night_light(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "off", {"supported_color_modes": ["color_temp"]})
    entry = await _setup(hass)
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": _eid(hass, entry, "number", "sleep_brightness"), "value": 5},
        blocking=True,
    )
    await _switch(hass, entry, "sleeping")

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert turn_on[0].data["brightness_pct"] == 5
    assert turn_on[0].data["color_temp_kelvin"] == 2700  # teinte de nuit


async def test_sleep_presumes_occupancy_for_fans(hass: HomeAssistant) -> None:
    fan_off = async_mock_service(hass, "homeassistant", "turn_off")
    fan_speed = async_mock_service(hass, "fan", "set_percentage")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(TEMP, "28")
    hass.states.async_set(FAN, "on", {"percentage": 50})
    entry = await _setup(hass, **{CONF_LIGHTS: [], CONF_FANS: [FAN], CONF_TEMPERATURE: TEMP})
    await _switch(hass, entry, "sleeping")

    # Le détecteur ne voit plus le dormeur : les ventilateurs continuent...
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    await _later(hass, hours=1)
    assert fan_off == []
    assert _room(hass, entry).attributes["occupied"] is False

    # ... et suivent toujours la température.
    hass.states.async_set(TEMP, "30")
    await hass.async_block_till_done()
    assert fan_speed[-1].data["percentage"] == 100


async def test_sleep_leaves_climate_alone(hass: HomeAssistant) -> None:
    clim_off = async_mock_service(hass, "climate", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set("climate.salon", "cool", {"temperature": 24})
    entry = await _setup(hass, **{CONF_LIGHTS: [], CONF_CLIMATES: ["climate.salon"]})
    await _switch(hass, entry, "sleeping")

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    await _later(hass, minutes=16)
    assert clim_off == []


async def test_bedtime_gesture_starts_sleep(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)

    hass.states.async_set(LIGHT, "off")
    await hass.async_block_till_done()
    room = _room(hass, entry)
    assert room.state == "sleeping"
    assert room.attributes["sleep_source"] == "lights_off"
    # Le sommeil garde la lumière éteinte : pas besoin de contrôle manuel.
    assert room.attributes["overrides_until_wake"] == []
    # Sans le réglage, un geste ne présume pas l'occupation (salon quitté).
    assert room.attributes["presumed_occupied"] is False


async def test_bedtime_gesture_during_day_is_plain_override(hass: HomeAssistant) -> None:
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)

    hass.states.async_set(LIGHT, "off")
    await hass.async_block_till_done()
    assert _room(hass, entry).state == "override"


async def test_bedtime_gesture_disabled(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)
    await _bedtime(hass, entry, "override")

    hass.states.async_set(LIGHT, "off")
    await hass.async_block_till_done()
    assert _room(hass, entry).state == "override"
    assert _room(hass, entry).attributes["sleeping"] is False


async def test_guessed_sleep_lets_fans_stop(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LIGHT, "on")
    hass.states.async_set(FAN, "on")
    await _setup(hass, **{CONF_FANS: [FAN]})

    hass.states.async_set(LIGHT, "off")  # lumière éteinte en quittant la pièce
    await hass.async_block_till_done()
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    await _later(hass, seconds=1801)  # délai de nuit des ventilateurs

    assert _entities(turn_off) == [[FAN]]


async def test_guessed_sleep_can_presume_occupancy(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LIGHT, "on")
    hass.states.async_set(FAN, "on")
    entry = await _setup(hass, **{CONF_FANS: [FAN]})
    await _bedtime(hass, entry, "until_wake")

    hass.states.async_set(LIGHT, "off")  # extinction au coucher, dans une chambre
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["presumed_occupied"] is True
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    await _later(hass, seconds=1801)

    assert turn_off == []


async def test_sleep_entity(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on")
    hass.states.async_set(BED, "off")
    entry = await _setup(hass, **{CONF_SLEEP: BED})
    turn_on.clear()
    hass.states.async_set(LIGHT, "off")  # éteinte à la main avant de s'allonger
    await hass.async_block_till_done()

    hass.states.async_set(BED, "on")
    await hass.async_block_till_done()
    room = _room(hass, entry)
    assert room.state == "sleeping"
    assert room.attributes["sleep_source"] == "entity"
    # La lumière éteinte avant le coucher reste éteinte par le sommeil.
    assert room.attributes["overrides_until_wake"] == []

    hass.states.async_set(BED, "unavailable")  # entité muette : on garde le sommeil
    await hass.async_block_till_done()
    assert _room(hass, entry).state == "sleeping"

    hass.states.async_set(BED, "off")
    await hass.async_block_till_done()
    room = _room(hass, entry)
    assert room.attributes["sleeping"] is False
    # Réveil par l'entité : l'autre dormeur n'est pas forcément levé, la
    # lumière attend un geste ou la fin du répit.
    assert room.attributes["lights_held"] is True
    assert turn_on == []
    await _later(hass, minutes=31)
    assert _entities(turn_on) == [[LIGHT]]


async def test_sleep_ends_at_night_end(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)
    await _switch(hass, entry, "sleeping")
    turn_on.clear()

    daytime.move_to("2026-10-19T07:00:00-07:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    # Le dormeur qui bouge à 7 h ne s'éclaire pas...
    room = _room(hass, entry)
    assert room.attributes["sleeping"] is False
    assert room.attributes["lights_held"] is True
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert turn_on == []

    # ... même redevenu immobile assez longtemps pour que la pièce semble vide.
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert turn_on == []
    assert _room(hass, entry).attributes["lights_held"] is True

    # Au bout de la durée du contrôle manuel, l'allumage automatique reprend.
    await _later(hass, minutes=31)
    assert _entities(turn_on) == [[LIGHT]]


async def test_light_gesture_ends_wake_hold(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)
    await _switch(hass, entry, "sleeping")
    daytime.move_to("2026-10-19T07:00:00-07:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["wake_hold_until"] is not None

    hass.states.async_set(LIGHT, "on")  # levé, allume à la main : réveillé
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["wake_hold_until"] is None


async def test_restart_across_night_end_in_living_room_has_no_hold(
    hass: HomeAssistant, daytime
) -> None:
    daytime.move_to("2026-10-19T07:10:00-07:00")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LIGHT, "off")
    entry = _entry(hass)
    switch = er.async_get(hass).async_get_or_create(
        "switch", DOMAIN, f"{entry.entry_id}_sleeping", config_entry=entry
    )
    until = dt_util.parse_datetime("2026-10-19T07:00:00-07:00")
    # Sommeil deviné au salon : il ne présume pas de dormeur, sans redémarrage non plus.
    mock_restore_cache(
        hass,
        [
            State(
                switch.entity_id,
                "on",
                {"until": until.isoformat(), "source": "lights_off", "presence_seen": True},
            )
        ],
    )
    await _start(hass, entry)
    assert _room(hass, entry).attributes["wake_hold_until"] is None


async def test_sleep_survives_restart(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "off")
    entry = _entry(hass)
    switch = er.async_get(hass).async_get_or_create(
        "switch", DOMAIN, f"{entry.entry_id}_sleeping", config_entry=entry
    )
    until = dt_util.utcnow() + timedelta(hours=7, minutes=30)
    mock_restore_cache(
        hass,
        [State(switch.entity_id, "on", {"until": until.isoformat(), "source": "lights_off"})],
    )
    await _start(hass, entry)

    room = _room(hass, entry)
    assert room.state == "sleeping"
    assert room.attributes["sleep_source"] == "lights_off"
    assert turn_on == []


async def test_expired_sleep_not_restored(hass: HomeAssistant) -> None:
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LIGHT, "off")
    entry = _entry(hass)
    switch = er.async_get(hass).async_get_or_create(
        "switch", DOMAIN, f"{entry.entry_id}_sleeping", config_entry=entry
    )
    past = dt_util.utcnow() - timedelta(minutes=5)
    mock_restore_cache(hass, [State(switch.entity_id, "on", {"until": past.isoformat()})])
    await _start(hass, entry)

    assert _room(hass, entry).attributes["sleeping"] is False


async def test_override_restored_from_pre_sleep_attribute(
    hass: HomeAssistant, daytime
) -> None:
    daytime.move_to(NIGHT)
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LIGHT, "off")
    until = dt_util.utcnow() + timedelta(hours=7, minutes=30)
    entry = await _setup_after_restart(
        hass,
        True,
        room_attrs={
            "lights_override_until": until.isoformat(),
            "overrides_until_morning": ["lights"],  # nom d'avant 0.10.0
        },
    )
    assert _room(hass, entry).attributes["overrides_until_wake"] == ["lights"]


async def test_manual_turn_on_while_asleep_keeps_set_duration(
    hass: HomeAssistant,
) -> None:
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)
    await _switch(hass, entry, "sleeping")

    hass.states.async_set(LIGHT, "on")  # lampe de chevet allumée à la main
    await hass.async_block_till_done()
    until = dt_util.parse_datetime(
        str(_room(hass, entry).attributes["lights_override_until"])
    )
    assert until - dt_util.utcnow() == timedelta(minutes=30)
    assert _room(hass, entry).attributes["overrides_until_wake"] == []

    await _later(hass, minutes=31)
    await _later(hass, minutes=31, seconds=61)
    assert _entities(turn_off) == [[LIGHT]]


async def _night_light_vacated(hass: HomeAssistant, brightness: int):
    """Lumière faible laissée allumée, pièce vidée jusqu'à l'avertissement."""
    turn_on = async_mock_service(hass, "light", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on", {**DIMMABLE, "brightness": brightness})
    await _setup(hass)
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    await _later(hass, seconds=121)
    return turn_on, turn_off


async def test_warning_dims_a_faint_light_further(hass: HomeAssistant) -> None:
    turn_on, turn_off = await _night_light_vacated(hass, 13)  # 5 %
    assert turn_on[-1].data["brightness"] == 6  # baisse, sans remonter à 20 %
    assert turn_off == []


async def test_warning_skipped_for_a_very_faint_light(hass: HomeAssistant) -> None:
    turn_on, turn_off = await _night_light_vacated(hass, 4)  # veilleuse à 1 %
    assert turn_on == []
    assert _entities(turn_off) == [[LIGHT]]


async def test_sleep_entity_still_on_after_morning_does_not_resleep(
    hass: HomeAssistant, daytime
) -> None:
    daytime.move_to(NIGHT)
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(BED, "off")
    entry = await _setup(hass, **{CONF_SLEEP: BED})
    hass.states.async_set(BED, "on")
    await hass.async_block_till_done()
    daytime.move_to("2026-10-19T07:00:00-07:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["sleeping"] is False

    # Le lit est toujours occupé : ni un rechargement, ni le retour d'une
    # entité muette ne rendorment la pièce.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["sleeping"] is False
    hass.states.async_set(BED, "unavailable")
    hass.states.async_set(BED, "on")
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["sleeping"] is False


async def test_sleep_entity_off_during_restart_wakes(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(BED, "off")  # sorti du lit pendant l'arrêt
    entry = _entry(hass, **{CONF_SLEEP: BED})
    switch = er.async_get(hass).async_get_or_create(
        "switch", DOMAIN, f"{entry.entry_id}_sleeping", config_entry=entry
    )
    until = dt_util.utcnow() + timedelta(hours=7)
    mock_restore_cache(
        hass, [State(switch.entity_id, "on", {"until": until.isoformat(), "source": "entity"})]
    )
    await _start(hass, entry)
    assert _room(hass, entry).attributes["sleeping"] is False


async def test_presumed_sleep_keeps_manual_fan_speed(hass: HomeAssistant) -> None:
    speed = async_mock_service(hass, "fan", "set_percentage")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(TEMP, "30")
    hass.states.async_set(FAN, "on", {"percentage": 100})
    entry = await _setup(hass, **{CONF_LIGHTS: [], CONF_FANS: [FAN], CONF_TEMPERATURE: TEMP})
    await _switch(hass, entry, "sleeping")
    hass.states.async_set(FAN, "on", {"percentage": 30})  # réglé à la main la nuit
    await hass.async_block_till_done()

    hass.states.async_set(PIR, "off")  # le détecteur perd le dormeur
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    assert _room(hass, entry).attributes["overrides_until_wake"] == ["fans"]
    assert speed == []


async def test_fan_speed_set_before_bed_holds_until_wake(hass: HomeAssistant) -> None:
    hass.states.async_set(PIR, "on")
    hass.states.async_set(TEMP, "30")
    hass.states.async_set(FAN, "on", {"percentage": 100})
    entry = await _setup(hass, **{CONF_LIGHTS: [], CONF_FANS: [FAN], CONF_TEMPERATURE: TEMP})
    hass.states.async_set(FAN, "on", {"percentage": 30})
    await hass.async_block_till_done()

    await _switch(hass, entry, "sleeping")
    assert _room(hass, entry).attributes["overrides_until_wake"] == ["fans"]


async def test_sleep_switch_does_not_start_fans_in_empty_room(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "homeassistant", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(FAN, "off")
    entry = await _setup(hass, **{CONF_LIGHTS: [], CONF_FANS: [FAN]})

    await _switch(hass, entry, "sleeping")  # depuis le salon, avant le coucher
    assert turn_on == []

    hass.states.async_set(PIR, "on")  # l'enfant se couche
    await hass.async_block_till_done()
    assert _entities(turn_on) == [[FAN]]
    assert _room(hass, entry).attributes["presumed_occupied"] is True


async def test_bedtime_gesture_ignores_automations(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)

    # Scène « tout éteindre » lancée par une automatisation en partant
    hass.states.async_set(LIGHT, "off", context=Context(parent_id="automation"))
    await hass.async_block_till_done()
    assert _room(hass, entry).state == "override"
    assert _room(hass, entry).attributes["sleeping"] is False


async def test_guessed_sleep_ends_when_living_room_empties(
    hass: HomeAssistant, daytime
) -> None:
    daytime.move_to(NIGHT)
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)  # « jusqu'à ce que la pièce se vide » par défaut
    turn_on.clear()
    hass.states.async_set(LIGHT, "off")  # éteinte en partant se coucher
    await hass.async_block_till_done()
    assert _room(hass, entry).state == "sleeping"

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    assert _room(hass, entry).attributes["sleeping"] is False

    hass.states.async_set(PIR, "on")  # retour au salon à 23 h 30
    await hass.async_block_till_done()
    assert _entities(turn_on) == [[LIGHT]]


async def test_two_lamps_at_bedtime_log_only_sleep(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    entries = async_capture_events(hass, "logbook_entry")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LIGHT, "on")
    hass.states.async_set("light.salon_2", "on")
    await _setup(hass, **{CONF_LIGHTS: [LIGHT, "light.salon_2"]})

    hass.states.async_set(LIGHT, "off")
    hass.states.async_set("light.salon_2", "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=6)

    messages = [e.data["message"] for e in entries]
    assert not any("pendant" in m for m in messages)
    assert any(m.startswith("passe en sommeil") for m in messages)


async def test_night_end_change_moves_sleep_deadline(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)
    hass.states.async_set(LIGHT, "off")
    await hass.async_block_till_done()

    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": _eid(hass, entry, "time", "night_end"), "time": "08:30:00"},
        blocking=True,
    )
    until = dt_util.parse_datetime(str(_room(hass, entry).attributes["sleeping_until"]))
    assert dt_util.as_local(until).strftime("%H:%M") == "08:30"


async def test_night_end_moved_before_now_wakes(hass: HomeAssistant, daytime) -> None:
    daytime.move_to("2026-10-19T06:45:00-07:00")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)
    await _switch(hass, entry, "sleeping")
    await _switch(hass, entry, "forced_night")

    # 6 h 30 est déjà passé : ni le sommeil ni la nuit forcée ne vont jusqu'à demain.
    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": _eid(hass, entry, "time", "night_end"), "time": "06:30:00"},
        blocking=True,
    )
    attrs = _room(hass, entry).attributes
    assert attrs["sleeping"] is False
    assert attrs["forced_night"] is False


async def test_morning_hold_for_unseen_sleeper(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)
    await _switch(hass, entry, "sleeping")
    turn_on.clear()
    hass.states.async_set(PIR, "off")  # dormeur immobile, perdu par le détecteur
    await hass.async_block_till_done()
    await _later(hass, seconds=31)

    daytime.move_to("2026-10-19T07:00:00-07:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    held = dt_util.parse_datetime(str(_room(hass, entry).attributes["wake_hold_until"]))
    assert dt_util.as_local(held).strftime("%H:%M") == "07:30"

    hass.states.async_set(PIR, "on")  # il bouge à 7 h 05 : pas de lumière
    await hass.async_block_till_done()
    assert turn_on == []

    # Au bout de 30 min, l'allumage automatique reprend.
    await _later(hass, minutes=31)
    assert _entities(turn_on) == [[LIGHT]]
    assert _room(hass, entry).attributes["lights_held"] is False


async def test_morning_hold_restored(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "off")
    until = dt_util.utcnow() + timedelta(minutes=20)
    entry = await _setup_after_restart(
        hass, True, room_attrs={"wake_hold_until": until.isoformat()}
    )
    assert _room(hass, entry).attributes["lights_held"] is True
    assert turn_on == []


async def test_night_light_after_bedtime_script(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on")
    entry = await _setup(hass)
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": _eid(hass, entry, "number", "sleep_brightness"), "value": 5},
        blocking=True,
    )
    # Script du coucher : Sommeil, puis lumière éteinte
    await _switch(hass, entry, "sleeping")
    hass.states.async_set(LIGHT, "off", context=Context(parent_id="script"))
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["lights_override_until"] is None
    turn_on.clear()

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    hass.states.async_set(PIR, "on")  # lever à 3 h : la veilleuse s'allume
    await hass.async_block_till_done()
    assert turn_on[-1].data["brightness_pct"] == 5

    # Veilleuse éteinte à la main : refus tenu jusqu'au réveil
    hass.states.async_set(LIGHT, "on", {"brightness": 13})
    await hass.async_block_till_done()
    hass.states.async_set(LIGHT, "off")
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["overrides_until_wake"] == ["lights"]


async def test_restored_sleep_keeps_manual_turn_on_duration(
    hass: HomeAssistant, daytime
) -> None:
    daytime.move_to(NIGHT)
    hass.states.async_set(PIR, "on")
    hass.states.async_set(FAN, "on")
    entry = await _setup(hass, **{CONF_LIGHTS: [], CONF_FANS: [FAN]})

    # Restauration dans l'ordre inverse : le contrôle manuel du ventilateur
    # allumé à la main (sa nature n'est pas sauvegardée), puis le sommeil.
    fan_until = dt_util.utcnow() + timedelta(minutes=20)
    entry.runtime_data.restore_override("fans", fan_until, until_wake=False)
    until = dt_util.utcnow() + timedelta(hours=7, minutes=30)
    entry.runtime_data.start_sleep(
        until=until, presence_seen=True, restored=True, reevaluate=False
    )
    attrs = entry.runtime_data.attributes
    assert attrs["overrides_until_wake"] == []
    assert attrs["fans_override_until"] == fan_until


async def test_legacy_night_override_switch_migrates(hass: HomeAssistant) -> None:
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LIGHT, "off")
    entry = _entry(hass)
    ent_reg = er.async_get(hass)
    legacy = ent_reg.async_get_or_create(
        "switch", DOMAIN, f"{entry.entry_id}_night_override_until_morning",
        config_entry=entry,
    )
    mock_restore_cache(hass, [State(legacy.entity_id, "on")])
    await _start(hass, entry)

    assert ent_reg.async_get(legacy.entity_id) is None
    select = hass.states.get(_eid(hass, entry, "select", "bedtime_gesture"))
    assert select.state == "until_wake"


# ----------------------------------------------------------------------
# Sommeil : rien ne s'allume ni ne s'arrête sur un dormeur
# ----------------------------------------------------------------------

CLIM = "climate.chambre"
MORNING = "2026-10-19T07:00:00-07:00"


async def _vacate(hass: HomeAssistant) -> None:
    """Le détecteur perd le dormeur : absence confirmée."""
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)


async def test_sleep_started_on_unseen_sleeper_keeps_fan_running(
    hass: HomeAssistant, daytime
) -> None:
    daytime.move_to(NIGHT)
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(FAN, "on")
    hass.states.async_set(BED, "off")
    await _setup(hass, **{CONF_LIGHTS: [], CONF_FANS: [FAN], CONF_SLEEP: BED})
    await _vacate(hass)  # déjà immobile au lit, perdu par le détecteur

    # Le téléphone se met en charge : sommeil, sans présence vue depuis.
    hass.states.async_set(BED, "on")
    await hass.async_block_till_done()
    await _later(hass, hours=2)
    assert turn_off == []


async def test_sleep_never_acts_on_running_climate(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    clim_off = async_mock_service(hass, "climate", "turn_off")
    clim_preset = async_mock_service(hass, "climate", "set_preset_mode")
    clim_temp = async_mock_service(hass, "climate", "set_temperature")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(CLIM, "cool", {"temperature": 24, "preset_modes": ["eco"]})
    entry = await _setup(hass, **{CONF_LIGHTS: [], CONF_CLIMATES: [CLIM]})
    await _vacate(hass)
    await _switch(hass, entry, "sleeping")  # depuis le téléphone, dormeur déjà perdu
    for action in ("off", "eco", "setback"):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": _eid(hass, entry, "select", "climate_vacant_night"), "option": action},
            blocking=True,
        )
        await _later(hass, hours=1)
    assert clim_off == clim_preset == clim_temp == []


async def test_fan_keeps_running_through_wake_grace(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(FAN, "on")
    entry = await _setup(hass, **{CONF_LIGHTS: [], CONF_FANS: [FAN]})
    await _switch(hass, entry, "sleeping")
    await _vacate(hass)

    # Réveil de 7 h : le dormeur que le détecteur ne voit pas est toujours là.
    daytime.move_to(MORNING)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await _later(hass, minutes=10)
    assert turn_off == []
    assert _room(hass, entry).attributes["presumed_occupied"] is True

    # 30 min plus tard sans signe de vie : la pièce est vide depuis des heures.
    await _later(hass, minutes=31)
    await _later(hass, minutes=31, seconds=1)
    assert _entities(turn_off) == [[FAN]]


async def test_restart_across_night_end_keeps_light_off(hass: HomeAssistant, daytime) -> None:
    daytime.move_to("2026-10-19T07:10:00-07:00")
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "off")
    entry = _entry(hass)
    switch = er.async_get(hass).async_get_or_create(
        "switch", DOMAIN, f"{entry.entry_id}_sleeping", config_entry=entry
    )
    until = dt_util.parse_datetime(MORNING)  # échu pendant le redémarrage
    mock_restore_cache(
        hass,
        [
            State(
                switch.entity_id,
                "on",
                {"until": until.isoformat(), "source": "manual", "presence_seen": True},
            )
        ],
    )
    await _start(hass, entry)

    assert turn_on == []
    held = dt_util.parse_datetime(str(_room(hass, entry).attributes["wake_hold_until"]))
    assert held - until == timedelta(minutes=30)


async def test_warning_return_while_asleep_never_brightens(
    hass: HomeAssistant, daytime
) -> None:
    daytime.move_to(NIGHT)
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on", DIMMABLE)  # luminosité inconnue
    entry = await _setup(hass)
    await _switch(hass, entry, "sleeping")
    turn_on.clear()
    await _vacate(hass)
    await _later(hass, seconds=61)  # avertissement : la lampe baisse
    assert _room(hass, entry).attributes["lights_warning"] is True
    turn_on.clear()

    hass.states.async_set(PIR, "on")  # le dormeur bouge
    await hass.async_block_till_done()
    assert all(call.data.get("brightness_pct") != 100 for call in turn_on)


async def test_manual_fan_off_stays_off_at_night_end(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    events = async_capture_events(hass, "logbook_entry")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(TEMP, "30")
    hass.states.async_set(FAN, "on", {"percentage": 100})
    entry = await _setup(hass, **{CONF_LIGHTS: [], CONF_FANS: [FAN], CONF_TEMPERATURE: TEMP})
    # Réveil hors de la seconde 0 : l'échéance du geste passe avant le tic
    # de la minute, comme dans Home Assistant à la fin de nuit.
    wake_at = dt_util.parse_datetime(MORNING) + timedelta(seconds=30)
    entry.runtime_data.start_sleep(until=wake_at)
    await hass.async_block_till_done()
    hass.states.async_set(FAN, "off", {"percentage": 0})  # éteint à la main au coucher
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["overrides_until_wake"] == ["fans"]
    events.clear()

    daytime.move_to(MORNING)  # tic de la minute, avant l'échéance
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    # Le geste prend fin à la seconde du réveil : rien n'est décidé en sommeil.
    daytime.move_to(wake_at)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    messages = [event.data["message"] for event in events]
    assert _room(hass, entry).attributes["sleeping"] is False
    assert not any("(sommeil" in text for text in messages), messages
    assert "reprend la gestion des ventilateurs" not in messages


async def test_still_sensor_lets_fans_stop_during_sleep(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")  # radar : voit le dormeur immobile
    hass.states.async_set(FAN, "on")
    entry = await _setup(
        hass, **{CONF_LIGHTS: [], CONF_FANS: [FAN], CONF_PRESENCE_STILL: [PIR]}
    )
    await _switch(hass, entry, "sleeping")
    await _vacate(hass)  # parti dormir ailleurs : la pièce est vraiment vide

    assert _room(hass, entry).attributes["presumed_occupied"] is False
    await _later(hass, seconds=1801)  # délai d'arrêt de nuit
    assert _entities(turn_off) == [[FAN]]


async def test_dead_still_sensor_presumes_again(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set("binary_sensor.radar", "unavailable")
    hass.states.async_set(FAN, "on")
    entry = await _setup(
        hass,
        presence_sensors=[PIR, "binary_sensor.radar"],
        **{CONF_LIGHTS: [], CONF_FANS: [FAN], CONF_PRESENCE_STILL: ["binary_sensor.radar"]},
    )
    await _switch(hass, entry, "sleeping")
    await _vacate(hass)  # seul le PIR répond : il perd le dormeur immobile

    assert _room(hass, entry).attributes["presumed_occupied"] is True
    await _later(hass, hours=2)
    assert turn_off == []


async def test_still_sensor_ends_wake_hold_when_room_empties(
    hass: HomeAssistant, daytime
) -> None:
    daytime.move_to(NIGHT)
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass, **{CONF_PRESENCE_STILL: [PIR]})
    await _switch(hass, entry, "sleeping")
    turn_on.clear()
    daytime.move_to(MORNING)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["lights_held"] is True  # dormeur au lit

    await _vacate(hass)  # levé et sorti : le radar le dit, le réveil est fini
    assert _room(hass, entry).attributes["wake_hold_until"] is None
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert _entities(turn_on) == [[LIGHT]]


async def test_sleep_entity_ignored_in_room_seen_empty(hass: HomeAssistant) -> None:
    events = async_capture_events(hass, "logbook_entry")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(BED, "off")
    entry = await _setup(hass, **{CONF_SLEEP: BED, CONF_PRESENCE_STILL: [PIR]})

    hass.states.async_set(BED, "on")  # téléphone posé immobile au salon
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["sleeping"] is False
    assert "personne n'est dans la pièce" in events[-1].data["message"]

    hass.states.async_set(BED, "off")
    hass.states.async_set(PIR, "on")  # au lit
    hass.states.async_set(BED, "on")
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["sleeping"] is True


async def test_sleep_entity_ignored_long_after_pir_lost_presence(
    hass: HomeAssistant,
) -> None:
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(BED, "off")
    entry = await _setup(hass, **{CONF_SLEEP: BED})
    await _vacate(hass)
    entry.runtime_data._vacant_since -= 31 * 60  # pièce vide depuis 31 min

    hass.states.async_set(BED, "on")
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["sleeping"] is False
