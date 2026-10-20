"""Machine à états d'une pièce gérée par Lumina."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
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
    CLIMATE_ACTION_ECO,
    CLIMATE_ACTION_NONE,
    CLIMATE_ACTION_OFF,
    CLIMATE_ACTION_SETBACK,
    CLIMATE_IDLE_MODES,
    CLIMATE_RESTORE_WINDOW,
    CLIMATE_SETBACK,
    CONF_CLIMATES,
    CONF_FANS,
    CONF_HUMIDITY,
    CONF_ILLUMINANCE,
    CONF_LIGHTS,
    CONF_PRESENCE,
    CONF_PRESENCE_HOLD,
    CONF_TEMPERATURE,
    DAYLIGHT_OFF_DELAY,
    DAYLIGHT_RELOCK_DELAY,
    DEFAULT_CLIMATE_ACTIONS,
    DEFAULT_SETTINGS,
    DEFAULT_TIMES,
    DOMAIN,
    FAN_MIN_CYCLE,
    FAN_SPEED_MIN_CHANGE,
    FANS_WITH_CLIMATE_MIX,
    FANS_WITH_CLIMATE_NORMAL,
    FANS_WITH_CLIMATE_OFF,
    HOLD_INACTIVE_STATES,
    KIND_CLIMATE,
    KIND_FANS,
    KIND_LIGHTS,
    LOG_THROTTLE,
    MODE_ALL,
    OVERRIDE_DEBOUNCE,
    PERIOD_DAY,
    PERIOD_NIGHT,
    ROOM_OCCUPIED,
    ROOM_OVERRIDE,
    ROOM_VACANT,
    SELECT_CLIMATE_VACANT_DAY,
    SELECT_CLIMATE_VACANT_NIGHT,
    SETTING_CLIMATE_VACANT_DELAY,
    SETTING_DAY_BRIGHTNESS,
    SETTING_DAY_COLOR_TEMP,
    SETTING_DAYLIGHT_OFF_LUX,
    SETTING_FAN_MIN_SPEED,
    SETTING_FAN_MIX_SPEED,
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
from .messages import message

_LOGGER = logging.getLogger(__name__)

_INVALID_STATES = {STATE_UNAVAILABLE, STATE_UNKNOWN}
_EVENT_LOGBOOK_ENTRY = "logbook_entry"
# Attributs dont un changement manuel vaut reprise, en plus de l'état
_OVERRIDE_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    KIND_FANS: ("percentage",),
    KIND_CLIMATE: ("temperature", "preset_mode", "fan_mode"),
}


def _cancel(timer: CALLBACK_TYPE | None) -> None:
    """Annule une minuterie, s'il y en a une."""
    if timer is not None:
        timer()


# eq=False : chaque groupe est un objet unique, comparé par identité.
@dataclass(eq=False)
class ActuatorGroup:
    """Groupe d'actionneurs (lumières, ventilateurs ou clims) d'une pièce."""

    kind: str
    entity_ids: list[str]
    off_delay_key: str
    night_off_delay_key: str
    enabled: bool = True
    # Tous allumés, ou seulement si aucun ne l'est déjà
    mode: str = MODE_ALL
    override_until: datetime | None = None
    off_timer: CALLBACK_TYPE | None = None
    # Échéance de l'extinction programmée (ou de la fin de l'avertissement)
    off_at: datetime | None = None
    override_timer: CALLBACK_TYPE | None = None
    # Instant (horloge de la boucle) du début de la reprise manuelle
    override_started: float | None = None
    # Lumières baissées en attendant l'extinction
    warning: bool = False
    # Dernière bascule marche/arrêt due à la température (ventilateurs)
    last_temp_switch: float | None = None
    cycle_timer: CALLBACK_TYPE | None = None

    @property
    def overridden(self) -> bool:
        return self.override_until is not None

    @property
    def active(self) -> bool:
        """Le groupe est-il piloté automatiquement en ce moment ?"""
        return bool(self.entity_ids) and self.enabled and not self.overridden

    def cancel_off_timer(self) -> None:
        _cancel(self.off_timer)
        self.off_timer = None
        self.off_at = None
        self.warning = False

    def clear_override(self) -> None:
        _cancel(self.override_timer)
        self.override_timer = None
        self.override_until = None
        self.override_started = None

    def cancel_cycle_timer(self) -> None:
        _cancel(self.cycle_timer)
        self.cycle_timer = None


