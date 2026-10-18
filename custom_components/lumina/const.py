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
}

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
