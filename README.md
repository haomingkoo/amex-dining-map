# Amex Benefits Explorer

Map-first explorer for American Express benefits, starting with a live Japan
dining dataset and expanding into stays, Love Dining, and 10Xcelerator.

## Scope

- Multi-program shell with top-level tabs for:
  - Dining
  - Plat Stay
  - Love Dining
  - 10Xcelerator
- Live Japan dining dataset from public Pocket Concierge pages
- Route-based dining views for:
  - World shell
  - Japan
  - Tokyo
  - Kyoto
  - Osaka
- Static web UI with:
  - search
  - city / district / cuisine filters
  - kid-policy / English menu / reservation-type filters
  - KML download buttons
  - mobile cards
  - multi-dataset roadmap panels for upcoming programs

## Accuracy Notes

- Dining facts currently come from Pocket Concierge Japan pages and venue detail
  endpoints.
- Coordinates are not equal across all future programs. The app is designed to
  surface confidence instead of pretending every pin is equally exact.
- Michelin status is intentionally left blank unless verified from an official
  Michelin source.
- Kid friendliness is normalized from explicit source text. Missing policy is
  treated as unknown, not family-friendly.

## Project Layout

```text
amex-dining-map/
├── data/
│   ├── geocode_cache.json
│   ├── japan-restaurants.json
│   ├── venue_detail_cache.json
│   └── kml/
├── .env.example
├── scripts/
│   └── sync_japan_mvp.py
└── web/
    ├── app.js
    ├── index.html
    └── styles.css
```

## Build Dining Data

The sync script fetches public Pocket Concierge landing pages, normalizes the
restaurant records, geocodes them using Nominatim with a local cache, and writes
JSON + KML outputs.

```bash
cd /Users/koohaoming/dev/amex-dining-map
python3 scripts/sync_japan_mvp.py
```

## Local Environment

Optional keys for future assistant work should live in `.env` and never be
committed. Use `.env.example` as the template.

```bash
cp .env.example .env
```

## Run Web App

Serve the repo root and open the web app from `/web/`.

```bash
cd /Users/koohaoming/dev/amex-dining-map
python3 -m http.server 8000
```

Then open:

```text
http://localhost:8000/web/
```

## Current Build Status

- Sprint 1:
  multi-dataset shell and nested dining routing
- Sprint 2:
  Plat Stay ingestion + blackout-date planner
- Sprint 3:
  Love Dining Restaurants and Hotels ingestion
- Later:
  global dining expansion, sync alerts, and a grounded assistant layer
