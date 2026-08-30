# Table for Two Reminders Implementation Plan

> Historical and superseded. This plan predates the deployed security hardening; use `reminders/README.md` for the active architecture and behavior. In particular, re-subscribing no longer replaces confirmed preferences before explicit confirmation.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the abandoned Google-Form/Sheet/Gmail-SMTP reminder signup with a native on-site form backed by a FastAPI + SQLite service on Railway, double opt-in, sending via the existing Resend account; rewire the existing alert job to read subscribers from the new API and send via Resend.

**Architecture:** New `reminders/` FastAPI service (mirrors `trader-koo`) stores subscribers in SQLite on a Railway volume. The static site posts to it; the existing GitHub Action keeps scraping/matching and just swaps its subscriber source (Sheet CSV → API) and email transport (SMTP → Resend).

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, stdlib `sqlite3`, Pydantic v2, Resend HTTP API via `urllib` (no SDK), Railway, vanilla JS frontend.

## Global Constraints

- Python style: snake_case, type hints on all signatures, f-strings, `pathlib`, max line 88, `from __future__ import annotations`. (per `/Users/koohaoming/dev/.claude/rules/python-style.md`)
- No new dependency where stdlib + an installed dep suffices (Resend = `urllib`, not the SDK). No ORM — raw `sqlite3`.
- Secrets only via env / Railway; never committed. `.env.example` uses placeholders.
- Sender: `dinnertime@kooexperience.com`. Resend domain `kooexperience.com` already verified (reused from trader-koo).
- CORS allowed origin: `https://amex-explorer.kooexperience.com`.
- Tokens: `secrets.token_urlsafe(32)`; confirm token expiry 7 days (168h).
- Conventional Commits; work on branch `feat/table-for-two-reminders`.
- Subscription field model (must stay compatible with `send_table_for_two_alerts.py`):
  `email, name, party_size, sessions[], venues[], date_start, date_end, unsubscribe_url`.

---

### Task 1: Scaffold the `reminders/` service

**Files:**
- Create: `reminders/app/__init__.py`, `reminders/app/main.py`, `reminders/app/config.py`
- Create: `reminders/requirements.txt`, `reminders/railway.toml`, `reminders/.env.example`, `reminders/README.md`
- Test: `reminders/tests/test_health.py`

**Interfaces:**
- Produces: `app.main:app` (FastAPI instance); `app.config:Settings` with
  `db_path: Path, resend_api_key: str, resend_from: str, alert_export_token: str,
  allowed_origin: str, confirm_token_expiry_hours: int, public_base_url: str`.

**Steps:**
- [ ] `requirements.txt`: `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `email-validator`. Pin versions.
- [ ] `config.py`: a `Settings` dataclass read from env with sane defaults; `db_path` defaults to `./reminders.db` for local, `/data/reminders.db` on Railway via `DB_PATH`.
- [ ] `main.py`: create `app`, add CORS middleware (`allow_origins=[settings.allowed_origin]`, methods `["GET","POST"]`), `GET /healthz` → `{"ok": True}`.
- [ ] `railway.toml`: nixpacks build, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- [ ] `.env.example`: placeholder lines for every env var.
- [ ] Test `test_health.py`: `TestClient(app).get("/healthz")` → 200 `{"ok": True}`.
- [ ] Run `pytest reminders/tests/test_health.py -v` → PASS. Commit.

---

### Task 2: SQLite data layer

**Files:**
- Create: `reminders/app/db.py`
- Test: `reminders/tests/test_db.py`

**Interfaces:**
- Produces:
  - `init_db(path: Path) -> None` — creates tables/indexes (idempotent).
  - `upsert_pending(conn, sub: SubscriberInput, ip: str) -> str` — insert/refresh a row as `pending`, returns the `confirm_token`. Re-subscribing the same email replaces prefs and issues a new confirm token.
  - `confirm(conn, token: str) -> bool` — set `active` if token valid + unexpired; returns success.
  - `unsubscribe(conn, token: str) -> bool` — set `unsubscribed`.
  - `active_subscribers(conn) -> list[dict]` — rows in export shape.
  - `count_recent_events(conn, ip: str, event_type: str, within_minutes: int) -> int`.
  - `log_event(conn, ip: str, event_type: str) -> None`.
  - `new_token() -> str` (= `secrets.token_urlsafe(32)`).
- Consumes: `SubscriberInput` from Task 4 (define a minimal local TypedDict/dataclass first if built before Task 4, then align).

**Steps:**
- [ ] Write schema from the spec (subscribers + subscribe_events + indexes) in `init_db`.
- [ ] Implement the functions above; store `sessions`/`venues` as JSON text; timestamps ISO-8601 UTC.
- [ ] Tests: init creates tables; upsert→pending; confirm valid token→active, expired/invalid→False; unsubscribe; `active_subscribers` returns only active in export shape; event count window works.
- [ ] Run `pytest reminders/tests/test_db.py -v` → PASS. Commit.

---

### Task 3: Resend emailer (copy trader-koo pattern)

**Files:**
- Create: `reminders/app/emailer.py`
- Test: `reminders/tests/test_emailer.py`

**Interfaces:**
- Produces:
  - `send_email(to: str, subject: str, html: str, *, api_key: str, sender: str, list_unsubscribe_url: str | None = None, timeout: int = 30) -> None` — POSTs to `https://api.resend.com/emails` via `urllib`; raises `RuntimeError` on non-2xx. Adds `List-Unsubscribe` header when given.
  - `confirm_email_html(name, confirm_url, unsubscribe_url) -> str`
  - `alert_email_html(...)`, `expired_email_html(...)` — or reuse the existing builders in `send_table_for_two_alerts.py` (Task 7 wires those to Resend; this task only needs the confirm email).

