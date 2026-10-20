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
    CONF_HUMIDITY,
    CONF_ILLUMINANCE,
    CONF_LIGHTS,
    CONF_PRESENCE,
    CONF_PRESENCE_HOLD,
    CONF_TEMPERATURE,
    DAYLIGHT_OFF_DELAY,
    DAYLIGHT_RELOCK_DELAY,
    DEFAULT_SETTINGS,
    DEFAULT_TIMES,
    DOMAIN,
    FAN_MIN_CYCLE,
    FAN_SPEED_MIN_CHANGE,
    HOLD_INACTIVE_STATES,
    KIND_FANS,
    KIND_LIGHTS,
    LIGHTS_MODE_ALL,
    LOG_THROTTLE,
    OVERRIDE_DEBOUNCE,
    PERIOD_DAY,
    PERIOD_NIGHT,
    ROOM_OCCUPIED,
    ROOM_OVERRIDE,
    ROOM_VACANT,
    SETTING_DAY_BRIGHTNESS,
    SETTING_DAY_COLOR_TEMP,
    SETTING_DAYLIGHT_OFF_LUX,
    SETTING_FAN_MIN_SPEED,
    SETTING_FAN_OFF_DELAY,
    SETTING_FAN_SPEED_RANGE,
    SETTING_LIGHT_OFF_DELAY,
    SETTING_LIGHT_WARNING,
    SETTING_LUX_THRESHOLD,
    SETTING_NIGHT_BRIGHTNESS,
    SETTING_NIGHT_COLOR_TEMP,
    SETTING_NIGHT_FAN_OFF_DELAY,
    SETTING_NIGHT_LIGHT_OFF_DELAY,
    SETTING_NIGHT_TEMP_THRESHOLD,
    SETTING_OVERRIDE_DURATION,
    SETTING_TEMP_THRESHOLD,
    SETTING_VACANCY_CONFIRM,
    SUN_BELOW_HORIZON,
    SUN_ENTITY,
    TEMP_HYSTERESIS,
    TIME_NIGHT_END,
    TIME_NIGHT_START,
    WARNING_BRIGHTNESS,
)
from .heat import apparent_temperature

_LOGGER = logging.getLogger(__name__)

_INVALID_STATES = {STATE_UNAVAILABLE, STATE_UNKNOWN}
_EVENT_LOGBOOK_ENTRY = "logbook_entry"


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
        # Instant (horloge de la boucle) du début de la reprise manuelle
        self.override_started: float | None = None
        # Lumières baissées en attendant l'extinction
        self.warning = False
        # Dernière bascule marche/arrêt due à la température (ventilateurs)
        self.last_temp_switch: float | None = None
        self.cycle_timer: CALLBACK_TYPE | None = None

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
        self.warning = False

    def clear_override(self) -> None:
        if self.override_timer is not None:
            self.override_timer()
            self.override_timer = None
        self.override_until = None
        self.override_started = None

    def cancel_cycle_timer(self) -> None:
        if self.cycle_timer is not None:
            self.cycle_timer()
            self.cycle_timer = None


