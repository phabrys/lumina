"""Ventilateurs d'une pièce : marche selon la température, vitesse, clim."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.fan import (
    ATTR_PERCENTAGE,
    ATTR_PERCENTAGE_STEP,
    SERVICE_SET_PERCENTAGE,
)
from homeassistant.const import (
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
)
from homeassistant.core import (
    callback,
)

from .base import (
    ActuatorGroup,
    RoomBase,
    domain_of,
)
from .const import (
    FAN_MIN_CYCLE,
    FAN_SPEED_MIN_CHANGE,
    FANS_WITH_CLIMATE_MIX,
    FANS_WITH_CLIMATE_NORMAL,
    FANS_WITH_CLIMATE_OFF,
    KIND_FANS,
    SETTING_FAN_MIN_SPEED,
    SETTING_FAN_MIX_SPEED,
    SETTING_FAN_SPEED_RANGE,
    SETTING_NIGHT_TEMP_THRESHOLD,
    SETTING_TEMP_THRESHOLD,
    TEMP_HYSTERESIS,
)


class FanControl(RoomBase):
    """Partie du contrôleur consacrée aux ventilateurs."""

    def _evaluate_fans(self) -> None:
        group = self.groups[KIND_FANS]
        if not group.active or not self.occupied_or_presumed:
            return
        group.cancel_off_timer()
        if self.fans_with_climate != FANS_WITH_CLIMATE_NORMAL and self._climate_running():
            self._evaluate_fans_with_climate(group)
            return
        threshold = self._setting(SETTING_TEMP_THRESHOLD, SETTING_NIGHT_TEMP_THRESHOLD)
        temp: float | None = None
        if self.temperature is None:
            want_on: bool | None = True
        else:
            temp = self._effective_temperature()
            if temp is None:
                want_on = None  # capteur indisponible : on ne touche à rien
            elif temp >= threshold:
                want_on = True
            elif temp <= threshold - TEMP_HYSTERESIS:
                want_on = False
            else:
                want_on = None  # dans la bande d'hystérésis

        is_on = self._any_on(group)
        percentage = self._fan_percentage(temp, threshold)
        targets = self._to_turn_on(group) if want_on is True else []
        switching = bool(targets) or (want_on is False and is_on)
        # Bascule trop proche de la précédente : reportée, mais la vitesse des
        # ventilateurs en marche suit toujours la température.
        blocked = switching and self.temperature is not None and self._fan_cycle_blocked(group)
        if want_on is False and is_on:
            if blocked:
                return
            self._call(group, SERVICE_TURN_OFF)
            group.last_temp_switch = self.hass.loop.time()
            self._log("fans_off_temperature", reason=self._reason())
            return
        # Ventilateurs déjà en marche : vitesse ajustée, même si d'autres démarrent.
        if is_on and want_on is not False and percentage is not None:
            self._adjust_fan_speed(group, percentage)
        if targets and not blocked:
            self._turn_on_fans(targets, percentage)
            group.last_temp_switch = self.hass.loop.time()
            if percentage is not None:
                self._log("fans_on_speed", percentage=percentage, reason=self._reason())
            else:
                self._log("fans_on", reason=self._reason())

    def _evaluate_fans_with_climate(self, group: ActuatorGroup) -> None:
        """Clim en marche : brassage à vitesse fixe, ou ventilateurs arrêtés."""
        if self.fans_with_climate == FANS_WITH_CLIMATE_OFF:
            if self._any_on(group):
                self._call(group, SERVICE_TURN_OFF)
                self._log("fans_off_climate")
            return
        if self.fans_with_climate != FANS_WITH_CLIMATE_MIX:
            return
        speed = round(self.settings[SETTING_FAN_MIX_SPEED])
        if self._any_on(group):
            self._adjust_fan_speed(group, speed)
        targets = self._to_turn_on(group)
        if targets:
            self._turn_on_fans(targets, speed)
            self._log("fans_mix", percentage=speed)

    def _fan_cycle_blocked(self, group: ActuatorGroup) -> bool:
        """Bloque une bascule trop proche de la précédente et la reprogramme."""
        if group.last_temp_switch is None:
            return False
        remaining = FAN_MIN_CYCLE - (self.hass.loop.time() - group.last_temp_switch)
        if remaining <= 0:
            return False
        if not group.cycle_timer.active:

            @callback
            def _retry(_now: datetime) -> None:
                # Le cycle minimal est écoulé : la prochaine bascule est permise.
                group.last_temp_switch = None
                if self.occupied_or_presumed:
                    self._evaluate_fans()
                self._notify()

            group.cycle_timer.start(self.hass, remaining, _retry)
        return True

    def _fan_percentage(self, temp: float | None, threshold: float) -> int | None:
        """Vitesse proportionnelle à l'écart au seuil, None sans régulation."""
        min_speed = self.settings[SETTING_FAN_MIN_SPEED]
        if temp is None or min_speed <= 0:
            return None
        span = max(self.settings[SETTING_FAN_SPEED_RANGE], 0.1)
        ratio = min(max((temp - threshold) / span, 0.0), 1.0)
        return round(min_speed + (100 - min_speed) * ratio)

    def _turn_on_fans(self, entity_ids: list[str], percentage: int | None) -> None:
        context = self._new_context()
        fans = [e for e in entity_ids if domain_of(e) == "fan"]
        others = [e for e in entity_ids if domain_of(e) != "fan"]
        if fans and percentage is not None:
            self._service("fan", SERVICE_TURN_ON, fans, context, percentage=percentage)
        elif fans:
            others = entity_ids
        if others:
            self._service("homeassistant", SERVICE_TURN_ON, others, context)

    def _adjust_fan_speed(self, group: ActuatorGroup, percentage: int) -> None:
        to_adjust: list[str] = []
        for entity_id in group.entity_ids:
            state = self.hass.states.get(entity_id)
            if domain_of(entity_id) != "fan" or state is None or state.state != STATE_ON:
                continue
            current = state.attributes.get(ATTR_PERCENTAGE)
            step = state.attributes.get(ATTR_PERCENTAGE_STEP) or 1
            if (
                current is None
                # Pleine vitesse atteinte ou quittée : toujours appliquer.
                or (current != percentage and 100 in (current, percentage))
                or abs(current - percentage) >= max(step / 2, FAN_SPEED_MIN_CHANGE)
            ):
                to_adjust.append(entity_id)
        if to_adjust:
            self._service(
                "fan",
                SERVICE_SET_PERCENTAGE,
                to_adjust,
                self._new_context(),
                percentage=percentage,
            )
            self._log(
                "fans_speed",
                throttle="fan_speed",
                percentage=percentage,
                reason=self._reason(),
            )
