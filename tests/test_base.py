"""Tests de la minuterie partagée par les parties du contrôleur."""

from datetime import timedelta

from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.lumina.base import Timer


async def test_timer_fires_once_and_clears(hass: HomeAssistant, daytime) -> None:
    fired = []
    timer = Timer()
    timer.start(hass, 60, fired.append)
    assert timer.active
    assert timer.at == dt_util.utcnow() + timedelta(seconds=60)

    daytime.tick(timedelta(seconds=61))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert len(fired) == 1
    assert not timer.active
    assert timer.at is None


async def test_timer_restart_replaces_previous(hass: HomeAssistant, daytime) -> None:
    fired = []
    timer = Timer()
    timer.start(hass, 30, lambda _now: fired.append("first"))
    when = dt_util.utcnow() + timedelta(seconds=90)
    timer.start_at(hass, when, lambda _now: fired.append("second"))
    assert timer.at == when

    daytime.tick(timedelta(seconds=91))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert fired == ["second"]


async def test_timer_cancel(hass: HomeAssistant, daytime) -> None:
    fired = []
    timer = Timer()
    timer.start(hass, 30, fired.append)
    timer.cancel()
    timer.cancel()  # sans minuterie : sans effet
    assert not timer.active
    assert timer.at is None

    daytime.tick(timedelta(seconds=31))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert fired == []
