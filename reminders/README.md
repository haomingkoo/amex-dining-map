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
| POST | `/api/telegram/guide/webhook` | Authenticated private-chat Telegram guide ingress |

## Deployment (Railway)

Service root = `reminders/`. Mount a persistent volume at `/data` and set `DB_PATH=/data/reminders.db`.
See `.env.example` for the full env var list.

For a CLI deployment from the repository root, preserve that service root:

```bash
railway up reminders --path-as-root --detach --service amex-reminders --json
```

Capture the returned deployment ID, poll `railway deployment list --json` until
that exact deployment is `SUCCESS`, then require `/healthz` to return `200` with
the same `deployment_id`. A health response from the previous instance is not
acceptance. Finally probe the intended disabled/enabled feature state.

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

Create the owner-alert bot separately in BotFather, add it to a private channel
with post-only permission, and obtain the numeric `-100...` channel ID from a
trusted Telegram update/API inspection. Verify the ID against a test channel
message before enabling. Enable in this order: deploy secrets and cutoff, test
authenticated ingestion while disabled, enable the flag, send one reviewed test
event, then verify its single `sent` row. On `unknown` or `dead`, inspect the
owner delivery table and Railway `owner_alert_delivery` event; never blindly
replay an ambiguous delivery. Rotate by disabling, replacing the bot token and
ingestion token independently, redeploying, testing, then enabling. Roll back by
disabling owner alerts; public guide and email reminders remain independent.

## Public Telegram guide

The guide bot is a separate, disabled-by-default Telegram identity. Its current
surface is private chats only: `/start`, `/help`, `/venues`, exact venue/menu
lookup, and `/release <venue> [lunch|dinner]` observed release-pattern answers.
It uses a generated source catalogue with official Amex menu links and
never invokes an LLM, follows a user URL, joins groups, or reads owner-channel
configuration. The catalogue is bundled with the Railway revision; the TFT
refresh rebuilds it, but a normal reviewed Railway deployment is required to
serve that newer revision. Substantive venue and menu answers expose the source check time and warn
when the bundled roster or menu index is stale. Release answers expose exact
observation counts, median and range, tracker confidence, latest detection, and
history freshness. They explicitly describe scheduled AMEXPlatSG cache
detection—not an official release policy or current availability.

The current guide does not yet answer T&C or current-slot questions and does not
create Telegram reminders; those remain #38–#40.

Spam controls are intentionally quiet: Telegram's webhook secret is checked
before JSON parsing, update IDs are durably deduplicated, identities are stored
only as keyed hashes, and per-user/global minute and daily quotas are
consumed atomically. Groups, bots, unsupported updates, and rate-limited bursts
return success without sending a reply, preventing warning-message
amplification. Replay metadata expires after seven days and quota metadata
after 24 hours; message text and usernames are not stored.

Before enabling, create a separate BotFather bot and generate two independent
43+ character values for `TELEGRAM_GUIDE_WEBHOOK_SECRET` and
`TELEGRAM_IDENTITY_HASH_SALT`. Keep Railway on one persistent SQLite-backed
replica. Register `/api/telegram/guide/webhook` with Telegram using the secret
token, `allowed_updates=["message"]`, and `drop_pending_updates=true` only for
the first activation. Real private-chat, replay, group-ignore, and rate-limit
acceptance remains mandatory before calling the bot live.

### Guide bot activation and operations

Read secrets into an ephemeral shell without echoing or command-line arguments,
then register the webhook. `drop_pending_updates=true` is for first activation
or an intentional queue reset only. Unset all temporary values immediately.

```bash
read -rs TELEGRAM_GUIDE_BOT_TOKEN; export TELEGRAM_GUIDE_BOT_TOKEN
read -rs TELEGRAM_GUIDE_WEBHOOK_SECRET; export TELEGRAM_GUIDE_WEBHOOK_SECRET
export GUIDE_WEBHOOK_URL='https://<service-host>/api/telegram/guide/webhook'

python3 - <<'PY'
import json
import os
import urllib.parse
import urllib.request

base = f"https://api.telegram.org/bot{os.environ['TELEGRAM_GUIDE_BOT_TOKEN']}"
payload = urllib.parse.urlencode({
    "url": os.environ["GUIDE_WEBHOOK_URL"],
    "secret_token": os.environ["TELEGRAM_GUIDE_WEBHOOK_SECRET"],
    "allowed_updates": json.dumps(["message"]),
    "drop_pending_updates": "true",
}).encode()
with urllib.request.urlopen(base + "/setWebhook", data=payload, timeout=30) as response:
    assert json.load(response).get("ok") is True
with urllib.request.urlopen(base + "/getWebhookInfo", timeout=30) as response:
    info = json.load(response)
    assert info.get("ok") is True
    print(json.dumps(info["result"], indent=2))
PY

unset TELEGRAM_GUIDE_BOT_TOKEN TELEGRAM_GUIDE_WEBHOOK_SECRET GUIDE_WEBHOOK_URL
```

Monitor Railway health and error rates, Telegram `pending_update_count` and
`last_error_message`, SQLite volume use, and the age/manual-review fields in the
bundled TFT catalogue. A healthy HTTP endpoint is not proof of a working bot;
send `/venues`, both VUE menu variants, `/release VUE dinner`, an unknown venue,
and a group message
from real Telegram clients after each activation.

For token rotation, disable `TELEGRAM_GUIDE_ENABLED`, delete the webhook, rotate
the BotFather token and both independent random secrets, redeploy, register the
new webhook without dropping pending updates, repeat acceptance, then re-enable.
Rotate owner-alert and guide-bot credentials separately.

```bash
read -rs TELEGRAM_GUIDE_BOT_TOKEN; export TELEGRAM_GUIDE_BOT_TOKEN
python3 - <<'PY'
import json
import os
import urllib.parse
import urllib.request

url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_GUIDE_BOT_TOKEN']}/deleteWebhook"
payload = urllib.parse.urlencode({"drop_pending_updates": "false"}).encode()
with urllib.request.urlopen(url, data=payload, timeout=30) as response:
    assert json.load(response).get("ok") is True
PY
unset TELEGRAM_GUIDE_BOT_TOKEN
```

Rollback by disabling the guide flag and deleting its webhook; owner alerts and
email reminders remain independent. If delivery is ambiguous, inspect the
stored terminal state and Telegram webhook information instead of resending.
Restore only from the persistent SQLite volume or a verified backup, never from
chat logs. The service stores no message text or usernames.

## Operational logs

Railway emits one JSON line per HTTP request with a generated request ID, method,
path, status, and latency. Subscription events record only a short keyed recipient
fingerprint and the state transition; emails, names, tokens, query strings,
Telegram message text, and credentials are never logged. Use the `X-Request-ID`
response header to correlate a browser failure with Railway logs.

Guide and owner delivery attempts also emit privacy-safe outcome events with
state, bounded error code, command class where applicable, attempt, and latency.
HTTP 200 can still contain a terminal Telegram outcome, so alert on `unknown`,
`dead`, and `catalog_invalid`, and inspect their SQLite rows before intervention.

For email reminders, monitor the Table for Two Alerts workflow conclusion,
Resend delivery/bounce events, the cached availability age, and the incremental
sent-key receipt file. A failed delivery step still commits refreshed availability
and then fails the job visibly. Rotate export/hash/Resend secrets one at a time:
pause the workflow, update Railway and GitHub copies where shared, probe export,
send one controlled test, then resume. Back up the SQLite volume before schema or
credential work, verify the copy opens and passes an integrity check, and test a
restore in a temporary service before relying on it. During an incident, disable
the affected surface first; do not delete the volume or sent receipts.
