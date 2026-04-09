# CLAUDE.md — amex-dining-map

## What This Project Is

An AMEX dining map that enriches partner restaurant data with Tabelog review scores,
ratings, and metadata. Restaurant data comes from Pocket Concierge and is matched
against Tabelog listings to add quality signals (score, review count, price tier).

The enriched data powers a GeoJSON map and `restaurant-quality-signals.json` used
by the frontend.

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
| `retry_rejects_phone.py` | Targeted phone/name Tabelog searches | Quick pass, low yield |
| `retry_rejects_ddg.py` | Full DDG + Yahoo name searches + Groq judge | Moderate yield |
| `retry_rejects_cached.py` | **Cache-first** (Claude WebSearch URLs) + DDG fallback + Groq judge | **Best — run this** |

### URL Cache (`data/tabelog-url-cache.json`)

Maps `restaurant_id → tabelog_url`, populated by running parallel Claude agents
in this CLI with WebSearch. Cache-first retry uses this directly — enrich the
specific page instead of searching.

**To refresh the cache** (e.g. for new rejects): see "Adding New Restaurants" below.

---

## Correct Run Order

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
GROQ_API_KEY=...        # LLM judge (free tier sufficient)
BRAVE_API_KEY=...       # Optional: Brave Search for URL discovery
```

---

## Data Files (gitignored)

Large binary/cache files are gitignored. Committed:
- `data/japan-restaurants.json`
- `data/japan-restaurants.geojson`
- `data/restaurant-quality-signals.json`
- `data/tabelog-url-cache.json`  ← commit this, it's the Claude-searched URL index
