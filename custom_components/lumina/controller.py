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
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
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
    CONF_CLIMATES,
    CONF_FANS,
    CONF_HUMIDITY,
    CONF_ILLUMINANCE,
    CONF_LIGHTS,
    CONF_PRESENCE,
    CONF_PRESENCE_HOLD,
    CONF_TEMPERATURE,
    DEFAULT_CLIMATE_ACTIONS,
    DEFAULT_SETTINGS,
    DEFAULT_TIMES,
    FAN_MIN_CYCLE,
    FAN_SPEED_MIN_CHANGE,
    FANS_WITH_CLIMATE_MIX,
    FANS_WITH_CLIMATE_NORMAL,
    FANS_WITH_CLIMATE_OFF,
    HOLD_INACTIVE_STATES,
    KIND_CLIMATE,
    KIND_FANS,
    KIND_LIGHTS,
    MODE_ALL,
    OVERRIDE_DEBOUNCE,
    PERIOD_DAY,
    PERIOD_NIGHT,
    ROOM_OCCUPIED,
    ROOM_OVERRIDE,
    ROOM_VACANT,
    SETTING_CLIMATE_VACANT_DELAY,
    SETTING_DAY_BRIGHTNESS,
    SETTING_DAY_COLOR_TEMP,
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
from .daylight import DaylightControl
from .heat import apparent_temperature

_LOGGER = logging.getLogger(__name__)

# Attributs dont un changement manuel vaut reprise, en plus de l'état
_OVERRIDE_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    KIND_FANS: (ATTR_PERCENTAGE,),
    KIND_CLIMATE: (ATTR_TEMPERATURE, ATTR_PRESET_MODE, ATTR_FAN_MODE),
}


class RoomController(ClimateControl, DaylightControl):
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
    - détecteur indisponible → l'occupation en cours est conservée ;
    - clims : jamais allumées par Lumina ; pièce vide → action réglable
      (arrêt, eco, consigne relevée), annulée au retour dans la pièce ;
    - clim en marche → ventilateurs normaux, en brassage ou arrêtés ;
    - la nuit, une reprise manuelle peut durer jusqu'au matin ;
    - capteur de luminosité muet → on se fie à la position du soleil ;
    - la nuit (plage horaire ou forcée), réglages dédiés.
    """

    def __init__(self, hass: HomeAssistant, name: str, config: Mapping[str, Any]) -> None:
        super().__init__(hass, name)
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

    def _compute_occupied(self) -> bool:
        if any(self._is_on(entity_id) for entity_id in self.presence):
            return True
        # Le maintien prolonge une occupation, il ne la déclenche pas.
        return self.occupied and self._hold_active()

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
        if self.illuminance is None:
            # Pas de capteur choisi : la pièce est considérée comme sombre.
            return True
        lux = self._numeric_state(self.illuminance)
        if lux is not None:
            return lux < self.settings[SETTING_LUX_THRESHOLD]
        # Capteur muet : on se fie au soleil plutôt que de supposer la nuit.
        sun = self.hass.states.get(SUN_ENTITY)
        if sun is None or sun.state in INVALID_STATES:
            return True
        return sun.state == SUN_BELOW_HORIZON

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
        saved = group.saved_brightness
        group.cancel_off_timer()
        brightness = self._setting(SETTING_DAY_BRIGHTNESS, SETTING_NIGHT_BRIGHTNESS)
        if was_warning and self._any_on(group):
            # Quelqu'un est revenu pendant l'avertissement : on rétablit.
            self._restore_lights(group, saved, brightness)
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
            if self.occupied or not group.active or not self._any_on(group):
                self._notify()
                return
            warning = self.settings[SETTING_LIGHT_WARNING]
            dimmable = (
                [
                    e
                    for e in group.entity_ids
                    if domain_of(e) == "light" and self._is_on(e)
                ]
                if group.kind == KIND_LIGHTS and warning > 0
                else []
            )
            if dimmable:
                # Luminosité de chaque lumière, rétablie si quelqu'un revient
                group.saved_brightness = {
                    e: self._brightness(e) for e in dimmable
                }
                self._service(
                    "light", SERVICE_TURN_ON, dimmable, self._new_context(),
                    **{ATTR_BRIGHTNESS_PCT: WARNING_BRIGHTNESS},
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
            if not self.occupied and group.active and self._any_on(group):
                self._turn_off(group)
            self._notify()

        group.off_timer = async_call_later(self.hass, delay, _delay_elapsed)
        group.off_at = dt_util.utcnow() + timedelta(seconds=delay)

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
        cancel_timer(self._vacancy_timer)
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
                self._start_override(group)
            # Clim lancée ou arrêtée : les ventilateurs s'adaptent.
            if group.kind == KIND_CLIMATE and STATE_FIELD in changed and self.occupied:
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
