"""Calcul de la température ressentie (indice de chaleur de la NOAA)."""

from __future__ import annotations

import math


def apparent_temperature(temperature_c: float, humidity: float) -> float:
    """Température ressentie en °C à partir de la température et de l'humidité.

    Formule de la NOAA : approximation de Steadman pour les températures
    modérées, régression de Rothfusz au-delà de ~26,7 °C (80 °F).
    """
    rh = max(0.0, min(100.0, humidity))
    t = temperature_c * 9 / 5 + 32  # °F

    hi = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    if (hi + t) / 2 >= 80:
        hi = (
            -42.379
            + 2.04901523 * t
            + 10.14333127 * rh
            - 0.22475541 * t * rh
            - 0.00683783 * t * t
            - 0.05481717 * rh * rh
            + 0.00122874 * t * t * rh
            + 0.00085282 * t * rh * rh
            - 0.00000199 * t * t * rh * rh
        )
        if rh < 13 and 80 <= t <= 112:
            hi -= ((13 - rh) / 4) * math.sqrt((17 - abs(t - 95)) / 17)
        elif rh > 85 and 80 <= t <= 87:
            hi += ((rh - 85) / 10) * ((87 - t) / 5)

    return round((hi - 32) * 5 / 9, 1)
