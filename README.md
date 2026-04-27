# Unofficial Platinum Experience

Map-first explorer for Singapore-issued American Express Platinum benefits. The
site keeps official source data separate from enrichment so users can see when
each dataset was cached, where it came from, and when a human review is needed.

Live site: `https://amex-explorer.kooexperience.com/`

## Programs

- `Dining`: Japan restaurants from Pocket Concierge plus the official Amex
  Global/Local Dining Credit directory. Singapore records are labelled as Local
  Dining Credit, not abroad Global Dining Credit.
- `Plat Stay`: official Plat Stay property set from the current Amex PDF.
- `Love Dining`: Singapore restaurant and hotel outlets with official discount
  terms, exclusions, booking notes, and cache metadata.
- `Table for Two`: Singapore Platinum set-menu roster from the official Amex
  page, with 18/18 mapped roster venues and DiningCity `AMEXPlatSG`
  slot-level availability checks for party-size/date/session filtering.

## Data Trust Model

- `official`: names, official roster membership, addresses, terms links, and
  source hashes from Amex or Pocket Concierge.
- `cached`: source fetch times and hashes stored in `data/*-source.json` files
  and rendered in the UI.
- `live-cache`: Table for Two availability from DiningCity's public
  `AMEXPlatSG` project endpoint. The UI stores returned slot dates, times, and
  max party size so filters are evaluated per slot. Final booking and voucher
  redemption still happen in the Amex Experiences App.
- `enriched`: geocodes, Google Maps ratings, summaries, and third-party quality
  signals. These are helpful, but not the source of truth.
- `manual`: screenshots and menu captures. These are fallback context only;
  users must confirm in the Amex Experiences App before booking.

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
- `data/table-for-two.json`: Table for Two official roster, T&C/FAQ links,
  roster source metadata, and cached `AMEXPlatSG` availability.

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
- `refresh-table-for-two.yml`: daily public Table for Two roster and baseline
  `AMEXPlatSG` availability refresh at `01:30 UTC`. The browser also refreshes
  Table for Two availability while the page is open.
- `table-for-two-alerts.yml`: twice-hourly Table for Two availability refresh
  and SMTP alert sender. It reads signup rows from a configured CSV endpoint,
  sends only newly matched slots, and stores salted sent-key hashes.
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

Current coordinate audit notes:

- Global Dining: 1,479 mapped records, 457 records without coordinates.
- Japan Dining: 845 mapped records, no missing coordinates.
- Love Dining: 73 mapped records, 6 bundled/unmapped records.
- Table for Two: 18 mapped records, no missing coordinates.
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
- A real Table for Two waitlist/alert feature needs a backend or scheduled
  notifier to store user preferences and send notifications after the browser
  closes. The included GitHub Actions notifier can poll a Google Form/Sheet
  CSV endpoint and send through SMTP, but the signup storage still lives outside
  GitHub Pages.
- Prefer official Amex/Pocket Concierge sources for facts; enrichments should be
  labelled and easy to override.

## Table for Two Email Alerts

The static site cannot store visitor emails by itself. For a Google-based setup,
create a Google Form that collects email, party size, dates, sessions, and
venues, link it to a Sheet, then expose the responses to the alert workflow via
a CSV endpoint. Use an Apps Script endpoint with a secret token for private
responses; a published CSV link is simpler but exposes emails to anyone who has
the URL.

When `TABLE_FOR_TWO_ALERT_SIGNUP_URL` is set and the Table for Two data refresh
runs, the site shows a `Booking alerts` panel above the Table for Two venue
results. The scheduled alert workflow then polls the CSV endpoint and emails
matching newly-seen slots. A copy-paste Google Apps Script setup is in
[`docs/table-for-two-alerts-google-apps-script.md`](docs/table-for-two-alerts-google-apps-script.md).

Recommended Sheet/Form fields:

```text
enabled,email,name,party size,dates,sessions,venues,unsubscribe url
```

`dates`, `sessions`, and `venues` may be comma-separated. Use `enabled=false`
when a user unsubscribes.

Set these repository secrets before enabling the scheduled workflow:

```text
TABLE_FOR_TWO_ALERTS_CSV_URL=https://script.google.com/.../exec?token=...
TABLE_FOR_TWO_ALERT_SIGNUP_URL=https://forms.gle/... or https://script.google.com/.../exec
ALERT_UNSUBSCRIBE_BASE_URL=https://script.google.com/.../exec?action=unsubscribe
ALERT_HASH_SALT=<random long string>
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=no-reply@kooexperience.com
SMTP_PASS=<Google app password or SMTP relay password>
SMTP_FROM=Table for Two Alerts <no-reply@kooexperience.com>
SMTP_REPLY_TO=no-reply@kooexperience.com
```

For Google Workspace, make sure `no-reply@kooexperience.com` is a real mailbox
or a verified send-as alias for the mailbox used by `SMTP_USER`. The simplest
GitHub Actions setup is Gmail SMTP with 2-step verification and an app password;
Workspace SMTP relay can also work, but GitHub-hosted runner IPs are not stable.
The domain should have Google SPF, DKIM, and DMARC records so alert mail is not
treated as spoofed.

Security notes:

- Do not expose the Google Sheet as a public CSV. Use Apps Script and a secret
  token in `TABLE_FOR_TWO_ALERTS_CSV_URL`.
- Keep `ALERT_HASH_SALT`, SMTP passwords, Apps Script tokens, and form admin URLs
  in GitHub Actions secrets only.
- The repository stores only salted hashes of sent alert keys in
  `data/table-for-two-alert-sent.json`; it should not store user emails.
- The alert workflow sends one confirmation email per unmatched signup
  preference scope so the user receives an unsubscribe link even before a slot
  matches. It also sends one positive match email per signup preference scope.
  After a match email is sent, it records a salted matched key so that signup
  does not keep sending new slot-time emails. If an alert's exact dates or date
  range pass without any matching slot email having been sent, it sends one
  expiry email and records a salted expiry key so that closure email is not
  repeated.
- Unsubscribe links are added to email bodies and `List-Unsubscribe` headers. The
  Apps Script unsubscribe endpoint should verify the `email` and `token` query
  parameters, then mark matching rows as `enabled=false`.
- Only set `ALERT_ONE_CLICK_UNSUBSCRIBE=true` if the Apps Script endpoint also
  supports one-click unsubscribe POST requests.
