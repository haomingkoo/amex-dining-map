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

## Deployment (Railway)

Service root = `reminders/`. Mount a persistent volume at `/data` and set `DB_PATH=/data/reminders.db`.
See `.env.example` for the full env var list.

Security controls include explicit double opt-in actions, separate manage and
unsubscribe capabilities, atomic keyed-hash IP/email/global quotas, 16 KiB API
body limits, owner-only SQLite permissions, bounded retention, restricted CORS,
no-store token pages, and browser security headers. Set a strong independent
`ABUSE_HASH_SALT` in production and keep every token in deployment secrets.
