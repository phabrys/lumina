"""Sommeil d'une pièce : entrée, réveil, présomption d'occupation, réveil du matin."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    State,
    callback,
)
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .base import INVALID_STATES, STATE_FIELD, ActuatorGroup, RoomBase, cancel_timer
from .const import (
    BEDTIME_OVERRIDE,
    BEDTIME_UNTIL_VACANT,
    BEDTIME_UNTIL_WAKE,
    KIND_FANS,
    KIND_LIGHTS,
    SETTING_OVERRIDE_DURATION,
    SLEEP_ENTITY,
    SLEEP_LIGHTS_OFF,
    SLEEP_MANUAL,
    WAKE_MORNING,
)

# Réveils qui laissent au dormeur un répit : l'heure de fin de nuit, et
# l'entité de sommeil (un téléphone qui bouge ne dit pas que tous sont levés)
_HELD_WAKES = (WAKE_MORNING, SLEEP_ENTITY)


class SleepControl(RoomBase):
    """Partie du contrôleur consacrée au sommeil.

    Un dormeur immobile peut échapper au détecteur : en sommeil, rien ne
    s'allume (sauf la veilleuse) et ni ventilateur ni clim ne s'arrêtent parce
    que la pièce semble vide. Au réveil du matin ou par l'entité de sommeil,
    ce répit dure encore la durée du contrôle manuel, sauf geste sur la
    lumière. Un détecteur qui voit l'immobilité (radar) rend l'absence réelle :
    rien n'est alors présumé.
    """

    # Entité qui met la pièce en sommeil (lit, téléphone en charge…)
    sleep_entity: str | None

    def _init_sleep(self, sleep_entity: str | None) -> None:
        self.sleep_entity = sleep_entity
        # Sommeil : jusqu'à la prochaine heure de fin de nuit au plus tard
        self.sleeping = False
        self.sleeping_until: datetime | None = None
        self.sleep_source: str | None = None
        # Présence détectée depuis le début du sommeil : la présomption
        # d'occupation prolonge une présence, elle ne la déclenche pas.
        self._sleep_presence_seen = False
        # Lumières éteintes à la main la nuit : contrôle manuel ou sommeil
        self.bedtime_gesture = BEDTIME_UNTIL_VACANT
        # Réveil du matin : le dormeur peut être encore au lit
        self.wake_hold_until: datetime | None = None
        self._wake_hold_timer: CALLBACK_TYPE | None = None
        # Veilleuse allumée par Lumina pendant ce sommeil : l'éteindre à la
        # main est un refus qui tient jusqu'au réveil.
        self._night_light_lit = False

    def _reevaluate_with_vacancy_credit(self) -> None:
        """Réévalue en déduisant des délais d'extinction l'absence déjà écoulée."""
        raise NotImplementedError

    def _still_watch(self) -> bool:
        """Un détecteur qui voit les personnes immobiles répond-il ?"""
        raise NotImplementedError

    def _presence_for_sleep(self) -> bool:
        """Quelqu'un est-il (ou était-il à l'instant) dans la pièce ?"""
        raise NotImplementedError

    # --- Entrée et sortie -------------------------------------------------

    @callback
    def set_bedtime_gesture(self, mode: str, *, reevaluate: bool = True) -> None:
        self.bedtime_gesture = mode
        self._refresh(reevaluate)

    @callback
    def start_sleep(
        self,
        *,
        source: str = SLEEP_MANUAL,
        until: datetime | None = None,
        presence_seen: bool | None = None,
        restored: bool = False,
        reevaluate: bool = True,
    ) -> None:
        """Met la pièce en sommeil, jusqu'à la prochaine fin de nuit au plus tard.

        `restored` : sommeil d'avant un redémarrage. Les contrôles manuels sont
        restaurés à part avec leur propre échéance, ils ne sont pas convertis.
        """
        if until is None:
            until = self._next_night_end()
        if until <= dt_util.utcnow():
            # Fin de nuit passée pendant le redémarrage : le réveil est en cours.
            if restored and (self.occupied or self._presumes(source, bool(presence_seen))):
                self._start_wake_hold(until)
            return
        if self.sleeping and source == self.sleep_source and until == self.sleeping_until:
            return
        was_sleeping = self.sleeping
        self.sleeping = True
        self.sleep_source = source
        if not was_sleeping:
            self._release_wake_hold()
            self._night_light_lit = False
            self._sleep_presence_seen = self.occupied if presence_seen is None else presence_seen
            for group in self.groups.values():
                if restored or not group.overridden or group.override_turned_on:
                    continue  # un allumage à la main garde sa durée
                if group.kind == KIND_LIGHTS:
                    # Le sommeil empêche déjà l'allumage : une lumière éteinte
                    # au coucher n'a pas besoin de contrôle manuel, et la
                    # veilleuse reste possible.
                    group.clear_override()
                else:
                    # Ventilateur ou clim réglés au coucher : jusqu'au réveil
                    group.override_until_wake = True
        if until != self.sleeping_until:
            self._set_sleeping_until(until)
        if not was_sleeping and reevaluate:
            self._log(
                f"sleep_started_{source}",
                time=dt_util.as_local(until).strftime("%H:%M"),
            )
        self._refresh(reevaluate)

    @callback
    def wake(self, *, reason: str = SLEEP_MANUAL, reevaluate: bool = True) -> None:
        """Fin du sommeil : les gestes tenus jusqu'au réveil prennent fin.

        Au réveil du matin ou par l'entité de sommeil, un dormeur peut être
        encore au lit, même invisible pour le détecteur : le répit du réveil
        commence.
        """
        if not self.sleeping:
            return
        sleeper = reason in _HELD_WAKES and self.occupied_or_presumed
        self.sleeping = False
        self.sleeping_until = None
        self.sleep_source = None
        self._sleep_presence_seen = False
        self._night_light_lit = False
        for group in self.groups.values():
            if group.override_until_wake:
                group.clear_override()
        if sleeper:
            self._start_wake_hold(dt_util.utcnow())
        else:
            self._release_wake_hold()
        if reason in _HELD_WAKES and self.wake_hold_until is not None:
            self._log(
                f"sleep_ended_{reason}_held",
                time=dt_util.as_local(self.wake_hold_until).strftime("%H:%M"),
            )
        else:
            self._log(f"sleep_ended_{reason}")
        if reevaluate:
            self._reevaluate_with_vacancy_credit()
        else:
            self._notify()

    def _set_sleeping_until(self, until: datetime) -> None:
        """Échéance du sommeil, suivie par les gestes tenus jusqu'au réveil."""
        self.sleeping_until = until
        for group in self.groups.values():
            if group.override_until_wake:
                cancel_timer(group.override_timer)
                self._arm_override(group, until)

    def _follow_night_end(self) -> None:
        """Nouvelle heure de fin de nuit, appliquée le jour du réveil prévu.

        Déjà passée, le sommeil prend fin tout de suite au lieu de durer
        jusqu'au lendemain.
        """
        if not self.sleeping or self.sleeping_until is None:
            return
        until = self._moved_night_end(self.sleeping_until)
        if until > dt_util.utcnow():
            self._set_sleeping_until(until)
        else:
            self.wake(reason=WAKE_MORNING, reevaluate=False)

    def _check_sleep_end(self) -> bool:
        """Heure de fin de nuit atteinte : réveil, même d'un sommeil oublié."""
        if self.sleeping_until is None or dt_util.utcnow() < self.sleeping_until:
            return False
        self.wake(reason=WAKE_MORNING, reevaluate=False)
        return True

    # --- Présomption d'occupation -----------------------------------------

    def _presumes(self, source: str | None, seen: bool) -> bool:
        """Ce sommeil présume-t-il un dormeur que le détecteur ne voit plus ?

        Seulement après une présence réelle depuis le coucher, pour un sommeil
        deviné au geste, seulement dans une chambre, et jamais quand un
        détecteur voit les personnes immobiles.
        """
        return (
            seen
            and (source != SLEEP_LIGHTS_OFF or self.bedtime_gesture == BEDTIME_UNTIL_WAKE)
            and not self._still_watch()
        )

    @property
    def presumed_occupied(self) -> bool:
        """Dormeur présumé là, pendant le sommeil ou le réveil du matin."""
        if self.wake_hold_until is not None:
            # Un détecteur qui voit l'immobilité verrait le dormeur.
            return not self._still_watch()
        return self.sleeping and self._presumes(self.sleep_source, self._sleep_presence_seen)

    @property
    def occupied_or_presumed(self) -> bool:
        return self.occupied or self.presumed_occupied

    def _keeps_running(self, group: ActuatorGroup) -> bool:
        """Ventilateurs et clim ne s'arrêtent pas sur un dormeur, même invisible.

        Avec un détecteur qui voit l'immobilité, une pièce vide l'est vraiment.
        """
        if group.kind == KIND_LIGHTS:
            return False
        return (self.sleeping and not self._still_watch()) or self.presumed_occupied

    # --- Réveil du matin --------------------------------------------------

    @property
    def lights_held(self) -> bool:
        """Lumière gardée éteinte pendant le réveil du matin."""
        return self.wake_hold_until is not None and bool(self.groups[KIND_LIGHTS].entity_ids)

    @callback
    def restore_wake_hold(self, until: datetime) -> None:
        """Réveil en cours avant le redémarrage : le dormeur peut être encore là."""
        if until > dt_util.utcnow():
            self._hold_wake(until)

    def _start_wake_hold(self, since: datetime) -> None:
        """Répit du réveil : la durée du contrôle manuel à partir de `since`."""
        minutes = self.settings[SETTING_OVERRIDE_DURATION]
        until = since + timedelta(minutes=minutes)
        if minutes > 0 and until > dt_util.utcnow():
            self._hold_wake(until)
        else:
            self._release_wake_hold()

    def _hold_wake(self, until: datetime) -> None:
        """Répit jusqu'à `until`, sauf geste sur la lumière.

        Une pièce qui semble vide ne l'interrompt pas : un dormeur immobile
        n'est pas toujours vu par le détecteur.
        """

        @callback
        def _hold_end(_now: datetime) -> None:
            self._wake_hold_timer = None
            self.wake_hold_until = None
            self._log("wake_hold_end")
            # Sans signe de vie depuis, l'absence déjà écoulée compte.
            self._reevaluate_with_vacancy_credit()

        cancel_timer(self._wake_hold_timer)
        self.wake_hold_until = until
        self._wake_hold_timer = async_call_later(self.hass, until - dt_util.utcnow(), _hold_end)

    def _release_wake_hold(self) -> None:
        cancel_timer(self._wake_hold_timer)
        self._wake_hold_timer = None
        self.wake_hold_until = None

    # --- Événements -------------------------------------------------------

    def _sleep_entity_state(self) -> str | None:
        """État exploitable de l'entité de sommeil, None si absente ou muette."""
        if self.sleep_entity is None:
            return None
        state = self.hass.states.get(self.sleep_entity)
        if state is None or state.state in INVALID_STATES:
            return None
        return state.state

    @callback
    def _on_sleep_entity(self, event: Event[EventStateChangedData]) -> None:
        """Seul un passage à « on » ou à « off » compte (lit, téléphone en charge…).

        Le retour d'une entité muette à « on » ne rendort pas une pièce réveillée
        le matin ; à « off », il réveille un sommeil qu'elle avait lancé.
        Un passage à « on » dans une pièce vide (téléphone posé ailleurs) est
        ignoré.
        """
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        if new_state is None or new_state.state in INVALID_STATES:
            return
        old = None if old_state is None else old_state.state
        if new_state.state == STATE_ON and old == STATE_OFF:
            if not self.sleeping and not self._presence_for_sleep():
                self._log("sleep_entity_ignored_vacant")
                self._notify()
                return
            self.start_sleep(source=SLEEP_ENTITY)
        elif new_state.state == STATE_OFF and (
            old == STATE_ON or self.sleep_source == SLEEP_ENTITY
        ):
            self.wake(reason=SLEEP_ENTITY)

    def _is_bedtime_gesture(
        self, group: ActuatorGroup, changed: dict[str, Any], new_state: State
    ) -> bool:
        """La nuit, les lumières (à défaut les ventilateurs) éteintes à la main ?

        Une automatisation ou un script (scène « tout éteindre » en partant…)
        ne compte pas : seul un geste physique, vocal ou depuis l'interface.
        """
        if (
            self.bedtime_gesture == BEDTIME_OVERRIDE
            or not self.is_night
            or self.sleeping
            or new_state.context.parent_id is not None
        ):
            return False
        lights = self.groups[KIND_LIGHTS]
        bedtime_group = lights if lights.entity_ids else self.groups[KIND_FANS]
        return (
            group is bedtime_group
            and group.enabled
            and changed.get(STATE_FIELD) == STATE_OFF
            and not self._any_on(group)
        )
