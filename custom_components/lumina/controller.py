"""Machine à états d'une pièce gérée par Lumina."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.components.climate import ATTR_FAN_MODE, ATTR_PRESET_MODE
from homeassistant.components.fan import (
    ATTR_PERCENTAGE,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
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
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .base import (
    INVALID_STATES,
    STATE_FIELD,
    ActuatorGroup,
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
    FANS_WITH_CLIMATE_NORMAL,
    KIND_CLIMATE,
    KIND_FANS,
    KIND_LIGHTS,
    OVERRIDE_DEBOUNCE,
    ROOM_OCCUPIED,
    ROOM_OVERRIDE,
    ROOM_SLEEPING,
    ROOM_VACANT,
    SETTING_CLIMATE_VACANT_DELAY,
    SETTING_FAN_OFF_DELAY,
    SETTING_LIGHT_OFF_DELAY,
    SETTING_LUX_THRESHOLD,
    SETTING_NIGHT_FAN_OFF_DELAY,
    SETTING_NIGHT_LIGHT_OFF_DELAY,
    SETTING_OVERRIDE_DURATION,
    SLEEP_ENTITY,
    SLEEP_LIGHTS_OFF,
    SUN_BELOW_HORIZON,
    SUN_ENTITY,
    WAKE_VACANT,
)
from .daylight import DaylightControl
from .days import DayControl
from .fans import FanControl
from .lights import LightControl
from .periods import PeriodControl
from .presence import PresenceControl
from .sleep import SleepControl

# Attributs dont un changement manuel vaut reprise, en plus de l'état
_OVERRIDE_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    KIND_FANS: (ATTR_PERCENTAGE,),
    KIND_CLIMATE: (ATTR_TEMPERATURE, ATTR_PRESET_MODE, ATTR_FAN_MODE),
}


class RoomController(
    LightControl,
    FanControl,
    SleepControl,
    ClimateControl,
    DaylightControl,
    DayControl,
    PresenceControl,
    PeriodControl,
):
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
        self._init_presence(
            list(config.get(CONF_PRESENCE, [])),
            list(config.get(CONF_PRESENCE_STILL) or []),
            list(config.get(CONF_PRESENCE_HOLD, [])),
            entry_id or name,
        )
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
        self._init_periods()
        self._init_sleep(config.get(CONF_SLEEP))
        self._init_days(config.get(CONF_WORKDAY), list(config.get(CONF_HOLIDAYS) or []))
        self._init_climate(dict(DEFAULT_CLIMATE_ACTIONS))
        self._init_daylight()
        # Ventilateurs pendant que la clim tourne
        self.fans_with_climate = FANS_WITH_CLIMATE_NORMAL
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
        self._update_period()
        self._unsubs.append(async_track_time_change(self.hass, self._on_minute, second=0))
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
            group.cycle_timer.cancel()
        self._reset_daylight()
        self._stop_presence()
        self._release_wake_hold()

    def _track(
        self,
        entity_ids: list[str],
        action: Callable[[Event[EventStateChangedData]], None],
    ) -> None:
        if entity_ids:
            self._unsubs.append(async_track_state_change_event(self.hass, entity_ids, action))

    async def _on_started(self, _hass: HomeAssistant) -> None:
        # Entité de sommeil éteinte pendant l'arrêt de Home Assistant : réveil.
        # Un état « on » déjà vu (réveil du matin passé) ne rendort pas la pièce.
        if self.sleep_source == SLEEP_ENTITY and self._sleep_entity_state() == STATE_OFF:
            self.wake(reason=SLEEP_ENTITY, reevaluate=False)
        if self.occupied and not self._compute_occupied() and not self._presence_unknown():
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

    def _night_end_moved(self) -> None:
        """Nouvelle fin de nuit, appliquée le jour de l'échéance en cours.

        Déjà passée, la nuit forcée et le sommeil prennent fin tout de suite.
        """
        self._move_forced_night_end()
        self._follow_night_end()
        self._update_period()

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
            "sleep_presence_seen": self.sleep_presence_seen,
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
            "vacancy_pending": self._vacancy.active,
            "vacancy_at": self._vacancy.at,
            "presence_hold_active": self._hold_active(),
            "effective_temperature": self._effective_temperature(),
            "lights_override_until": lights.override_until,
            "fans_override_until": fans.override_until,
            "lights_off_pending": lights.off_timer.active,
            "lights_off_at": lights.off_timer.at,
            "fans_off_at": fans.off_timer.at,
            "lights_warning": lights.warning,
            "fans_off_pending": fans.off_timer.active,
            "climate_override_until": climate.override_until,
            # Contrôles manuels qui tiennent jusqu'à la fin du sommeil
            "overrides_until_wake": overrides_until_wake,
            "climate_running": self._climate_running(),
            "climate_vacant_action": self._climate_action(),
            "climate_vacant_at": climate.off_timer.at,
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
                    and not group.off_timer.active
                    and self._any_on(group)
                    and self._needs_vacant_action(group)
                ):
                    self._schedule_off(group)
        self._notify()

    def _is_dark(self) -> bool:
        """Fait-il assez sombre pour allumer ?"""
        lux = self._numeric_state(self.illuminance)
        if lux is not None:
            return lux < self.settings[SETTING_LUX_THRESHOLD]
        # Pas de capteur choisi, ou capteur muet : on se fie au soleil.
        return not self._sun_up()

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
                    "reason_lux_unavailable_sun_down" if below else "reason_lux_unavailable"
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

    # --- Extinction -----------------------------------------------------

    def _schedule_off(self, group: ActuatorGroup) -> None:
        group.cancel_off_timer()
        group.cycle_timer.cancel()
        delay = self._setting(group.off_delay_key, group.night_off_delay_key)
        # Le délai court depuis la fin réelle de présence, pas depuis la confirmation.
        delay = max(delay - self._off_delay_credit, 0)

        @callback
        def _delay_elapsed(_now: datetime) -> None:
            if (
                self.occupied
                or self._keeps_running(group)
                or self._presence_unknown()
                or not group.active
                or not self._any_on(group)
            ):
                self._notify()
                return
            if not self._start_light_warning(group, _final_off):
                self._turn_off(group)
            self._notify()

        @callback
        def _final_off(_now: datetime) -> None:
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

        group.off_timer.start(self.hass, delay, _delay_elapsed)

    def _turn_off(self, group: ActuatorGroup) -> None:
        if group.kind == KIND_CLIMATE:
            self._apply_climate_vacant(group)
            return
        self._call(group, SERVICE_TURN_OFF)
        self._log(f"{group.kind}_off_vacant")

    # ------------------------------------------------------------------
    # Gestion des événements
    # ------------------------------------------------------------------

    def _room_vacated(self) -> None:
        """Pièce vide confirmée : réveil éventuel, levée des reprises manuelles."""
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
        self._expire_forced_night()
        woke = self._check_sleep_end()
        previous = self.period
        self._update_period()
        changed = self.period != previous
        if changed:
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
    def _on_environment(self, _event: Event[EventStateChangedData]) -> None:
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
                self._start_override(group, turned_on=changed.get(STATE_FIELD) == STATE_ON)
                if self._is_bedtime_gesture(group, changed, new_state):
                    self.start_sleep(source=SLEEP_LIGHTS_OFF)
            # Clim lancée ou arrêtée : les ventilateurs s'adaptent.
            if group.kind == KIND_CLIMATE and STATE_FIELD in changed and self.occupied_or_presumed:
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
        group.cycle_timer.cancel()
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
            if group.override_started == started and not group.override_until_wake:
                self._log(f"{group.kind}_override", minutes=minutes)

        group.override_log_timer.start(self.hass, OVERRIDE_DEBOUNCE, _log_override)
