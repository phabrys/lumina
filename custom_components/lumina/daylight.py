"""Lumière du jour : extinction quand elle suffit, puis verrou d'allumage."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.const import SERVICE_TURN_OFF
from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .base import RoomBase, Timer
from .const import (
    DAYLIGHT_OFF_DELAY,
    DAYLIGHT_RELOCK_DELAY,
    KIND_LIGHTS,
    SETTING_DAYLIGHT_OFF_LUX,
    SETTING_LUX_THRESHOLD,
    SETTING_SUNRISE_DELAY,
    SETTING_SUNSET_ADVANCE,
    SUN_ABOVE_HORIZON,
    SUN_ENTITY,
    SUN_NEXT_RISING,
    SUN_NEXT_SETTING,
)


class DaylightControl(RoomBase):
    """Partie du contrôleur consacrée à la lumière naturelle."""

    def _init_daylight(self) -> None:
        # Lumière du jour : extinction différée, puis verrou d'allumage
        self.daylight_locked = False
        self._daylight_timer = Timer()
        self._relock_timer = Timer()
        # Dernier avis du soleil (marges comprises), pour réagir à son changement
        self._sun_was_up: bool | None = None

    def _sun_up(self) -> bool:
        """Assez de jour d'après le soleil, marges du matin et du soir comprises.

        Inconnu, le soleil est supposé couché. Le lever du jour se déduit du
        prochain, un jour plus tôt : l'écart d'un jour à l'autre est minime.
        """
        sun = self.hass.states.get(SUN_ENTITY)
        if sun is None or sun.state != SUN_ABOVE_HORIZON:
            return False
        now = dt_util.utcnow()
        setting = _parse(sun.attributes.get(SUN_NEXT_SETTING))
        advance = timedelta(minutes=self.settings[SETTING_SUNSET_ADVANCE])
        if setting is not None and now >= setting - advance:
            return False
        rising = _parse(sun.attributes.get(SUN_NEXT_RISING))
        delay = timedelta(minutes=self.settings[SETTING_SUNRISE_DELAY])
        return rising is None or now >= rising - timedelta(days=1) + delay

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
                if self.illuminance is None:
                    # Le soleil ne vacille pas : pas de délai de confirmation.
                    self.daylight_locked = False
                elif not self._relock_timer.active:
                    self._relock_timer.start(
                        self.hass, DAYLIGHT_RELOCK_DELAY, self._unlock_daylight
                    )
            else:
                self._relock_timer.cancel()

        if (
            not self._daylight_enough()
            or not self.occupied
            or not group.active
            or not self._any_on(group)
        ):
            self._daylight_timer.cancel()
            return
        if self.illuminance is None:
            # Marge du matin déjà écoulée : extinction sans attendre.
            self._daylight_off(dt_util.utcnow())
        elif not self._daylight_timer.active:
            self._daylight_timer.start(self.hass, DAYLIGHT_OFF_DELAY, self._daylight_off)

    @callback
    def _daylight_off(self, _now: datetime) -> None:
        group = self.groups[KIND_LIGHTS]
        if self._daylight_enough() and group.active and self._any_on(group):
            self._call(group, SERVICE_TURN_OFF)
            self.daylight_locked = True
            if self.illuminance is None:
                self._log("lights_off_sun_up")
            else:
                self._log("lights_off_daylight", lux=self._numeric_state(self.illuminance))
        self._notify()

    @callback
    def _unlock_daylight(self, _now: datetime) -> None:
        self.daylight_locked = False
        self.async_reevaluate()

    def _reset_daylight(self) -> None:
        self._daylight_timer.cancel()
        self._relock_timer.cancel()
        self.daylight_locked = False


def _parse(value: object) -> datetime | None:
    """Heure du soleil lue dans ses attributs (texte ISO ou datetime)."""
    if isinstance(value, datetime):
        return value
    return dt_util.parse_datetime(value) if isinstance(value, str) else None
