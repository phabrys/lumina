"""Diagnostics téléchargeables depuis la page de l'intégration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import LuminaConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LuminaConfigEntry
) -> dict[str, Any]:
    """État complet d'une pièce : configuration, réglages et entités suivies."""
    controller = entry.runtime_data

    states: dict[str, Any] = {}
    for entity_id in controller.tracked_entities:
        state = hass.states.get(entity_id)
        states[entity_id] = (
            None
            if state is None
            else {
                "state": state.state,
                "last_changed": state.last_changed.isoformat(),
                "attributes": {
                    key: state.attributes.get(key)
                    for key in (
                        "device_class",
                        "brightness",
                        "color_temp_kelvin",
                        "supported_color_modes",
                        "percentage",
                        "percentage_step",
                        "unit_of_measurement",
                    )
                    if key in state.attributes
                },
            }
        )

    return {
        "entry": {
            "title": entry.title,
            "version": f"{entry.version}.{entry.minor_version}",
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "controller": {
            "room_state": controller.room_state,
            "apparent_temperature": controller.apparent_temperature,
            "settings": dict(controller.settings),
            "times": {key: value.isoformat() for key, value in controller.times.items()},
            "climate_actions": dict(controller.climate_actions),
            "groups": {
                kind: {
                    "entity_ids": group.entity_ids,
                    "enabled": group.enabled,
                    "mode": group.mode,
                    "override_until": group.override_until,
                    "off_pending": group.off_timer is not None,
                    "warning": group.warning,
                }
                for kind, group in controller.groups.items()
            },
            **controller.attributes,
        },
        "states": states,
    }