**Steps:**
- [ ] Port `_send_resend_email` from `trader-koo/trader_koo/report/email_dispatch.py` (lines ~88–124): `urllib.request` POST, Bearer auth, JSON `{from, to, subject, html, headers}`.
- [ ] `confirm_email_html`: short branded HTML with the confirm button + unsubscribe footer.
- [ ] Test with a stubbed `urllib.request.urlopen` (monkeypatch): asserts URL, Bearer header, payload `from/to/subject`, and that non-2xx raises. No network.
- [ ] Run `pytest reminders/tests/test_emailer.py -v` → PASS. Commit.

---

### Task 4: Request schemas + validation

**Files:**
- Create: `reminders/app/schemas.py`, `reminders/app/venues.py`
- Test: `reminders/tests/test_schemas.py`

**Interfaces:**
- Produces:
  - `SubscribeRequest(BaseModel)`: `email: EmailStr`, `name: str | None`, `party_size: int` (1–20), `sessions: list[Literal["Lunch","Dinner"]]` (non-empty), `venues: list[str]` (non-empty; `["any"]` allowed), `date_start: date`, `date_end: date`, `website: str = ""` (honeypot — must be empty).
  - validators: `date_start <= date_end`; `date_start >= today`; `date_end <= today + 120d`; venues each in the known set or `any`.
  - `load_known_venues(data_path: Path) -> set[str]` — names from `data/table-for-two.json`.

**Steps:**
- [ ] Implement models + field validators (Pydantic v2 `field_validator`/`model_validator`).
- [ ] `venues.py`: load venue names/aliases from the committed `data/table-for-two.json`.
- [ ] Tests: valid payload passes; rejects bad email, party_size 0/21, empty sessions, unknown venue, past date_start, date_end before start, horizon > 120d, non-empty honeypot.
- [ ] Run `pytest reminders/tests/test_schemas.py -v` → PASS. Commit.

---

### Task 5: API endpoints (subscribe / confirm / unsubscribe / subscribers)

**Files:**
- Modify: `reminders/app/main.py`
- Create: `reminders/app/routes.py`
- Test: `reminders/tests/test_api.py`

**Interfaces:**
- Consumes: db (Task 2), emailer (Task 3), schemas (Task 4), config (Task 1).
- Produces endpoints:
  - `POST /api/subscribe` — validate `SubscribeRequest`; honeypot non-empty → 200 silent no-op; per-IP rate limit (>5 in 60 min → 429); `upsert_pending`; send confirm email; → `{"ok": true, "message": "Check your email to confirm."}`.
  - `GET /api/confirm?token=` — `confirm()`; HTML page "You're subscribed" or "Link expired".
  - `GET /api/unsubscribe?token=` — `unsubscribe()`; HTML page "You're unsubscribed".
  - `GET /api/subscribers` — require `Authorization: Bearer <ALERT_EXPORT_TOKEN>` (constant-time compare); → `{"subscriptions": [...]}` in the matcher's shape, each with `unsubscribe_url` built from `public_base_url`.

**Steps:**
- [ ] Implement routes; client IP from `X-Forwarded-For` first hop (Railway proxy) else `request.client.host`.
- [ ] Wire confirm/unsubscribe URLs off `settings.public_base_url`.
- [ ] Tests (TestClient, temp SQLite, stubbed emailer): happy path subscribe→pending + email sent once; honeypot silent; rate limit 6th→429; confirm activates and appears in `/api/subscribers` (with valid token); wrong/no token→401/403; unsubscribe removes from export.
- [ ] Run `pytest reminders/tests/test_api.py -v` → PASS. Commit.

---

### Task 6: Native signup form on the site (replace Google Form link)

**Files:**
- Modify: `web/index.html` (`#tft-alert-signup-panel`, ~892–898)
- Modify: `web/app.js` (`tableForTwoAlertSignupPanel/Link` ~859–860, signup wiring ~4163–4166)
- Modify: `web/styles.css` (form styles, dark theme)

**Interfaces:**
- Consumes: `POST {REMINDERS_API}/api/subscribe`. Add a `REMINDERS_API_BASE` const in `app.js`.

