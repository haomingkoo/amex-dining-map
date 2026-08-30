from __future__ import annotations

import pytest

from scripts import build_telegram_public_config


def test_missing_username_keeps_public_actions_disabled():
    assert build_telegram_public_config.build_config("") == {
        "schema_version": 1,
        "enabled": False,
        "bot_username": None,
    }


def test_valid_username_enables_public_actions_without_a_token():
    assert build_telegram_public_config.build_config("@KooTftGuideBot") == {
        "schema_version": 1,
        "enabled": True,
        "bot_username": "KooTftGuideBot",
    }


@pytest.mark.parametrize(
    "username",
    ["not-a-bot", "https://t.me/KooTftGuideBot", "1234Bot", "short"],
)
def test_invalid_username_fails_closed(username):
    with pytest.raises(ValueError, match="valid public bot username"):
        build_telegram_public_config.build_config(username)
