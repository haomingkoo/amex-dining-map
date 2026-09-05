# Unofficial Platinum Experience

Map-first explorer for Singapore-issued American Express Platinum benefits. The
site keeps official source data separate from enrichment so users can see when
each dataset was cached, where it came from, and when a human review is needed.

[**Open the live Amex benefit explorer**](https://amex-explorer.kooexperience.com/)

## Programs

- `Dining`: Japan restaurants from Pocket Concierge plus the official Amex
  Global/Local Dining Credit directory. Singapore records are labelled as Local
  Dining Credit, not abroad Global Dining Credit.
- `Plat Stay`: official Plat Stay property set from the current Amex PDF.
- `Love Dining`: Singapore restaurant and hotel outlets with official discount
  terms, exclusions, booking notes, and cache metadata.
- `Table for Two`: Singapore Platinum set-menu roster from the official Amex
  page plus the reviewed DiningCity `AMEXPlatSG` membership feed, with 30/30
  mapped roster venues (28 current booking-project venues and 2 retained
  historical records) and DiningCity `AMEXPlatSG` slot-level availability
  checks for party-size/date/session filtering.

## Data Trust Model

- `official`: names, official roster membership, addresses, terms links, and
  source hashes from Amex or Pocket Concierge.
- `cached`: source fetch times and hashes stored in `data/*-source.json` files
  and rendered in the UI.
- `live-cache`: Table for Two availability from DiningCity's public
  `AMEXPlatSG` project endpoint. The UI stores returned slot dates, times, and
  max party size so filters are evaluated per slot. Final booking and voucher
  redemption still happen in the Amex Experiences App.
- `availability-cache`: Pocket Concierge public availability calendar and
  date-level slot summaries for Japan filters. The cache stores dates, times,
  sessions, and party-size ranges only.
- `enriched`: geocodes, Google Maps ratings, summaries, and third-party quality
  signals. These are helpful, but not the source of truth.
- `manual`: screenshots and menu captures. These are fallback context only;
  users must confirm in the Amex Experiences App before booking.

## Key Data Files

- `data/japan-restaurants.json`: Pocket Concierge Japan dining records.
- `data/japan-dining-source.json`: Japan cache time, source URL, counts, and
  stable record hash.
- `data/pocket-availability.json`: cached Pocket Concierge reservation dates,
  waitlist dates, and upcoming date-level time, party-size, and seating ranges
  for Japan filters.
- `data/global-restaurants.json`: Amex Global/Local Dining Credit records.
- `data/global-dining-source.json`: Amex directory cache time, source API,
  country counts, and verification counts.
- `data/plat-stays.json`: Plat Stay properties.
- `data/plat-stay-source.json`: Plat Stay PDF source URL, cache time, page count,
  and PDF hash.
- `data/love-dining.json`: Love Dining restaurants and hotel outlets.
- `data/love-dining-source.json`: Love Dining source pages, T&C PDF hashes,
  counts, reviewed hashes, and manual-review flag.
- `data/table-for-two.json`: Table for Two official roster, T&C/FAQ links,
  roster source metadata, and cached `AMEXPlatSG` availability.
- `data/table-for-two-release-history.json`: first-seen venue/date/session
  observations and evidence-bounded release lead-time patterns.
- `data/updates.json`: published and review-gated before-and-after changes.

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
python3 scripts/scrape_table_for_two.py --availability-only
python3 scripts/check_table_for_two_availability.py --venue-id tft-15-stamford-restaurant --meal Lunch --times 12:00,12:30 --date YYYY-MM-DD
python3 scripts/source_change_alert.py --program "Plat Stay" --meta data/plat-stay-source.json --data data/plat-stays.json --output /tmp/plat-stay-alert.md
```

## GitHub Workflows

- `deploy-pages.yml`: deploys the static site on pushes to `main`.
- `refresh-data.yml`: daily Japan dining, Pocket availability, and Plat Stay
  refresh at `21:00 UTC`.
- `refresh-love-dining.yml`: daily Love Dining refresh at `21:45 UTC`.
- `refresh-table-for-two.yml`: daily public Table for Two roster and baseline
  `AMEXPlatSG` availability refresh at `22:00 UTC`, including official menu PDF
  version checks. The browser also refreshes availability while the page is open.
- `table-for-two-alerts.yml`: scheduled every 15 minutes for Table for Two availability refresh
  and Resend email sender. It exports confirmed subscriptions from the Railway
  reminder service, sends newly matched slots, stores salted sent-key hashes,
  and records first-seen release observations.
  GitHub schedules can start late or be skipped during platform load; the UI's
  checked timestamp and stale state are authoritative, not the nominal cron.
  This high-frequency job has its own concurrency group so slower daily source
  writers cannot replace a pending availability run.
- `refresh-global-dining.yml`: daily Amex Global/Local Dining refresh at
  `21:30 UTC`.
- Source-change workflows open/update GitHub Issues labelled `data-alert` when
  counts, official hashes, source image hashes, T&C hashes, or official records
  change. They also append structured before-and-after records to
  `data/updates.json`; review-gated records are hidden from the public UI until
  approved.

## Validation

Run these before pushing data or UI changes:

```bash
python3 -m json.tool data/love-dining-source.json >/tmp/love-source.valid.json
python3 -m json.tool data/japan-dining-source.json >/tmp/japan-source.valid.json
python3 -m json.tool data/pocket-availability.json >/tmp/pocket-availability.valid.json
python3 -m json.tool data/table-for-two.json >/tmp/table-for-two.valid.json
python3 -m json.tool data/table-for-two-release-history.json >/tmp/tft-release-history.valid.json
python3 -m json.tool data/updates.json >/tmp/updates.valid.json
python3 -m py_compile scripts/source_change_alert.py scripts/scrape_love_dining.py scripts/scrape_table_for_two.py scripts/check_table_for_two_availability.py scripts/scrape_pocket_availability.py scripts/sync_japan_mvp.py
python3 scripts/audit_coordinates.py
python3 scripts/audit_content_provenance.py
node --check web/app.js
git diff --check
```

Current coordinate audit notes:

- Global Dining: 1,822 mapped records, 104 records without coordinates.
- Japan Dining: 843 mapped records, no missing coordinates.
- Plat Stay: 76 mapped records, no missing coordinates.
- Love Dining: 77 mapped records, 6 intentionally bundled/unmapped records.
- Table for Two: 30 mapped records (28 current booking-project venues and 2 retained historical records), no missing coordinates.
- The bounds audit catches impossible country-level pins; it does not prove
  every pin is within 20m of a restaurant entrance.

## Safety Boundaries

- Do not scrape logged-in Amex Experiences App endpoints or bypass app access.
- Do not commit cookies, tokens, private screenshots, or user-specific booking
  data.
- Do not present generic public DiningCity restaurant time slots as Table for Two
  inventory. Only the DiningCity `AMEXPlatSG` project endpoint is used for Table
  for Two availability.
- Treat cached Table for Two availability as planning data. Users still need to
  complete booking and voucher redemption in the Amex Experiences App.
- Table for Two alert subscriptions use the Railway reminder service and require
  email confirmation. GitHub Pages never stores subscriber email addresses.
- Prefer official Amex/Pocket Concierge sources for facts; enrichments should be
  labelled and easy to override.

## Table for Two Email Alerts

The Table for Two page contains a native signup form. It sends the selected
venues, party size, sessions, and date range to the FastAPI service in
`reminders/`. The service stores pending and confirmed subscriptions in SQLite,
sends double-opt-in messages through Resend, and supports explicit plus
email-provider one-click unsubscribe through POST actions.

The scheduled workflow exports confirmed subscribers and matches them against
the latest `AMEXPlatSG` availability cache. Required workflow secrets are:

```text
REMINDERS_API_BASE=https://<service-host>
ALERT_EXPORT_TOKEN=<random long token>
ALERT_HASH_SALT=<random long string>
ABUSE_HASH_SALT=<different random long string, Railway service>
RESEND_API_KEY=<resend API key>
RESEND_FROM=<verified sender>
```

See [`reminders/README.md`](reminders/README.md) for service endpoints and local
development. The older Google Apps Script setup remains under `docs/` as a
historical migration reference and is not the active architecture.

## Telegram Companions

Two isolated Telegram identities are implemented but disabled by default. The
owner-alert bot can deliver reviewed before-and-after updates only to one fixed
private channel. The public guide bot answers deterministic private-chat TFT
program, venue, official-menu, T&C, FAQ, slot, and release questions from a
bundled source snapshot. It does not
invoke an LLM, fetch user URLs, read subscriber data, or share the owner bot's
token. Real Telegram activation remains pending; setup, rotation, monitoring,
rollback, privacy, and freshness procedures are in
[`reminders/README.md`](reminders/README.md).

## Public Updates

`data/updates.json` is the durable public change ledger. Each entry includes the
program, detection time, official source, and explicit before-and-after values.
The site-wide Updates strip shows only entries with `status: published`.

`data/source-health.json` is the public troubleshooting summary for Global
Dining, Japan Dining, Plat Stay, Love Dining, TFT roster, TFT menus, TFT
availability, Google Maps, and Tabelog. The Updates panel keeps official program
sources separate from optional availability and rating enrichment, shows exact
upstream check times and coverage, and recomputes staleness in the browser so a
frozen deployment cannot continue to look current. Scheduled refreshes record
bounded success/failure state, while a separate monitor emits owner events when
a source becomes stale, fails, recovers, or enters/leaves review.

TFT menu candidates use a stricter PDF- and snapshot-bound publish path. See
the [TFT menu review runbook](docs/tft-menu-review-runbook.md); do not publish a
menu candidate with the generic update-review command below.

The TFT participating-roster image is also review-gated. A new image hash keeps
the last approved snapshot (currently 21 active and two historical venues) public and records one source-scoped review
item; it does not silently turn the hardcoded roster into a claimed official
addition or removal. After reviewing the complete image, add a hash-addressed
manifest under `data/reviews/table-for-two-roster/` with predecessor lineage,
then apply it with:

```bash
python3 scripts/apply_tft_roster_review.py \
  --manifest data/reviews/table-for-two-roster/<observed-image-sha256>.json
```

The resumable apply path preserves existing menu and availability state and
publishes exact reviewed per-venue additions/removals. Re-run with `--check`
before committing; an interrupted ledger append is recovered from bounded
pending events on the next run.

The structured DiningCity `AMEXPlatSG` membership feed is maintained separately
from that official-image lineage. A new feed-only venue is published only after
two successful observations agree on its identity and the record has an online
AMEXPlatSG status, a DiningCity Singapore URL, an address, and Singapore-bounded
coordinates. A feed-only venue is retired only after two successful absences;
one missed or failed scan retains the last good listing. Official-image venues
are never auto-deleted. Every confirmed transition is written as a deduplicated
before-and-after update, while incomplete or conflicting records remain in the
review queue. Scheduled runs emit one bounded `TFT_MAINTENANCE` JSON summary for
diagnosis without logging response bodies or credentials.

Table for Two T&C and FAQ successors follow the same retained-snapshot rule,
but their review is bound to exact PDF bytes and page-level clause evidence.
Use the [TFT official-document review runbook](docs/tft-document-review-runbook.md)
to diagnose `review_required` or `pending_events`, apply one reviewed
predecessor-to-successor transition, and verify its owner event before commit.

Generic Love Dining and Table for Two source changes are written as
`status: review_required`. After checking the official source, publish or reject
one with:

```bash
python3 scripts/review_update.py <update-id> --status published --note "Checked against official source"
```

Do not use this generic command for TFT menus, the participating roster, or
official T&C/FAQ documents; each has its own evidence-bound runbook and apply
command above.

## Observed Table for Two Release Patterns

The scheduled availability job records when each venue, date, and meal first
appears. The site derives typical lead times only after at least three repeat
observations. Detection time is shown only when at least 60% of observations
fall in the same half-hour window.

These are cache observations, not official release policies. Rebuild the local
historical baseline from recent Git snapshots with:

```bash
python3 scripts/track_table_for_two_releases.py --from-git --history-limit 300
```

The disabled-by-default Telegram guide bundles the reviewed aggregate projection
and answers `/release <exact venue> [lunch|dinner]`. It reports first-detected
lead time, observation count, confidence, latest detection, and snapshot age;
it never presents these observations as a restaurant schedule or current seats.
The archival availability workflow rebuilds and commits this release-history
projection after tracking new observations. The public web app gets current
availability from the bounded Railway live snapshot instead; release-pattern
history remains a separate, slower evidence surface.
Rebuild or verify the bundled projection with:

```bash
python3 scripts/build_tft_guide_catalog.py
python3 scripts/build_tft_guide_catalog.py --check
```

Security notes:

- Keep subscriber exports, Resend credentials, tokens, and service admin URLs in
  deployment secrets only.
- The repository stores only salted hashes of sent alert keys in
  `data/table-for-two-alert-sent.json`; it should not store user emails.
- Subscriber emails are stored only in the Railway SQLite service.
- Public update records must never contain subscriber data, tokens, scraper
  credentials, or private booking information.
