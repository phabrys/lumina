"""Période de la pièce : jour, soirée ou nuit, selon les plages et la nuit forcée."""

from __future__ import annotations

from datetime import datetime, time

from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .base import RoomBase
from .const import (
    NIGHT_END_TIMES,
    PERIOD_DAY,
    PERIOD_EVENING,
    PERIOD_NIGHT,
    TIME_EVENING_START,
    TIME_NIGHT_START,
)


def _within(start: time, end: time, moment: time) -> bool:
    """`moment` dans la plage [start, end[, éventuellement à cheval sur minuit."""
    if start == end:
        return False
    if start < end:
        return start <= moment < end
    return moment >= start or moment < end


class PeriodControl(RoomBase):
    """Partie du contrôleur qui connaît la période en cours.

    La nuit forcée tient jusqu'à la prochaine heure de fin de nuit.
    """

    forced_night: bool
    forced_night_until: datetime | None

    def _init_periods(self) -> None:
        self.forced_night = False
        self.forced_night_until = None
        self.period = PERIOD_DAY
        # Période d'après les seules plages horaires
        self._natural_period = PERIOD_DAY

    @callback
    def update_time(self, key: str, value: time, *, reevaluate: bool = True) -> None:
        changed = self.times[key] != value
        self.times[key] = value
        if changed and key in NIGHT_END_TIMES:
            self._night_end_moved()
        else:
            self._update_period()
        self._refresh(reevaluate)

    @callback
    def set_forced_night(
        self,
        forced: bool,
        *,
        until: datetime | None = None,
        reevaluate: bool = True,
    ) -> None:
        """Force la nuit jusqu'à la prochaine heure de fin de nuit."""
        if forced and until is None:
            until = self._next_night_end()
        if forced and until is not None and until <= dt_util.utcnow():
            forced = False  # échéance déjà passée (restauration tardive)
        if forced == self.forced_night and until == self.forced_night_until:
            return
        self.forced_night = forced
        self.forced_night_until = until if forced else None
        previous = self.period
        self.period = self._effective_period()
        if reevaluate and self.period != previous:
            self._log("night_forced" if forced else f"{self.period}_restored")
        self._refresh(reevaluate)

    def _update_period(self) -> None:
        """Période recalculée à l'heure qu'il est."""
        self._natural_period = self._compute_natural_period()
        self.period = self._effective_period()

    def _compute_natural_period(self) -> str:
        """Jour, soirée ou nuit selon les plages réglées.

        Début = fin de nuit : pas de nuit. Début de soirée = début de nuit, ou
        pris dans la nuit : pas de soirée.
        """
        local = dt_util.now()
        start = self.times[TIME_NIGHT_START]
        end = self.night_end_on(local.date())
        evening = self.times[TIME_EVENING_START]
        now = local.time().replace(tzinfo=None)
        if _within(start, end, now):
            return PERIOD_NIGHT
        if not _within(start, end, evening) and _within(evening, start, now):
            return PERIOD_EVENING
        return PERIOD_DAY

    def _effective_period(self) -> str:
        return PERIOD_NIGHT if self.forced_night else self._natural_period

    def _expire_forced_night(self) -> None:
        """Heure de fin de nuit atteinte : le forçage s'arrête de lui-même."""
        if (
            self.forced_night
            and self.forced_night_until is not None
            and dt_util.utcnow() >= self.forced_night_until
        ):
            self.forced_night = False
            self.forced_night_until = None

    def _move_forced_night_end(self) -> None:
        """La nuit forcée suit la nouvelle heure de fin de nuit ; passée, elle cesse."""
        if self.forced_night and self.forced_night_until is not None:
            until = self._moved_night_end(self.forced_night_until)
            self.forced_night = until > dt_util.utcnow()
            self.forced_night_until = until if self.forced_night else None
