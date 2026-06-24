# Table for Two Reminder Signup — Design Spec

**Date:** 2026-06-24
**Status:** Approved (design), pending implementation
**Branch:** `feat/table-for-two-reminders`

## Objective

Let people sign up on the site for Table for Two availability reminders. They fill a
native form, confirm by email (double opt-in), and receive an email **only when** real
availability matches their request — plus a single "your window passed, no availability
came up" note when their date range expires. Subscriptions live in a real database, not a
Google Sheet.

## Why we're rebuilding

The old signup/sending path is abandoned and broken:
- Signup was a Google Form → Google Sheet → CSV (`TABLE_FOR_TWO_ALERTS_CSV_URL`).
- Sending was Gmail SMTP from a Google Workspace mailbox that got sunset → alerts have been
  failing (`535 BadCredentials`) since 2026-06-23.

The **scraping + matching** pipeline in this repo is healthy and maintained — we keep it.
Only the signup and sending halves are replaced.

## Architecture

Reuse the proven pattern from the sibling `trader-koo` project (FastAPI + SQLite + Resend
on Railway). Keep the existing GitHub Action for scrape/match; swap only its subscriber
source and email transport.

```
[Native form on amex-explorer.kooexperience.com]
        │ POST JSON
        ▼
[reminders service — Railway: FastAPI + SQLite on a volume]
   POST /api/subscribe   → validate, store 'pending', send confirm email (Resend)
   GET  /api/confirm     → activate (status 'active')
   GET  /api/unsubscribe → one-click off (status 'unsubscribed')
   GET  /api/subscribers → token-gated export (ALERT_EXPORT_TOKEN) for the alert job
   GET  /healthz
        │  GET subscribers (active only)
        ▼
[Existing GitHub Action: scrape_table_for_two.py + send_table_for_two_alerts.py]
   (matching logic UNCHANGED)
        │ send via Resend (replaces Gmail SMTP)
        ▼
   availability alert  /  "window passed" email
```

### Components

1. **reminders service** (new, Railway) — small FastAPI app.
   - `app/main.py` — endpoints, CORS, rate limiting.
   - `app/db.py` — SQLite schema + queries (stdlib `sqlite3`, no ORM).
   - `app/emailer.py` — Resend via `urllib` (copied from trader-koo pattern, no SDK).
   - `app/schemas.py` — Pydantic request/response models + validation.
2. **Subscriber DB** — SQLite file on a Railway persistent volume.
3. **Frontend form** — replaces the "Create alert" Google-Form link in the Table for Two
   panel (`web/index.html` + `web/app.js`).
4. **Alert job** — existing `send_table_for_two_alerts.py`, modified: fetch subscribers
   from `/api/subscribers`; send via Resend.

## Data model (SQLite)

```sql
CREATE TABLE subscribers (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL,
  name TEXT,
  party_size INTEGER NOT NULL,
  sessions TEXT NOT NULL,          -- JSON array, subset of ["Lunch","Dinner"]
  venues TEXT NOT NULL,            -- JSON array of venue names, or ["any"]
  date_start TEXT NOT NULL,        -- YYYY-MM-DD
  date_end TEXT NOT NULL,          -- YYYY-MM-DD
  status TEXT NOT NULL DEFAULT 'pending',  -- pending | active | unsubscribed
  confirm_token TEXT,
  confirm_token_expires_ts TEXT,
  unsubscribe_token TEXT NOT NULL,
  source_ip TEXT,
  created_ts TEXT NOT NULL,
  confirmed_ts TEXT,
  unsubscribed_ts TEXT
);
CREATE INDEX idx_subscribers_status ON subscribers(status);
CREATE INDEX idx_subscribers_confirm_token ON subscribers(confirm_token);
CREATE INDEX idx_subscribers_unsub_token ON subscribers(unsubscribe_token);

CREATE TABLE subscribe_events (        -- per-IP rate limiting + audit
  id INTEGER PRIMARY KEY,
  source_ip TEXT,
  event_type TEXT NOT NULL,            -- subscribe_attempt | confirm | unsubscribe
  created_ts TEXT NOT NULL
);
CREATE INDEX idx_events_ip_ts ON subscribe_events(source_ip, created_ts);
```

