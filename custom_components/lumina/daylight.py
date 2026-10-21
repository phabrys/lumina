"""Lumière du jour : extinction quand elle suffit, puis verrou d'allumage."""

from __future__ import annotations

from datetime import datetime

from homeassistant.const import SERVICE_TURN_OFF
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers.event import async_call_later

from .base import RoomBase, cancel_timer
from .const import (
    DAYLIGHT_OFF_DELAY,
    DAYLIGHT_RELOCK_DELAY,
    KIND_LIGHTS,
    SETTING_DAYLIGHT_OFF_LUX,
    SETTING_LUX_THRESHOLD,
)


class DaylightControl(RoomBase):
    """Partie du contrôleur consacrée à la lumière naturelle."""

    def _init_daylight(self) -> None:
        # Lumière du jour : extinction différée, puis verrou d'allumage
        self.daylight_locked = False
        self._daylight_timer: CALLBACK_TYPE | None = None
        self._relock_timer: CALLBACK_TYPE | None = None

    def _check_daylight(self) -> None:
        """Éteint les lumières quand la lumière naturelle suffit durablement."""
        group = self.groups[KIND_LIGHTS]
        off_lux = self.settings[SETTING_DAYLIGHT_OFF_LUX]
        lux = self._numeric_state(self.illuminance)

        # Verrou posé après une extinction : levé quand il refait sombre.
        if self.daylight_locked:
            if lux is not None and lux < self.settings[SETTING_LUX_THRESHOLD]:
                if self._relock_timer is None:
                    self._relock_timer = async_call_later(
                        self.hass, DAYLIGHT_RELOCK_DELAY, self._unlock_daylight
                    )
            else:
                cancel_timer(self._relock_timer)
                self._relock_timer = None

        if (
            off_lux <= 0
            or lux is None
            or lux < off_lux
            or not self.occupied
            or not group.active
            or not self._any_on(group)
        ):
            cancel_timer(self._daylight_timer)
            self._daylight_timer = None
            return
        if self._daylight_timer is None:
            self._daylight_timer = async_call_later(
                self.hass, DAYLIGHT_OFF_DELAY, self._daylight_off
            )

    @callback
    def _daylight_off(self, _now: datetime) -> None:
        self._daylight_timer = None
        group = self.groups[KIND_LIGHTS]
        lux = self._numeric_state(self.illuminance)
        off_lux = self.settings[SETTING_DAYLIGHT_OFF_LUX]
        if (
            off_lux > 0
            and lux is not None
            and lux >= off_lux
            and group.active
            and self._any_on(group)
        ):
            self._call(group, SERVICE_TURN_OFF)
            self.daylight_locked = True
            self._log("lights_off_daylight", lux=lux)
        self._notify()

    @callback
    def _unlock_daylight(self, _now: datetime) -> None:
        self._relock_timer = None
        self.daylight_locked = False
        self.async_reevaluate()

    def _reset_daylight(self) -> None:
        cancel_timer(self._daylight_timer)
        cancel_timer(self._relock_timer)
        self._daylight_timer = None
        self._relock_timer = None
        self.daylight_locked = False
