"""Type des jours (semaine, repos, vacances), qui choisit l'heure de fin de nuit."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
import logging
from typing import Any

from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .base import RoomBase
from .const import DAY_HOLIDAYS, DAY_OFF, DAY_WORK

_LOGGER = logging.getLogger(__name__)


class DayControl(RoomBase):
    """Partie du contrôleur qui connaît le type d'aujourd'hui et de demain.

    Vacances si un calendrier de vacances a un événement ce jour-là, sinon
    repos si l'entité Workday ne le compte pas travaillé, sinon semaine. Le
    type est mis en cache : la fin de nuit se calcule sans attendre.
    """

    # Entité Workday et calendriers de vacances, facultatifs
    workday_entity: str | None
    holiday_calendars: list[str]

    def _init_days(self, workday_entity: str | None, holiday_calendars: list[str]) -> None:
        self.workday_entity = workday_entity
        self.holiday_calendars = holiday_calendars
        self.day_kinds = {}
        self._days_task: asyncio.Task[None] | None = None

    @property
    def day_sources(self) -> list[str]:
        return [*([self.workday_entity] if self.workday_entity else []), *self.holiday_calendars]

    @callback
    def _schedule_day_kinds(self, *_args: Any) -> None:
        """Relit le type des jours (au démarrage, chaque heure, à chaque changement)."""
        if not self.day_sources or (self._days_task is not None and not self._days_task.done()):
            return
        self._days_task = self.hass.async_create_background_task(
            self._async_update_day_kinds(), f"lumina {self.name} day kinds"
        )

    @callback
    def _on_day_source(self, _event: Event[EventStateChangedData]) -> None:
        self._schedule_day_kinds()

    def _cancel_day_kinds(self) -> None:
        if self._days_task is not None:
            self._days_task.cancel()
            self._days_task = None

    async def _async_update_day_kinds(self) -> None:
        today = dt_util.now().date()
        days = [today, today + timedelta(days=1)]
        kinds = {day: await self._day_kind(day) for day in days}
        if self._stopped:
            return
        before = [self.night_end_on(day) for day in days]
        self.day_kinds = kinds
        if [self.night_end_on(day) for day in days] != before:
            self._night_end_moved()
            self.async_reevaluate()
        else:
            self._notify()

    async def _day_kind(self, day: date) -> str:
        if self.holiday_calendars and await self._has_holidays(day):
            return DAY_HOLIDAYS
        if self.workday_entity and not await self._is_workday(day):
            return DAY_OFF
        return DAY_WORK

    async def _has_holidays(self, day: date) -> bool:
        """Un des calendriers de vacances a-t-il un événement ce jour-là ?"""
        start = datetime.combine(day, time(), dt_util.get_default_time_zone())
        try:
            response = await self.hass.services.async_call(
                "calendar",
                "get_events",
                {
                    "start_date_time": start.isoformat(),
                    "end_date_time": (start + timedelta(days=1)).isoformat(),
                },
                target={"entity_id": self.holiday_calendars},
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            _LOGGER.debug("%s : calendriers de vacances illisibles (%s)", self.name, err)
            return self.day_kinds.get(day) == DAY_HOLIDAYS
        return any(
            isinstance(result, dict) and result.get("events")
            for result in (response or {}).values()
        )

    async def _is_workday(self, day: date) -> bool:
        """Jour travaillé selon Workday ; illisible, le type déjà connu ou lundi-vendredi."""
        assert self.workday_entity is not None
        try:
            response = await self.hass.services.async_call(
                "workday",
                "check_date",
                {"check_date": day.isoformat()},
                target={"entity_id": self.workday_entity},
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            _LOGGER.debug("%s : jours travaillés illisibles (%s)", self.name, err)
            response = None
        result = (response or {}).get(self.workday_entity)
        if isinstance(result, dict) and "workday" in result:
            return bool(result["workday"])
        if day in self.day_kinds:
            return self.day_kinds[day] != DAY_OFF
        return day.weekday() < 5
