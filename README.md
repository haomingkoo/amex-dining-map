# Unofficial Platinum Experience

Map-first explorer for Singapore-issued American Express Platinum benefits. The
site keeps official source data separate from enrichment so users can see when
each dataset was cached, where it came from, and when a human review is needed.

Live site: `https://xplorer.kooexperience.com/`

## Programs

- `Dining`: Japan restaurants from Pocket Concierge plus the official Amex
  Global/Local Dining Credit directory. Singapore records are labelled as Local
  Dining Credit, not abroad Global Dining Credit.
- `Plat Stay`: official Plat Stay property set from the current Amex PDF.
- `Love Dining`: Singapore restaurant and hotel outlets with official discount
  terms, exclusions, booking notes, and cache metadata.
- `Table for Two`: Singapore Platinum set-menu roster from the official Amex
  page, with cache-only availability fields where app screenshots have been
  manually captured.

## Data Trust Model

- `official`: names, official roster membership, addresses, terms links, and
  source hashes from Amex or Pocket Concierge.
- `cached`: source fetch times and hashes stored in `data/*-source.json` files
  and rendered in the UI.
- `enriched`: geocodes, Google Maps ratings, summaries, and third-party quality
  signals. These are helpful, but not the source of truth.
- `manual`: Table for Two availability screenshots and menu screenshots. These
  are never treated as live availability; users must confirm in the Amex
  Experiences App before booking.

## Key Data Files

- `data/japan-restaurants.json`: Pocket Concierge Japan dining records.
- `data/japan-dining-source.json`: Japan cache time, source URL, counts, and
  stable record hash.
- `data/global-restaurants.json`: Amex Global/Local Dining Credit records.
- `data/global-dining-source.json`: Amex directory cache time, source API,
  country counts, and verification counts.
- `data/plat-stays.json`: Plat Stay properties.
- `data/plat-stay-source.json`: Plat Stay PDF source URL, cache time, page count,
  and PDF hash.
- `data/love-dining.json`: Love Dining restaurants and hotel outlets.
- `data/love-dining-source.json`: Love Dining source pages, T&C PDF hashes,
  counts, reviewed hashes, and manual-review flag.
- `data/table-for-two.json`: Table for Two official roster, T&C/FAQ links, source
  image hashes, and cache-only availability notes.

## Routes

- `/#/dining/world`: all dining records.
- `/#/dining/taiwan`: Taiwan Global Dining Credit records.
- `/#/dining/singapore`: Singapore Local Dining Credit records.
- `/#/stays`: Plat Stay explorer.
- `/#/love-dining`: Love Dining explorer.
- `/#/table-for-two`: Table for Two roster and cached availability explorer.
- `/#/alerts`: source-change summary panel.

## Local Run

Serve the repository root and open `/web/`.

```bash
python3 -m http.server 8000
```

Then open:

```text
http://localhost:8000/web/
```

## Refresh Commands

```bash
python3 scripts/sync_japan_mvp.py
python3 scripts/sync_plat_stay.py
python3 scripts/scrape_global_dining.py
python3 scripts/scrape_love_dining.py --no-geocode
python3 scripts/scrape_table_for_two.py
```

Useful targeted checks:

```bash
python3 scripts/verify_global_dining_official.py --country-code TW --max-list 40
python3 scripts/scrape_love_dining.py --diff --no-geocode
python3 scripts/check_table_for_two_availability.py --venue-id tft-15-stamford-restaurant --meal Lunch --times 12:00,12:30 --date 2026-04-28
python3 scripts/source_change_alert.py --program "Plat Stay" --meta data/plat-stay-source.json --data data/plat-stays.json --output /tmp/plat-stay-alert.md
```

## GitHub Workflows

- `deploy-pages.yml`: deploys the static site on pushes to `main`.
- `refresh-data.yml`: daily Japan dining and Plat Stay refresh at `01:00 UTC`.
- `refresh-love-dining.yml`: daily Love Dining refresh at `01:45 UTC`.
- `refresh-table-for-two.yml`: daily public Table for Two roster refresh at
  `01:30 UTC`.
- `refresh-global-dining.yml`: monthly Amex Global/Local Dining refresh on the
  first day of the month at `01:00 UTC`.
- Source-change workflows open/update GitHub Issues labelled `data-alert` when
  counts, official hashes, source image hashes, T&C hashes, or official records
  change.

## Validation

Run these before pushing data or UI changes:

```bash
python3 -m json.tool data/love-dining-source.json >/tmp/love-source.valid.json
python3 -m json.tool data/japan-dining-source.json >/tmp/japan-source.valid.json
python3 -m json.tool data/table-for-two.json >/tmp/table-for-two.valid.json
python3 -m py_compile scripts/source_change_alert.py scripts/scrape_love_dining.py scripts/scrape_table_for_two.py scripts/check_table_for_two_availability.py scripts/sync_japan_mvp.py
python3 scripts/audit_coordinates.py
python3 scripts/audit_content_provenance.py
node --check web/app.js
git diff --check
```

## Safety Boundaries

- Do not scrape logged-in Amex Experiences App endpoints or bypass app access.
- Do not commit cookies, tokens, private screenshots, or user-specific booking
  data.
- Do not present Table for Two cache data as live inventory.
- Prefer official Amex/Pocket Concierge sources for facts; enrichments should be
  labelled and easy to override.
