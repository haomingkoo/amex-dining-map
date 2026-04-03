# Tabelog Matching Stack

## Goal

Match Pocket Concierge Japan restaurants to the exact Tabelog listing URL with high precision, then extract:

- raw Tabelog score
- review count
- honest-stars transformation
- exact Tabelog URL for user handoff

Current truth-set result on the `51-70` sample:

- `20/20` records have a real exact Tabelog listing
- current matcher gets `9/20` exact top URLs
- current promoted `verified` precision on that sample is `9/9`

That means the main problem is still `discovery coverage`, not reckless auto-accept.

## Inputs We Need

From Pocket Concierge:

- restaurant id
- English name
- native Japanese name / aliases
- prefecture
- city
- district / town
- source-localized address
- phone number when available
- nearest station text
- cuisine / category

From Tabelog:

- search-result candidates
- exact listing URL
- detail page address
- phone number
- transportation / station
- cuisine
- score
- review count

## Core Tools Needed

### 1. Pocket Concierge Native Metadata Fetcher

Purpose:

- get the native title and keywords from the Japanese Pocket Concierge page

Why:

- English names are often not enough for Japanese restaurant discovery

Current implementation:

- `scripts/match_tabelog_candidates.py`

### 2. Prefecture-Scoped Tabelog Search Fetcher

Purpose:

- search Tabelog inside the right prefecture first

Why:

- this is still the cheapest first-pass discovery layer

Current implementation:

- `scripts/match_tabelog_candidates.py`

### 3. External Search Fallback

Purpose:

- recover exact listings when internal Tabelog search misses them

Recommended sources:

- Yahoo Japan site search
- `site:tabelog.com`
- `site:selection.tabelog.com`

Why:

- many exact listings exist but do not surface cleanly inside Tabelog’s own search

Current implementation:

- Yahoo fallback is already in `scripts/match_tabelog_candidates.py`

Still needed:

- stronger query templates
- more phone/address-led fallback queries

### 4. Tabelog Detail Fetcher

Purpose:

- verify candidates using detail-page facts

Signals to extract:

- listing URL
- street address
- address locality / region
- postal code
- phone
- transportation
- cuisine
- score
- review count

Why:

- discovery alone is not enough; we need hard verification

Current implementation:

- `scripts/match_tabelog_candidates.py`

### 5. URL Canonicalizer

Purpose:

- normalize:
  - `tabelog.com`
  - `selection.tabelog.com`
  - `s.tabelog.com`

Why:

- the same restaurant may appear under multiple Tabelog hosts and page shapes

Current implementation:

- `scripts/match_tabelog_candidates.py`

Still needed:

- better handling of moved-page patterns

### 6. Matching / Verification Engine

Purpose:

- score and classify candidates into:
  - `verified`
  - `review`
  - `reject`

Best evidence:

- native name
- prefecture / city / district
- street-block digits
- phone
- station
- cuisine

Important:

- phone should be strong positive evidence, not an absolute veto
- address should be component-based, not one big string
- floor / building digits should not incorrectly defeat street-number matches

Current implementation:

- `scripts/match_tabelog_candidates.py`

Recent fixes already made:

- address-block matching instead of flattening all digits
- softer location handling when Tabelog locality is missing but phone + address + name strongly agree
- top-vs-second gap logic

### 7. Ground-Truth Calibration Set

Purpose:

- measure real recall and precision

Without this:

- we just tune blindly

Current implementation:

- `data/tabelog-ground-truth-sample.json`

Minimum useful size:

- `20` records

Better:

- `20` hard records
- then `50`
- then a larger stratified set

### 8. Batch Runner + Progress Sidecar

Purpose:

- run slices like:
  - `51-100`
  - `101-150`

Why:

- lets us improve one slice, measure it, then scale safely

Current implementation:

- `scripts/match_tabelog_candidates.py`
- progress sidecar JSON already supported

### 9. Cache Layer

Purpose:

- avoid repeating the same HTTP fetches and LLM calls

Needed caches:

- Pocket native metadata
- Tabelog search pages
- Tabelog detail pages
- future LLM judgments

Current implementation:

- `data/tabelog-match-http-cache.json`

### 10. Optional LLM Judge

Purpose:

- decide gray-zone cases where the candidate set is already close

Best use:

- rerank top `2-5` candidates
- not primary discovery

Good for:

- cross-script weirdness
- branch ambiguity
- cases that look right to a human but miss one rigid symbolic rule

Bad for:

- missing exact URLs that never surfaced in the candidate pool

Suggested provider:

- Groq-backed judge over structured candidate features

Status:

- hook point identified
- not yet benchmarked against the truth set

### 11. Evaluation Layer

Purpose:

- compare matcher versions on the same truth set

Metrics that matter:

- top-URL exact hit rate
- verified precision
- review coverage
- collapse rate onto wrong local favorites

Current truth-set insight:

- current exact top hit rate on sample `51-70`: `45%`
- current verified precision on that sample: `100%`

That tells us:

- we are conservative
- but discovery still misses too many exact pages

## Nice-To-Have Tools

### Browser / Headless Fallback

Use only for the hard tail:

- Playwright or Chromium-based fallback

Why:

- only when HTTP/search discovery still misses exact URLs

This should stay rare because it is slower and harder to maintain.

### Search Critic / Audit Worker

Use for:

- examining misses
- grouping failure modes
- designing better query templates

This can be done with sub-agents or manual review.

## What Is Still Missing

1. Better discovery query templates for the `11` known misses in the truth set.
2. Moved-page awareness for cases like `Aji Takebayashi`.
3. Stronger address/phone-led external queries for Nishinakasu / Otemon / Kitakyushu clusters.
4. A real A/B benchmark for:
   - current matcher
   - current matcher + Groq judge
5. Promotion of verified truth-backed matches into:
   - `data/restaurant-quality-signals.json`

## Practical Build Order

1. Expand the ground-truth set.
2. Fix discovery on the misses.
3. Rerun against the same truth set.
4. Add Groq as a gray-zone judge.
5. Re-benchmark.
6. Only then widen from `20` to `50` to `100+`.
