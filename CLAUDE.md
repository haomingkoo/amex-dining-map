# CLAUDE.md — amex-dining-map

## Agent skills

### Issue tracker

Issues and PRDs live in GitHub Issues; external PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the canonical `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix` labels. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. See `docs/agents/domain.md`.

## What This Project Is

An AMEX Platinum map covering five datasets:
1. **Japan** — Pocket Concierge partner restaurants enriched with Tabelog review scores,
   ratings, and metadata.
2. **Global Dining Credit** — 15 non-Japan countries (1,926 records) pulled from Amex's own
   dining-offers API at `https://dining-offers-prod.amex.r53.tuimedia.com`
   (`/api/countries`, then `/api/country/{code}/merchants?origin=SG`).
3. **Love Dining** — Singapore hotel and restaurant program scraped from Amex SG website
   (83 venues: 31 restaurants + 52 hotel outlets, geocoded via Nominatim).
4. **Table for Two** — Amex SG Table for Two roster (30 venues in `data/table-for-two.json`),
   with live slot availability from `api.diningcity.asia` (project `AMEXPlatSG`).
5. **Plat Stay** — Amex Platinum hotel/stay partners (76 records in `data/plat-stays.json`)
   from `go.amex/platstay`.

All datasets display Google Maps ratings (scraped via Playwright) from `data/google-maps-ratings.json`.

---

## Pipeline Overview

```
japan-restaurants.json          ← source restaurant records (Pocket Concierge)
        │
        ▼
match_tabelog_candidates.py     ← main matcher: browse area pages + search fallback
        │
        ▼
tabelog-match-results.json      ← per-restaurant match decisions
        │
        ▼
promote_tabelog_matches.py      ← write verified/review matches into quality signals
        │
        ▼
restaurant-quality-signals.json ← final output consumed by the map

dining-offers-prod.amex.r53.tuimedia.com (Amex dining-offers API)
        │
        ▼
scrape_global_dining.py         ← /api/countries + /api/country/{code}/merchants?origin=SG
        │
        ▼
global-restaurants.json         ← 15-country global dining partner data (1,926 records)
```

---

## Matching Pipeline: How It Works

### Main Matcher (`match_tabelog_candidates.py`)

Runs in two modes per restaurant:
1. **Browse mode**: fetches Tabelog area pages for the restaurant's prefecture/city,
   collects candidate listings, scores them
2. **Search fallback**: if browse finds only rejects, runs targeted Tabelog search
   + DDG/Yahoo fallback

**Scoring** (`candidate_match_assessment`): confidence score 0–100 from signals:
- `phone_exact` (+10), `phone_conflict` (−6 to −10)
- `district_match` (+16), `district_mismatch` (−18)
- `address_digits_exact` (+20), `address_digits_conflict` (−18)
- `native_name_strong` (+18), `english_name_strong` (+12)
- `station_strong` (+7)

**Thresholds**: confidence ≥ 70 + no conflicts → `verified`; ≥ 55 → `review`; else → `reject`

**Groq LLM judge** (`groq_judge_match`): called for top candidates with confidence < 50.
Uses `llama-3.3-70b` via Groq API (already in `.env`). Result cached in HTTP cache.

### Retry Scripts (run after main matcher for rejects)

| Script | Strategy | When to use |
|--------|----------|-------------|
| `retry_rejects_cached.py` | **Cache-first** (Claude WebSearch URLs) + DDG/Yahoo fallback + Groq judge | **Best — run this** |

### URL Cache (`data/tabelog-url-cache.json`)

Maps `restaurant_id → tabelog_url`, populated by running parallel Claude agents
in this CLI with WebSearch. Cache-first retry uses this directly — enrich the
specific page instead of searching.

**To refresh the cache** (e.g. for new rejects): see "Adding New Restaurants" below.

---

## Global Dining Scraper

```bash
# Scrape all 15 non-Japan countries (~1,930 restaurants, 0.25s pause between requests)
python3 scripts/scrape_global_dining.py

# Check for additions/removals against last snapshot
python3 scripts/scrape_global_dining.py --diff

# Quick test without writing files
python3 scripts/scrape_global_dining.py --dry-run --limit 20
```

Source: Amex's own dining-offers API at `https://dining-offers-prod.amex.r53.tuimedia.com`
(`API_BASE_URL` in the script). `main()` calls `fetch_official_records()`, which hits
`/api/countries` and then `/api/country/{code}/merchants?origin=SG` for every non-Japan
country (Japan is skipped via `SKIP_COUNTRIES` because Pocket Concierge covers it).
The public landing page is `https://www.americanexpress.com/en-sg/benefits/diningbenefit/`,
recorded as `source_url` in `data/global-dining-source.json`. The `remap_url` /
`fetch_sitemap_urls` / JSON-LD helpers and the `BASE_URL`, `SITEMAP_URL`, `SITEMAP_DOMAIN`
constants are legacy dead code kept only to parse old stored source URLs.

Output: `data/global-restaurants.json` — committed to repo and loaded by frontend.
Snapshot: `data/global-dining-snapshot.json` — gitignored, used for diff detection only.

---

## Google Maps Ratings Pipeline

