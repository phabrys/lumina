"""Constantes de l'intégration Lumina."""

from __future__ import annotations

from datetime import time
from typing import Final

DOMAIN: Final = "lumina"

# Clés de configuration (config flow / options flow)
CONF_AREA: Final = "area_id"
CONF_PRESENCE: Final = "presence_sensors"
CONF_ILLUMINANCE: Final = "illuminance_sensor"
CONF_TEMPERATURE: Final = "temperature_sensor"
CONF_LIGHTS: Final = "lights"
CONF_FANS: Final = "fans"
CONF_PRESENCE_HOLD: Final = "presence_hold"
CONF_HUMIDITY: Final = "humidity_sensor"

# États d'une entité de maintien de présence considérés comme inactifs
HOLD_INACTIVE_STATES: Final = frozenset(
    {"off", "idle", "standby", "paused", "unavailable", "unknown", "not_home", "closed"}
)

# Groupes d'actionneurs
KIND_LIGHTS: Final = "lights"
KIND_FANS: Final = "fans"

# Réglages exposés en entités number (restaurés au redémarrage)
SETTING_LUX_THRESHOLD: Final = "lux_threshold"
SETTING_LIGHT_OFF_DELAY: Final = "light_off_delay"
SETTING_FAN_OFF_DELAY: Final = "fan_off_delay"
SETTING_TEMP_THRESHOLD: Final = "temperature_threshold"
SETTING_OVERRIDE_DURATION: Final = "override_duration"
SETTING_DAY_BRIGHTNESS: Final = "day_brightness"
SETTING_DAY_COLOR_TEMP: Final = "day_color_temp"
SETTING_FAN_MIN_SPEED: Final = "fan_min_speed"
SETTING_FAN_SPEED_RANGE: Final = "fan_speed_range"
SETTING_LIGHT_WARNING: Final = "light_warning_duration"
SETTING_NIGHT_COLOR_TEMP: Final = "night_color_temp"
SETTING_DAYLIGHT_OFF_LUX: Final = "daylight_off_lux"
SETTING_VACANCY_CONFIRM: Final = "vacancy_confirmation"

# Réglages propres à la nuit
SETTING_NIGHT_BRIGHTNESS: Final = "night_brightness"
SETTING_NIGHT_LIGHT_OFF_DELAY: Final = "night_light_off_delay"
SETTING_NIGHT_FAN_OFF_DELAY: Final = "night_fan_off_delay"
SETTING_NIGHT_TEMP_THRESHOLD: Final = "night_temperature_threshold"

DEFAULT_SETTINGS: Final[dict[str, float]] = {
    SETTING_LUX_THRESHOLD: 50,  # lx
    SETTING_LIGHT_OFF_DELAY: 120,  # s
    SETTING_FAN_OFF_DELAY: 300,  # s
    SETTING_TEMP_THRESHOLD: 27.0,  # °C
    SETTING_OVERRIDE_DURATION: 30,  # min
    SETTING_DAY_BRIGHTNESS: 100,  # %
    SETTING_NIGHT_BRIGHTNESS: 30,  # % (0 = pas d'allumage automatique la nuit)
    SETTING_NIGHT_LIGHT_OFF_DELAY: 60,  # s
    # Long par défaut : un PIR ne détecte pas un dormeur immobile.
    SETTING_NIGHT_FAN_OFF_DELAY: 1800,  # s
    SETTING_NIGHT_TEMP_THRESHOLD: 26.0,  # °C
    # Vitesse des ventilateurs au seuil (0 = simple marche/arrêt),
    # puis montée jusqu'à 100 % sur la plage de température indiquée.
    SETTING_FAN_MIN_SPEED: 33,  # %
    SETTING_FAN_SPEED_RANGE: 3.0,  # °C
    # Baisse de la lumière avant extinction (0 = extinction directe)
    SETTING_LIGHT_WARNING: 15,  # s
    # Teinte des lumières compatibles (0 = ne pas modifier)
    SETTING_DAY_COLOR_TEMP: 4000,  # K
    SETTING_NIGHT_COLOR_TEMP: 2700,  # K
    # Extinction quand la lumière naturelle suffit (0 = désactivé). À régler
    # au-dessus de ce que mesure le capteur avec les lampes allumées.
    SETTING_DAYLIGHT_OFF_LUX: 0,  # lx
    # Absence confirmée seulement après ce délai sans présence : évite qu'une
    # micro-coupure du détecteur vide la pièce (et lève la reprise manuelle).
    SETTING_VACANCY_CONFIRM: 30,  # s
}

# Ventilateurs : durée minimale entre deux bascules dues à la température
FAN_MIN_CYCLE: Final = 300  # s

# Changements d'état rapprochés d'un même groupe = une seule reprise manuelle
OVERRIDE_DEBOUNCE: Final = 5  # s

# Repli quand le capteur de luminosité ne répond pas
SUN_ENTITY: Final = "sun.sun"
SUN_BELOW_HORIZON: Final = "below_horizon"

# Lumière du jour : durée au-dessus du seuil avant extinction, et durée
# sous le seuil d'allumage avant de réautoriser l'allumage automatique.
DAYLIGHT_OFF_DELAY: Final = 300  # s
DAYLIGHT_RELOCK_DELAY: Final = 600  # s

# Plusieurs lumières : toutes allumées, ou aucune action si l'une l'est déjà
LIGHTS_MODE_ALL: Final = "all"
LIGHTS_MODE_ANY: Final = "any"
LIGHTS_MODES: Final = [LIGHTS_MODE_ALL, LIGHTS_MODE_ANY]

# Écart minimal de vitesse avant de réajuster un ventilateur
FAN_SPEED_MIN_CHANGE: Final = 10  # points de %

# Intervalle minimal entre deux entrées de journal de même nature
LOG_THROTTLE: Final = 600  # s

# Luminosité appliquée pendant l'avertissement avant extinction
WARNING_BRIGHTNESS: Final = 20  # %

# Plage de nuit (entités time, restaurées au redémarrage)
TIME_NIGHT_START: Final = "night_start"
TIME_NIGHT_END: Final = "night_end"

DEFAULT_TIMES: Final[dict[str, time]] = {
    TIME_NIGHT_START: time(22, 0),
    TIME_NIGHT_END: time(7, 0),
}

PERIOD_DAY: Final = "day"
PERIOD_NIGHT: Final = "night"

# Hystérésis appliquée à la température pour éviter les bascules répétées
TEMP_HYSTERESIS: Final = 1.0

# États de la pièce (capteur enum)
ROOM_OCCUPIED: Final = "occupied"
ROOM_VACANT: Final = "vacant"
ROOM_OVERRIDE: Final = "override"
ROOM_STATES: Final = [ROOM_OCCUPIED, ROOM_VACANT, ROOM_OVERRIDE]