class RoomController:
    """Pilote les lumières et ventilateurs d'une pièce.

    Règles :
    - présence détectée → lumières allumées si la pièce est sombre,
      ventilateurs allumés si la température (ressentie) dépasse le seuil,
      à une vitesse qui augmente avec la chaleur ;
    - une entité de maintien (TV, enceinte…) active garde la pièce occupée
      quand les détecteurs ne voient plus personne ;
    - pièce vide → les lumières baissent, puis s'éteignent ; les
      ventilateurs s'arrêtent après leur propre délai ;
    - une absence n'est prise en compte qu'après un court délai de
      confirmation, pour ignorer les micro-coupures des détecteurs ;
    - action manuelle sur un actionneur → reprise manuelle du groupe
      pendant une durée réglable, levée aussi quand la pièce se vide ;
    - ventilateurs : pas de marche/arrêt plus rapprochés que FAN_MIN_CYCLE ;
    - capteur de luminosité muet → on se fie à la position du soleil ;
    - la nuit (plage horaire ou forcée), réglages dédiés.
    """

    def __init__(self, hass: HomeAssistant, name: str, config: Mapping[str, Any]) -> None:
        self.hass = hass
        self.name = name
        self.presence: list[str] = list(config.get(CONF_PRESENCE, []))
        self.presence_hold: list[str] = list(config.get(CONF_PRESENCE_HOLD, []))
        self.illuminance: str | None = config.get(CONF_ILLUMINANCE)
        self.temperature: str | None = config.get(CONF_TEMPERATURE)
        self.humidity: str | None = config.get(CONF_HUMIDITY)
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
        self.forced_night = False
        self.forced_night_until: datetime | None = None
        self.lights_mode = LIGHTS_MODE_ALL
        # Lumière du jour : extinction différée, puis verrou d'allumage
        self.daylight_locked = False
        self._daylight_timer: CALLBACK_TYPE | None = None
        self._relock_timer: CALLBACK_TYPE | None = None
        self._last_logs: dict[str, datetime] = {}
        self.period = PERIOD_DAY
        self._natural_period = PERIOD_DAY
        self.occupied = False
        # Confirmation d'absence en cours, et instant où la présence a cessé
        self._vacancy_timer: CALLBACK_TYPE | None = None
        self._presence_lost_at: float | None = None
        # Temps déjà écoulé depuis la fin de présence, déduit des délais
        # d'extinction programmés au moment où l'absence est confirmée
        self._off_delay_credit = 0.0
        # Entité du capteur d'état, à laquelle le journal rattache ses entrées
        self.state_entity_id: str | None = None
        self._own_contexts: deque[str] = deque(maxlen=64)
        self._unsubs: list[CALLBACK_TYPE] = []
        self._listeners: list[Callable[[], None]] = []

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    @callback
    def async_start(self) -> None:
        """Abonne le contrôleur aux changements d'état utiles."""
        self._track([*self.presence, *self.presence_hold], self._on_presence)
        environment = [
            e for e in (self.illuminance, self.temperature, self.humidity) if e
        ]
        if environment:
            self._track(environment, self._on_environment)
        for group in self.groups.values():
            if group.entity_ids:
                self._track(group.entity_ids, self._make_actuator_handler(group))
        self.occupied = self._compute_occupied()
        self._natural_period = self._compute_natural_period()
        self.period = self._effective_period()
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
            group.cancel_cycle_timer()
        self._reset_daylight()
        self._cancel_vacancy()

    def _track(self, entity_ids: list[str], action: Callable[..., Any]) -> None:
        if entity_ids:
            self._unsubs.append(
                async_track_state_change_event(self.hass, entity_ids, action)
            )

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
        self._refresh(reevaluate)

    @callback
    def update_setting(self, key: str, value: float, *, reevaluate: bool = True) -> None:
        self.settings[key] = value
        self._refresh(reevaluate)

    @callback
    def update_time(self, key: str, value: time, *, reevaluate: bool = True) -> None:
        self.times[key] = value
        self._natural_period = self._compute_natural_period()
        self.period = self._effective_period()
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
            self._log(
                "passe en mode nuit (forcé)" if forced else "repasse en mode jour"
            )
        self._refresh(reevaluate)

    @callback
    def set_lights_mode(self, mode: str, *, reevaluate: bool = True) -> None:
        self.lights_mode = mode
        self._refresh(reevaluate)

    def _next_night_end(self) -> datetime:
        """Prochaine occurrence de l'heure de fin de nuit (même sans plage de nuit)."""
        now = dt_util.now()
        end = self.times[TIME_NIGHT_END]
        candidate = now.replace(
            hour=end.hour, minute=end.minute, second=0, microsecond=0
        )
        if candidate <= now:
            candidate += timedelta(days=1)
        return dt_util.as_utc(candidate)

    @property
    def is_night(self) -> bool:
        return self.period == PERIOD_NIGHT

    @property
    def room_state(self) -> str:
        if any(group.overridden for group in self.groups.values()):
            return ROOM_OVERRIDE
        return ROOM_OCCUPIED if self.occupied else ROOM_VACANT

    @property
    def apparent_temperature(self) -> float | None:
        """Température ressentie, ou None sans humidité exploitable."""
        temp = self._numeric_state(self.temperature)
        humidity = self._numeric_state(self.humidity)
        if temp is None or humidity is None:
            return None
        return apparent_temperature(temp, humidity)

    @property
    def attributes(self) -> dict[str, Any]:
        lights = self.groups[KIND_LIGHTS]
        fans = self.groups[KIND_FANS]
        return {
            "period": self.period,
            "forced_night": self.forced_night,
            "forced_night_until": self.forced_night_until,
            "lights_mode": self.lights_mode,
            "daylight_locked": self.daylight_locked,
            "occupied": self.occupied,
            "vacancy_pending": self._vacancy_timer is not None,
            "presence_hold_active": self._hold_active(),
            "effective_temperature": self._effective_temperature(),
            "lights_override_until": lights.override_until,
            "fans_override_until": fans.override_until,
            "lights_off_pending": lights.off_timer is not None,
            "lights_warning": lights.warning,
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

    def _refresh(self, reevaluate: bool) -> None:
        if reevaluate:
            self.async_reevaluate()
        else:
            self._notify()

    def _compute_natural_period(self) -> str:
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

    def _effective_period(self) -> str:
        return PERIOD_NIGHT if self.forced_night else self._natural_period

    def _setting(self, day_key: str, night_key: str) -> float:
        return self.settings[night_key if self.is_night else day_key]

    def _compute_occupied(self) -> bool:
        if any(
            (state := self.hass.states.get(entity_id)) is not None
            and state.state == STATE_ON
            for entity_id in self.presence
        ):
            return True
        # Le maintien prolonge une occupation, il ne la déclenche pas.
        return self.occupied and self._hold_active()

    def _hold_active(self) -> bool:
        return any(
            (state := self.hass.states.get(entity_id)) is not None
            and state.state not in HOLD_INACTIVE_STATES
            for entity_id in self.presence_hold
        )

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

    def _effective_temperature(self) -> float | None:
        """Température ressentie si l'humidité est connue, sinon mesurée."""
        apparent = self.apparent_temperature
        if apparent is not None:
            return apparent
        return self._numeric_state(self.temperature)

    def _is_dark(self) -> bool:
        if self.illuminance is None:
            # Pas de capteur choisi : la pièce est considérée comme sombre.
            return True
        lux = self._numeric_state(self.illuminance)
        if lux is not None:
            return lux < self.settings[SETTING_LUX_THRESHOLD]
        # Capteur muet : on se fie au soleil plutôt que de supposer la nuit.
        sun = self.hass.states.get(SUN_ENTITY)
        if sun is None or sun.state in _INVALID_STATES:
            return True
        return sun.state == SUN_BELOW_HORIZON

    def _any_on(self, group: ActuatorGroup) -> bool:
        return any(
            (state := self.hass.states.get(entity_id)) is not None
            and state.state == STATE_ON
            for entity_id in group.entity_ids
        )

    def _reason(self) -> str:
        """Contexte lisible des décisions, pour le journal."""
        parts = ["nuit" if self.is_night else "jour"]
        lux = self._numeric_state(self.illuminance)
        if lux is not None:
            parts.append(f"{lux:g} lx")
        elif self.illuminance is not None:
            sun = self.hass.states.get(SUN_ENTITY)
            below = sun is not None and sun.state == SUN_BELOW_HORIZON
            parts.append(
                "luminosité indisponible, soleil couché"
                if below
                else "luminosité indisponible"
            )
        temp = self._effective_temperature()
        if temp is not None:
            label = "ressentis" if self.apparent_temperature is not None else ""
            parts.append(f"{temp:g} °C {label}".strip())
        return ", ".join(parts)

    # --- Lumières -------------------------------------------------------

    def _evaluate_lights(self) -> None:
        group = self.groups[KIND_LIGHTS]
        if not group.active or not self.occupied:
            return
        was_warning = group.warning
        group.cancel_off_timer()
        brightness = self._setting(SETTING_DAY_BRIGHTNESS, SETTING_NIGHT_BRIGHTNESS)
        if was_warning and self._any_on(group):
            # Quelqu'un est revenu pendant l'avertissement : on rétablit.
            self._turn_on_lights(group, max(brightness, 1))
            self._log(f"rétablit les lumières, présence de retour ({self._reason()})")
            return
        self._check_daylight()
        if brightness <= 0 or self.daylight_locked:
            return  # pas d'allumage automatique pour l'instant
        if not self._is_dark():
            return
        off = [e for e in group.entity_ids if not self._is_on(e)]
        if self.lights_mode == LIGHTS_MODE_ALL:
            targets = off
        else:
            targets = group.entity_ids if len(off) == len(group.entity_ids) else []
        if targets:
            self._turn_on_lights(group, brightness, targets)
            self._log(f"allume les lumières à {brightness:g} % ({self._reason()})")

    # --- Lumière du jour --------------------------------------------------

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
            elif self._relock_timer is not None:
                self._relock_timer()
                self._relock_timer = None

        if (
            off_lux <= 0
            or lux is None
            or lux < off_lux
            or not self.occupied
            or not group.active
            or not self._any_on(group)
        ):
            if self._daylight_timer is not None:
                self._daylight_timer()
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
            self._log(f"éteint les lumières, lumière naturelle suffisante ({lux:g} lx)")
        self._notify()

    @callback
    def _unlock_daylight(self, _now: datetime) -> None:
        self._relock_timer = None
        self.daylight_locked = False
        self.async_reevaluate()

    def _reset_daylight(self) -> None:
        for timer in (self._daylight_timer, self._relock_timer):
            if timer is not None:
                timer()
        self._daylight_timer = None
        self._relock_timer = None
        self.daylight_locked = False

    def _is_on(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        return state is not None and state.state == STATE_ON

    def _turn_on_lights(
        self,
        group: ActuatorGroup,
        brightness: float,
        entity_ids: list[str] | None = None,
    ) -> None:
        color_temp = self._setting(SETTING_DAY_COLOR_TEMP, SETTING_NIGHT_COLOR_TEMP)
        context = self._new_context()
        lights_ct: list[str] = []
        lights_plain: list[str] = []
        others: list[str] = []
        for entity_id in entity_ids or group.entity_ids:
            if not entity_id.startswith("light."):
                others.append(entity_id)
            elif color_temp > 0 and self._supports_color_temp(entity_id):
                lights_ct.append(entity_id)
            else:
                lights_plain.append(entity_id)
        data = {"brightness_pct": round(brightness)}
        if lights_ct:
            self._service(
                "light", SERVICE_TURN_ON, lights_ct, context,
                **data, color_temp_kelvin=round(color_temp),
            )
        if lights_plain:
            self._service("light", SERVICE_TURN_ON, lights_plain, context, **data)
        if others:
            self._service("homeassistant", SERVICE_TURN_ON, others, context)

    def _supports_color_temp(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        return "color_temp" in (state.attributes.get("supported_color_modes") or [])

    # --- Ventilateurs ---------------------------------------------------

    def _evaluate_fans(self) -> None:
        group = self.groups[KIND_FANS]
        if not group.active or not self.occupied:
            return
        group.cancel_off_timer()
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
        switching = (want_on is True and not is_on) or (want_on is False and is_on)
        if switching and self.temperature is not None and self._fan_cycle_blocked(group):
            return
        if want_on is True and not is_on:
            self._turn_on_fans(group, percentage)
            group.last_temp_switch = self.hass.loop.time()
            speed = f" à {percentage} %" if percentage is not None else ""
            self._log(f"allume les ventilateurs{speed} ({self._reason()})")
        elif want_on is False and is_on:
            self._call(group, SERVICE_TURN_OFF)
            group.last_temp_switch = self.hass.loop.time()
            self._log(f"arrête les ventilateurs, température revenue ({self._reason()})")
        elif is_on and want_on is not False and percentage is not None:
            self._adjust_fan_speed(group, percentage)

    def _fan_cycle_blocked(self, group: ActuatorGroup) -> bool:
        """Bloque une bascule trop proche de la précédente et la reprogramme."""
        if group.last_temp_switch is None:
            return False
        remaining = FAN_MIN_CYCLE - (self.hass.loop.time() - group.last_temp_switch)
        if remaining <= 0:
            return False
        if group.cycle_timer is None:

            @callback
            def _retry(_now: datetime) -> None:
                group.cycle_timer = None
                # Le cycle minimal est écoulé : la prochaine bascule est permise.
                group.last_temp_switch = None
                if self.occupied:
                    self._evaluate_fans()
                self._notify()

            group.cycle_timer = async_call_later(self.hass, remaining, _retry)
        return True

    def _fan_percentage(self, temp: float | None, threshold: float) -> int | None:
        """Vitesse proportionnelle à l'écart au seuil, None sans régulation."""
        min_speed = self.settings[SETTING_FAN_MIN_SPEED]
        if temp is None or min_speed <= 0:
            return None
        span = max(self.settings[SETTING_FAN_SPEED_RANGE], 0.1)
        ratio = min(max((temp - threshold) / span, 0.0), 1.0)
        return round(min_speed + (100 - min_speed) * ratio)

    def _turn_on_fans(self, group: ActuatorGroup, percentage: int | None) -> None:
        context = self._new_context()
        fans = [e for e in group.entity_ids if e.startswith("fan.")]
        others = [e for e in group.entity_ids if not e.startswith("fan.")]
        if fans and percentage is not None:
            self._service("fan", SERVICE_TURN_ON, fans, context, percentage=percentage)
        elif fans:
            others = group.entity_ids
        if others:
            self._service("homeassistant", SERVICE_TURN_ON, others, context)

    def _adjust_fan_speed(self, group: ActuatorGroup, percentage: int) -> None:
        to_adjust: list[str] = []
        for entity_id in group.entity_ids:
            state = self.hass.states.get(entity_id)
            if (
                not entity_id.startswith("fan.")
                or state is None
                or state.state != STATE_ON
            ):
                continue
            current = state.attributes.get("percentage")
            step = state.attributes.get("percentage_step") or 1
            if (
                current is None
                # Pleine vitesse atteinte ou quittée : toujours appliquer.
                or (current != percentage and 100 in (current, percentage))
                or abs(current - percentage) >= max(step / 2, FAN_SPEED_MIN_CHANGE)
            ):
                to_adjust.append(entity_id)
        if to_adjust:
            self._service(
                "fan", "set_percentage", to_adjust, self._new_context(),
                percentage=percentage,
            )
            self._log(
                f"règle les ventilateurs à {percentage} % ({self._reason()})",
                throttle="fan_speed",
            )

    # --- Extinction -----------------------------------------------------

    def _schedule_off(self, group: ActuatorGroup) -> None:
        group.cancel_off_timer()
        group.cancel_cycle_timer()
        delay = self._setting(group.off_delay_key, group.night_off_delay_key)
        # Le délai court depuis la fin réelle de présence, pas depuis la confirmation.
        delay = max(delay - self._off_delay_credit, 0)

        @callback
        def _delay_elapsed(_now: datetime) -> None:
            group.off_timer = None
            if self.occupied or not group.active or not self._any_on(group):
                self._notify()
                return
            warning = self.settings[SETTING_LIGHT_WARNING]
            dimmable = [
                e for e in group.entity_ids
                if e.startswith("light.")
                and (state := self.hass.states.get(e)) is not None
                and state.state == STATE_ON
            ]
            if group.kind == KIND_LIGHTS and warning > 0 and dimmable:
                self._service(
                    "light", SERVICE_TURN_ON, dimmable, self._new_context(),
                    brightness_pct=WARNING_BRIGHTNESS,
                )
                group.warning = True
                group.off_timer = async_call_later(self.hass, warning, _final_off)
                self._log("baisse les lumières avant extinction")
            else:
                self._turn_off(group)
            self._notify()

        @callback
        def _final_off(_now: datetime) -> None:
            group.off_timer = None
            group.warning = False
            if not self.occupied and group.active and self._any_on(group):
                self._turn_off(group)
            self._notify()

        group.off_timer = async_call_later(self.hass, delay, _delay_elapsed)

    def _turn_off(self, group: ActuatorGroup) -> None:
        self._call(group, SERVICE_TURN_OFF)
        label = "les lumières" if group.kind == KIND_LIGHTS else "les ventilateurs"
        self._log(f"éteint {label}, pièce vide")

    # ------------------------------------------------------------------
    # Gestion des événements
    # ------------------------------------------------------------------

    @callback
    def _on_presence(self, event: Event[EventStateChangedData]) -> None:
        present = self._compute_occupied()
        if present:
            # Présence (re)détectée : une éventuelle confirmation d'absence tombe.
            self._cancel_vacancy()
            if not self.occupied:
                self.occupied = True
                _LOGGER.debug("%s : pièce occupée", self.name)
                self.async_reevaluate()
            else:
                self._notify()
            return

        if not self.occupied:
            self._notify()  # l'état du maintien a pu changer
            return
        confirm = self.settings[SETTING_VACANCY_CONFIRM]
        if confirm <= 0:
            self._presence_lost_at = self.hass.loop.time()
            self._set_vacant()
            return
        if self._vacancy_timer is None:
            self._presence_lost_at = self.hass.loop.time()
            self._vacancy_timer = async_call_later(
                self.hass, confirm, self._confirm_vacancy
            )
        self._notify()

    @callback
    def _confirm_vacancy(self, _now: datetime) -> None:
        self._vacancy_timer = None
        if self._compute_occupied():
            self._notify()
            return
        self._set_vacant()

    def _cancel_vacancy(self) -> None:
        if self._vacancy_timer is not None:
            self._vacancy_timer()
            self._vacancy_timer = None
        self._presence_lost_at = None

    def _set_vacant(self) -> None:
        """Pièce vide confirmée : levée des reprises manuelles, extinctions."""
        self.occupied = False
        _LOGGER.debug("%s : pièce vide", self.name)
        for group in self.groups.values():
            group.clear_override()
        self._reset_daylight()
        if self._presence_lost_at is not None:
            self._off_delay_credit = max(
                self.hass.loop.time() - self._presence_lost_at, 0.0
            )
        self._presence_lost_at = None
        try:
            self.async_reevaluate()
        finally:
            self._off_delay_credit = 0.0

    @callback
    def _on_minute(self, _now: datetime) -> None:
        if (
            self.forced_night
            and self.forced_night_until is not None
            and dt_util.utcnow() >= self.forced_night_until
        ):
            # Heure de fin de nuit atteinte : le forçage s'arrête de lui-même.
            self.forced_night = False
            self.forced_night_until = None
        self._natural_period = self._compute_natural_period()
        period = self._effective_period()
        if period != self.period:
            self.period = period
            self._log("passe en mode nuit" if self.is_night else "passe en mode jour")
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
            ):
                return
            changed = old_state.state != new_state.state
            # Un changement de vitesse à la main compte aussi comme reprise.
            if (
                not changed
                and group.kind == KIND_FANS
                and new_state.state == STATE_ON
                and old_state.attributes.get("percentage")
                != new_state.attributes.get("percentage")
            ):
                changed = True
            if not changed or new_state.context.id in self._own_contexts:
                return
            self._start_override(group)

        return _handler

    def _start_override(self, group: ActuatorGroup) -> None:
        minutes = self.settings[SETTING_OVERRIDE_DURATION]
        if not group.entity_ids or not group.enabled or minutes <= 0:
            return
        now = self.hass.loop.time()
        if (
            group.overridden
            and group.override_started is not None
            and now - group.override_started < OVERRIDE_DEBOUNCE
        ):
            # Même geste (extinction + changement de vitesse, plusieurs lampes…)
            return
        group.clear_override()
        group.cancel_off_timer()
        group.cancel_cycle_timer()
        duration = timedelta(minutes=minutes)
        group.override_started = now
        group.override_until = dt_util.utcnow() + duration
        label = "lumières" if group.kind == KIND_LIGHTS else "ventilateurs"
        self._log(f"laisse la main sur les {label} pendant {minutes:g} min")

        @callback
        def _end_override(_now: datetime) -> None:
            group.override_timer = None
            group.override_until = None
            group.override_started = None
            self._log(f"reprend la gestion des {label}")
            self.async_reevaluate()

        group.override_timer = async_call_later(self.hass, duration, _end_override)
        self._notify()

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------

    def _new_context(self) -> Context:
        context = Context()
        self._own_contexts.append(context.id)
        return context

    def _call(self, group: ActuatorGroup, service: str) -> None:
        # homeassistant.turn_on/off accepte des domaines mixtes (light, fan, switch).
        self._service("homeassistant", service, group.entity_ids, self._new_context())

    def _service(
        self,
        domain: str,
        service: str,
        entity_ids: list[str],
        context: Context,
        **data: Any,
    ) -> None:
        _LOGGER.debug("%s : %s.%s %s %s", self.name, domain, service, entity_ids, data)
        self.hass.async_create_task(
            self.hass.services.async_call(
                domain,
                service,
                {ATTR_ENTITY_ID: entity_ids, **data},
                blocking=False,
                context=context,
            )
        )

    def _log(self, message: str, *, throttle: str | None = None) -> None:
        """Ajoute une entrée au Journal de Home Assistant.

        Avec `throttle`, les entrées de même nature sont espacées d'au moins
        LOG_THROTTLE secondes (ajustements de vitesse fréquents, par exemple).
        """
        _LOGGER.debug("%s : %s", self.name, message)
        if throttle is not None:
            now = dt_util.utcnow()
            last = self._last_logs.get(throttle)
            if last is not None and (now - last).total_seconds() < LOG_THROTTLE:
                return
            self._last_logs[throttle] = now
        data: dict[str, Any] = {
            "name": f"Lumina {self.name}",
            "message": message,
            "domain": DOMAIN,
        }
        if self.state_entity_id:
            data["entity_id"] = self.state_entity_id
        self.hass.bus.async_fire(_EVENT_LOGBOOK_ENTRY, data)

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()
