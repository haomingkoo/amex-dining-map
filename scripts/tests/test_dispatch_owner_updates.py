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


INGEST_URL = "https://alerts.example.test/api/owner-alerts/events"
BATCH_URL = "https://alerts.example.test/api/owner-alerts/batch"


class BatchResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return json.dumps(self.payload).encode()


def _fake_batch(monkeypatch, results):
    requests = []

    def fake_open(request, timeout):
        requests.append((request, timeout))
        return BatchResponse({"ok": True, "results": results, "message_count": 1})

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_open)
    return requests


def test_batch_url_replaces_events_suffix():
    assert MODULE.batch_url(INGEST_URL) == BATCH_URL


@pytest.mark.parametrize(
    "url",
    [
        "https://alerts.example.test/api/owner-alerts/event",
        "https://alerts.example.test/events",
        "https://alerts.example.test/api/owner-alerts/events/",
    ],
)
def test_batch_url_fails_closed_for_unexpected_ingest_url(url):
    with pytest.raises(RuntimeError, match="must end with /api/owner-alerts/events"):
        MODULE.batch_url(url)


def test_dispatch_posts_all_events_in_one_request(monkeypatch):
    requests = _fake_batch(
        monkeypatch,
        [
            {"id": "one", "state": "sent"},
            {"id": "two", "state": "before_activation"},
            {"id": "three", "state": "withheld"},
        ],
    )

    outcomes = {}
    assert MODULE.dispatch(
        INGEST_URL,
        "x" * 43,
        [{"id": "one"}, {"id": "two"}, {"id": "three"}],
        outcomes,
    ) == 3
    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url == BATCH_URL
    assert request.get_header("Authorization") == "Bearer " + "x" * 43
    assert json.loads(request.data) == {
        "events": [{"id": "one"}, {"id": "two"}, {"id": "three"}]
    }
    assert timeout == 30
    assert outcomes == {"one": "sent", "two": "before_activation", "three": "withheld"}


def test_dispatch_skips_request_when_nothing_selected(monkeypatch):
    requests = _fake_batch(monkeypatch, [])
    assert MODULE.dispatch(INGEST_URL, "x" * 43, [], {}) == 0
    assert requests == []


def test_dispatch_chunks_beyond_service_batch_limit(monkeypatch):
    requests = []

    def fake_open(request, timeout):
        requests.append(request)
        ids = [event["id"] for event in json.loads(request.data)["events"]]
        return BatchResponse(
            {"ok": True, "results": [{"id": i, "state": "sent"} for i in ids]}
        )

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_open)
    events = [{"id": f"event-{i}"} for i in range(501)]

    assert MODULE.dispatch(INGEST_URL, "x" * 43, events, {}) == 501
    assert [len(json.loads(r.data)["events"]) for r in requests] == [500, 1]


@pytest.mark.parametrize("state", ["retry", "sending", "conflict"])
def test_dispatch_fails_loudly_for_non_terminal_state(monkeypatch, state):
    _fake_batch(
        monkeypatch,
        [{"id": "one", "state": "sent"}, {"id": "two", "state": state}],
    )

    outcomes = {}
    with pytest.raises(RuntimeError, match=f"two:{state}"):
        MODULE.dispatch(INGEST_URL, "x" * 43, [{"id": "one"}, {"id": "two"}], outcomes)
    assert outcomes == {"one": "sent"}


def test_dispatch_fails_loudly_for_missing_result(monkeypatch):
    _fake_batch(monkeypatch, [{"id": "one", "state": "sent"}])

    with pytest.raises(RuntimeError, match="two:missing"):
        MODULE.dispatch(INGEST_URL, "x" * 43, [{"id": "one"}, {"id": "two"}], {})


@pytest.mark.parametrize("state", ["unknown", "dead"])
def test_dispatch_quarantines_terminal_state_without_sticking_workflow(
    monkeypatch, capsys, state
):
    _fake_batch(
        monkeypatch,
        [{"id": "one", "state": state, "error_code": "telegram_terminal"}],
    )

    outcomes = {}
    assert MODULE.dispatch(INGEST_URL, "x" * 43, [{"id": "one"}], outcomes) == 1
    assert "::warning title=Owner alert quarantined::one" in capsys.readouterr().err
    assert outcomes == {"one": state}


def test_dispatch_quarantines_schema_rejection_and_continues(monkeypatch, capsys):
    _fake_batch(
        monkeypatch,
        [{"id": "broken", "state": "schema_rejected"}, {"id": "valid", "state": "sent"}],
    )

    outcomes = {}
    assert MODULE.dispatch(
        INGEST_URL, "x" * 43, [{"id": "broken"}, {"id": "valid"}], outcomes
    ) == 2
    assert "::warning title=Owner alert schema rejected::broken" in capsys.readouterr().err
    assert outcomes == {"broken": "schema_rejected", "valid": "sent"}


def test_dispatch_explains_missing_digest_deploy(monkeypatch):
    def not_found(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO())

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", not_found)

    with pytest.raises(RuntimeError, match="needs the owner-alert digest deploy"):
        MODULE.dispatch(INGEST_URL, "x" * 43, [{"id": "one"}], {})


def test_dispatch_rejects_unacknowledged_batch(monkeypatch):
    monkeypatch.setattr(
        MODULE.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: BatchResponse({"ok": False}),
    )

    with pytest.raises(RuntimeError, match="did not acknowledge"):
        MODULE.dispatch(INGEST_URL, "x" * 43, [{"id": "one"}], {})


def test_main_records_terminal_states_into_ledger(tmp_path: Path, monkeypatch):
    path = tmp_path / "updates.json"
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    updates = [
        {"id": "sent-one", "status": "published", "kind": "added", "detected_at": now},
        {"id": "retry-one", "status": "published", "kind": "removed", "detected_at": now},
        {"id": "noise", "status": "published", "kind": "source_stale", "detected_at": now},
    ]
    path.write_text(json.dumps({"schema_version": 1, "updates": updates}))
    requests = _fake_batch(
        monkeypatch,
        [{"id": "sent-one", "state": "sent"}, {"id": "retry-one", "state": "retry"}],
    )
    monkeypatch.setenv("OWNER_ALERT_INGEST_URL", INGEST_URL)
    monkeypatch.setenv("OWNER_ALERT_INGEST_TOKEN", "x" * 43)
    monkeypatch.setattr(MODULE.sys, "argv", ["dispatch", "--updates", str(path)])

    with pytest.raises(RuntimeError, match="retry-one:retry"):
        MODULE.main()

    assert len(requests) == 1
    stored = {e["id"]: e.get("owner_delivery_state") for e in json.loads(path.read_text())["updates"]}
    assert stored == {"sent-one": "sent", "retry-one": None, "noise": "withheld"}


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