**Steps:**
- [ ] Replace the "Create alert" `<a>` with an inline `<form>`: email, name (optional), party size (number), session checkboxes (Lunch/Dinner), venue multi-select (+ "Any venue"), date_start/date_end (`<input type="date">`), hidden honeypot `website` field, submit button, status `<p aria-live="polite">`.
- [ ] `app.js`: on submit, `fetch` POST JSON; show success ("Check your email to confirm.") / error; basic client validation mirrors server (native `required`, `min`/`max`).
- [ ] Remove `alert_signup_url`-driven link logic; keep the panel always visible (no longer gated on a signup URL).
- [ ] Style to match the existing `tft-alert-panel` aesthetic.
- [ ] Manual verify: form renders, posts to a locally-running service, success message shows. Commit.

---

### Task 7: Rewire the alert job (subscribers from API + Resend; drop SMTP/CSV)

**Files:**
- Modify: `scripts/send_table_for_two_alerts.py`
- Modify: `.github/workflows/table-for-two-alerts.yml`
- Test: `scripts/tests/test_alert_subscriber_source.py` (or inline `demo()` self-check)

**Interfaces:**
- Consumes: `GET /api/subscribers` (Bearer `ALERT_EXPORT_TOKEN`) → matcher subscription shape.

**Steps:**
- [ ] Add `fetch_api_subscriptions(base_url, token) -> list[dict]`; feed into existing `subscription_from_row`. Source priority: API when `REMINDERS_API_BASE` set, else local JSON.
- [ ] Replace `send_messages` SMTP body with the Resend `send_email` helper (share the Task 3 function or duplicate minimally). Remove `smtplib`/`ssl`/`smtp_config_from_env`.
- [ ] Remove `--subscriptions-csv-url` / `TABLE_FOR_TWO_ALERTS_CSV_URL` usage.
- [ ] Workflow: drop all `SMTP_*` + CSV env; add `REMINDERS_API_BASE`, `ALERT_EXPORT_TOKEN`, `RESEND_API_KEY`, `RESEND_FROM`. Update the "Check alert configuration" gate accordingly.
- [ ] Test: stub the API fetch + Resend send; assert subscriptions parse and an alert email is built+"sent". Run → PASS. Commit.

---

### Task 8: Deploy to Railway + Resend key + smoke test

**Files:** none (infra). Possibly `reminders/README.md` deploy notes.

**Steps (some require the user — flagged):**
- [ ] **User:** Resend dashboard → API Keys → create `amex-reminders` key. Provide it (set via CLI, not echoed).
- [ ] `railway init`/link a new service with root `reminders/`; add a persistent volume mounted at `/data`.
- [ ] Set Railway vars: `DB_PATH=/data/reminders.db`, `RESEND_API_KEY`, `RESEND_FROM=dinnertime@kooexperience.com`, `ALERT_EXPORT_TOKEN` (reuse existing secret value or rotate), `ALLOWED_ORIGIN=https://amex-explorer.kooexperience.com`, `PUBLIC_BASE_URL=<service URL>`, `CONFIRM_TOKEN_EXPIRY_HOURS=168`.
- [ ] Deploy; hit `/healthz`; do a real subscribe→confirm email round trip to your own address.
- [ ] Put `REMINDERS_API_BASE` + `RESEND_API_KEY`/`RESEND_FROM`/`ALERT_EXPORT_TOKEN` into GitHub Actions secrets; point the frontend `REMINDERS_API_BASE` at the service URL.
- [ ] Trigger the alert workflow; confirm green + a test alert delivers.

---

### Task 9: Remove dead old-system code + secrets cleanup

**Files:**
- Modify: `web/index.html`, `web/app.js` (any remaining `alert_signup_url`)
- Modify: `scripts/scrape_table_for_two.py` if it injects `alert_signup_url` into `data/table-for-two.json`
- Delete: `data/table-for-two-alerts.example.json` (CSV/JSON-source artifact, if fully unused)

**Steps:**
- [ ] `grep -rn "alert_signup_url\|SIGNUP_URL\|CSV_URL\|smtplib\|SMTP_" web/ scripts/` → zero functional hits remain.
- [ ] Remove the now-unused GitHub `SMTP_*` and `TABLE_FOR_TWO_ALERTS_CSV_URL` secrets (CLI).
- [ ] Update `CLAUDE.md` Table for Two / alerts section to describe the new flow.
- [ ] Commit. Open PR.

---

## Self-Review

- **Spec coverage:** form (T6), DB (T2), double opt-in (T2/T5), validation+security (T4/T5), Resend (T3/T7), export endpoint (T5), alert rewire (T7), remove dead code (T9), Railway/SQLite deploy (T8), unsubscribe (T2/T5/T6). All spec sections covered.
- **Placeholders:** none — each task has concrete files, interfaces, and test cases.
- **Type consistency:** subscription export shape (`email, name, party_size, sessions[], venues[], date_start, date_end, unsubscribe_url`) is identical across T2, T5, T7 and matches the existing matcher.
