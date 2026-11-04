"""Appareils lents et lampes à crans : un seul ordre, un vrai avertissement."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_mock_service,
)

from homeassistant.core import HomeAssistant

from .common import LIGHT, LUX, PIR, _entities, _later, _setup


@pytest.fixture(autouse=True)
def _daytime(daytime):
    """En journée, pour que la nuit n'entre pas en jeu."""


async def _dark_room_with_slow_light(hass: HomeAssistant):
    """Présence dans une pièce sombre, lampe qui ne répond pas encore."""
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "off")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass)
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    return entry, turn_on


async def test_slow_light_gets_a_single_order(hass: HomeAssistant) -> None:
    entries = async_capture_events(hass, "logbook_entry")
    _, turn_on = await _dark_room_with_slow_light(hass)
    assert _entities(turn_on) == [[LIGHT]]

    # Comme le 02/11 à 18:14 : la luminosité change avant la réponse de la lampe.
    for lux in ("4", "3", "2"):
        hass.states.async_set(LUX, lux)
        await hass.async_block_till_done()

    assert _entities(turn_on) == [[LIGHT]]
    assert len([e for e in entries if e.data["message"].startswith("allume")]) == 1


async def test_order_is_sent_again_without_answer(hass: HomeAssistant, daytime) -> None:
    _, turn_on = await _dark_room_with_slow_light(hass)

    daytime.tick(timedelta(seconds=61))
    hass.states.async_set(LUX, "4")
    await hass.async_block_till_done()

    assert _entities(turn_on) == [[LIGHT], [LIGHT]]


async def test_answer_ends_the_wait(hass: HomeAssistant) -> None:
    """La lampe a répondu : plus rien n'est attendu, un nouvel ordre part aussitôt."""
    _, turn_on = await _dark_room_with_slow_light(hass)
    context = turn_on[-1].context
    hass.states.async_set(LIGHT, "on", context=context)
    await hass.async_block_till_done()
    hass.states.async_set(LIGHT, "off", context=context)  # ordre de Lumina, pas un geste
    await hass.async_block_till_done()

    hass.states.async_set(LUX, "4")
    await hass.async_block_till_done()
    assert _entities(turn_on) == [[LIGHT], [LIGHT]]


async def _lowest_step_lamp_vacated(hass: HomeAssistant):
    """Lampe au cran 51 dans une pièce qui se vide, jusqu'à l'avertissement."""
    entries = async_capture_events(hass, "logbook_entry")
    turn_on = async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on", {"brightness": 51, "supported_color_modes": ["brightness"]})
    await _setup(hass)
    turn_on.clear()
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    await _later(hass, seconds=121)
    return turn_on, entries


async def test_warning_stays_above_the_zero_step(hass: HomeAssistant) -> None:
    turn_on, _ = await _lowest_step_lamp_vacated(hass)
    # round(25 / 51) vaut 0 et éteindrait une lampe à 5 crans ; round(26 / 51) vaut 1.
    assert turn_on[-1].data["brightness"] == 26


async def test_lamp_going_off_during_warning_is_logged(hass: HomeAssistant) -> None:
    turn_on, entries = await _lowest_step_lamp_vacated(hass)
    hass.states.async_set(LIGHT, "off", context=turn_on[-1].context)
    await hass.async_block_till_done()

    await _later(hass, seconds=16)
    assert "éteint les lumières, pièce vide" in [e.data["message"] for e in entries]