The export endpoint emits the field shape `send_table_for_two_alerts.py` already consumes
(`email`, `name`, `party_size`, `sessions`, `venues`, `dates`/`date_start`/`date_end`,
`unsubscribe_url`), so the matcher needs no logic changes.

## Email flow (3 emails, all via Resend, from `dinnertime@kooexperience.com`)

1. **Confirm** — sent once on signup. Link to `/api/confirm?token=…`. The only non-alert
   email. Confirm token expires in 7 days.
2. **Availability alert** — sent by the alert job when a slot matches. Dedup via the
   existing sent-log.
3. **Window passed** — sent once when the requested date range expires with no match
   (existing `build_expired_email`).

Every email includes a one-click unsubscribe link (`/api/unsubscribe?token=…`) and a
`List-Unsubscribe` header.

## Security

- **Double opt-in** — prevents subscribing an address you don't own.
- **Validation** (Pydantic): email format; `party_size` 1–20; `sessions` ⊆
  {Lunch, Dinner}; `venues` validated against the real venue list (or "any"); `date_start
  ≤ date_end`, not in the past, within a sane horizon (e.g. ≤ 120 days out).
- **Rate limit** — per-IP cap on `POST /api/subscribe` (e.g. 5 / hour) via a window count
  on `subscribe_events`. Hidden honeypot field rejects bots. (No CAPTCHA initially — YAGNI;
  add Cloudflare Turnstile only if spam appears.)
- **CORS** — allow only `https://amex-explorer.kooexperience.com`.
- **Tokens** — `secrets.token_urlsafe(32)`; constant-time comparison; confirm token expiry.
- **Export endpoint** — `Authorization: Bearer <ALERT_EXPORT_TOKEN>` (secret already exists).
- **Secrets** — Railway env only, never committed. `.env.example` with placeholders.
- Minimal PII (email + preferences + IP for abuse control). HTTPS via Railway.

## Resend

Reuse the existing Resend account (already used by trader-koo, `kooexperience.com` already
verified → no DNS work). Use a **dedicated API key** for this app so it can be revoked
independently. Env: `RESEND_API_KEY`, `RESEND_FROM=dinnertime@kooexperience.com`.

## Deployment (Railway)

- New Railway service from this repo, root directory = the reminders service dir.
- Persistent volume mounted for the SQLite file (`DB_PATH` env).
- Env vars: `RESEND_API_KEY`, `RESEND_FROM`, `ALERT_EXPORT_TOKEN`, `ALLOWED_ORIGIN`,
  `DB_PATH`, `CONFIRM_TOKEN_EXPIRY_HOURS`.
- The GitHub Action gets the service URL + `ALERT_EXPORT_TOKEN` to fetch subscribers, and
  `RESEND_API_KEY`/`RESEND_FROM` to send.

## What gets removed (dead old-system code)

- Google Form "Create alert" link: `tft-alert-signup-panel` / `tft-alert-signup-link`
  wiring in `web/index.html` and `web/app.js` (`alert_signup_url`).
- Google Sheet CSV source: `TABLE_FOR_TWO_ALERTS_CSV_URL` reading in
  `send_table_for_two_alerts.py`; `TABLE_FOR_TWO_ALERT_SIGNUP_URL`.
- Gmail SMTP: the `smtplib` send branch and `SMTP_*` secrets/env wiring.
- **Keep:** the scraper, the matcher, and the sent-log dedup.

## Testing

- **Unit:** token gen/expiry; validation rejects (bad email, past date, unknown venue,
  party-size bounds, bad session); rate-limit window; export shape.
- **Integration:** subscribe → pending; confirm → active and present in export;
  unsubscribe → excluded from export. Honeypot/rate-limit rejected.
- **Self-check:** a runnable `demo()`/`test_*` per repo convention.
- **Manual end-to-end:** real signup → confirm email arrives via Resend → alert fires when
  availability matches.

## Out of scope (later, only if needed)

- Moving the scraper/matcher off GitHub Actions onto Railway.
- Moving sent-state dedup from the repo JSON into the DB.
- CAPTCHA / Turnstile.
- Subscriber self-service edit (re-subscribe with new prefs covers it for now).