```bash
# Scrape ratings for all datasets (Playwright, ~1-2 hours for full run)
python3 scripts/scrape_google_ratings_playwright.py

# Only missing records (preferred for incremental updates)
python3 scripts/scrape_google_ratings_playwright.py --missing-only

# Specific datasets
python3 scripts/scrape_google_ratings_playwright.py --datasets love japan global

# Dry run
python3 scripts/scrape_google_ratings_playwright.py --dry-run
```

Output: `data/google-maps-ratings.json` — `{id: {rating, review_count, google_name, google_address, maps_url}}`

**Important**: Run sequentially or use `--missing-only` for concurrent runs (race condition fixed in incremental save).

---

## Global Dining Description Pipeline

```
scrape_global_dining.py          ← scrape source data
        │
        ▼
enrich_global_website_signals.py ← scrape each restaurant's official website
        │
        ▼
enrich_from_web_search.py        ← fetch Michelin inspector descriptions (Algolia)
        │
        ▼
derive_global_source_tags.py     ← derive known_for/signature tags + summary_official
        │
        ▼
generate_global_descriptions.py  ← generate AI descriptions (Groq) for remaining records
```

### Michelin Enrichment (`enrich_from_web_search.py`)

Queries Michelin's public Algolia index (`prod-restaurants-en`) directly — no browser needed.
Credentials stored in `.env` as `MICHELIN_ALGOLIA_APP_ID` and `MICHELIN_ALGOLIA_API_KEY`.
These are public read-only keys embedded in Michelin's frontend JS (visible in browser Network
tab on guide.michelin.com). Requires `Referer: guide.michelin.com` header.

```bash
# Initial seed (run once, ~10 min for the full ~1,930-restaurant dataset)
python3 scripts/enrich_from_web_search.py --force --delay 0.2

# Incremental update (skips fresh cached entries, retries no_result after 90 days)
python3 scripts/enrich_from_web_search.py

# Single country
python3 scripts/enrich_from_web_search.py --country France
```

**Coverage**: Countries with Michelin Guide coverage get real inspector descriptions.
Australia and New Zealand have no Michelin Guide → correct `no_result`, retried after 90 days.

**Match verification**: name token overlap ≥ 0.6 (excluding generic words like "restaurant",
"bar", "grill") + country cname match. Prevents cross-country false matches.

**Cache**: `data/web-search-signals-cache.json` — `michelin` hits kept forever,
`no_result` retried after 90 days, `error` always retried.

---

## Correct Run Order (Japan)

```bash
# 1. Run main matcher (first time or after new restaurants added)
python3 scripts/match_tabelog_candidates.py

# 2. Run cache-first retry on rejects (fastest, highest yield)
python3 scripts/retry_rejects_cached.py

# 3. Promote verified + review matches into quality signals
python3 scripts/promote_tabelog_matches.py

# 4. Merge signals into restaurant data
python3 scripts/merge_restaurant_quality_signals.py
```

---

## Key Caches (do not delete)

| File | What it stores | Notes |
|------|---------------|-------|
| `tabelog-match-http-cache.json` | All HTTP responses (Tabelog pages, DDG results) | Large (~30MB). Saves re-fetching. |
| `tabelog-url-cache.json` | Claude-found Tabelog URLs per restaurant ID | Built via CLI WebSearch agents. Rebuild for new rejects. |
| `tabelog-match-results.json` | All match decisions | Source of truth for match status. |
| `geocode_cache.json` | Geocoding results | |
| `venue_detail_cache.json` | Venue detail API responses | |

---

## Known Scoring Issues & Lessons Learned

### Why rejects happen

1. **`phone_conflict` dominates (90% of rejects)** — AMEX phones are often outdated.
   Tabelog sometimes stores "unknown" as `+81-不明の為情報お待ちしております` which
   `normalize_digits` strips to `"81"`, creating a false conflict.

2. **`district_mismatch` from romanization** — "Marunochi" vs "Marunouchi" (same place,
   different spelling) fires `district_mismatch`. Cascades into `district_address_conflict`.

3. **Browse-only is insufficient** — the original pipeline ran `browse_area` only and
   skipped DDG fallback when browse was active. 265/276 rejects had never had any
   web search run. Fix: always run `retry_rejects_cached.py` after the main matcher.

4. **`name_address_anchor` too strict** — softens phone penalty only when BOTH name
   AND address digits match. Since address digits often differ (AMEX vs Tabelog
   formatting), this never fires even for obvious name matches.

### The winning fix

