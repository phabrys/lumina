"""Tests du config flow (ajout d'une pièce)."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)

from custom_components.lumina.const import (
    CONF_AREA,
    CONF_LIGHTS,
    CONF_PRESENCE,
    DOMAIN,
)


def _suggested(result, key):
    for marker in result["data_schema"].schema:
        if marker == key:
            return (marker.description or {}).get("suggested_value")
    return None


async def test_add_room_with_discovery(hass: HomeAssistant) -> None:
    area = ar.async_get(hass).async_create("Bureau")
    ent_reg = er.async_get(hass)
    pir = ent_reg.async_get_or_create(
        "binary_sensor", "test", "pir_bureau", original_device_class="motion"
    )
    light = ent_reg.async_get_or_create("light", "test", "lumiere_bureau")
    for entry in (pir, light):
        ent_reg.async_update_entity(entry.entity_id, area_id=area.id)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AREA: area.id}
    )
    assert result["step_id"] == "entities"
    assert _suggested(result, CONF_PRESENCE) == [pir.entity_id]
    assert _suggested(result, CONF_LIGHTS) == [light.entity_id]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PRESENCE: [pir.entity_id], CONF_LIGHTS: [light.entity_id]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bureau"
    assert result["data"][CONF_AREA] == area.id


async def test_room_requires_an_actuator(hass: HomeAssistant) -> None:
    area = ar.async_get(hass).async_create("Couloir")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AREA: area.id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRESENCE: ["binary_sensor.pir_couloir"]}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_actuator"}


async def test_discovery_through_devices(hass: HomeAssistant) -> None:
    """Entités rattachées par leur appareil, sauf si elles sont affectées ailleurs."""
    area_reg = ar.async_get(hass)
    bureau = area_reg.async_create("Bureau")
    couloir = area_reg.async_create("Couloir")
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", "multicapteur")}
    )
    dr.async_get(hass).async_update_device(device.id, area_id=bureau.id)
    ent_reg = er.async_get(hass)
    pir = ent_reg.async_get_or_create(
        "binary_sensor", "test", "pir", device_id=device.id,
        original_device_class="motion", original_name="Mouvement",
    )
    elsewhere = ent_reg.async_get_or_create(
        "binary_sensor", "test", "pir_couloir", device_id=device.id,
        original_device_class="motion", original_name="Mouvement couloir",
    )
    ent_reg.async_update_entity(elsewhere.entity_id, area_id=couloir.id)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AREA: bureau.id}
    )
    assert _suggested(result, CONF_PRESENCE) == [pir.entity_id]