class RoomController:
    """Pilote les lumières, ventilateurs et clims d'une pièce.

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
    - clims : jamais allumées par Lumina ; pièce vide → action réglable
      (arrêt, eco, consigne relevée), annulée au retour dans la pièce ;
    - clim en marche → ventilateurs normaux, en brassage ou arrêtés ;
    - la nuit, une reprise manuelle peut durer jusqu'au matin ;
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
            KIND_CLIMATE: ActuatorGroup(
                KIND_CLIMATE,
                list(config.get(CONF_CLIMATES, [])),
                SETTING_CLIMATE_VACANT_DELAY,
                SETTING_CLIMATE_VACANT_DELAY,
            ),
        }
        self.settings: dict[str, float] = dict(DEFAULT_SETTINGS)
        self.times: dict[str, time] = dict(DEFAULT_TIMES)
        self.forced_night = False
        self.forced_night_until: datetime | None = None
        # La nuit, une reprise manuelle dure jusqu'à la fin de la nuit
        self.night_override_until_morning = True
        # Clim en pièce vide (jour / nuit) et ventilateurs pendant la clim
        self.climate_actions: dict[str, str] = dict(DEFAULT_CLIMATE_ACTIONS)
        self.fans_with_climate = FANS_WITH_CLIMATE_NORMAL
        # État des clims avant l'action en pièce vide, pour le rétablir au retour
        self._climate_saved: dict[str, dict[str, Any]] | None = None
        self._climate_saved_action: str | None = None
        self._climate_saved_at: datetime | None = None
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
        self._vacancy_at: datetime | None = None
        self._presence_lost_at: float | None = None
        # Temps déjà écoulé depuis la fin de présence, déduit des délais
        # d'extinction programmés au moment où l'absence est confirmée
        self._off_delay_credit = 0.0
        # Entité du capteur d'état, à laquelle le journal rattache ses entrées
        self.state_entity_id: str | None = None
        self._own_contexts: deque[str] = deque(maxlen=64)
        self._unsubs: list[CALLBACK_TYPE] = []
        self._listeners: list[Callable[[], None]] = []
        # Contrôleur arrêté (pièce déchargée ou rechargée) : plus de journal
        self._stopped = False

    @property
    def environment_sensors(self) -> list[str]:
        """Capteurs de luminosité, température et humidité choisis."""
        return [e for e in (self.illuminance, self.temperature, self.humidity) if e]

    @property
    def tracked_entities(self) -> list[str]:
        """Toutes les entités que le contrôleur écoute."""
        return [
            *self.presence,
            *self.presence_hold,
            *self.environment_sensors,
            *(e for group in self.groups.values() for e in group.entity_ids),
        ]

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    @callback
    def restore_occupied(self) -> None:
        """Pièce occupée avant le redémarrage : le maintien peut prolonger l'occupation."""
        self.occupied = True

    @callback
    def async_start(self) -> None:
        """Abonne le contrôleur aux changements d'état utiles."""
        self._track([*self.presence, *self.presence_hold], self._on_presence)
        self._track(self.environment_sensors, self._on_environment)
        for group in self.groups.values():
            self._track(group.entity_ids, self._make_actuator_handler(group))
        # Une occupation restaurée est gardée jusqu'au démarrage complet de
        # Home Assistant : les médias n'ont peut-être pas encore repris leur état.
        if not self.occupied:
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
        self._stopped = True
        while self._unsubs:
            self._unsubs.pop()()
        for group in self.groups.values():
            group.cancel_off_timer()
            group.clear_override()
            group.cancel_cycle_timer()
        self._reset_daylight()
        self._cancel_vacancy()

    def _track(
        self,
        entity_ids: list[str],
        action: Callable[[Event[EventStateChangedData]], None],
    ) -> None:
        if entity_ids:
            self._unsubs.append(
                async_track_state_change_event(self.hass, entity_ids, action)
            )

    async def _on_started(self, _hass: HomeAssistant) -> None:
        if self.occupied and not self._compute_occupied():
            # Occupation d'avant le redémarrage que rien ne confirme : elle est
            # levée après la confirmation d'absence, sauf si un média reprend.
            self._presence_lost()
            return
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
            if kind == KIND_CLIMATE:
                self._clear_climate_saved()
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
            self._log("night_forced" if forced else "day_restored")
        self._refresh(reevaluate)

    @callback
    def set_mode(self, kind: str, mode: str, *, reevaluate: bool = True) -> None:
        self.groups[kind].mode = mode
        self._refresh(reevaluate)

    @callback
    def set_climate_action(self, key: str, action: str, *, reevaluate: bool = True) -> None:
        self.climate_actions[key] = action
        self._refresh(reevaluate)

    @callback
    def set_fans_with_climate(self, mode: str, *, reevaluate: bool = True) -> None:
        self.fans_with_climate = mode
        self._refresh(reevaluate)

    @callback
    def set_night_override_until_morning(
        self, enabled: bool, *, reevaluate: bool = True
    ) -> None:
        self.night_override_until_morning = enabled
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
        climate = self.groups[KIND_CLIMATE]
        return {
            "period": self.period,
            "forced_night": self.forced_night,
            "forced_night_until": self.forced_night_until,
            "lights_mode": lights.mode,
            "fans_mode": fans.mode,
            "daylight_locked": self.daylight_locked,
            "occupied": self.occupied,
            "vacancy_pending": self._vacancy_timer is not None,
            "vacancy_at": self._vacancy_at,
            "presence_hold_active": self._hold_active(),
            "effective_temperature": self._effective_temperature(),
            "lights_override_until": lights.override_until,
            "fans_override_until": fans.override_until,
            "lights_off_pending": lights.off_timer is not None,
            "lights_off_at": lights.off_at,
            "fans_off_at": fans.off_at,
            "lights_warning": lights.warning,
            "fans_off_pending": fans.off_timer is not None,
            "climate_override_until": climate.override_until,
            "climate_running": self._climate_running(),
            "climate_vacant_action": self._climate_action(),
            "climate_vacant_at": climate.off_at,
            "climate_vacant_applied": self._climate_saved_action,
            "fans_with_climate": self.fans_with_climate,
            # Entités de la pièce, pour les cartes et les tableaux de bord
            "presence_sensors": self.presence,
            "presence_hold_entities": self.presence_hold,
            "illuminance_sensor": self.illuminance,
            "temperature_sensor": self.temperature,
            "humidity_sensor": self.humidity,
            "lights": lights.entity_ids,
            "fans": fans.entity_ids,
            "climates": climate.entity_ids,
        }

    @callback
    def async_resume(self) -> None:
        """Lève les reprises manuelles et réapplique les règles tout de suite."""
        resumed = False
        for group in self.groups.values():
            if group.overridden:
                group.clear_override()
                resumed = True
        if resumed:
            self._log("resumed")
        self.async_reevaluate()

    # ------------------------------------------------------------------
    # Évaluation
    # ------------------------------------------------------------------

    @callback
    def async_reevaluate(self) -> None:
        """Réapplique les règles à l'état courant de la pièce."""
        if self.occupied:
            self._evaluate_lights()
            self._evaluate_fans()
            self._evaluate_climate()
        else:
            for group in self.groups.values():
                if (
                    group.active
                    and group.off_timer is None
                    and self._any_on(group)
                    and self._needs_vacant_action(group)
                ):
                    self._schedule_off(group)
        self._notify()

    def _needs_vacant_action(self, group: ActuatorGroup) -> bool:
        """Les clims n'ont d'action en pièce vide que si elle est réglée et pas encore faite."""
        if group.kind != KIND_CLIMATE:
            return True
        return (
            self._climate_action() != CLIMATE_ACTION_NONE
            and self._climate_saved is None
        )

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
        if any(self._is_on(entity_id) for entity_id in self.presence):
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

    def _is_on(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        if entity_id.startswith("climate."):
            # L'état d'une clim est son mode : tout sauf « off » est en marche.
            return state.state not in _INVALID_STATES and state.state != "off"
        return state.state == STATE_ON

    def _any_on(self, group: ActuatorGroup) -> bool:
        return any(self._is_on(entity_id) for entity_id in group.entity_ids)

    def _climate_running(self) -> bool:
        """Une clim de la pièce agit-elle sur la température ?"""
        return any(
            (state := self.hass.states.get(entity_id)) is not None
            and state.state not in _INVALID_STATES
            and state.state not in CLIMATE_IDLE_MODES
            for entity_id in self.groups[KIND_CLIMATE].entity_ids
        )

    def _climate_action(self) -> str:
        """Action sur les clims en pièce vide, pour la période en cours."""
        key = SELECT_CLIMATE_VACANT_NIGHT if self.is_night else SELECT_CLIMATE_VACANT_DAY
        return self.climate_actions[key]

    def _to_turn_on(self, group: ActuatorGroup) -> list[str]:
        """Entités du groupe à allumer, selon son mode."""
        off = [e for e in group.entity_ids if not self._is_on(e)]
        if group.mode == MODE_ALL:
            return off
        return group.entity_ids if len(off) == len(group.entity_ids) else []

    def _reason(self) -> str:
        """Contexte lisible des décisions, pour le journal."""
        parts = [self._message("reason_night" if self.is_night else "reason_day")]
        lux = self._numeric_state(self.illuminance)
        if lux is not None:
            parts.append(f"{lux:g} lx")
        elif self.illuminance is not None:
            sun = self.hass.states.get(SUN_ENTITY)
            below = sun is not None and sun.state == SUN_BELOW_HORIZON
            parts.append(
                self._message(
                    "reason_lux_unavailable_sun_down"
                    if below
                    else "reason_lux_unavailable"
                )
            )
        apparent = self.apparent_temperature
        if apparent is not None:
            parts.append(self._message("reason_apparent_temperature", temp=apparent))
        elif (temp := self._numeric_state(self.temperature)) is not None:
            parts.append(self._message("reason_temperature", temp=temp))
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
            self._log("lights_restored", reason=self._reason())
            return
        self._check_daylight()
        if brightness <= 0 or self.daylight_locked:
            return  # pas d'allumage automatique pour l'instant
        if not self._is_dark():
            return
        targets = self._to_turn_on(group)
        if targets:
            self._turn_on_lights(group, brightness, targets)
            self._log("lights_on", brightness=brightness, reason=self._reason())

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
            else:
                _cancel(self._relock_timer)
                self._relock_timer = None

        if (
            off_lux <= 0
            or lux is None
            or lux < off_lux
            or not self.occupied
            or not group.active
            or not self._any_on(group)
        ):
            _cancel(self._daylight_timer)
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
        _cancel(self._daylight_timer)
        _cancel(self._relock_timer)
        self._daylight_timer = None
        self._relock_timer = None
        self.daylight_locked = False

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
        if switching and self.temperature is not None and self._fan_cycle_blocked(group):
            return
        if want_on is False and is_on:
            self._call(group, SERVICE_TURN_OFF)
            group.last_temp_switch = self.hass.loop.time()
            self._log("fans_off_temperature", reason=self._reason())
            return
        # Ventilateurs déjà en marche : vitesse ajustée, même si d'autres démarrent.
        if is_on and want_on is not False and percentage is not None:
            self._adjust_fan_speed(group, percentage)
        if targets:
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

    def _turn_on_fans(self, entity_ids: list[str], percentage: int | None) -> None:
        context = self._new_context()
        fans = [e for e in entity_ids if e.startswith("fan.")]
        others = [e for e in entity_ids if not e.startswith("fan.")]
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
                "fans_speed",
                throttle="fan_speed",
                percentage=percentage,
                reason=self._reason(),
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
            group.off_at = None
            if self.occupied or not group.active or not self._any_on(group):
                self._notify()
                return
            warning = self.settings[SETTING_LIGHT_WARNING]
            dimmable = [
                e for e in group.entity_ids if e.startswith("light.") and self._is_on(e)
            ]
            if group.kind == KIND_LIGHTS and warning > 0 and dimmable:
                self._service(
                    "light", SERVICE_TURN_ON, dimmable, self._new_context(),
                    brightness_pct=WARNING_BRIGHTNESS,
                )
                group.warning = True
                group.off_timer = async_call_later(self.hass, warning, _final_off)
                group.off_at = dt_util.utcnow() + timedelta(seconds=warning)
                self._log("lights_warning")
            else:
                self._turn_off(group)
            self._notify()

        @callback
        def _final_off(_now: datetime) -> None:
            group.off_timer = None
            group.off_at = None
            group.warning = False
            if not self.occupied and group.active and self._any_on(group):
                self._turn_off(group)
            self._notify()

        group.off_timer = async_call_later(self.hass, delay, _delay_elapsed)
        group.off_at = dt_util.utcnow() + timedelta(seconds=delay)

    def _turn_off(self, group: ActuatorGroup) -> None:
        if group.kind == KIND_CLIMATE:
            self._apply_climate_vacant(group)
            return
        self._call(group, SERVICE_TURN_OFF)
        self._log(f"{group.kind}_off_vacant")

    # --- Clims ----------------------------------------------------------

    def _apply_climate_vacant(self, group: ActuatorGroup) -> None:
        """Pièce vide depuis le délai réglé : arrêt, eco ou consigne relevée."""
        action = self._climate_action()
        if action == CLIMATE_ACTION_NONE:
            return
        context = self._new_context()
        saved: dict[str, dict[str, Any]] = {}
        for entity_id in group.entity_ids:
            state = self.hass.states.get(entity_id)
            if state is None or not self._is_on(entity_id):
                continue
            attrs = state.attributes
            previous = {
                "hvac_mode": state.state,
                "temperature": attrs.get("temperature"),
                "preset_mode": attrs.get("preset_mode"),
            }
            if action == CLIMATE_ACTION_OFF:
                self._service("climate", SERVICE_TURN_OFF, [entity_id], context)
            elif action == CLIMATE_ACTION_ECO:
                if CLIMATE_ACTION_ECO not in (attrs.get("preset_modes") or []):
                    continue  # pas de mode eco sur cette clim
                self._service(
                    "climate", "set_preset_mode", [entity_id], context,
                    preset_mode=CLIMATE_ACTION_ECO,
                )
            elif action == CLIMATE_ACTION_SETBACK:
                target = previous["temperature"]
                if target is None:
                    continue
                # Moins de froid (ou de chaud) : la consigne s'éloigne de la pièce.
                delta = -CLIMATE_SETBACK if state.state == "heat" else CLIMATE_SETBACK
                low = attrs.get("min_temp", target + delta)
                high = attrs.get("max_temp", target + delta)
                self._service(
                    "climate", "set_temperature", [entity_id], context,
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
        if not group.entity_ids or not self.occupied:
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
                    "climate", "set_hvac_mode", [entity_id], context,
                    hvac_mode=previous["hvac_mode"],
                )
            elif action == CLIMATE_ACTION_ECO:
                self._service(
                    "climate", "set_preset_mode", [entity_id], context,
                    preset_mode=previous["preset_mode"] or "none",
                )
            elif action == CLIMATE_ACTION_SETBACK and previous["temperature"] is not None:
                self._service(
                    "climate", "set_temperature", [entity_id], context,
                    temperature=previous["temperature"],
                )
        self._log("climate_restored")

    def _clear_climate_saved(self) -> None:
        self._climate_saved = None
        self._climate_saved_action = None
        self._climate_saved_at = None

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
        self._presence_lost()

    def _presence_lost(self) -> None:
        """Plus personne de détecté : la pièce se vide après confirmation."""
        confirm = self.settings[SETTING_VACANCY_CONFIRM]
        if confirm <= 0:
            self._presence_lost_at = self.hass.loop.time()
            self._set_vacant()
            return
        if self._vacancy_timer is None:
            self._presence_lost_at = self.hass.loop.time()
            self._vacancy_at = dt_util.utcnow() + timedelta(seconds=confirm)
            self._vacancy_timer = async_call_later(
                self.hass, confirm, self._confirm_vacancy
            )
        self._notify()

    @callback
    def _confirm_vacancy(self, _now: datetime) -> None:
        self._vacancy_timer = None
        self._vacancy_at = None
        if self._compute_occupied():
            self._notify()
            return
        self._set_vacant()

    def _cancel_vacancy(self) -> None:
        _cancel(self._vacancy_timer)
        self._vacancy_timer = None
        self._vacancy_at = None
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
            self._log("night_started" if self.is_night else "day_started")
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
            mode_changed = old_state.state != new_state.state
            # Un réglage changé à la main (vitesse, consigne…) compte aussi.
            changed = mode_changed or any(
                old_state.attributes.get(attr) != new_state.attributes.get(attr)
                for attr in _OVERRIDE_ATTRIBUTES.get(group.kind, ())
            )
            if changed and new_state.context.id not in self._own_contexts:
                self._start_override(group)
            # Clim lancée ou arrêtée : les ventilateurs s'adaptent.
            if group.kind == KIND_CLIMATE and mode_changed and self.occupied:
                self._evaluate_fans()
                self._notify()

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
        if group.kind == KIND_CLIMATE:
            self._clear_climate_saved()  # la clim est reprise en main
        group.override_started = now
        if self.is_night and self.night_override_until_morning:
            # Réglage du coucher : il tient jusqu'à la fin de la nuit.
            group.override_until = self._next_night_end()
            duration = group.override_until - dt_util.utcnow()
            self._log(
                f"{group.kind}_override_morning",
                time=dt_util.as_local(group.override_until).strftime("%H:%M"),
            )
        else:
            duration = timedelta(minutes=minutes)
            group.override_until = dt_util.utcnow() + duration
            self._log(f"{group.kind}_override", minutes=minutes)

        @callback
        def _end_override(_now: datetime) -> None:
            group.override_timer = None
            group.override_until = None
            group.override_started = None
            self._log(f"{group.kind}_override_end")
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
            self._async_service(domain, service, entity_ids, context, data)
        )

    async def _async_service(
        self,
        domain: str,
        service: str,
        entity_ids: list[str],
        context: Context,
        data: dict[str, Any],
    ) -> None:
        # Appel bloquant dans une tâche à part : Lumina n'attend pas, mais
        # l'échec d'une entité (script introuvable, appareil muet…) remonte ici.
        try:
            await self.hass.services.async_call(
                domain,
                service,
                {ATTR_ENTITY_ID: entity_ids, **data},
                blocking=True,
                context=context,
            )
        except Exception as err:  # noqa: BLE001 - toute erreur doit être signalée
            _LOGGER.warning(
                "%s : échec de %s.%s sur %s : %s",
                self.name, domain, service, ", ".join(entity_ids), err,
            )
            # Pièce déchargée entre-temps : le Journal ne concerne plus ce contrôleur.
            if self._stopped:
                return
            self._log(
                "service_failed",
                throttle=f"error:{domain}.{service}",
                action=f"{domain}.{service}",
                entities=", ".join(entity_ids),
                error=err,
            )

    def _message(self, key: str, **values: Any) -> str:
        return message(self.hass.config.language, key, **values)

    def _log(self, key: str, *, throttle: str | None = None, **values: Any) -> None:
        """Ajoute au Journal de Home Assistant le message `key` (voir messages.py).

        Avec `throttle`, les entrées de même nature sont espacées d'au moins
        LOG_THROTTLE secondes (ajustements de vitesse fréquents, par exemple).
        """
        text = self._message(key, **values)
        _LOGGER.debug("%s : %s", self.name, text)
        if throttle is not None:
            now = dt_util.utcnow()
            last = self._last_logs.get(throttle)
            if last is not None and (now - last).total_seconds() < LOG_THROTTLE:
                return
            self._last_logs[throttle] = now
        data: dict[str, Any] = {
            "name": f"Lumina {self.name}",
            "message": text,
            "domain": DOMAIN,
        }
        if self.state_entity_id:
            data["entity_id"] = self.state_entity_id
        self.hass.bus.async_fire(_EVENT_LOGBOOK_ENTRY, data)

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()
