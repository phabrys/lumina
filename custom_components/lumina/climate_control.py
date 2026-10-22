"""Clims d'une pièce : action en pièce vide, rétablissement au retour."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.climate import (
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_PRESET_MODE,
    ATTR_PRESET_MODES,
    PRESET_NONE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, SERVICE_TURN_OFF
from homeassistant.core import State
from homeassistant.util import dt as dt_util

from .base import INVALID_STATES, ActuatorGroup, RoomBase
from .const import (
    CLIMATE_ACTION_ECO,
    CLIMATE_ACTION_NONE,
    CLIMATE_ACTION_OFF,
    CLIMATE_ACTION_SETBACK,
    CLIMATE_IDLE_MODES,
    CLIMATE_RESTORE_WINDOW,
    CLIMATE_SETBACK,
    KIND_CLIMATE,
    SELECT_CLIMATE_VACANT_DAY,
    SELECT_CLIMATE_VACANT_NIGHT,
)

_ATTR_HVAC_MODE_SAVED = "hvac_mode"


def _running(state: State | None) -> bool:
    """La clim agit-elle sur la température (ni arrêtée, ni en simple ventilation) ?"""
    return (
        state is not None
        and state.state not in INVALID_STATES
        and state.state not in CLIMATE_IDLE_MODES
    )


class ClimateControl(RoomBase):
    """Partie du contrôleur consacrée aux clims."""

    # Clim en pièce vide (jour / nuit)
    climate_actions: dict[str, str]

    def _init_climate(self, actions: dict[str, str]) -> None:
        self.climate_actions = actions
        # État des clims avant l'action en pièce vide, pour le rétablir au retour
        self._climate_saved: dict[str, dict[str, Any]] | None = None
        self._climate_saved_action: str | None = None
        self._climate_saved_at: datetime | None = None

    def _climate_running(self) -> bool:
        """Une clim de la pièce agit-elle sur la température ?"""
        return any(
            _running(self.hass.states.get(entity_id))
            for entity_id in self.groups[KIND_CLIMATE].entity_ids
        )

    def _climate_action(self) -> str:
        """Action sur les clims en pièce vide, pour la période en cours."""
        key = SELECT_CLIMATE_VACANT_NIGHT if self.night_rules else SELECT_CLIMATE_VACANT_DAY
        return self.climate_actions[key]

    def _needs_vacant_action(self, group: ActuatorGroup) -> bool:
        """Les clims n'ont d'action en pièce vide que si elle est réglée et pas encore faite."""
        if group.kind != KIND_CLIMATE:
            return True
        return (
            self._climate_action() != CLIMATE_ACTION_NONE
            and self._climate_saved is None
            and self._climate_running()
        )

    def _apply_climate_vacant(self, group: ActuatorGroup) -> None:
        """Pièce vide depuis le délai réglé : arrêt, eco ou consigne relevée."""
        action = self._climate_action()
        if action == CLIMATE_ACTION_NONE:
            return
        context = self._new_context()
        saved: dict[str, dict[str, Any]] = {}
        for entity_id in group.entity_ids:
            state = self.hass.states.get(entity_id)
            # Une clim arrêtée ou en simple ventilation n'a rien à économiser.
            if state is None or not _running(state):
                continue
            attrs = state.attributes
            previous: dict[str, Any] = {
                _ATTR_HVAC_MODE_SAVED: state.state,
                ATTR_TEMPERATURE: attrs.get(ATTR_TEMPERATURE),
                ATTR_PRESET_MODE: attrs.get(ATTR_PRESET_MODE),
            }
            if action == CLIMATE_ACTION_OFF:
                self._service("climate", SERVICE_TURN_OFF, [entity_id], context)
            elif action == CLIMATE_ACTION_ECO:
                if CLIMATE_ACTION_ECO not in (attrs.get(ATTR_PRESET_MODES) or []):
                    continue  # pas de mode eco sur cette clim
                self._service(
                    "climate", SERVICE_SET_PRESET_MODE, [entity_id], context,
                    preset_mode=CLIMATE_ACTION_ECO,
                )
            elif action == CLIMATE_ACTION_SETBACK:
                target = previous[ATTR_TEMPERATURE]
                if target is None:
                    continue  # consigne double (heat_cool, auto) : pas de setback
                # Moins de froid (ou de chaud) : la consigne s'éloigne de la pièce.
                delta = -CLIMATE_SETBACK if state.state == HVACMode.HEAT else CLIMATE_SETBACK
                low = attrs.get(ATTR_MIN_TEMP, target + delta)
                high = attrs.get(ATTR_MAX_TEMP, target + delta)
                self._service(
                    "climate", SERVICE_SET_TEMPERATURE, [entity_id], context,
                    temperature=min(max(target + delta, low), high),
                )
            saved[entity_id] = previous
        if not saved:
            return
        self._climate_saved = saved
        self._climate_saved_action = action
        self._climate_saved_at = dt_util.utcnow()
        self._log(f"climate_{action}_vacant")

    def _evaluate_climate(self) -> None:
        """Retour dans la pièce : rétablit les clims modifiées en son absence."""
        group = self.groups[KIND_CLIMATE]
        if not group.entity_ids or not self.occupied_or_presumed:
            return
        group.cancel_off_timer()
        saved, action, saved_at = (
            self._climate_saved,
            self._climate_saved_action,
            self._climate_saved_at,
        )
        if saved is None or saved_at is None:
            return
        self._clear_climate_saved()
        elapsed = (dt_util.utcnow() - saved_at).total_seconds()
        if not group.active or elapsed > CLIMATE_RESTORE_WINDOW:
            return
        context = self._new_context()
        for entity_id, previous in saved.items():
            if action == CLIMATE_ACTION_OFF:
                self._service(
                    "climate", SERVICE_SET_HVAC_MODE, [entity_id], context,
                    hvac_mode=previous[_ATTR_HVAC_MODE_SAVED],
                )
            elif action == CLIMATE_ACTION_ECO:
                self._service(
                    "climate", SERVICE_SET_PRESET_MODE, [entity_id], context,
                    preset_mode=previous[ATTR_PRESET_MODE] or PRESET_NONE,
                )
            elif action == CLIMATE_ACTION_SETBACK and previous[ATTR_TEMPERATURE] is not None:
                self._service(
                    "climate", SERVICE_SET_TEMPERATURE, [entity_id], context,
                    temperature=previous[ATTR_TEMPERATURE],
                )
        self._log("climate_restored")

    def _clear_climate_saved(self) -> None:
        self._climate_saved = None
        self._climate_saved_action = None
        self._climate_saved_at = None
