#!/usr/bin/env python3
"""Build the public, non-secret Telegram guide configuration for Pages."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


USERNAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,28}[Bb][Oo][Tt]")


def build_config(username: str) -> dict:
    value = username.strip().removeprefix("@").strip()
    if not value:
        return {"schema_version": 1, "enabled": False, "bot_username": None}
    if USERNAME_RE.fullmatch(value) is None:
        raise ValueError("TELEGRAM_GUIDE_BOT_USERNAME must be a valid public bot username")
    return {"schema_version": 1, "enabled": True, "bot_username": value}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = build_config(os.getenv("TELEGRAM_GUIDE_BOT_USERNAME", ""))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(config, indent=2) + "\n")
    print(f"Telegram guide public config: {'enabled' if config['enabled'] else 'disabled'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
