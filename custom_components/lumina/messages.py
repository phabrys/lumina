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
        "reason_sleep": "sommeil",
        "reason_lux_unavailable": "luminosité indisponible",
        "reason_lux_unavailable_sun_down": "luminosité indisponible, soleil couché",
        "reason_temperature": "{temp:g} °C",
        "reason_apparent_temperature": "{temp:g} °C ressentis",
        # Période
        "night_forced": "passe en mode nuit (forcé)",
        "day_restored": "repasse en mode jour",
        "night_started": "passe en mode nuit",
        "day_started": "passe en mode jour",
        # Sommeil
        "sleep_started_manual": "passe en sommeil jusqu'à {time}",
        "sleep_started_entity": "passe en sommeil jusqu'à {time} (entité de sommeil)",
        "sleep_started_lights_off": "passe en sommeil jusqu'à {time} (lumières éteintes à la main)",
        "sleep_ended_manual": "sort du sommeil",
        "sleep_ended_entity": "sort du sommeil (entité de sommeil)",
        "sleep_ended_morning": "sort du sommeil, fin de la nuit",
        "sleep_ended_morning_held": (
            "sort du sommeil, fin de la nuit ; lumière éteinte jusqu'à ce que la pièce "
            "se vide, {time} au plus tard"
        ),
        "lights_hold_end": "reprend l'allumage des lumières après le réveil",
        "sleep_ended_vacant": "sort du sommeil, pièce vide",
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
        "fans_off_climate": "arrête les ventilateurs, la clim tourne",
        "fans_mix": "met les ventilateurs en brassage à {percentage} %, la clim tourne",
        # Clims
        "climate_off_vacant": "éteint la clim, pièce vide",
        "climate_eco_vacant": "passe la clim en eco, pièce vide",
        "climate_setback_vacant": "relève la consigne de la clim, pièce vide",
        "climate_restored": "rétablit la clim, présence de retour",
        # Reprise manuelle
        "lights_override": "laisse la main sur les lumières pendant {minutes:g} min",
        "fans_override": "laisse la main sur les ventilateurs pendant {minutes:g} min",
        "lights_override_end": "reprend la gestion des lumières",
        "fans_override_end": "reprend la gestion des ventilateurs",
        "climate_override": "laisse la main sur la clim pendant {minutes:g} min",
        "climate_override_end": "reprend la gestion de la clim",
        "lights_override_wake": "laisse la main sur les lumières jusqu'au réveil ({time})",
        "fans_override_wake": "laisse la main sur les ventilateurs jusqu'au réveil ({time})",
        "climate_override_wake": "laisse la main sur la clim jusqu'au réveil ({time})",
        "resumed": "reprend la gestion automatique (à la demande)",
        # Erreurs
        "service_failed": "échec de {action} sur {entities} : {error}",
    },
    "en": {
        "reason_day": "day",
        "reason_night": "night",
        "reason_sleep": "sleep",
        "reason_lux_unavailable": "illuminance unavailable",
        "reason_lux_unavailable_sun_down": "illuminance unavailable, sun down",
        "reason_temperature": "{temp:g} °C",
        "reason_apparent_temperature": "{temp:g} °C apparent",
        "night_forced": "switches to night mode (forced)",
        "day_restored": "switches back to day mode",
        "night_started": "switches to night mode",
        "day_started": "switches to day mode",
        "sleep_started_manual": "goes to sleep until {time}",
        "sleep_started_entity": "goes to sleep until {time} (sleep entity)",
        "sleep_started_lights_off": "goes to sleep until {time} (lights turned off by hand)",
        "sleep_ended_manual": "wakes up",
        "sleep_ended_entity": "wakes up (sleep entity)",
        "sleep_ended_morning": "wakes up, end of the night",
        "sleep_ended_morning_held": (
            "wakes up, end of the night; lights stay off until the room empties, "
            "{time} at the latest"
        ),
        "lights_hold_end": "resumes turning the lights on after wake-up",
        "sleep_ended_vacant": "wakes up, room empty",
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
        "fans_off_climate": "stops the fans, the AC is running",
        "fans_mix": "sets the fans to circulate air at {percentage} %, the AC is running",
        "climate_off_vacant": "turns off the AC, room empty",
        "climate_eco_vacant": "switches the AC to eco, room empty",
        "climate_setback_vacant": "raises the AC setpoint, room empty",
        "climate_restored": "restores the AC, presence back",
        "lights_override": "leaves the lights to manual control for {minutes:g} min",
        "fans_override": "leaves the fans to manual control for {minutes:g} min",
        "lights_override_end": "resumes managing the lights",
        "fans_override_end": "resumes managing the fans",
        "climate_override": "leaves the AC to manual control for {minutes:g} min",
        "climate_override_end": "resumes managing the AC",
        "lights_override_wake": "leaves the lights to manual control until wake-up ({time})",
        "fans_override_wake": "leaves the fans to manual control until wake-up ({time})",
        "climate_override_wake": "leaves the AC to manual control until wake-up ({time})",
        "resumed": "resumes automatic control (on request)",
        "service_failed": "{action} failed on {entities}: {error}",
    },
}


def message(language: str, key: str, **values: Any) -> str:
    """Message `key` dans la langue donnée (« fr-CA » → « fr »), anglais à défaut.

    Un message absent d'une traduction est lui aussi donné en anglais.
    """
    catalog = MESSAGES.get(language.split("-")[0].lower(), {})
    template = catalog.get(key) or MESSAGES[DEFAULT_LANGUAGE][key]
    return template.format(**values)
