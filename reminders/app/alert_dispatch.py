"""Trigger the Table for Two Alerts workflow; GitHub's own cron drops most runs."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
ALERT_WORKFLOW = "table-for-two-alerts.yml"
# Matches the workflow's intended "every 15 minutes" cron.
DISPATCH_INTERVAL_SECONDS = 900
REQUEST_TIMEOUT_SECONDS = 10
HTTP_NO_CONTENT = 204

last_dispatch: dict[str, str | int | None] = {"at": None, "status": None, "error": None}


def dispatch(token: str, repo: str, opener: Callable = urllib.request.urlopen) -> int:
    request = urllib.request.Request(
        f"{GITHUB_API}/repos/{repo}/actions/workflows/{ALERT_WORKFLOW}/dispatches",
        data=json.dumps({"ref": "main"}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.status


def dispatch_and_record(token: str, repo: str, opener: Callable = urllib.request.urlopen) -> None:
    """Dispatch once and keep the outcome for /healthz; a failure is logged, never raised."""
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        status = dispatch(token, repo, opener)
        last_dispatch.update(at=at, status=status, error=None)
        if status != HTTP_NO_CONTENT:
            logger.warning("alert_dispatch unexpected_status=%s", status)
    except urllib.error.HTTPError as exc:
        last_dispatch.update(at=at, status=exc.code, error="http_error")
        logger.warning("alert_dispatch failed status=%s", exc.code)
    except (urllib.error.URLError, TimeoutError) as exc:
        last_dispatch.update(at=at, status=None, error="network_error")
        logger.warning("alert_dispatch failed error=%s", type(exc).__name__)
