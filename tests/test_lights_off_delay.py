"""Délai d'extinction des lumières : doublé après un retour rapide."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_mock_service,
)

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .common import FAN, LIGHT, LUX, PIR, _later, _room, _setup
from custom_components.lumina.const import CONF_FANS


@pytest.fixture(autouse=True)
def _daytime(daytime):
    """En journée : délai réglé de 120 s pour les lumières."""


async def _occupied_lit_room(hass: HomeAssistant, **extra):
    async_mock_service(hass, "homeassistant", "turn_off")
    async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on")
    return await _setup(hass, **extra)


async def _leave(hass: HomeAssistant, entry, attribute: str = "lights_off_at") -> float:
    """La pièce se vide : secondes avant l'extinction programmée."""
    hass.states.async_set(PIR, "off")
    await hass.async_block_till_done()
    await _later(hass, seconds=31)
    at = dt_util.parse_datetime(str(_room(hass, entry).attributes[attribute]))
    return (at - dt_util.utcnow()).total_seconds()


async def _lights_go_off(hass: HomeAssistant, entry) -> float:
    delay = await _leave(hass, entry)
    await _later(hass, seconds=delay + 1)
    hass.states.async_set(LIGHT, "off")
    await hass.async_block_till_done()
    return delay


async def _come_back(hass: HomeAssistant) -> None:
    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()
    hass.states.async_set(LIGHT, "on")
    await hass.async_block_till_done()


async def test_quick_return_doubles_the_delay(hass: HomeAssistant, daytime) -> None:
    entries = async_capture_events(hass, "logbook_entry")
    entry = await _occupied_lit_room(hass)
    assert await _lights_go_off(hass, entry) == pytest.approx(120, abs=5)

    daytime.tick(timedelta(minutes=4))
    await _come_back(hass)

    assert await _leave(hass, entry) == pytest.approx(240, abs=5)
    room = _room(hass, entry)
    assert room.attributes["lights_off_delay_factor"] == 2
    assert room.attributes["lights_off_delay"] == 240
    assert "retour rapide : prochaine extinction après 4 min" in [
        e.data["message"] for e in entries
    ]


async def test_later_return_keeps_the_delay(hass: HomeAssistant, daytime) -> None:
    entry = await _occupied_lit_room(hass)
    await _lights_go_off(hass, entry)

    daytime.tick(timedelta(minutes=10))
    await _come_back(hass)

    assert await _leave(hass, entry) == pytest.approx(120, abs=5)


async def test_long_absence_resets_the_delay(hass: HomeAssistant, daytime) -> None:
    entries = async_capture_events(hass, "logbook_entry")
    entry = await _occupied_lit_room(hass)
    await _lights_go_off(hass, entry)
    daytime.tick(timedelta(minutes=1))
    await _come_back(hass)
    await _lights_go_off(hass, entry)

    daytime.tick(timedelta(minutes=31))
    await _come_back(hass)

    assert await _leave(hass, entry) == pytest.approx(120, abs=5)
    assert _room(hass, entry).attributes["lights_off_delay_factor"] == 1
    assert "longue absence : délai d'extinction habituel" in [e.data["message"] for e in entries]


async def test_delay_is_capped(hass: HomeAssistant, daytime) -> None:
    entry = await _occupied_lit_room(hass)
    delays = []
    for _ in range(5):
        delays.append(await _lights_go_off(hass, entry))
        daytime.tick(timedelta(minutes=1))
        await _come_back(hass)

    assert delays == pytest.approx([120, 240, 480, 900, 900], abs=5)
    assert _room(hass, entry).attributes["lights_off_delay"] == 900


async def test_return_during_warning_doubles_the_delay(hass: HomeAssistant) -> None:
    async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LUX, "5")
    hass.states.async_set(LIGHT, "on", {"brightness": 255, "supported_color_modes": ["brightness"]})
    entry = await _setup(hass)
    delay = await _leave(hass, entry)
    await _later(hass, seconds=delay + 1)
    assert _room(hass, entry).attributes["lights_warning"] is True

    hass.states.async_set(PIR, "on")
    await hass.async_block_till_done()

    assert await _leave(hass, entry) == pytest.approx(240, abs=5)


async def test_fans_keep_their_delay(hass: HomeAssistant, daytime) -> None:
    hass.states.async_set(FAN, "on")
    entry = await _occupied_lit_room(hass, **{CONF_FANS: [FAN]})
    fans = await _leave(hass, entry, "fans_off_at")
    await _later(hass, seconds=121)
    hass.states.async_set(LIGHT, "off")
    await hass.async_block_till_done()
    daytime.tick(timedelta(minutes=1))
    await _come_back(hass)

    assert _room(hass, entry).attributes["lights_off_delay_factor"] == 2
    assert await _leave(hass, entry, "fans_off_at") == pytest.approx(fans, abs=5)
