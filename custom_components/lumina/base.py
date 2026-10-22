"""Socle commun du contrôleur : groupes d'actionneurs, appels de service, journal."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
import logging
from typing import Any

from homeassistant.components.climate import ATTR_HVAC_MODE, ATTR_PRESET_MODE, HVACMode
from homeassistant.components.fan import ATTR_PERCENTAGE, ATTR_PERCENTAGE_STEP
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, State, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    CONFIRMATION_WINDOW,
    DOMAIN,
    LOG_THROTTLE,
    MODE_ALL,
    PERIOD_NIGHT,
    TIME_NIGHT_END,
)
from .messages import message

_LOGGER = logging.getLogger(__name__)

INVALID_STATES = {STATE_UNAVAILABLE, STATE_UNKNOWN}
_EVENT_LOGBOOK_ENTRY = "logbook_entry"
# Champ « état » dans les changements attendus, à côté des attributs
STATE_FIELD = "state"


def domain_of(entity_id: str) -> str:
    """Domaine d'une entité (« light » pour « light.salon »)."""
    return entity_id.partition(".")[0]


def cancel_timer(timer: CALLBACK_TYPE | None) -> None:
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
    # Reprise manuelle qui tient jusqu'à la fin du sommeil
    override_until_wake: bool = False
    # Reprise due à un allumage à la main (elle garde la durée réglée)
    override_turned_on: bool = False
    # Entrée de journal différée de la reprise manuelle
    override_log_timer: CALLBACK_TYPE | None = None
    # Lumières baissées en attendant l'extinction
    warning: bool = False
    # Luminosité (0-255) de chaque lumière avant l'avertissement
    saved_brightness: dict[str, int | None] = field(default_factory=dict)
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
        cancel_timer(self.off_timer)
        self.off_timer = None
        self.off_at = None
        self.warning = False
        self.saved_brightness = {}

    def clear_override(self) -> None:
        cancel_timer(self.override_timer)
        self.override_timer = None
        self.override_until = None
        self.override_started = None
        self.override_until_wake = False
        self.override_turned_on = False
        cancel_timer(self.override_log_timer)
        self.override_log_timer = None

    def cancel_cycle_timer(self) -> None:
        cancel_timer(self.cycle_timer)
        self.cycle_timer = None


def _expected_fields(domain: str, service: str, data: dict[str, Any]) -> dict[str, Any]:
    """État et attributs qu'un appel de service doit produire sur l'entité."""
    expected: dict[str, Any] = {}
    if service == SERVICE_TURN_OFF:
        expected[STATE_FIELD] = HVACMode.OFF if domain == "climate" else STATE_OFF
    elif service == SERVICE_TURN_ON and domain != "climate":
        expected[STATE_FIELD] = STATE_ON
    if ATTR_HVAC_MODE in data:
        expected[STATE_FIELD] = data[ATTR_HVAC_MODE]
    for attr in (ATTR_PERCENTAGE, ATTR_PRESET_MODE, ATTR_TEMPERATURE):
        if attr in data:
            expected[attr] = data[attr]
    return expected


