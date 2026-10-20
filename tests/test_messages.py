"""Tests du catalogue de messages du Journal."""

from custom_components.lumina.messages import MESSAGES, message


def test_languages_have_the_same_messages() -> None:
    assert MESSAGES["fr"].keys() == MESSAGES["en"].keys()


def test_regional_and_unknown_languages() -> None:
    assert message("fr-CA", "resumed") == MESSAGES["fr"]["resumed"]
    assert message("de", "resumed") == MESSAGES["en"]["resumed"]
