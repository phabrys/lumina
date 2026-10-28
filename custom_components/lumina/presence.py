"""Présence dans une pièce : occupation, confirmation d'absence, détecteurs muets."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers import issue_registry as ir

from .base import INVALID_STATES, RoomBase, Timer
from .const import (
    DOMAIN,
    HOLD_INACTIVE_STATES,
    ISSUE_PRESENCE_UNAVAILABLE,
    PRESENCE_ISSUE_DELAY,
    SETTING_VACANCY_CONFIRM,
    SLEEP_RECENT_PRESENCE,
)

_LOGGER = logging.getLogger(__name__)


class PresenceControl(RoomBase):
    """Partie du contrôleur qui sait si la pièce est occupée.

    Une absence n'est prise en compte qu'après un court délai de
    confirmation. Un détecteur muet ne dit pas que la pièce est vide :
    l'occupation en cours est conservée, et la panne est signalée.
    """

    # Détecteurs de présence, ceux qui voient l'immobilité, et entités de maintien
    presence: list[str]
    presence_still: list[str]
    presence_hold: list[str]

    def _init_presence(
        self,
        presence: list[str],
        presence_still: list[str],
        presence_hold: list[str],
        issue_suffix: str,
    ) -> None:
        self.presence = presence
        self.presence_still = [e for e in presence_still if e in presence]
        self.presence_hold = presence_hold
        self.occupied = False
        # Panne de détecteur signalée dans les Réparations, propre à la pièce
        self._issue_id = f"{ISSUE_PRESENCE_UNAVAILABLE}_{issue_suffix}"
        self._issue_timer = Timer()
        self._issue_raised = False
        # Confirmation d'absence en cours, et instant où la présence a cessé
        self._vacancy = Timer()
        self._presence_lost_at: float | None = None
        # Début (horloge de la boucle) de l'absence en cours, s'il est connu
        self._vacant_since: float | None = None
        # Temps déjà écoulé depuis la fin de présence, déduit des délais
        # d'extinction programmés au moment où l'absence est confirmée
        self._off_delay_credit = 0.0

    def _stop_presence(self) -> None:
        self._cancel_vacancy()
        self._issue_timer.cancel()

    @callback
    def restore_occupied(self) -> None:
        """Pièce occupée avant le redémarrage : le maintien peut prolonger l'occupation."""
        self.occupied = True

    # --- États -------------------------------------------------------------

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
            if (state := self.hass.states.get(entity_id)) is None or state.state in INVALID_STATES
        ]

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
            self._issue_timer.cancel()
            if self._issue_raised:
                ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
                self._issue_raised = False
            return
        if self._issue_raised or self._issue_timer.active:
            return

        @callback
        def _raise(_now: datetime) -> None:
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

        self._issue_timer.start(self.hass, PRESENCE_ISSUE_DELAY, _raise)

    # --- Événements --------------------------------------------------------

    @callback
    def _on_presence(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        is_detector = event.data["entity_id"] in self.presence
        if is_detector:
            self._check_presence_health()
        if is_detector and (new_state is None or new_state.state in INVALID_STATES):
            # Détecteur muet (redémarrage de Zigbee2MQTT…) : il ne dit pas que
            # la pièce est vide, l'occupation en cours est conservée.
            self._notify()
            return
        present = self._compute_occupied()
        if present:
            # Présence (re)détectée : une éventuelle confirmation d'absence tombe.
            self._cancel_vacancy()
            self._note_sleeper_presence()
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

    # --- Absence -----------------------------------------------------------

    def _presence_lost(self) -> None:
        """Plus personne de détecté : la pièce se vide après confirmation."""
        confirm = self.settings[SETTING_VACANCY_CONFIRM]
        if confirm <= 0:
            self._presence_lost_at = self.hass.loop.time()
            self._set_vacant()
            return
        if not self._vacancy.active:
            self._presence_lost_at = self.hass.loop.time()
            self._vacancy.start(self.hass, confirm, self._confirm_vacancy)
        self._notify()

    @callback
    def _confirm_vacancy(self, _now: datetime) -> None:
        if self._compute_occupied() or self._presence_unknown():
            # Détecteurs devenus muets pendant la confirmation : rien ne dit
            # que la pièce est vide, l'occupation est conservée.
            self._presence_lost_at = None
            self._notify()
            return
        self._set_vacant()

    def _cancel_vacancy(self) -> None:
        self._vacancy.cancel()
        self._presence_lost_at = None

    def _set_vacant(self) -> None:
        """Pièce vide confirmée : ce qu'elle entraîne, puis extinctions."""
        self.occupied = False
        _LOGGER.debug("%s : pièce vide", self.name)
        self._room_vacated()
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
