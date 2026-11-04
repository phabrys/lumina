"""Lumière éteinte à la main : tenue tant que la pièce reste occupée."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_mock_service,
)

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .common import (
    LIGHT,
    LUX,
    NIGHT,
    PIR,
    _eid,
    _entities,
    _later,
    _room,
    _setup,
    _setup_after_restart,
    _switch,
)
from custom_components.lumina.const import CONF_LIGHTS

LIGHT2 = "light.salon_lampadaire"
# Soirée : le geste du coucher n'est pas encore armé.
EVENING = "2026-10-18T21:47:34-07:00"


@pytest.fixture(autouse=True)
def _daytime(daytime):
    """En journée sauf mention contraire : le geste du coucher n'est pas armé."""


async def _lit_room(hass: HomeAssistant, **extra):
    """Pièce occupée et sombre, lumière allumée."""
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on")
    return await _setup(hass, **extra)


async def _off_by_hand(hass: HomeAssistant) -> None:
    hass.states.async_set(LIGHT, "off")
    await hass.async_block_till_done()


async def test_stays_off_after_override_duration(hass: HomeAssistant) -> None:
    entries = async_capture_events(hass, "logbook_entry")
    turn_on = async_mock_service(hass, "light", "turn_on")
    entry = await _lit_room(hass)

    await _off_by_hand(hass)
    await _later(hass, minutes=31)
    hass.states.async_set(LUX, "4")  # un capteur qui bouge ne rallume pas
    await hass.async_block_till_done()

    room = _room(hass, entry)
    assert turn_on == []
    assert room.state == "override"
    assert room.attributes["overrides_until_vacant"] == ["lights"]
    assert "garde les lumières éteintes tant que la pièce reste occupée" in [
        e.data["message"] for e in entries
    ]


async def test_evening_gesture_holds_into_the_night(hass: HomeAssistant, daytime) -> None:
    """Soir du 03/11 : éteinte à 21:47, rallumée à 22:17 sur des personnes au lit."""
    daytime.move_to(EVENING)
    turn_on = async_mock_service(hass, "light", "turn_on")
    entry = await _lit_room(hass)

    await _off_by_hand(hass)
    assert _room(hass, entry).attributes["sleeping"] is False

    daytime.move_to(NIGHT)
    await _later(hass, minutes=1)
    assert turn_on == []
    assert _room(hass, entry).state == "override"


async def test_hold_goes_past_night_end(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(EVENING)
    turn_on = async_mock_service(hass, "light", "turn_on")
    entry = await _lit_room(hass)
    await _off_by_hand(hass)

    # La limite de la minuterie n'est pas une fin : la pièce est toujours occupée.
    daytime.move_to(dt_util.utcnow() + timedelta(hours=10))
    await _later(hass, seconds=1)
    assert turn_on == []
    assert _room(hass, entry).attributes["overrides_until_vacant"] == ["lights"]
    assert _room(hass, entry).attributes["lights_override_until"] is not None


async def test_vacant_room_ends_hold(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    entry = await _lit_room(hass)
    await _off_by_hand(hass)

    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    assert _room(hass, entry).attributes["overrides_until_vacant"] == []

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    assert _entities(turn_on) == [[LIGHT]]


async def test_turning_on_by_hand_ends_hold(hass: HomeAssistant) -> None:
    entry = await _lit_room(hass)
    await _off_by_hand(hass)
    await _later(hass, seconds=6)

    hass.states.async_set(LIGHT, "on")
    await hass.async_block_till_done()
    room = _room(hass, entry)
    assert room.attributes["overrides_until_vacant"] == []
    assert room.state == "override"  # la durée réglée

    await _later(hass, minutes=31)
    assert _room(hass, entry).state == "occupied"


async def test_turning_back_on_at_once_ends_hold(hass: HomeAssistant) -> None:
    entry = await _lit_room(hass)
    await _off_by_hand(hass)

    hass.states.async_set(LIGHT, "on")  # dans les 5 s du geste précédent
    await hass.async_block_till_done()
    assert _room(hass, entry).attributes["overrides_until_vacant"] == []

    await _later(hass, minutes=31)
    assert _room(hass, entry).state == "occupied"


async def test_resume_button_ends_hold(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    entry = await _lit_room(hass)
    await _off_by_hand(hass)

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _eid(hass, entry, "button", "resume")},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert _entities(turn_on) == [[LIGHT]]
    assert _room(hass, entry).attributes["overrides_until_vacant"] == []


async def test_lamp_left_on_keeps_the_duration(hass: HomeAssistant) -> None:
    hass.states.async_set(LIGHT2, "on")
    entry = await _lit_room(hass, **{CONF_LIGHTS: [LIGHT, LIGHT2]})

    await _off_by_hand(hass)
    assert _room(hass, entry).attributes["overrides_until_vacant"] == []


async def test_off_in_empty_room_keeps_the_duration(hass: HomeAssistant) -> None:
    entry = await _lit_room(hass)
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)

    await _off_by_hand(hass)
    assert _room(hass, entry).attributes["overrides_until_vacant"] == []


async def test_sleep_takes_over_the_hold(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    entry = await _lit_room(hass)
    await _off_by_hand(hass)

    await _switch(hass, entry, "sleeping")
    room = _room(hass, entry)
    assert room.state == "sleeping"
    assert room.attributes["overrides_until_vacant"] == []
    assert turn_on == []


async def test_hold_survives_restart(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup_after_restart(
        hass,
        True,
        room_attrs={
            "lights_override_until": (dt_util.utcnow() + timedelta(hours=7)).isoformat(),
            "overrides_until_vacant": ["lights"],
        },
    )

    assert _room(hass, entry).attributes["overrides_until_vacant"] == ["lights"]
    assert turn_on == []


async def test_hold_survives_restart_past_its_limit(hass: HomeAssistant) -> None:
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup_after_restart(
        hass,
        True,
        room_attrs={
            "lights_override_until": (dt_util.utcnow() - timedelta(minutes=1)).isoformat(),
            "overrides_until_vacant": ["lights"],
        },
    )

    assert _room(hass, entry).attributes["overrides_until_vacant"] == ["lights"]
    assert turn_on == []
