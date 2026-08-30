# Security audit — 30 August 2026

Scope: the public static explorer, data-driven rendering, GitHub Actions, the Railway FastAPI/SQLite reminder service, dependencies, live response controls, secrets handling, abuse paths, and the planned Telegram ingress.

## Outcome

No secret was detected across 1,854 commits and approximately 738 MB of Git history. The live subscriber export rejected unauthenticated access, production CORS accepted only the Explorer origin, SQL statements use bound parameters, and confirmation tokens use cryptographically secure randomness.

Two high-risk paths were found and remediated in the pending code:

1. Manual GitHub Action inputs could reach shell execution through direct interpolation and `eval` in a job with repository write access and a Groq secret.
2. A spoofable forwarded-IP-only limit allowed repeated confirmation email abuse, while re-subscribing a known active address replaced its preferences and disabled alerts until reconfirmation.

The security gate is not production-complete until this revision is deployed and the live checks below are repeated.

## Findings and disposition

| Severity | Finding | Disposition |
| --- | --- | --- |
| High | Workflow-dispatch shell injection | Removed `eval`, moved inputs through environment variables, validated allowed shapes, and used argument arrays. |
| High | Spoofable email abuse and active-subscriber reset | Added atomic keyed-hash IP, email, and global quotas; used the trusted proxy hop rather than the attacker-controlled prefix; preserved active settings in a separate pending change until confirmation. |
| Medium | Confirmation and unsubscribe changed state on GET | GET now renders an explicit action page; POST performs the state change. The unsubscribe POST also supports email-provider one-click requests. |
| Medium | User name injected into trusted-sender HTML email | Escaped body and attribute values and added a malicious-name regression test. |
| Medium | One long-lived token controlled manage and unsubscribe | New subscriptions receive distinct management and unsubscribe capabilities; token pages are no-store and no-referrer. Existing delivered links remain compatible after migration, so legacy rows retain a shared capability until a user-confirmed rotation path exists. Plaintext capability storage also remains a future hardening opportunity. |
| Medium | Token/PII pages lacked response controls | Added CSP, HSTS, no-store, no-referrer, nosniff, frame denial, and permissions policy middleware; disabled public OpenAPI output. |
| Medium | Unbounded request and list parsing | Added a 16 KiB API-body limit and explicit list/string cardinality limits. |
| Medium | Raw IPs and expired records retained indefinitely; DB mode could be 0644 | Abuse identifiers are now keyed hashes, old events and expired pending records are purged, unsubscribed records have a retention window, confirmed rows discard the source identifier, and the SQLite file is forced to mode 0600. |
| Medium | Dynamic URLs were escaped but their protocols were not constrained | Added a DOM URL policy that removes unsafe protocols from dynamically rendered links and images, plus negative controls for `javascript:`, `data:`, and insecure remote HTTP. |
| Medium | CDN scripts lacked integrity and the static page lacked CSP | Added SRI/crossorigin attributes and a restrictive CSP/referrer meta policy. Edge-level frame and permissions headers remain recommended because GitHub Pages cannot express them in repository content. |
| Medium | Movable action tags, unrestricted Actions, no security updates | Pinned every action referenced by this repository to an immutable commit, restricted the repository to GitHub-owned actions, enabled dependency security updates, and added weekly pip/Actions Dependabot checks. Repository-wide SHA enforcement cannot remain enabled because GitHub's own Pages artifact action currently calls a transitive action by version tag; the local workflow pins remain enforced by review and verification. |
| Medium | Resolved Starlette 0.41.3 had known advisories | Upgraded FastAPI, Starlette through its resolved dependency, Uvicorn, Pydantic, and pytest; a fresh resolved-tree audit reports no known vulnerability. |
| Medium | Main has no branch protection | Residual. Scheduled data workflows currently commit directly to main, so protection needs a designed automation bypass or PR-based refresh path before enabling it. |
| Low | Runtime-installed Playwright was unpinned | Pinned the workflow installation to a reviewed version. A hashed Python lock remains desirable. |

## Telegram threat model

Before enabling the bot:

- Verify Telegram's webhook secret header with constant-time comparison.
- Deduplicate every update ID before side effects.
- Use numeric owner user and channel IDs, never usernames, for privileged delivery.
- Accept public v1 usage only in private chats; ignore group and channel commands.
- Keep the bot token, webhook secret, owner IDs, and ingestion token only in deployment secrets.
- Apply per-user and global limits, bounded input/output, expiring conversation state, and idempotent delivery keys.
- Treat official document and menu text as untrusted evidence, not instructions.
- Never fetch a user-supplied URL or give an optional language model credentials, network tools, subscriber exports, or delivery authority.
- Escape Telegram formatting and allow citations only through reviewed URL policies.
- Store minimal Telegram identifiers and provide deletion and retention behavior.
- “Find a slot” reads cached AMEXPlatSG observations only; it never books, handles Amex credentials, or guarantees inventory.

## Verification evidence

- Baseline reminder suite before changes: 40 passed on Python 3.12.
- Hardened reminder suite: 47 passed on Python 3.12.
- Updated fully resolved production dependency audit: no known vulnerabilities.
- Frontend syntax and all JavaScript regression scripts pass, including unsafe-protocol negative controls.
- Live pre-deployment evidence: static HTTPS/HSTS/nosniff present; reminder CORS restricted correctly; subscriber export returned 401 without credentials; reminder responses lacked security headers before this change.

## Required production recheck

After deployment, repeat:

1. valid and hostile-origin CORS requests;
2. spoofed forwarded-chain and repeated-email rate tests with non-delivery fixtures;
3. active-user re-subscribe preservation;
4. GET versus POST confirmation/unsubscribe behavior;
5. cache, referrer, CSP, HSTS, frame, and content-type headers;
6. mobile TFT signup, VUE detail, menus, T&Cs, release qualification, and observed-slot wording;
7. resolved dependency and GitHub security-setting inspection.
