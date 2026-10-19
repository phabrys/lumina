"""Tests de la migration de configuration et des diagnostics."""

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.lumina.const import (
    CONF_AREA,
    CONF_LIGHTS,
    CONF_PRESENCE,
    CONF_PRESENCE_HOLD,
    DOMAIN,
)
from custom_components.lumina.diagnostics import async_get_config_entry_diagnostics


async def test_migration_from_1_1(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bureau",
        version=1,
        minor_version=1,
        data={
            CONF_AREA: "bureau",
            CONF_PRESENCE: "binary_sensor.pir_bureau",  # ancienne forme : texte seul
            CONF_LIGHTS: ["light.bureau"],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.minor_version == 2
    assert entry.data[CONF_PRESENCE] == ["binary_sensor.pir_bureau"]
    assert entry.data[CONF_PRESENCE_HOLD] == []


async def test_future_version_is_refused(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bureau",
        version=2,
        data={CONF_AREA: "bureau", CONF_PRESENCE: [], CONF_LIGHTS: []},
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


async def test_diagnostics(hass: HomeAssistant) -> None:
    async_mock_service(hass, "light", "turn_on")  # pièce occupée et sombre
    hass.states.async_set("binary_sensor.pir_bureau", "on")
    hass.states.async_set("light.bureau", "off", {"brightness": None})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bureau",
        version=1,
        minor_version=2,
        data={
            CONF_AREA: "bureau",
            CONF_PRESENCE: ["binary_sensor.pir_bureau"],
            CONF_LIGHTS: ["light.bureau"],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["version"] == "1.2"
    assert diag["controller"]["room_state"] == "occupied"
    assert "lux_threshold" in diag["controller"]["settings"]
    assert diag["states"]["light.bureau"]["state"] == "off"
