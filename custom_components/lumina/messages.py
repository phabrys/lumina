"""Messages du Journal, dans la langue de Home Assistant.

Les entrées du Journal sont du texte libre : les fichiers de traduction de
l'intégration ne s'y appliquent pas, d'où ce catalogue.
"""

from __future__ import annotations

from typing import Any, Final

DEFAULT_LANGUAGE: Final = "en"

MESSAGES: Final[dict[str, dict[str, str]]] = {
    "fr": {
        # Raison des décisions
        "reason_day": "jour",
        "reason_night": "nuit",
        "reason_lux_unavailable": "luminosité indisponible",
        "reason_lux_unavailable_sun_down": "luminosité indisponible, soleil couché",
        "reason_temperature": "{temp:g} °C",
        "reason_apparent_temperature": "{temp:g} °C ressentis",
        # Période
        "night_forced": "passe en mode nuit (forcé)",
        "day_restored": "repasse en mode jour",
        "night_started": "passe en mode nuit",
        "day_started": "passe en mode jour",
        # Lumières
        "lights_restored": "rétablit les lumières, présence de retour ({reason})",
        "lights_on": "allume les lumières à {brightness:g} % ({reason})",
        "lights_off_daylight": "éteint les lumières, lumière naturelle suffisante ({lux:g} lx)",
        "lights_warning": "baisse les lumières avant extinction",
        "lights_off_vacant": "éteint les lumières, pièce vide",
        # Ventilateurs
        "fans_on": "allume les ventilateurs ({reason})",
        "fans_on_speed": "allume les ventilateurs à {percentage} % ({reason})",
        "fans_off_temperature": "arrête les ventilateurs, température revenue ({reason})",
        "fans_speed": "règle les ventilateurs à {percentage} % ({reason})",
        "fans_off_vacant": "éteint les ventilateurs, pièce vide",
        # Reprise manuelle
        "lights_override": "laisse la main sur les lumières pendant {minutes:g} min",
        "fans_override": "laisse la main sur les ventilateurs pendant {minutes:g} min",
        "lights_override_end": "reprend la gestion des lumières",
        "fans_override_end": "reprend la gestion des ventilateurs",
        "resumed": "reprend la gestion automatique (à la demande)",
        # Erreurs
        "service_failed": "échec de {action} sur {entities} : {error}",
    },
    "en": {
        "reason_day": "day",
        "reason_night": "night",
        "reason_lux_unavailable": "illuminance unavailable",
        "reason_lux_unavailable_sun_down": "illuminance unavailable, sun down",
        "reason_temperature": "{temp:g} °C",
        "reason_apparent_temperature": "{temp:g} °C apparent",
        "night_forced": "switches to night mode (forced)",
        "day_restored": "switches back to day mode",
        "night_started": "switches to night mode",
        "day_started": "switches to day mode",
        "lights_restored": "restores the lights, presence back ({reason})",
        "lights_on": "turns on the lights at {brightness:g} % ({reason})",
        "lights_off_daylight": "turns off the lights, enough daylight ({lux:g} lx)",
        "lights_warning": "dims the lights before turning them off",
        "lights_off_vacant": "turns off the lights, room empty",
        "fans_on": "turns on the fans ({reason})",
        "fans_on_speed": "turns on the fans at {percentage} % ({reason})",
        "fans_off_temperature": "stops the fans, temperature back down ({reason})",
        "fans_speed": "sets the fans to {percentage} % ({reason})",
        "fans_off_vacant": "turns off the fans, room empty",
        "lights_override": "leaves the lights to manual control for {minutes:g} min",
        "fans_override": "leaves the fans to manual control for {minutes:g} min",
        "lights_override_end": "resumes managing the lights",
        "fans_override_end": "resumes managing the fans",
        "resumed": "resumes automatic control (on request)",
        "service_failed": "{action} failed on {entities}: {error}",
    },
}


def message(language: str, key: str, **values: Any) -> str:
    """Message `key` dans la langue donnée (« fr-CA » → « fr »), anglais à défaut."""
    catalog = MESSAGES.get(language.split("-")[0].lower(), MESSAGES[DEFAULT_LANGUAGE])
    return catalog[key].format(**values)
