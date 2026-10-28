# CLAUDE.md — amex-dining-map

## Agent docs
- Issues: GitHub Issues via `gh`; external PRs are not a triage surface. See `docs/agents/issue-tracker.md`.
- Labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.
- Domain: single context. See `docs/agents/domain.md`.

## Tests
- Python: `reminders/.venv/bin/python -m pytest scripts/tests -q` (needs `reminders/requirements-dev.txt`, as in CI; system python3 lacks pypdf)
- Reminders: `python3 -m pytest reminders/tests -q` (local venv `reminders/.venv`, Python 3.11–3.13; Railway runs 3.12)
- JS: `for f in scripts/tests/*.js; do node "$f"; done`
- Verifiers: `node scripts/verify-project.mjs` (needs `uv`; CI passes `--static-only` to skip the suite re-runs). `verify-tft-browser-evidence.mjs` probes production and stays manual.
- The `Tests` workflow runs all of these on PRs and main. It is not a deploy gate.

## Deploys
- Site: GitHub Pages via `Deploy Pages`, on push to main and after each data workflow completes. It skips when main is already live.
- Reminders service (`reminders/`, Railway project `amex-reminders`) does NOT auto-deploy. Manual: `railway up reminders --path-as-root --detach --service amex-reminders --json` from repo root, then confirm `/healthz` reports the new `deployment_id`. Full checklist in `reminders/README.md`.
- `Table for Two Alerts` and the refresh workflows run from main, so script changes take effect only after merge.
- Data workflows commit to main themselves (`chore: update source health`, etc.). Pull before branching.

## Gotchas
- Never put assertions about live data values in `Deploy Pages`. A ratings-projection check once blocked 22 deploys and left the site stale for two days. Data-shaped checks go in `Tests`.
- GitHub cron drops most 15-minute runs. The reminders service dispatches `Table for Two Alerts` itself when `GITHUB_DISPATCH_TOKEN` is set (`/healthz` shows `alert_dispatch_enabled`).
- The alert job reads live slots from the service's `/api/tft/slots` and fails if they are over 30 minutes old.
- `review_required` in `data/source-health.json` is a human review flag, not staleness. The watchdog ignores it.
- Watchdog dry run: `python3 scripts/watchdog_stale_sources.py --dry-run`.
- Japan Tabelog run order: `match_tabelog_candidates.py` → `retry_rejects_cached.py` → `promote_tabelog_matches.py` → `merge_restaurant_quality_signals.py`. Always run the cache-first retry; browse-only matching leaves most rejects unsearched.
- Tabelog phone placeholders (`不明…`) normalise to `81` and fake a `phone_conflict`. Romanisation variants (Marunochi/Marunouchi) fake `district_mismatch`.
- `scripts/scrape_google_ratings_playwright.py`: use `--missing-only` for incremental or concurrent runs.

## Safety
- Never commit `.env`. Env vars: `GROQ_API_KEY`, `MICHELIN_ALGOLIA_APP_ID`, `MICHELIN_ALGOLIA_API_KEY` (public read-only Algolia keys from guide.michelin.com; requests need a `Referer: guide.michelin.com` header).
- The local pre-commit hook rejects added lines containing a key name followed by `=` (Groq, Michelin, MapTiler), placeholders included. Name env vars in docs without `=`.
- Do not delete these caches: `data/tabelog-match-http-cache.json`, `data/tabelog-url-cache.json`, `data/tabelog-match-results.json`, `data/geocode_cache.json`, `data/venue_detail_cache.json`. Several are gitignored and exist only locally.
- Reminders and alert secrets live in Railway and GitHub Actions. See `reminders/.env.example` for names.
