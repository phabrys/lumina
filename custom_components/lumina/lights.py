"""Lumières d'une pièce : allumage, teinte, rétablissement et avertissement."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_BRIGHTNESS_PCT,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_SUPPORTED_COLOR_MODES,
    ColorMode,
    brightness_supported,
)
from homeassistant.const import (
    SERVICE_TURN_ON,
)
from homeassistant.helpers.event import (
    async_call_later,
)
from homeassistant.util import dt as dt_util

from .base import (
    ActuatorGroup,
    RoomBase,
    domain_of,
)
from .const import (
    KIND_LIGHTS,
    SETTING_DAY_BRIGHTNESS,
    SETTING_DAY_COLOR_TEMP,
    SETTING_EVENING_BRIGHTNESS,
    SETTING_EVENING_COLOR_TEMP,
    SETTING_LIGHT_WARNING,
    SETTING_NIGHT_BRIGHTNESS,
    SETTING_NIGHT_COLOR_TEMP,
    SETTING_SLEEP_BRIGHTNESS,
    WARNING_BRIGHTNESS,
    WARNING_MIN_BRIGHTNESS,
)


class LightControl(RoomBase):
    """Partie du contrôleur consacrée aux lumières."""

    def _evaluate_lights(self) -> None:
        group = self.groups[KIND_LIGHTS]
        if not group.active or not self.occupied:
            return
        was_warning = group.warning
        saved = group.saved_brightness
        group.cancel_off_timer()
        brightness = (
            self.settings[SETTING_SLEEP_BRIGHTNESS]
            if self.sleeping
            else self._light_setting(
                SETTING_DAY_BRIGHTNESS, SETTING_EVENING_BRIGHTNESS, SETTING_NIGHT_BRIGHTNESS
            )
        )
        if was_warning and self._any_on(group):
            # Quelqu'un est revenu pendant l'avertissement : on rétablit. En
            # sommeil, une luminosité inconnue n'est pas devinée : la lampe
            # reste baissée plutôt que d'éclairer le dormeur en grand.
            if self.sleeping:
                saved = {e: level for e, level in saved.items() if level}
            self._restore_lights(group, saved, brightness)
            self._log("lights_restored", reason=self._reason())
            return
        self._check_daylight()
        if brightness <= 0 or self.daylight_locked or self.lights_held:
            return  # pas d'allumage automatique pour l'instant
        if not self._is_dark():
            return
        targets = self._to_turn_on(group)
        if targets:
            self._turn_on_lights(group, brightness, targets)
            self._night_light_lit = self.sleeping
            self._log("lights_on", brightness=brightness, reason=self._reason())

    def _turn_on_lights(
        self,
        group: ActuatorGroup,
        brightness: float,
        entity_ids: list[str] | None = None,
    ) -> None:
        color_temp = self._light_setting(
            SETTING_DAY_COLOR_TEMP, SETTING_EVENING_COLOR_TEMP, SETTING_NIGHT_COLOR_TEMP
        )
        context = self._new_context()
        lights_ct: list[str] = []
        lights_plain: list[str] = []
        others: list[str] = []
        for entity_id in entity_ids or group.entity_ids:
            if domain_of(entity_id) != "light":
                others.append(entity_id)
            elif color_temp > 0 and self._supports_color_temp(entity_id):
                lights_ct.append(entity_id)
            else:
                lights_plain.append(entity_id)
        data = {ATTR_BRIGHTNESS_PCT: round(brightness)}
        if lights_ct:
            self._service(
                "light",
                SERVICE_TURN_ON,
                lights_ct,
                context,
                **data,
                **{ATTR_COLOR_TEMP_KELVIN: round(color_temp)},
            )
        if lights_plain:
            self._service("light", SERVICE_TURN_ON, lights_plain, context, **data)
        if others:
            self._service("homeassistant", SERVICE_TURN_ON, others, context)

    def _restore_lights(
        self, group: ActuatorGroup, saved: dict[str, int | None], brightness: float
    ) -> None:
        """Rend à chaque lumière baissée la luminosité qu'elle avait avant."""
        context = self._new_context()
        by_level: dict[int, list[str]] = {}
        unknown: list[str] = []
        for entity_id, level in saved.items():
            if level:
                by_level.setdefault(level, []).append(entity_id)
            else:
                unknown.append(entity_id)
        for level, entity_ids in by_level.items():
            self._service("light", SERVICE_TURN_ON, entity_ids, context, **{ATTR_BRIGHTNESS: level})
        if unknown:
            # Luminosité d'avant inconnue : celle du réglage, ou pleine si
            # l'allumage automatique est coupé (luminosité réglée à 0).
            self._turn_on_lights(group, brightness if brightness > 0 else 100, unknown)

    def _supports_color_temp(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        modes = state.attributes.get(ATTR_SUPPORTED_COLOR_MODES) or []
        return ColorMode.COLOR_TEMP in modes

    def _dimmable(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        return state is not None and brightness_supported(
            state.attributes.get(ATTR_SUPPORTED_COLOR_MODES)
        )

    def _brightness(self, entity_id: str) -> int | None:
        state = self.hass.states.get(entity_id)
        return None if state is None else state.attributes.get(ATTR_BRIGHTNESS)

    def _start_light_warning(
        self, group: ActuatorGroup, on_end: Callable[[datetime], None]
    ) -> bool:
        """Baisse les lumières avant l'extinction ; faux si aucune ne peut baisser.

        Baisser, jamais éclairer : la moitié de la luminosité actuelle, au plus
        WARNING_BRIGHTNESS. Une veilleuse trop faible s'éteint directement, et
        une lumière sans variateur ne peut pas baisser.
        """
        warning = self.settings[SETTING_LIGHT_WARNING]
        if group.kind != KIND_LIGHTS or warning <= 0:
            return False
        targets: dict[int, list[str]] = {}
        for entity_id in group.entity_ids:
            if (
                domain_of(entity_id) != "light"
                or not self._is_on(entity_id)
                or not self._dimmable(entity_id)
            ):
                continue
            current = self._brightness(entity_id)
            target = round(255 * WARNING_BRIGHTNESS / 100)
            if current is not None:
                target = min(target, current // 2)
            if target >= WARNING_MIN_BRIGHTNESS:
                targets.setdefault(target, []).append(entity_id)
        if not targets:
            return False
        # Luminosité de chaque lumière, rétablie si quelqu'un revient
        group.saved_brightness = {
            e: self._brightness(e) for entity_ids in targets.values() for e in entity_ids
        }
        context = self._new_context()
        for target, entity_ids in targets.items():
            self._service(
                "light",
                SERVICE_TURN_ON,
                entity_ids,
                context,
                **{ATTR_BRIGHTNESS: target},
            )
        group.warning = True
        group.off_timer = async_call_later(self.hass, warning, on_end)
        group.off_at = dt_util.utcnow() + timedelta(seconds=warning)
        self._log("lights_warning")
        return True
