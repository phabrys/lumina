"""Fixtures communes aux tests Lumina."""

import pytest

from .common import NOON


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Autorise le chargement de custom_components/lumina dans les tests."""
    yield


@pytest.fixture(autouse=True)
def french_language(hass):
    """Les tests vérifient les messages du Journal en français."""
    hass.config.language = "fr"


@pytest.fixture
def daytime(freezer):
    """Fige l'horloge en journée, sauf si un test la déplace."""
    freezer.move_to(NOON)
    return freezer
