from __future__ import annotations

import asyncio
import io
import json
import urllib.error

import pytest

from app import alert_dispatch, main


class Response:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_dispatch_posts_main_ref_to_the_alerts_workflow():
    seen = {}

    def opener(request, timeout):
        seen.update(url=request.full_url, body=json.loads(request.data), auth=request.headers["Authorization"])
        return Response()

    status = alert_dispatch.dispatch("tok", "owner/repo", opener)

    assert status == 204
    assert seen == {
        "url": "https://api.github.com/repos/owner/repo/actions/workflows/table-for-two-alerts.yml/dispatches",
        "body": {"ref": "main"},
        "auth": "Bearer tok",
    }


def test_rejected_dispatch_is_recorded_not_raised():
    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO())

    alert_dispatch.dispatch_and_record("bad", "owner/repo", opener)

    assert (alert_dispatch.last_dispatch["status"], alert_dispatch.last_dispatch["error"]) == (401, "http_error")


def test_dispatch_loop_runs_then_waits_the_interval():
    events: list[object] = []

    async def fake_to_thread(call, *args):
        events.append(("thread", call, args))

    async def fake_sleep(seconds):
        events.append(("sleep", seconds))
        raise asyncio.CancelledError

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await main.run_periodically(
                900, alert_dispatch.dispatch_and_record, "tok", "owner/repo", to_thread=fake_to_thread, sleep=fake_sleep
            )

    asyncio.run(scenario())

    assert events == [("thread", alert_dispatch.dispatch_and_record, ("tok", "owner/repo")), ("sleep", 900)]