Run Claude agents (via this CLI's WebSearch) to find the exact Tabelog URL for each
reject, cache it, then enrich that specific page. Bypasses Tabelog's own search
entirely. Found 272/275 rejects in one parallel run.

---

## Adding New Restaurants / Refreshing Cache

When new restaurants are added to `japan-restaurants.json`:

1. Run main matcher to process new records
2. For new rejects, spawn parallel Claude agents to find URLs:
   ```
   # In this CLI session — see session notes for the agent prompt pattern
   # Split rejects into batches, spawn 5 parallel agents with WebSearch
   # Merge results into data/tabelog-url-cache.json
   ```
3. Run `retry_rejects_cached.py`

---

## Environment Variables (`.env`)

```
GROQ_API_KEY=...        # LLM judge for Japan matching + AI description generation
```

`enrich_from_web_search.py` also requires `MICHELIN_ALGOLIA_APP_ID` and the
matching Michelin Algolia API key in the same `.env`. They are named here without
assignment syntax on purpose: the pre-commit hook rejects any diff containing
`<NAME>=` for these keys, placeholder or not.

Note: `.env.example` currently ships only `GROQ_API_KEY`.
(Reminders-service and alert-job secrets are separate; see the Table for Two Reminders
section below.)

---

## Data Files (gitignored)

Large caches are gitignored (see `.gitignore`): `tabelog-match-http-cache.json`,
`tabelog-match-candidates.json`, `tabelog-match-results.json` (plus their `.progress.json`
sidecars), `global-dining-snapshot.json`, `web-search-signals-cache.json`,
`review-promotion-batch.json`, `tabelog-ground-truth-sample.json`,
`plat_stay_geoapify_cache.json`, `plat_stay_tomtom_cache.json` and `data/tft-menus/`.
(`global-website-signals-cache.json` and `global-dining-geocode-cache.json` are listed in
`.gitignore` but were committed before the rule was added, so they remain tracked.)

Everything else under `data/` is committed, including every dataset the frontend loads
(`japan-restaurants.json`, `japan-restaurants.geojson`, `global-restaurants.json`,
`love-dining.json`, `plat-stays.json`, `plat-stays.geojson`, `table-for-two.json`,
`table-for-two-slots.json`) plus `google-maps-ratings.json`,
`restaurant-quality-signals.json`, `source-health.json`, `pocket-availability.json`,
`geocode_cache.json`, `venue_detail_cache.json`, and `tabelog-url-cache.json`
(the Claude-searched URL index).

---

## Staleness Watchdog

`scripts/build_source_health.py` writes per-source freshness into `data/source-health.json`
every 30 minutes (`Monitor Source Health`). `scripts/watchdog_stale_sources.py` then acts
on it:

- A source past its `stale_after_hours` limit, or with a non-clear `failure_state`, gets
  its owning workflow re-dispatched (`SOURCE_WORKFLOWS`), at most once per workflow per
  6 hours. Sources sharing a workflow collapse into one dispatch.
- If a retry already ran inside that window and the source is still degraded, the watchdog
  opens a single `source-health` issue. Only one is open at a time, so the 30-minute
  cadence cannot spam it.
- `tabelog-ratings` is intentionally unmapped. `Match Tabelog Candidates` uploads a
  candidate artifact and commits nothing, so no retry can clear it. It escalates instead.

`review_required` is a human review flag, not staleness, and never triggers the watchdog.

Dry run without dispatching anything:

```bash
python3 scripts/watchdog_stale_sources.py --dry-run
```

## Table for Two Reminders Service (`reminders/`)

Self-hosted signup for Table for Two availability alerts. Replaced the old
Google Form + Google Sheet + Gmail SMTP flow (all removed).

**Service:** `reminders/` — FastAPI + SQLite on Railway (project `amex-reminders`,
URL `https://amex-reminders-production.up.railway.app`, SQLite on a `/data` volume).
Email via the Resend HTTP API (no SDK), sending from `dinnertime@kooexperience.com`
(the `kooexperience.com` domain is already verified in the shared Resend account,
reused from `trader-koo`).

```
Native form on the site (web/, #/table-for-two)
   POST /api/subscribe  → store 'pending', send double opt-in confirm email
   GET  /api/confirm     → render confirmation action; POST activates
   GET  /api/manage?token=  → dedicated-token self-service page; POST updates
   GET  /api/unsubscribe?token= → render action; POST unsubscribes
   GET  /api/subscribers → Bearer ALERT_EXPORT_TOKEN export for the alert job
        │
        ▼
scripts/send_table_for_two_alerts.py  (GitHub Action, runs from main)
   fetches active subscribers from /api/subscribers, sends matches/expired via Resend
```

Security: double opt-in; atomic keyed-hash IP/email/global limits plus honeypot;
CORS locked to the site origin; separate per-subscriber manage and unsubscribe
capabilities; no-store token pages; bounded retention and request sizes.

**Deploy the service:** `cd reminders && railway up -c` (linked to the `amex-reminders`
project). Local dev/tests use a Python 3.11–3.13 venv (`reminders/.venv`); Railway
pins 3.12. Run `reminders/.venv/bin/python -m pytest reminders/tests`.

**Secrets** (Railway service + GitHub Actions): `RESEND_API_KEY`, `RESEND_FROM`,
`ALERT_EXPORT_TOKEN`, `REMINDERS_API_BASE`, plus service-only `DB_PATH`,
`ALLOWED_ORIGIN`, `PUBLIC_BASE_URL`, `CONFIRM_TOKEN_EXPIRY_HOURS`, and the existing
`ALERT_HASH_SALT`, plus service-only `ABUSE_HASH_SALT` and proxy/rate settings.
The `Table for Two Alerts` workflow runs from `main`, so the
alert job only picks up rewires after a merge.
