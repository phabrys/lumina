"""Machine à états d'une pièce gérée par Lumina."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, time, timedelta
import logging
from typing import Any

from homeassistant.components.climate import ATTR_FAN_MODE, ATTR_PRESET_MODE
from homeassistant.components.fan import (
    ATTR_PERCENTAGE,
    ATTR_PERCENTAGE_STEP,
    SERVICE_SET_PERCENTAGE,
)
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_BRIGHTNESS_PCT,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_SUPPORTED_COLOR_MODES,
    ColorMode,
    brightness_supported,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .base import (
    INVALID_STATES,
    STATE_FIELD,
    ActuatorGroup,
    cancel_timer,
    domain_of,
)
from .climate_control import ClimateControl
from .const import (
    BEDTIME_UNTIL_VACANT,
    CONF_CLIMATES,
    CONF_FANS,
    CONF_HOLIDAYS,
    CONF_HUMIDITY,
    CONF_ILLUMINANCE,
    CONF_LIGHTS,
    CONF_PRESENCE,
    CONF_PRESENCE_HOLD,
    CONF_PRESENCE_STILL,
    CONF_SLEEP,
    CONF_TEMPERATURE,
    CONF_WORKDAY,
    DAY_WORK,
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
    ISSUE_PRESENCE_UNAVAILABLE,
    KIND_CLIMATE,
    KIND_FANS,
    KIND_LIGHTS,
    MODE_ALL,
    NIGHT_END_TIMES,
    OVERRIDE_DEBOUNCE,
    PERIOD_DAY,
    PERIOD_EVENING,
    PERIOD_NIGHT,
    PRESENCE_ISSUE_DELAY,
    ROOM_OCCUPIED,
    ROOM_OVERRIDE,
    ROOM_SLEEPING,
    ROOM_VACANT,
    SETTING_CLIMATE_VACANT_DELAY,
    SETTING_DAY_BRIGHTNESS,
    SETTING_DAY_COLOR_TEMP,
    SETTING_EVENING_BRIGHTNESS,
    SETTING_EVENING_COLOR_TEMP,
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
    SETTING_SLEEP_BRIGHTNESS,
    SETTING_TEMP_THRESHOLD,
    SETTING_VACANCY_CONFIRM,
    SLEEP_ENTITY,
    SLEEP_LIGHTS_OFF,
    SLEEP_RECENT_PRESENCE,
    SUN_BELOW_HORIZON,
    SUN_ENTITY,
    TEMP_HYSTERESIS,
    TIME_EVENING_START,
    TIME_NIGHT_START,
    WAKE_VACANT,
    WARNING_BRIGHTNESS,
    WARNING_MIN_BRIGHTNESS,
)
from .daylight import DaylightControl
from .days import DayControl
from .heat import apparent_temperature
from .sleep import SleepControl

_LOGGER = logging.getLogger(__name__)

# Attributs dont un changement manuel vaut reprise, en plus de l'état
_OVERRIDE_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    KIND_FANS: (ATTR_PERCENTAGE,),
    KIND_CLIMATE: (ATTR_TEMPERATURE, ATTR_PRESET_MODE, ATTR_FAN_MODE),
}


def _within(start: time, end: time, moment: time) -> bool:
    """`moment` dans la plage [start, end[, éventuellement à cheval sur minuit."""
    if start == end:
        return False
    if start < end:
        return start <= moment < end
    return moment >= start or moment < end


class RoomController(SleepControl, ClimateControl, DaylightControl, DayControl):
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
    - détecteur indisponible → l'occupation en cours est conservée ; tous
      muets → rien ne s'éteint, et la panne est signalée dans les Réparations ;
    - clims : pièce vide → action réglable (arrêt, eco, consigne relevée),
      annulée au retour dans la pièce ; en soirée, avec une consigne réglée,
      allumées en froid quand la pièce est occupée et arrêtées quand elle se vide ;
    - clim en marche → ventilateurs normaux, en brassage ou arrêtés ;
    - sommeil (switch, entité choisie, ou lumières éteintes à la main la
      nuit) : pas d'allumage automatique sauf veilleuse, gestes manuels
      tenus jusqu'au réveil ; une fois quelqu'un détecté, la pièce est
      présumée occupée pour les ventilateurs et la clim, sauf détecteur qui
      voit l'immobilité ; il prend fin à l'heure de fin de nuit au plus tard,
      et le réveil (matin ou entité) laisse la lumière éteinte un moment ;
    - capteur de luminosité muet → on se fie à la position du soleil ;
    - la nuit (plage horaire ou forcée), réglages dédiés ; la fin de nuit
      suit le type du jour (semaine, repos, vacances) quand ses sources sont
      choisies ;
    - la soirée (du début de soirée au début de la nuit) ne change que la
      luminosité et la teinte des lumières, et la clim si sa consigne est
      réglée : le reste suit les règles du jour.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        config: Mapping[str, Any],
        entry_id: str | None = None,
    ) -> None:
        super().__init__(hass, name)
        self.presence: list[str] = list(config.get(CONF_PRESENCE, []))
        self.presence_still: list[str] = [
            e for e in config.get(CONF_PRESENCE_STILL) or [] if e in self.presence
        ]
        # Panne de détecteur signalée dans les Réparations, propre à la pièce
        self._issue_id = f"{ISSUE_PRESENCE_UNAVAILABLE}_{entry_id or name}"
        self._issue_timer: CALLBACK_TYPE | None = None
        self._issue_raised = False
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
        self._init_sleep(config.get(CONF_SLEEP))
        self._init_days(config.get(CONF_WORKDAY), list(config.get(CONF_HOLIDAYS) or []))
        self._init_climate(dict(DEFAULT_CLIMATE_ACTIONS))
        self._init_daylight()
        # Ventilateurs pendant que la clim tourne
        self.fans_with_climate = FANS_WITH_CLIMATE_NORMAL
        self.period = PERIOD_DAY
        self._natural_period = PERIOD_DAY
        self.occupied = False
        # Confirmation d'absence en cours, et instant où la présence a cessé
        self._vacancy_timer: CALLBACK_TYPE | None = None
        self._vacancy_at: datetime | None = None
        self._presence_lost_at: float | None = None
        # Début (horloge de la boucle) de l'absence en cours, s'il est connu
        self._vacant_since: float | None = None
        # Temps déjà écoulé depuis la fin de présence, déduit des délais
        # d'extinction programmés au moment où l'absence est confirmée
        self._off_delay_credit = 0.0
        self._unsubs: list[CALLBACK_TYPE] = []

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
            *([self.sleep_entity] if self.sleep_entity else []),
            *self.day_sources,
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
    def restore_override(self, kind: str, until: datetime, *, until_wake: bool) -> None:
        """Contrôle manuel d'avant le redémarrage : repris jusqu'à son échéance."""
        group = self.groups[kind]
        if not group.entity_ids or until <= dt_util.utcnow():
            return
        group.override_until_wake = until_wake
        self._arm_override(group, until)

    @callback
    def async_start(self) -> None:
        """Abonne le contrôleur aux changements d'état utiles."""
        self._track([*self.presence, *self.presence_hold], self._on_presence)
        self._track(self.environment_sensors, self._on_environment)
        # Soleil : remplace le capteur de luminosité absent ou muet.
        self._track([SUN_ENTITY], self._on_sun)
        if self.sleep_entity:
            self._track([self.sleep_entity], self._on_sleep_entity)
        self._track(self.day_sources, self._on_day_source)
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
        self._schedule_day_kinds()
        self._check_presence_health()

    @callback
    def async_stop(self) -> None:
        """Désabonne le contrôleur et annule les minuteries."""
        self._stopped = True
        while self._unsubs:
            self._unsubs.pop()()
        self._cancel_day_kinds()
        for group in self.groups.values():
            group.cancel_off_timer()
            group.clear_override()
            group.cancel_cycle_timer()
        self._reset_daylight()
        self._cancel_vacancy()
        self._release_wake_hold()
        cancel_timer(self._issue_timer)
        self._issue_timer = None

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
        # Entité de sommeil éteinte pendant l'arrêt de Home Assistant : réveil.
        # Un état « on » déjà vu (réveil du matin passé) ne rendort pas la pièce.
        if self.sleep_source == SLEEP_ENTITY and self._sleep_entity_state() == STATE_OFF:
            self.wake(reason=SLEEP_ENTITY, reevaluate=False)
        if (
            self.occupied
            and not self._compute_occupied()
            and not self._presence_unknown()
        ):
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
        changed = self.times[key] != value
        self.times[key] = value
        if changed and key in NIGHT_END_TIMES:
            self._night_end_moved()
        else:
            self._natural_period = self._compute_natural_period()
            self.period = self._effective_period()
        self._refresh(reevaluate)

    def _night_end_moved(self) -> None:
        """Nouvelle fin de nuit, appliquée le jour de l'échéance en cours.

        Déjà passée, la nuit forcée et le sommeil prennent fin tout de suite.
        """
        if self.forced_night and self.forced_night_until is not None:
            until = self._moved_night_end(self.forced_night_until)
            self.forced_night = until > dt_util.utcnow()
            self.forced_night_until = until if self.forced_night else None
        self._follow_night_end()
        self._natural_period = self._compute_natural_period()
        self.period = self._effective_period()

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














    @property
    def room_state(self) -> str:
        if self.sleeping:
            return ROOM_SLEEPING
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
        overrides_until_wake = [
            group.kind for group in self.groups.values() if group.override_until_wake
        ]
        night_end_at = self._next_night_end()
        return {
            "period": self.period,
            "forced_night": self.forced_night,
            "forced_night_until": self.forced_night_until,
            "sleeping": self.sleeping,
            "sleeping_until": self.sleeping_until,
            "sleep_source": self.sleep_source,
            "sleep_presence_seen": self._sleep_presence_seen,
            "presumed_occupied": self.presumed_occupied,
            "sleep_entity": self.sleep_entity,
            "night_end_at": night_end_at,
            "night_end_day_kind": self.day_kinds.get(
                dt_util.as_local(night_end_at).date(), DAY_WORK
            ),
            "workday_entity": self.workday_entity,
            "holiday_calendars": self.holiday_calendars,
            "bedtime_gesture": self.bedtime_gesture,
            "lights_held": self.lights_held,
            "wake_hold_until": self.wake_hold_until,
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
            # Contrôles manuels qui tiennent jusqu'à la fin du sommeil
            "overrides_until_wake": overrides_until_wake,
            # Ancien nom, lu par Lumina Card 0.2
            "overrides_until_morning": overrides_until_wake,
            "climate_running": self._climate_running(),
            "climate_vacant_action": self._climate_action(),
            "climate_vacant_at": climate.off_at,
            "climate_vacant_applied": self._climate_saved_action,
            "fans_with_climate": self.fans_with_climate,
            # Entités de la pièce, pour les cartes et les tableaux de bord
            "presence_sensors": self.presence,
            "presence_still_sensors": self.presence_still,
            # Détecteurs muets ; tous muets, Lumina ne sait plus si la pièce est vide
            "presence_unavailable": self._dead_presence(),
            "presence_unknown": self._presence_unknown(),
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
        if self.wake_hold_until is not None:
            self._release_wake_hold()
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
        elif self._presence_unknown():
            pass  # détecteurs muets : rien ne dit que la pièce est vide
        else:
            if self.presumed_occupied:
                # Dormeur que le détecteur ne voit plus : les ventilateurs
                # suivent la température.
                self._evaluate_fans()
                self._evaluate_climate()
            for group in self.groups.values():
                if self._keeps_running(group):
                    continue
                if (
                    group.active
                    and group.off_timer is None
                    and self._any_on(group)
                    and self._needs_vacant_action(group)
                ):
                    self._schedule_off(group)
        self._notify()


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

    def _compute_occupied(self) -> bool:
        if any(self._is_on(entity_id) for entity_id in self.presence):
            return True
        # Le maintien prolonge une occupation, il ne la déclenche pas.
        return self.occupied and self._hold_active()

    def _dead_presence(self) -> list[str]:
        """Détecteurs de présence sans état exploitable."""
        return [
            entity_id
            for entity_id in self.presence
            if (state := self.hass.states.get(entity_id)) is None
            or state.state in INVALID_STATES
        ]

    def _still_watch(self) -> bool:
        """Un détecteur qui voit les personnes immobiles répond-il ?"""
        dead = self._dead_presence()
        return any(entity_id not in dead for entity_id in self.presence_still)

    def _presence_for_sleep(self) -> bool:
        """Quelqu'un est-il dans la pièce, pour une entité de sommeil qui s'active ?

        Un détecteur qui voit l'immobilité doit le voir maintenant ; à défaut
        (PIR), une présence récente suffit, le dormeur a pu cesser de bouger.
        Sans détecteur exploitable, l'entité est crue.
        """
        if self.occupied or not self.presence or self._presence_unknown():
            return True
        if self._still_watch():
            return False
        return (
            self._vacant_since is None
            or self.hass.loop.time() - self._vacant_since <= SLEEP_RECENT_PRESENCE
        )

    def _check_presence_health(self) -> None:
        """Signale dans les Réparations un détecteur muet depuis une heure."""
        if not self._dead_presence():
            cancel_timer(self._issue_timer)
            self._issue_timer = None
            if self._issue_raised:
                ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
                self._issue_raised = False
            return
        if self._issue_raised or self._issue_timer is not None:
            return

        @callback
        def _raise(_now: datetime) -> None:
            self._issue_timer = None
            dead = self._dead_presence()
            if not dead:
                return
            names = []
            for entity_id in dead:
                state = self.hass.states.get(entity_id)
                names.append(state.name if state is not None else entity_id)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_PRESENCE_UNAVAILABLE,
                translation_placeholders={"room": self.name, "sensors": ", ".join(names)},
            )
            self._issue_raised = True

        self._issue_timer = async_call_later(self.hass, PRESENCE_ISSUE_DELAY, _raise)

    def _presence_unknown(self) -> bool:
        """Les détecteurs existent mais aucun ne donne d'état exploitable."""
        states = [self.hass.states.get(entity_id) for entity_id in self.presence]
        return any(state is not None for state in states) and all(
            state is None or state.state in INVALID_STATES for state in states
        )

    def _hold_active(self) -> bool:
        return any(
            (state := self.hass.states.get(entity_id)) is not None
            and state.state not in HOLD_INACTIVE_STATES
            for entity_id in self.presence_hold
        )

    def _effective_temperature(self) -> float | None:
        """Température ressentie si l'humidité est connue, sinon mesurée."""
        apparent = self.apparent_temperature
        if apparent is not None:
            return apparent
        return self._numeric_state(self.temperature)

    def _is_dark(self) -> bool:
        lux = self._numeric_state(self.illuminance)
        if lux is not None:
            return lux < self.settings[SETTING_LUX_THRESHOLD]
        # Pas de capteur choisi, ou capteur muet : on se fie au soleil.
        return not self._sun_up()

    def _to_turn_on(self, group: ActuatorGroup) -> list[str]:
        """Entités du groupe à allumer, selon son mode."""
        off = [e for e in group.entity_ids if not self._is_on(e)]
        if group.mode == MODE_ALL:
            return off
        return group.entity_ids if len(off) == len(group.entity_ids) else []

    def _reason(self) -> str:
        """Contexte lisible des décisions, pour le journal."""
        period = "reason_sleep" if self.sleeping else f"reason_{self.period}"
        parts = [self._message(period)]
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
        elif not self._sun_up():
            parts.append(self._message("reason_sun_down"))
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
                "light", SERVICE_TURN_ON, lights_ct, context,
                **data, **{ATTR_COLOR_TEMP_KELVIN: round(color_temp)},
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
            self._service(
                "light", SERVICE_TURN_ON, entity_ids, context, **{ATTR_BRIGHTNESS: level}
            )
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

    # --- Ventilateurs ---------------------------------------------------

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
        blocked = (
            switching and self.temperature is not None and self._fan_cycle_blocked(group)
        )
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
        if group.cycle_timer is None:

            @callback
            def _retry(_now: datetime) -> None:
                group.cycle_timer = None
                # Le cycle minimal est écoulé : la prochaine bascule est permise.
                group.last_temp_switch = None
                if self.occupied_or_presumed:
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
            if (
                domain_of(entity_id) != "fan"
                or state is None
                or state.state != STATE_ON
            ):
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
                "fan", SERVICE_SET_PERCENTAGE, to_adjust, self._new_context(),
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
            if (
                self.occupied
                or self._keeps_running(group)
                or self._presence_unknown()
                or not group.active
                or not self._any_on(group)
            ):
                self._notify()
                return
            warning = self.settings[SETTING_LIGHT_WARNING]
            # Une lumière sans variateur ne peut pas baisser : pas d'avertissement.
            dimmable = (
                [
                    e
                    for e in group.entity_ids
                    if domain_of(e) == "light" and self._is_on(e) and self._dimmable(e)
                ]
                if group.kind == KIND_LIGHTS and warning > 0
                else []
            )
            # Baisser, jamais éclairer : la moitié de la luminosité actuelle,
            # au plus WARNING_BRIGHTNESS. Une veilleuse trop faible s'éteint
            # directement.
            targets: dict[int, list[str]] = {}
            for entity_id in dimmable:
                current = self._brightness(entity_id)
                target = round(255 * WARNING_BRIGHTNESS / 100)
                if current is not None:
                    target = min(target, current // 2)
                if target >= WARNING_MIN_BRIGHTNESS:
                    targets.setdefault(target, []).append(entity_id)
            if targets:
                # Luminosité de chaque lumière, rétablie si quelqu'un revient
                group.saved_brightness = {
                    e: self._brightness(e) for entity_ids in targets.values() for e in entity_ids
                }
                context = self._new_context()
                for target, entity_ids in targets.items():
                    self._service(
                        "light", SERVICE_TURN_ON, entity_ids, context,
                        **{ATTR_BRIGHTNESS: target},
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
            group.saved_brightness = {}
            if (
                not self.occupied
                and not self._presence_unknown()
                and group.active
                and self._any_on(group)
            ):
                self._turn_off(group)
            self._notify()

        group.off_timer = async_call_later(self.hass, delay, _delay_elapsed)
        group.off_at = dt_util.utcnow() + timedelta(seconds=delay)

    def _dimmable(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        return state is not None and brightness_supported(
            state.attributes.get(ATTR_SUPPORTED_COLOR_MODES)
        )

    def _brightness(self, entity_id: str) -> int | None:
        state = self.hass.states.get(entity_id)
        return None if state is None else state.attributes.get(ATTR_BRIGHTNESS)

    def _turn_off(self, group: ActuatorGroup) -> None:
        if group.kind == KIND_CLIMATE:
            self._apply_climate_vacant(group)
            return
        self._call(group, SERVICE_TURN_OFF)
        self._log(f"{group.kind}_off_vacant")

    # ------------------------------------------------------------------
    # Gestion des événements
    # ------------------------------------------------------------------

    @callback
    def _on_presence(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        if event.data["entity_id"] in self.presence:
            self._check_presence_health()
        if event.data["entity_id"] in self.presence and (
            new_state is None or new_state.state in INVALID_STATES
        ):
            # Détecteur muet (redémarrage de Zigbee2MQTT…) : il ne dit pas que
            # la pièce est vide, l'occupation en cours est conservée.
            self._notify()
            return
        present = self._compute_occupied()
        if present:
            # Présence (re)détectée : une éventuelle confirmation d'absence tombe.
            self._cancel_vacancy()
            if self.sleeping:
                self._sleep_presence_seen = True
            if not self.occupied:
                self.occupied = True
                self._vacant_since = None
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
        if self._compute_occupied() or self._presence_unknown():
            # Détecteurs devenus muets pendant la confirmation : rien ne dit
            # que la pièce est vide, l'occupation est conservée.
            self._presence_lost_at = None
            self._notify()
            return
        self._set_vacant()

    def _cancel_vacancy(self) -> None:
        cancel_timer(self._vacancy_timer)
        self._vacancy_timer = None
        self._vacancy_at = None
        self._presence_lost_at = None

    def _set_vacant(self) -> None:
        """Pièce vide confirmée : levée des reprises manuelles, extinctions."""
        self.occupied = False
        _LOGGER.debug("%s : pièce vide", self.name)
        if (
            self.sleeping
            and self.sleep_source == SLEEP_LIGHTS_OFF
            and self.bedtime_gesture == BEDTIME_UNTIL_VACANT
        ):
            # Lumières éteintes en quittant le salon : on y revient éclairé.
            self.wake(reason=WAKE_VACANT, reevaluate=False)
        if self._still_watch():
            # Le détecteur verrait un dormeur : le réveil est terminé.
            self._release_wake_hold()
        for group in self.groups.values():
            # Réglage du coucher (tout éteint) : un dormeur que le détecteur ne
            # voit plus ne le lève pas, sinon tout se rallumerait à son prochain
            # mouvement. Un groupe resté allumé est repris pour être éteint,
            # sauf ventilateurs et clim pendant le sommeil.
            keep = group.override_until_wake and (
                not self._any_on(group) or self._keeps_running(group)
            )
            if not keep:
                group.clear_override()
        self._reset_daylight()
        self._vacant_since = self._presence_lost_at
        self._presence_lost_at = None
        self._reevaluate_with_vacancy_credit()

    def _reevaluate_with_vacancy_credit(self) -> None:
        """Réévalue en déduisant des délais d'extinction l'absence déjà écoulée."""
        if not self.occupied and self._vacant_since is not None:
            self._off_delay_credit = max(self.hass.loop.time() - self._vacant_since, 0.0)
        try:
            self.async_reevaluate()
        finally:
            self._off_delay_credit = 0.0

    @callback
    def _on_minute(self, now: datetime) -> None:
        if now.minute == 0:
            # Chaque heure : un calendrier peut changer sans changer d'état.
            self._schedule_day_kinds()
        self._follow_clock()
        # Marges du lever et du coucher : franchies sans que le soleil change.
        self._follow_sun()

    def _wake_if_due(self) -> bool:
        """Fin de nuit atteinte : réveil d'abord, avant toute réévaluation.

        Les gestes tenus jusqu'au réveil arrivent à échéance à la seconde de
        la fin de nuit : levés juste avant le réveil, ils laisseraient Lumina
        réappliquer le sommeil (ventilateur éteint à la main rallumé).
        """
        if self.sleeping_until is None or dt_util.utcnow() < self.sleeping_until:
            return False
        self._follow_clock()
        return True

    def _follow_clock(self) -> None:
        """Fin de la nuit forcée, réveil et période à l'heure qu'il est."""
        if (
            self.forced_night
            and self.forced_night_until is not None
            and dt_util.utcnow() >= self.forced_night_until
        ):
            # Heure de fin de nuit atteinte : le forçage s'arrête de lui-même.
            self.forced_night = False
            self.forced_night_until = None
        woke = self._check_sleep_end()
        self._natural_period = self._compute_natural_period()
        period = self._effective_period()
        changed = period != self.period
        if changed:
            self.period = period
            self._log(f"{self.period}_started")
        if woke or changed:
            self._reevaluate_with_vacancy_credit()

    @callback
    def _on_sun(self, _event: Event[EventStateChangedData]) -> None:
        self._follow_sun()

    def _follow_sun(self) -> None:
        """Réévalue les lumières quand l'avis du soleil change."""
        up = self._sun_up()
        if up == self._sun_was_up:
            return
        self._sun_was_up = up
        if self.occupied:
            self._evaluate_lights()
        self._notify()

    @callback
    def _on_environment(self, event: Event[EventStateChangedData]) -> None:
        if self.occupied:
            self._evaluate_lights()
        if self.occupied_or_presumed:
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
                or old_state.state in INVALID_STATES
                or new_state.state in INVALID_STATES
            ):
                return
            changed: dict[str, Any] = {}
            if old_state.state != new_state.state:
                changed[STATE_FIELD] = new_state.state
            # Un réglage changé à la main (vitesse, consigne…) compte aussi.
            for attr in _OVERRIDE_ATTRIBUTES.get(group.kind, ()):
                value = new_state.attributes.get(attr)
                if old_state.attributes.get(attr) != value:
                    changed[attr] = value
            if changed and not self._is_own_change(new_state, changed):
                self._start_override(
                    group, turned_on=changed.get(STATE_FIELD) == STATE_ON
                )
                if self._is_bedtime_gesture(group, changed, new_state):
                    self.start_sleep(source=SLEEP_LIGHTS_OFF)
            # Clim lancée ou arrêtée : les ventilateurs s'adaptent.
            if (
                group.kind == KIND_CLIMATE
                and STATE_FIELD in changed
                and self.occupied_or_presumed
            ):
                self._evaluate_fans()
                self._notify()

        return _handler


    def _start_override(self, group: ActuatorGroup, *, turned_on: bool = False) -> None:
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
        if group.kind == KIND_LIGHTS:
            self._release_wake_hold()  # geste sur la lumière : on est réveillé
            if self.sleeping and not turned_on and not self._night_light_lit:
                # Le sommeil la garde déjà éteinte. Seule une veilleuse éteinte
                # à la main est un refus tenu jusqu'au réveil.
                return
        group.override_started = now
        group.override_turned_on = turned_on
        if self.sleeping and self.sleeping_until is not None and not turned_on:
            # En sommeil, un geste tient jusqu'au réveil. Un allumage à la main
            # garde la durée réglée, pour ne pas laisser une lumière allumée
            # toute la nuit dans une pièce vide.
            group.override_until_wake = True
            until = self.sleeping_until
            self._log(
                f"{group.kind}_override_wake",
                time=dt_util.as_local(until).strftime("%H:%M"),
            )
        else:
            until = dt_util.utcnow() + timedelta(minutes=minutes)
            self._log_override_later(group, minutes)
        self._arm_override(group, until)

    def _log_override_later(self, group: ActuatorGroup, minutes: float) -> None:
        """Journal du contrôle manuel, une fois le geste terminé.

        Deux lampes éteintes au coucher font passer en sommeil à la seconde :
        le contrôle « pendant 30 min » de la première n'est alors pas annoncé.
        """
        started = group.override_started

        @callback
        def _log_override(_now: datetime) -> None:
            group.override_log_timer = None
            if group.override_started == started and not group.override_until_wake:
                self._log(f"{group.kind}_override", minutes=minutes)

        cancel_timer(group.override_log_timer)
        group.override_log_timer = async_call_later(
            self.hass, OVERRIDE_DEBOUNCE, _log_override
        )
