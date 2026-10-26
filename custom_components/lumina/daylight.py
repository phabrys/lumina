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
    SUN_ABOVE_HORIZON,
    SUN_ENTITY,
)


class DaylightControl(RoomBase):
    """Partie du contrôleur consacrée à la lumière naturelle."""

    def _init_daylight(self) -> None:
        # Lumière du jour : extinction différée, puis verrou d'allumage
        self.daylight_locked = False
        self._daylight_timer: CALLBACK_TYPE | None = None
        self._relock_timer: CALLBACK_TYPE | None = None

    def _sun_up(self) -> bool:
        """Soleil levé ? Inconnu, il est supposé couché."""
        sun = self.hass.states.get(SUN_ENTITY)
        return sun is not None and sun.state == SUN_ABOVE_HORIZON

    def _daylight_enough(self) -> bool:
        """La lumière naturelle suffit-elle à éteindre ?

        Sans capteur de luminosité, le soleil levé en tient lieu.
        """
        if self.illuminance is None:
            return self._sun_up()
        off_lux = self.settings[SETTING_DAYLIGHT_OFF_LUX]
        lux = self._numeric_state(self.illuminance)
        return off_lux > 0 and lux is not None and lux >= off_lux

    def _dark_again(self) -> bool:
        """Fait-il de nouveau sombre, pour lever le verrou d'allumage ?"""
        if self.illuminance is None:
            return not self._sun_up()
        lux = self._numeric_state(self.illuminance)
        return lux is not None and lux < self.settings[SETTING_LUX_THRESHOLD]

    def _check_daylight(self) -> None:
        """Éteint les lumières quand la lumière naturelle suffit durablement."""
        group = self.groups[KIND_LIGHTS]

        # Verrou posé après une extinction : levé quand il refait sombre.
        if self.daylight_locked:
            if self._dark_again():
                if self._relock_timer is None:
                    self._relock_timer = async_call_later(
                        self.hass, DAYLIGHT_RELOCK_DELAY, self._unlock_daylight
                    )
            else:
                cancel_timer(self._relock_timer)
                self._relock_timer = None

        if (
            not self._daylight_enough()
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
        if self._daylight_enough() and group.active and self._any_on(group):
            self._call(group, SERVICE_TURN_OFF)
            self.daylight_locked = True
            if self.illuminance is None:
                self._log("lights_off_sun_up")
            else:
                self._log(
                    "lights_off_daylight", lux=self._numeric_state(self.illuminance)
                )
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
