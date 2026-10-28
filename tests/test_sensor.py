"""Tests du capteur d'état de la pièce."""

import pytest
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .common import _room, _setup
from custom_components.lumina.sensor import LuminaRoomStateSensor


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock: Recorder, enable_custom_integrations):
    """Comme dans conftest.py, mais le recorder démarre avant Home Assistant."""
    yield


async def test_unrecorded_attributes(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    start = dt_util.utcnow()
    entry = await _setup(hass)
    room = _room(hass, entry)
    unrecorded = LuminaRoomStateSensor._unrecorded_attributes
    # Des noms qui existent : une faute de frappe laisserait l'attribut enregistré.
    assert unrecorded <= room.attributes.keys()

    await async_wait_recording_done(hass)
    history = await recorder_mock.async_add_executor_job(
        get_significant_states, hass, start, None, [room.entity_id]
    )
    recorded = history[room.entity_id][-1].attributes
    assert not unrecorded & recorded.keys()
    assert "occupied" in recorded  # le reste est toujours enregistré
