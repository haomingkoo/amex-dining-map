# Table for Two Reminders Service

FastAPI + SQLite service that powers email reminder signups for the Table for Two map.
People subscribe via a native form on `amex-explorer.kooexperience.com`, confirm by email
(double opt-in), and the existing GitHub Action alert job pulls active subscribers from
here and emails them when availability matches.

Mirrors the `trader-koo` pattern. Email is sent via the Resend HTTP API (no SDK).

## Local development

```bash
cd reminders
python3.11 -m venv .venv          # 3.11–3.13 locally; Railway runs 3.12
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env              # fill in values
.venv/bin/python -m pytest -v     # run tests
.venv/bin/uvicorn app.main:app --reload   # run locally
```

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/healthz` | Liveness check |
| POST | `/api/subscribe` | Create a pending subscription, send confirm email |
| GET  | `/api/confirm?token=` | Render the confirmation action |
| POST | `/api/confirm?token=` | Activate new or changed settings |
| GET  | `/api/unsubscribe?token=` | Render the unsubscribe action |
| POST | `/api/unsubscribe?token=` | Unsubscribe, including email-provider one-click requests |
| GET/POST | `/api/manage?token=` | View or update reminder settings with the dedicated manage token |
| GET  | `/api/subscribers` | Active subscribers export (Bearer `ALERT_EXPORT_TOKEN`) |
| POST | `/api/owner-alerts/events` | Reviewed update ingestion (Bearer `OWNER_ALERT_INGEST_TOKEN`) |

## Deployment (Railway)

Service root = `reminders/`. Mount a persistent volume at `/data` and set `DB_PATH=/data/reminders.db`.
See `.env.example` for the full env var list.

Security controls include explicit double opt-in actions, separate manage and
unsubscribe capabilities, atomic keyed-hash IP/email/global quotas, 16 KiB API
body limits, owner-only SQLite permissions, bounded retention, restricted CORS,
no-store token pages, and browser security headers. Set a strong independent
`ABUSE_HASH_SALT` in production and keep every token in deployment secrets.

## Private owner alerts

The source refresh workflows replay a bounded recent window of
`status: published` entries from `data/updates.json` to the authenticated
Railway ingestion endpoint. Backend idempotency makes confirmed replays cheap,
while `OWNER_ALERT_NOT_BEFORE` prevents enabling the integration from flooding
the channel with historical events and still permits a later-reviewed event.
Each event uses its own HTTP request so one slow Telegram call cannot hold a
batch open. Railway is
the only component that holds the Telegram bot token and the exact private
channel ID. The request body cannot select a destination. Confirmed deliveries
are durably deduplicated in SQLite; review-required entries are withheld without
consuming their event ID.

Telegram has no idempotency key. A timeout can happen after Telegram accepted a
message but before the service received proof, so ambiguous outcomes are stored
as `unknown` and are not retried automatically. Definite retryable failures are
stored as `retry`; confirmed deliveries replay without another API call. A
terminal `unknown` or `dead` delivery is surfaced as a GitHub Actions warning
without leaving every source refresh permanently failed. It stays quarantined
until an operator resolves it; it is never blindly resent.

Keep `OWNER_ALERTS_ENABLED=false` until the BotFather bot, private owner channel,
numeric channel ID, activation cutoff, and independent ingestion token are configured. The GitHub
refresh jobs also need `OWNER_ALERT_INGEST_URL` and `OWNER_ALERT_INGEST_TOKEN`;
when both are absent, dispatch safely skips.

Generate the ingestion token with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`.
Immediately before enabling, set `OWNER_ALERT_NOT_BEFORE` to the current UTC
instant; do not copy an old fixed date, because that could release recent
historical ledger events on the first run.
