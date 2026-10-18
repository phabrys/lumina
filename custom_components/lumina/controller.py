"""Machine à états d'une pièce gérée par Lumina."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime, time, timedelta
import logging
from typing import Any

from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .const import (
    CONF_FANS,
    CONF_ILLUMINANCE,
    CONF_LIGHTS,
    CONF_PRESENCE,
    CONF_TEMPERATURE,
    DEFAULT_SETTINGS,
    DEFAULT_TIMES,
    KIND_FANS,
    KIND_LIGHTS,
    ROOM_OCCUPIED,
    ROOM_OVERRIDE,
    ROOM_VACANT,
    PERIOD_DAY,
    PERIOD_NIGHT,
    SETTING_DAY_BRIGHTNESS,
    SETTING_FAN_OFF_DELAY,
    SETTING_LIGHT_OFF_DELAY,
    SETTING_LUX_THRESHOLD,
    SETTING_NIGHT_BRIGHTNESS,
    SETTING_NIGHT_FAN_OFF_DELAY,
    SETTING_NIGHT_LIGHT_OFF_DELAY,
    SETTING_NIGHT_TEMP_THRESHOLD,
    SETTING_OVERRIDE_DURATION,
    SETTING_TEMP_THRESHOLD,
    TEMP_HYSTERESIS,
    TIME_NIGHT_END,
    TIME_NIGHT_START,
)

_LOGGER = logging.getLogger(__name__)

_INVALID_STATES = {STATE_UNAVAILABLE, STATE_UNKNOWN}


class ActuatorGroup:
    """Groupe d'actionneurs (lumières ou ventilateurs) d'une pièce."""

    def __init__(
        self,
        kind: str,
        entity_ids: list[str],
        off_delay_key: str,
        night_off_delay_key: str,
    ) -> None:
        self.kind = kind
        self.entity_ids = entity_ids
        self.off_delay_key = off_delay_key
        self.night_off_delay_key = night_off_delay_key
        self.enabled = True
        self.override_until: datetime | None = None
        self.off_timer: CALLBACK_TYPE | None = None
        self.override_timer: CALLBACK_TYPE | None = None

    @property
    def overridden(self) -> bool:
        return self.override_until is not None

    @property
    def active(self) -> bool:
        """Le groupe est-il piloté automatiquement en ce moment ?"""
        return bool(self.entity_ids) and self.enabled and not self.overridden

    def cancel_off_timer(self) -> None:
        if self.off_timer is not None:
            self.off_timer()
            self.off_timer = None

    def clear_override(self) -> None:
        if self.override_timer is not None:
            self.override_timer()
            self.override_timer = None
        self.override_until = None


class RoomController:
    """Pilote les lumières et ventilateurs d'une pièce.

    Règles :
    - présence détectée → lumières allumées si la pièce est sombre,
      ventilateurs allumés si la température dépasse le seuil ;
    - pièce vide → extinction après un délai propre à chaque groupe ;
    - action manuelle sur un actionneur → reprise manuelle du groupe
      pendant une durée réglable, levée aussi quand la pièce se vide.
    """

    def __init__(self, hass: HomeAssistant, name: str, config: Mapping[str, Any]) -> None:
        self.hass = hass
        self.name = name
        self.presence: list[str] = list(config.get(CONF_PRESENCE, []))
        self.illuminance: str | None = config.get(CONF_ILLUMINANCE)
        self.temperature: str | None = config.get(CONF_TEMPERATURE)
        self.groups: dict[str, ActuatorGroup] = {
            KIND_LIGHTS: ActuatorGroup(
                KIND_LIGHTS,
                list(config.get(CONF_LIGHTS, [])),
                SETTING_LIGHT_OFF_DELAY,
                SETTING_NIGHT_LIGHT_OFF_DELAY,
            ),
            KIND_FANS: ActuatorGroup(
                KIND_FANS,
                list(config.get(CONF_FANS, [])),
                SETTING_FAN_OFF_DELAY,
                SETTING_NIGHT_FAN_OFF_DELAY,
            ),
        }
        self.settings: dict[str, float] = dict(DEFAULT_SETTINGS)
        self.times: dict[str, time] = dict(DEFAULT_TIMES)
        self.period = PERIOD_DAY
        self.occupied = False
        self._own_contexts: deque[str] = deque(maxlen=64)
        self._unsubs: list[CALLBACK_TYPE] = []
        self._listeners: list[Callable[[], None]] = []

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    @callback
    def async_start(self) -> None:
        """Abonne le contrôleur aux changements d'état utiles."""
        self._unsubs.append(
            async_track_state_change_event(self.hass, self.presence, self._on_presence)
        )
        if self.illuminance:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.illuminance], self._on_environment
                )
            )
        if self.temperature:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.temperature], self._on_environment
                )
            )
        for group in self.groups.values():
            if group.entity_ids:
                self._unsubs.append(
                    async_track_state_change_event(
                        self.hass,
                        group.entity_ids,
                        self._make_actuator_handler(group),
                    )
                )
        self.occupied = self._compute_occupied()
        self.period = self._compute_period()
        self._unsubs.append(
            async_track_time_change(self.hass, self._on_minute, second=0)
        )
        self._unsubs.append(async_at_started(self.hass, self._on_started))

    @callback
    def async_stop(self) -> None:
        """Désabonne le contrôleur et annule les minuteries."""
        while self._unsubs:
            self._unsubs.pop()()
        for group in self.groups.values():
            group.cancel_off_timer()
            group.clear_override()

    async def _on_started(self, _hass: HomeAssistant) -> None:
        self.async_reevaluate()

    # ------------------------------------------------------------------
    # API utilisée par les entités
    # ------------------------------------------------------------------

    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> CALLBACK_TYPE:
        """Enregistre une entité à notifier à chaque changement d'état."""
        self._listeners.append(update_callback)

        @callback
        def remove() -> None:
            self._listeners.remove(update_callback)

        return remove

    @callback
    def set_enabled(self, kind: str, enabled: bool, *, reevaluate: bool = True) -> None:
        group = self.groups[kind]
        group.enabled = enabled
        if not enabled:
            group.cancel_off_timer()
            group.clear_override()
        if reevaluate:
            self.async_reevaluate()
        else:
            self._notify()

    @callback
    def update_setting(self, key: str, value: float, *, reevaluate: bool = True) -> None:
        self.settings[key] = value
        if reevaluate:
            self.async_reevaluate()
        else:
            self._notify()

    @callback
    def update_time(self, key: str, value: time, *, reevaluate: bool = True) -> None:
        self.times[key] = value
        self.period = self._compute_period()
        if reevaluate:
            self.async_reevaluate()
        else:
            self._notify()

    @property
    def is_night(self) -> bool:
        return self.period == PERIOD_NIGHT

    @property
    def room_state(self) -> str:
        if any(group.overridden for group in self.groups.values()):
            return ROOM_OVERRIDE
        return ROOM_OCCUPIED if self.occupied else ROOM_VACANT

    @property
    def attributes(self) -> dict[str, Any]:
        lights = self.groups[KIND_LIGHTS]
        fans = self.groups[KIND_FANS]
        return {
            "period": self.period,
            "occupied": self.occupied,
            "lights_override_until": lights.override_until,
            "fans_override_until": fans.override_until,
            "lights_off_pending": lights.off_timer is not None,
            "fans_off_pending": fans.off_timer is not None,
        }

    # ------------------------------------------------------------------
    # Évaluation
    # ------------------------------------------------------------------

    @callback
    def async_reevaluate(self) -> None:
        """Réapplique les règles à l'état courant de la pièce."""
        if self.occupied:
            self._evaluate_lights()
            self._evaluate_fans()
        else:
            for group in self.groups.values():
                if group.active and group.off_timer is None and self._any_on(group):
                    self._schedule_off(group)
        self._notify()

    def _compute_period(self) -> str:
        """Jour ou nuit selon la plage réglée (début = fin : pas de nuit)."""
        start = self.times[TIME_NIGHT_START]
        end = self.times[TIME_NIGHT_END]
        now = dt_util.now().time().replace(tzinfo=None)
        if start == end:
            night = False
        elif start < end:
            night = start <= now < end
        else:  # plage à cheval sur minuit
            night = now >= start or now < end
        return PERIOD_NIGHT if night else PERIOD_DAY

    def _setting(self, day_key: str, night_key: str) -> float:
        return self.settings[night_key if self.is_night else day_key]

    def _compute_occupied(self) -> bool:
        for entity_id in self.presence:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state == STATE_ON:
                return True
        return False

    def _numeric_state(self, entity_id: str | None) -> float | None:
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in _INVALID_STATES:
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def _is_dark(self) -> bool:
        lux = self._numeric_state(self.illuminance)
        # Sans capteur exploitable, on considère la pièce sombre.
        return lux is None or lux < self.settings[SETTING_LUX_THRESHOLD]

    def _any_on(self, group: ActuatorGroup) -> bool:
        return any(
            (state := self.hass.states.get(entity_id)) is not None
            and state.state == STATE_ON
            for entity_id in group.entity_ids
        )

    def _evaluate_lights(self) -> None:
        group = self.groups[KIND_LIGHTS]
        if not group.active or not self.occupied:
            return
        group.cancel_off_timer()
        brightness = self._setting(SETTING_DAY_BRIGHTNESS, SETTING_NIGHT_BRIGHTNESS)
        if brightness <= 0:
            return  # pas d'allumage automatique sur cette période
        if self._is_dark() and not self._any_on(group):
            self._call(group, SERVICE_TURN_ON, brightness_pct=brightness)

    def _evaluate_fans(self) -> None:
        group = self.groups[KIND_FANS]
        if not group.active or not self.occupied:
            return
        group.cancel_off_timer()
        if self.temperature is None:
            want_on: bool | None = True
        else:
            temp = self._numeric_state(self.temperature)
            threshold = self._setting(
                SETTING_TEMP_THRESHOLD, SETTING_NIGHT_TEMP_THRESHOLD
            )
            if temp is None:
                want_on = None  # capteur indisponible : on ne touche à rien
            elif temp >= threshold:
                want_on = True
            elif temp <= threshold - TEMP_HYSTERESIS:
                want_on = False
            else:
                want_on = None  # dans la bande d'hystérésis
        is_on = self._any_on(group)
        if want_on is True and not is_on:
            self._call(group, SERVICE_TURN_ON)
        elif want_on is False and is_on:
            self._call(group, SERVICE_TURN_OFF)

    def _schedule_off(self, group: ActuatorGroup) -> None:
        group.cancel_off_timer()
        delay = self._setting(group.off_delay_key, group.night_off_delay_key)

        @callback
        def _turn_off(_now: datetime) -> None:
            group.off_timer = None
            if not self.occupied and group.active and self._any_on(group):
                self._call(group, SERVICE_TURN_OFF)
            self._notify()

        group.off_timer = async_call_later(self.hass, delay, _turn_off)

    # ------------------------------------------------------------------
    # Gestion des événements
    # ------------------------------------------------------------------

    @callback
    def _on_presence(self, event: Event[EventStateChangedData]) -> None:
        occupied = self._compute_occupied()
        if occupied == self.occupied:
            return
        self.occupied = occupied
        _LOGGER.debug("%s : pièce %s", self.name, "occupée" if occupied else "vide")
        if not occupied:
            # Pièce vide : on lève les reprises manuelles et on programme l'extinction.
            for group in self.groups.values():
                group.clear_override()
        self.async_reevaluate()

    @callback
    def _on_minute(self, _now: datetime) -> None:
        period = self._compute_period()
        if period != self.period:
            self.period = period
            _LOGGER.debug("%s : passage en période %s", self.name, period)
            self.async_reevaluate()

    @callback
    def _on_environment(self, event: Event[EventStateChangedData]) -> None:
        if self.occupied:
            self._evaluate_lights()
            self._evaluate_fans()
            self._notify()

    def _make_actuator_handler(
        self, group: ActuatorGroup
    ) -> Callable[[Event[EventStateChangedData]], None]:
        @callback
        def _handler(event: Event[EventStateChangedData]) -> None:
            old_state = event.data["old_state"]
            new_state = event.data["new_state"]
            if (
                old_state is None
                or new_state is None
                or old_state.state in _INVALID_STATES
                or new_state.state in _INVALID_STATES
                or old_state.state == new_state.state
            ):
                return
            if new_state.context.id in self._own_contexts:
                return
            self._start_override(group)

        return _handler

    def _start_override(self, group: ActuatorGroup) -> None:
        minutes = self.settings[SETTING_OVERRIDE_DURATION]
        if not group.entity_ids or not group.enabled or minutes <= 0:
            return
        group.clear_override()
        group.cancel_off_timer()
        duration = timedelta(minutes=minutes)
        group.override_until = dt_util.utcnow() + duration
        _LOGGER.debug("%s : reprise manuelle des %s", self.name, group.kind)

        @callback
        def _end_override(_now: datetime) -> None:
            group.override_timer = None
            group.override_until = None
            self.async_reevaluate()

        group.override_timer = async_call_later(self.hass, duration, _end_override)
        self._notify()

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------

    def _call(
        self, group: ActuatorGroup, service: str, brightness_pct: float | None = None
    ) -> None:
        context = Context()
        self._own_contexts.append(context.id)
        _LOGGER.debug("%s : %s %s", self.name, service, group.entity_ids)
        entity_ids = group.entity_ids
        if brightness_pct is not None:
            # Les vraies lumières reçoivent la luminosité, les prises un simple allumage.
            lights = [e for e in entity_ids if e.startswith("light.")]
            entity_ids = [e for e in entity_ids if not e.startswith("light.")]
            if lights:
                self._service("light", service, lights, context,
                              brightness_pct=round(brightness_pct))
        if entity_ids:
            # homeassistant.turn_on/off accepte des domaines mixtes (light, fan, switch).
            self._service("homeassistant", service, entity_ids, context)

    def _service(
        self,
        domain: str,
        service: str,
        entity_ids: list[str],
        context: Context,
        **data: Any,
    ) -> None:
        self.hass.async_create_task(
            self.hass.services.async_call(
                domain,
                service,
                {ATTR_ENTITY_ID: entity_ids, **data},
                blocking=False,
                context=context,
            )
        )

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()
