"""Tests de la température ressentie (indice de chaleur de la NOAA)."""

import pytest

from custom_components.lumina.heat import apparent_temperature


@pytest.mark.parametrize(
    ("temperature", "humidity", "expected"),
    [
        (20, 50, 19.4),  # temps doux : approximation de Steadman
        (32.2, 70, 41.0),  # 90 °F, 70 % : 106 °F dans la table de la NOAA
        (28, 90, 34.0),  # chaleur humide
        (35, 10, 31.9),  # air très sec : correction à la baisse
    ],
)
def test_reference_values(temperature: float, humidity: float, expected: float) -> None:
    assert apparent_temperature(temperature, humidity) == expected


def test_humidity_is_clamped() -> None:
    assert apparent_temperature(30, 150) == apparent_temperature(30, 100)
    assert apparent_temperature(30, -5) == apparent_temperature(30, 0)
