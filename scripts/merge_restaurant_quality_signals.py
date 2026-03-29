#!/usr/bin/env python3
"""Apply external quality signals onto the generated Japan restaurant datasets."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
JSON_PATH = DATA_DIR / "japan-restaurants.json"
GEOJSON_PATH = DATA_DIR / "japan-restaurants.geojson"
QUALITY_SIGNALS_PATH = DATA_DIR / "restaurant-quality-signals.json"


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def apply_signals(record: dict, signals_by_id: dict) -> None:
    record["external_signals"] = signals_by_id.get(record["id"], {})


def main() -> None:
    signals_by_id = load_json(QUALITY_SIGNALS_PATH, {})
    restaurants = load_json(JSON_PATH, [])
    geojson = load_json(GEOJSON_PATH, {"type": "FeatureCollection", "features": []})

    for record in restaurants:
        apply_signals(record, signals_by_id)

    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        apply_signals(props, signals_by_id)

    save_json(JSON_PATH, restaurants)
    save_json(GEOJSON_PATH, geojson)
    print(f"Applied external signals to {len(restaurants)} restaurants.")


if __name__ == "__main__":
    main()