class RoomBase:
    """Outils partagés par les différentes parties du contrôleur de pièce."""

    hass: HomeAssistant
    name: str
    period: str
    sleeping: bool
    settings: dict[str, float]
    times: dict[str, time]
    groups: dict[str, ActuatorGroup]
    occupied: bool
    illuminance: str | None
    # Entité du capteur d'état, à laquelle le journal rattache ses entrées
    state_entity_id: str | None

    def __init__(self, hass: HomeAssistant, name: str) -> None:
        self.hass = hass
        self.name = name
        self.state_entity_id = None
        self._own_contexts: deque[str] = deque(maxlen=64)
        # Ce que Lumina vient de demander à chaque entité : un appareil lent
        # (cloud, clim) peut le confirmer plus tard sous un autre contexte.
        self._expected: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._last_logs: dict[str, datetime] = {}
        self._listeners: list[Callable[[], None]] = []
        # Contrôleur arrêté (pièce déchargée ou rechargée) : plus de journal
        self._stopped = False

    @callback
    def async_reevaluate(self) -> None:
        """Réapplique les règles à l'état courant de la pièce."""
        raise NotImplementedError

    @property
    def occupied_or_presumed(self) -> bool:
        """Pièce occupée, ou présumée occupée par un dormeur que le détecteur ne voit plus."""
        raise NotImplementedError

    def _refresh(self, reevaluate: bool) -> None:
        if reevaluate:
            self.async_reevaluate()
        else:
            self._notify()

    @property
    def is_night(self) -> bool:
        return self.period == PERIOD_NIGHT

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

    def _moved_night_end(self, until: datetime) -> datetime:
        """Échéance `until` ramenée à la nouvelle heure de fin de nuit, même jour."""
        end = self.times[TIME_NIGHT_END]
        local = dt_util.as_local(until).replace(hour=end.hour, minute=end.minute)
        return dt_util.as_utc(local)

    @property
    def night_rules(self) -> bool:
        """Réglages de nuit : la nuit, ou en sommeil (sieste comprise)."""
        return self.is_night or self.sleeping

    def _setting(self, day_key: str, night_key: str) -> float:
        return self.settings[night_key if self.night_rules else day_key]

    # --- États -------------------------------------------------------------

    def _numeric_state(self, entity_id: str | None) -> float | None:
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in INVALID_STATES:
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def _is_on(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        if domain_of(entity_id) == "climate":
            # L'état d'une clim est son mode : tout sauf « off » est en marche.
            return state.state not in INVALID_STATES and state.state != HVACMode.OFF
        return state.state == STATE_ON

    def _any_on(self, group: ActuatorGroup) -> bool:
        return any(self._is_on(entity_id) for entity_id in group.entity_ids)

    def _is_own_change(self, new_state: State, changed: dict[str, Any]) -> bool:
        """Le changement vient-il d'une commande de Lumina ?

        Soit il porte le contexte de la commande, soit il arrive peu après
        avec exactement ce qu'elle demandait (confirmation tardive).
        """
        if new_state.context.id in self._own_contexts:
            return True
        sent_at, expected = self._expected.get(new_state.entity_id, (None, {}))
        if (
            sent_at is None
            or (dt_util.utcnow() - sent_at).total_seconds() > CONFIRMATION_WINDOW
        ):
            return False
        step = new_state.attributes.get(ATTR_PERCENTAGE_STEP) or 1
        for key, value in changed.items():
            if key not in expected:
                return False
            wanted = expected[key]
            if key == ATTR_PERCENTAGE and value is not None:
                # La vitesse obtenue est arrondie au cran du ventilateur.
                if abs(value - wanted) > step:
                    return False
            elif value != wanted:
                return False
        return True

    # --- Contrôle manuel ---------------------------------------------------

    def _arm_override(self, group: ActuatorGroup, until: datetime) -> None:
        """Programme la fin de la reprise manuelle du groupe."""

        @callback
        def _end_override(_now: datetime) -> None:
            group.override_timer = None
            group.override_until = None
            group.override_started = None
            group.override_until_wake = False
            group.override_turned_on = False
            self._log(f"{group.kind}_override_end")
            self.async_reevaluate()

        group.override_until = until
        group.override_timer = async_call_later(
            self.hass, until - dt_util.utcnow(), _end_override
        )
        self._notify()

    # --- Commandes ---------------------------------------------------------

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
        now = dt_util.utcnow()
        for entity_id in entity_ids:
            expected = _expected_fields(domain_of(entity_id), service, data)
            sent_at, previous = self._expected.get(entity_id, (now, {}))
            if (now - sent_at).total_seconds() > CONFIRMATION_WINDOW:
                previous = {}
            self._expected[entity_id] = (now, {**previous, **expected})
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
        except Exception as err:
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

    # --- Journal et notifications -----------------------------------------

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
