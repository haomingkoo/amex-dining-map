# Japan Dining Map MVP

Japan-first MVP for plotting American Express dining venues on a searchable map,
with downloadable KML files for Google My Maps sharing.

## Scope

- Source-backed ingestion from public Pocket Concierge Japan landing pages
- Normalized JSON dataset for the web app
- Approximate geocoding with cache for map markers
- KML export for:
  - all Japan
  - Tokyo
  - Kyoto
  - Osaka
- Static web UI with:
  - search
  - city / district / cuisine filters
  - kid-policy / English menu / reservation-type filters
  - KML download buttons

## Accuracy Notes

- Restaurant facts come from Pocket Concierge area pages.
- Coordinates are approximate unless later replaced with stronger place matching.
- Michelin status is intentionally left blank in this MVP unless verified from an
  official Michelin source.
- Kid friendliness is normalized from explicit Pocket Concierge child-policy text.
  Missing policy is treated as `unknown`, not as family-friendly.

## Project Layout

```text
amex-dining-map/
├── data/
│   ├── geocode_cache.json
│   ├── japan-restaurants.json
│   └── kml/
├── scripts/
│   └── sync_japan_mvp.py
└── web/
    ├── app.js
    ├── index.html
    └── styles.css
```

## Build Data

The sync script fetches public Pocket Concierge landing pages, normalizes the
restaurant records, geocodes them using Nominatim with a local cache, and writes
JSON + KML outputs.

```bash
cd /Users/koohaoming/dev/amex-dining-map
python3 scripts/sync_japan_mvp.py
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

## Next Step After MVP

- Add Google Places enrichment for rating, editorial summary, and `goodForChildren`
- Add stronger address / place matching
- Add Michelin validation from official Michelin Guide pages
- Add issue-report / revalidation workflow
