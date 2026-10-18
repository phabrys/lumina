"""Constantes de l'intégration Lumina."""

from __future__ import annotations

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

DEFAULT_SETTINGS: Final[dict[str, float]] = {
    SETTING_LUX_THRESHOLD: 50,  # lx
    SETTING_LIGHT_OFF_DELAY: 120,  # s
    SETTING_FAN_OFF_DELAY: 300,  # s
    SETTING_TEMP_THRESHOLD: 27.0,  # °C
    SETTING_OVERRIDE_DURATION: 30,  # min
}

# Hystérésis appliquée à la température pour éviter les bascules répétées
TEMP_HYSTERESIS: Final = 1.0

# États de la pièce (capteur enum)
ROOM_OCCUPIED: Final = "occupied"
ROOM_VACANT: Final = "vacant"
ROOM_OVERRIDE: Final = "override"
ROOM_STATES: Final = [ROOM_OCCUPIED, ROOM_VACANT, ROOM_OVERRIDE]
