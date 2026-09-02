from __future__ import annotations

import importlib.util
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import urllib.error


MODULE_PATH = Path(__file__).resolve().parents[1] / "dispatch_owner_updates.py"
SPEC = importlib.util.spec_from_file_location("dispatch_owner_updates", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def test_published_events_replays_recent_and_excludes_review_queue(tmp_path: Path):
    path = tmp_path / "updates.json"
    path.write_text(
        json.dumps(
            {
                "updates": [
                    {
                        "id": "published",
                        "status": "published",
                        "detected_at": "2026-08-29T00:00:00Z",
                    },
                    {
                        "id": "review",
                        "status": "review_required",
                        "detected_at": "2026-08-29T00:00:00Z",
                    },
                    {
                        "id": "retracted",
                        "status": "retracted",
                        "detected_at": "2026-08-29T00:00:00Z",
                    },
                    {
                        "id": "old",
                        "status": "published",
                        "detected_at": "2026-04-01T00:00:00Z",
                    },
                    {
                        "id": "already-sent",
                        "status": "published",
                        "detected_at": "2026-08-29T00:00:00Z",
                        "owner_delivery_state": "sent",
                    },
                ]
            }
        )
    )

    assert MODULE.published_events(path, now=NOW) == [
        {
            "id": "published",
            "status": "published",
            "detected_at": "2026-08-29T00:00:00Z",
        }
    ]


@pytest.mark.parametrize(
    "state", sorted(MODULE.source_change_alert.TERMINAL_OWNER_DELIVERY_STATES)
)
def test_published_events_does_not_retry_terminal_receipts(tmp_path: Path, state: str):
    path = tmp_path / "updates.json"
    path.write_text(
        json.dumps(
            {
                "updates": [
                    {
                        "id": "terminal",
                        "status": "published",
                        "detected_at": "2026-08-29T00:00:00Z",
                        "owner_delivery_state": state,
                    }
                ]
            }
        )
    )

    assert MODULE.published_events(path, now=NOW) == []


def test_review_timestamp_promotes_an_older_event_into_replay_window(tmp_path: Path):
    current = tmp_path / "updates.json"
    current.write_text(
        json.dumps(
            {
                "updates": [
                    {
                        "id": "promoted",
                        "status": "published",
                        "detected_at": "2026-04-01T00:00:00Z",
                        "reviewed_at": "2026-08-29T00:00:00Z",
                    }
                ]
            }
        )
    )

    assert [event["id"] for event in MODULE.published_events(current, now=NOW)] == [
        "promoted"
    ]


def test_owner_notification_policy_keeps_changes_and_suppresses_health_flapping():
    events = [
        {"id": "venue-added", "kind": "added"},
        {"id": "menu-updated", "kind": "menu_updated"},
        {"id": "source-failed", "kind": "source_failed"},
        {"id": "review-required", "kind": "source_review_required"},
        {"id": "source-updated", "kind": "source_updated"},
        {"id": "terms", "kind": "terms_clause_modified"},
        {"id": "faq", "kind": "faq_clause_added"},
        {"id": "source-stale", "kind": "source_stale"},
        {"id": "source-recovered", "kind": "source_recovered"},
        {"id": "source-health", "kind": "source_health_changed"},
    ]

    selected, withheld = MODULE.select_owner_notifications(events)

    assert [event["id"] for event in selected] == [
        "venue-added",
        "menu-updated",
        "source-failed",
        "review-required",
        "source-updated",
        "terms",
        "faq",
    ]
    assert withheld == {
        "source-stale": "withheld",
        "source-recovered": "withheld",
        "source-health": "withheld",
    }


def test_owner_notification_policy_fails_visible_for_unknown_kind():
    with pytest.raises(RuntimeError, match="Unknown published owner event kind"):
        MODULE.select_owner_notifications([{"id": "future", "kind": "new_kind"}])


def test_invalid_published_timestamp_fails_closed(tmp_path: Path):
    path = tmp_path / "updates.json"
    path.write_text(
        json.dumps(
            {
                "updates": [
                    {
                        "id": "broken",
                        "status": "published",
                        "detected_at": "not-a-date",
                    }
                ]
            }
        )
    )

    with pytest.raises(RuntimeError, match="invalid timestamp"):
        MODULE.published_events(path, now=NOW)


def test_dispatch_posts_one_event_and_accepts_terminal_state(monkeypatch):
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return b'{"ok": true, "state": "sent"}'

    def fake_open(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_open)

    outcomes = {}
    assert MODULE.dispatch(
        "https://alerts.example.test/events", "x" * 32, [{"id": "one"}], outcomes
    ) == 1
    assert json.loads(requests[0][0].data) == {"event": {"id": "one"}}
    assert requests[0][1] == 15
    assert outcomes == {"one": "sent"}


def test_dispatch_fails_loudly_for_retry_state(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return b'{"ok": true, "state": "retry"}'

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())

    with pytest.raises(RuntimeError, match="one:retry"):
        MODULE.dispatch("https://alerts.example.test/events", "x" * 32, [{"id": "one"}])


@pytest.mark.parametrize("state", ["unknown", "dead"])
def test_dispatch_quarantines_terminal_state_without_sticking_workflow(
    monkeypatch, capsys, state
):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return json.dumps(
                {"ok": True, "state": state, "error_code": "telegram_terminal"}
            ).encode()

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())

    assert MODULE.dispatch(
        "https://alerts.example.test/events", "x" * 32, [{"id": "one"}]
    ) == 1
    assert "::warning title=Owner alert quarantined::one" in capsys.readouterr().err


def test_dispatch_quarantines_schema_rejection_and_continues(monkeypatch, capsys):
    calls = 0

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return b'{"ok": true, "state": "sent"}'

    def fake_open(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                request.full_url, 422, "Unprocessable Entity", {}, io.BytesIO()
            )
        return Response()

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_open)

    outcomes = {}
    assert MODULE.dispatch(
        "https://alerts.example.test/events",
        "x" * 43,
        [{"id": "broken"}, {"id": "valid"}],
        outcomes,
    ) == 2
    assert calls == 2
    assert "::warning title=Owner alert schema rejected::broken" in capsys.readouterr().err
    assert outcomes == {"broken": "schema_rejected", "valid": "sent"}


def test_delivery_receipts_are_persisted_without_changing_transition_identity(
    tmp_path: Path,
):
    path = tmp_path / "updates.json"
    event = {
        "id": "event-12345678",
        "transition_id": "a" * 20,
        "stream_id": "b" * 20,
        "occurrence": 1,
        "program": "Table for Two",
        "program_id": "table-for-two",
        "route": "#/table-for-two",
        "kind": "details_updated",
        "subject": "VUE",
        "detected_at": "2026-08-30T00:00:00Z",
        "status": "published",
        "before": {"state": "listed", "fields": {"Address": "A"}},
        "after": {"state": "listed", "fields": {"Address": "B"}},
        "changes": [{"field": "Address", "before": "A", "after": "B"}],
        "source_url": "https://www.americanexpress.com/example",
    }
    path.write_text(json.dumps({"schema_version": 1, "updates": [event]}))
    before = MODULE.source_change_alert.update_event_id(event)

    assert MODULE.source_change_alert.record_owner_delivery_states(
        path, {event["id"]: "sent"}, "2026-08-30T01:00:00Z"
    ) == 1
    stored = json.loads(path.read_text())["updates"][0]

    assert stored["owner_delivery_state"] == "sent"
    assert stored["owner_delivery_recorded_at"] == "2026-08-30T01:00:00Z"
    assert MODULE.source_change_alert.update_event_id(stored) == before
