"""Tests de la fin de nuit selon le type du jour : semaine, repos, vacances."""

import pytest

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .common import LIGHT, NIGHT, PIR, _eid, _room, _setup, _switch
from custom_components.lumina.const import CONF_HOLIDAYS, CONF_WORKDAY, DOMAIN

pytestmark = pytest.mark.usefixtures("daytime")

WORKDAY = "binary_sensor.workday"
HOLIDAYS = "calendar.vacances"
# NIGHT : dimanche 18 octobre 2026, 23 h 30 ; demain, lundi 19
MONDAY = "2026-10-19"


def _mock_workday(hass: HomeAssistant, days_off: set[str]) -> None:
    async def check_date(call: ServiceCall) -> dict:
        return {WORKDAY: {"workday": call.data["check_date"] not in days_off}}

    hass.services.async_register(
        "workday", "check_date", check_date, supports_response=SupportsResponse.ONLY
    )


def _mock_calendar(hass: HomeAssistant, holidays: set[str]) -> None:
    async def get_events(call: ServiceCall) -> dict:
        day = call.data["start_date_time"][:10]
        events = [{"summary": "Vacances"}] if day in holidays else []
        return {HOLIDAYS: {"events": events}}

    hass.services.async_register(
        "calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY
    )


async def _set_time(hass: HomeAssistant, entry, key: str, value: str) -> None:
    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": _eid(hass, entry, "time", key), "time": value},
        blocking=True,
    )
    await hass.async_block_till_done()


def _sleep_end(hass: HomeAssistant, entry) -> str:
    until = dt_util.parse_datetime(str(_room(hass, entry).attributes["sleeping_until"]))
    assert until is not None
    return dt_util.as_local(until).strftime("%H:%M")


async def test_without_sources_no_extra_night_ends(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    registry = er.async_get(hass)
    for key in ("night_end_day_off", "night_end_holidays"):
        assert registry.async_get_entity_id("time", DOMAIN, f"{entry.entry_id}_{key}") is None
    assert _room(hass, entry).attributes["night_end_day_kind"] == "workday"


async def test_day_off_ends_night_later(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    _mock_workday(hass, {MONDAY})
    hass.states.async_set(PIR, "on")
    hass.states.async_set(LIGHT, "off")
    entry = await _setup(hass, **{CONF_WORKDAY: WORKDAY})
    await _set_time(hass, entry, "night_end_day_off", "09:00:00")
    await _switch(hass, entry, "sleeping")

    assert _sleep_end(hass, entry) == "09:00"
    assert _room(hass, entry).attributes["night_end_day_kind"] == "day_off"


async def test_workday_keeps_week_night_end(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    _mock_workday(hass, set())
    hass.states.async_set(PIR, "on")
    entry = await _setup(hass, **{CONF_WORKDAY: WORKDAY})
    await _set_time(hass, entry, "night_end", "05:30:00")
    await _switch(hass, entry, "sleeping")

    assert _sleep_end(hass, entry) == "05:30"


async def test_holidays_win_over_day_off(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    _mock_workday(hass, {MONDAY})
    _mock_calendar(hass, {MONDAY})
    hass.states.async_set(PIR, "on")
    entry = await _setup(hass, **{CONF_WORKDAY: WORKDAY, CONF_HOLIDAYS: [HOLIDAYS]})
    await _set_time(hass, entry, "night_end_day_off", "07:30:00")
    await _set_time(hass, entry, "night_end_holidays", "08:00:00")
    await _switch(hass, entry, "sleeping")

    assert _sleep_end(hass, entry) == "08:00"
    assert _room(hass, entry).attributes["night_end_day_kind"] == "holidays"


async def test_holiday_morning_is_still_night(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(f"{MONDAY}T07:30:00-07:00")
    _mock_calendar(hass, {MONDAY})
    entry = await _setup(hass, **{CONF_HOLIDAYS: [HOLIDAYS]})

    # Fin de nuit à 8 h en vacances, 7 h en semaine
    assert _room(hass, entry).attributes["period"] == "night"


async def test_new_holiday_moves_sleep_deadline(hass: HomeAssistant, daytime) -> None:
    daytime.move_to(NIGHT)
    holidays: set[str] = set()
    _mock_calendar(hass, holidays)
    hass.states.async_set(HOLIDAYS, "off")
    hass.states.async_set(PIR, "on")
    entry = await _setup(hass, **{CONF_HOLIDAYS: [HOLIDAYS]})
    await _switch(hass, entry, "sleeping")
    assert _sleep_end(hass, entry) == "07:00"

    # Le calendrier change : demain est un jour de vacances.
    holidays.add(MONDAY)
    hass.states.async_set(HOLIDAYS, "on")
    await hass.async_block_till_done()

    assert _sleep_end(hass, entry) == "08:00"


async def test_unreadable_workday_falls_back_to_weekend(hass: HomeAssistant, daytime) -> None:
    # Vendredi soir, Workday absent : samedi est un jour de repos.
    daytime.move_to("2026-10-23T23:30:00-07:00")
    hass.states.async_set(PIR, "on")
    entry = await _setup(hass, **{CONF_WORKDAY: WORKDAY})
    await _switch(hass, entry, "sleeping")

    assert _sleep_end(hass, entry) == "08:00"


async def test_removed_source_removes_its_night_end(hass: HomeAssistant) -> None:
    _mock_workday(hass, set())
    entry = await _setup(hass, **{CONF_WORKDAY: WORKDAY})
    assert _eid(hass, entry, "time", "night_end_day_off")

    options = {key: value for key, value in entry.data.items() if key != CONF_WORKDAY}
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    unique_id = f"{entry.entry_id}_night_end_day_off"
    assert registry.async_get_entity_id("time", DOMAIN, unique_id) is None
