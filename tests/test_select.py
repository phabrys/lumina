"""Tests des choix de comportement (entités select)."""

from pytest_homeassistant_custom_component.common import mock_restore_cache

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er

from .common import FAN, _eid, _entry, _room, _setup, _start
from custom_components.lumina.const import CONF_CLIMATES, CONF_FANS, DOMAIN


def _select_keys(hass: HomeAssistant, entry) -> set[str]:
    prefix = f"{entry.entry_id}_"
    return {
        e.unique_id.removeprefix(prefix)
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.domain == "select"
    }


async def test_selects_follow_room_devices(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    assert _select_keys(hass, entry) == {"lights_mode", "bedtime_gesture"}


async def test_selects_with_fans_and_climate(hass: HomeAssistant) -> None:
    entry = await _setup(hass, **{CONF_FANS: [FAN], CONF_CLIMATES: ["climate.salon"]})
    assert _select_keys(hass, entry) == {
        "lights_mode",
        "fans_mode",
        "climate_vacant_day",
        "climate_vacant_night",
        "fans_with_climate",
        "bedtime_gesture",
    }


async def test_select_option_changes_controller(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    entity_id = _eid(hass, entry, "select", "lights_mode")
    await hass.services.async_call(
        "select", "select_option", {"entity_id": entity_id, "option": "any"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "any"
    assert _room(hass, entry).attributes["lights_mode"] == "any"


async def test_select_restored_after_restart(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    ent_reg = er.async_get(hass)
    bedtime = ent_reg.async_get_or_create(
        "select", DOMAIN, f"{entry.entry_id}_bedtime_gesture", config_entry=entry
    )
    mode = ent_reg.async_get_or_create(
        "select", DOMAIN, f"{entry.entry_id}_lights_mode", config_entry=entry
    )
    mock_restore_cache(
        hass,
        [
            State(bedtime.entity_id, "until_wake"),
            State(mode.entity_id, "inconnu"),  # option disparue : ignorée
        ],
    )
    await _start(hass, entry)

    attrs = _room(hass, entry).attributes
    assert attrs["bedtime_gesture"] == "until_wake"
    assert attrs["lights_mode"] == "all"
