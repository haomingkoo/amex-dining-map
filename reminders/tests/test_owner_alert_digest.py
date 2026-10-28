from __future__ import annotations

import io
import json
import logging
import urllib.error
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, owner_alert_store, telegram
from app.main import app
from app.owner_alert_routes import get_settings
from app.owner_alerts import OwnerAlertEvent, format_owner_digest
from app.telegram import TelegramDeliveryError
from tests.test_owner_alerts import TOKEN, _event, _settings, owner_client  # noqa: F401


EXPLORER = "https://amex-explorer.kooexperience.com"
PROGRAMS = [
    ("Japan Dining", "japan-dining", "#/japan"),
    ("Table for Two", "table-for-two", "#/table-for-two"),
    ("Global Dining", "global-dining", "#/global"),
    ("Explorer ratings", "explorer-ratings", "#/ratings"),
    ("Love Dining", "love-dining", "#/love-dining"),
    ("Plat Stay", "plat-stay", "#/stays"),
]


def _program_event(index: int, program: tuple[str, str, str], kind: str, subject: str) -> dict:
    event = _event(event_id=f"event-batch-{index:06d}")
    event.update(
        program=program[0],
        program_id=program[1],
        route=program[2],
        kind=kind,
        subject=subject,
    )
    return event


def _post_batch(client: TestClient, events: list, token: str = TOKEN):
    return client.post(
        "/api/owner-alerts/batch",
        json={"events": events},
        headers={"Authorization": f"Bearer {token}"},
    )


def _record_sends(monkeypatch, message_id: int = 501) -> list:
    calls = []

    def fake_send(bot_token, chat_id, text):
        calls.append((bot_token, chat_id, text))
        return message_id

    monkeypatch.setattr("app.owner_alert_routes.telegram.send_message", fake_send)
    return calls


def _states(response) -> dict[str, str]:
    return {item["id"]: item["state"] for item in response.json()["results"]}


def test_published_batch_sends_exactly_one_message(owner_client, monkeypatch):
    client, settings = owner_client
    calls = _record_sends(monkeypatch)
    events = [
        _program_event(i, PROGRAMS[i % 3], "added", f"Venue {i}") for i in range(12)
    ]

    response = _post_batch(client, events)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["message_count"] == 1
    assert set(_states(response).values()) == {"sent"}
    assert len(calls) == 1
    assert calls[0][1] == settings.telegram_owner_chat_id
    conn = db.connect(settings.db_path)
    try:
        rows = [
            owner_alert_store.get(conn, event["id"], settings.telegram_owner_chat_id)
            for event in events
        ]
    finally:
        conn.close()
    assert {row["state"] for row in rows} == {"sent"}
    assert {row["telegram_message_id"] for row in rows} == {501}


def test_digest_groups_by_program_with_counts_and_caps_items():
    raw = [
        _program_event(i, PROGRAMS[0], "added", f"Sushi {i}") for i in range(4)
    ] + [
        _program_event(10 + i, PROGRAMS[0], "removed", f"Gone {i}") for i in range(2)
    ] + [
        _program_event(20 + i, PROGRAMS[0], "details_updated", f"Changed {i}")
        for i in range(3)
    ] + [_program_event(30, PROGRAMS[5], "added", "Mandai")]
    events = [OwnerAlertEvent.model_validate(event) for event in raw]

    message = format_owner_digest(events, EXPLORER)

    assert message.splitlines()[0] == "Amex Explorer updates · 10 changes"
    assert "Japan Dining · 4 added, 2 removed, 3 details updated" in message
    assert "Plat Stay · 1 added" in message
    japan = message.split("Japan Dining ·")[1].split("Plat Stay ·")[0]
    item_lines = [line for line in japan.splitlines() if line[:2] in {"+ ", "− ", "~ "}]
    assert len(item_lines) == 5
    assert "…and 4 more" in japan
    assert "+ Sushi 0" in japan
    assert "− Gone 0" in japan
    assert f"Explorer: {EXPLORER}/#/japan" in japan
    assert "~ Changed" not in japan
    assert f"Explorer: {EXPLORER}/#/stays" in message
    assert "Before:" not in message


def test_digest_updates_list_changed_fields():
    raw = _program_event(1, PROGRAMS[1], "details_updated", "VUE")
    raw["changes"] = [
        {"field": "Address", "before": "A", "after": "B"},
        {"field": "Phone", "before": "1", "after": "2"},
    ]
    message = format_owner_digest([OwnerAlertEvent.model_validate(raw)], EXPLORER)

    assert "~ VUE: Address, Phone" in message
    assert message.splitlines()[0] == "Amex Explorer updates · 1 change"


def test_digest_stays_under_telegram_limit_for_huge_batches():
    kinds = ["added", "removed", "details_updated", "source_updated", "renamed"]
    raw = [
        _program_event(i, PROGRAMS[i % len(PROGRAMS)], kinds[i % len(kinds)], "S" * 500)
        for i in range(500)
    ]
    events = [OwnerAlertEvent.model_validate(event) for event in raw]

    message = format_owner_digest(events, EXPLORER)

    assert len(message) < 4000
    assert message.splitlines()[0] == "Amex Explorer updates · 500 changes"
    for name, _program_id, route in PROGRAMS:
        assert f"{name} · " in message
        assert f"Explorer: {EXPLORER}/{route}" in message


def test_replayed_batch_sends_nothing_and_reports_sent(owner_client, monkeypatch):
    client, _settings_value = owner_client
    calls = _record_sends(monkeypatch)
    events = [_program_event(i, PROGRAMS[0], "added", f"Venue {i}") for i in range(3)]

    _post_batch(client, events)
    replay = _post_batch(client, events)

    assert len(calls) == 1
    assert set(_states(replay).values()) == {"sent"}
    assert replay.json()["message_count"] == 0


def test_rate_limit_marks_all_retry_and_later_batch_resends_once(
    owner_client, monkeypatch, caplog
):
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")
    client, _settings_value = owner_client
    outcomes = [TelegramDeliveryError("telegram_http_429", "retry", retry_after=17), 502]
    calls = []

    def flaky(*args):
        calls.append(args)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("app.owner_alert_routes.telegram.send_message", flaky)
    events = [_program_event(i, PROGRAMS[1], "added", f"Venue {i}") for i in range(4)]

    first = _post_batch(client, events)
    second = _post_batch(client, events)

    assert set(_states(first).values()) == {"retry"}
    assert {item["error_code"] for item in first.json()["results"]} == {"telegram_http_429"}
    assert set(_states(second).values()) == {"sent"}
    assert len(calls) == 2
    assert all(f"Venue {i}" in calls[1][2] for i in range(4))
    digest_logs = [
        record for record in caplog.records if '"event":"owner_alert_digest"' in record.getMessage()
    ]
    assert digest_logs[0].levelno == logging.WARNING
    assert json.loads(digest_logs[0].getMessage())["retry_after"] == 17
    assert digest_logs[1].levelno == logging.INFO


def test_transport_timeout_marks_unknown_and_never_resends(owner_client, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")
    client, settings = owner_client
    calls = []

    def timeout(*args):
        calls.append(args)
        raise TelegramDeliveryError("telegram_transport_unknown", "unknown")

    monkeypatch.setattr("app.owner_alert_routes.telegram.send_message", timeout)
    events = [_program_event(i, PROGRAMS[2], "removed", f"Venue {i}") for i in range(3)]

    first = _post_batch(client, events)
    replay = _post_batch(client, events)

    assert set(_states(first).values()) == {"unknown"}
    assert set(_states(replay).values()) == {"unknown"}
    assert len(calls) == 1
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    for secret in (
        settings.telegram_bot_token,
        str(settings.telegram_owner_chat_id),
        "event-batch-",
        "Venue 0",
    ):
        assert secret not in log_text


def test_withheld_and_pre_activation_are_never_sent(owner_client, monkeypatch):
    client, _settings_value = owner_client
    calls = _record_sends(monkeypatch)
    review = _program_event(1, PROGRAMS[0], "added", "Review")
    review["status"] = "review_required"
    rejected = _program_event(2, PROGRAMS[0], "added", "Rejected")
    rejected["status"] = "rejected"
    historical = _program_event(3, PROGRAMS[0], "added", "Old")
    historical["detected_at"] = "2026-07-01T00:00:00Z"

    response = _post_batch(client, [review, rejected, historical])

    assert _states(response) == {
        "event-batch-000001": "withheld",
        "event-batch-000002": "withheld",
        "event-batch-000003": "before_activation",
    }
    assert response.json()["message_count"] == 0
    assert calls == []


def test_malformed_event_is_rejected_alone(owner_client, monkeypatch):
    client, _settings_value = owner_client
    calls = _record_sends(monkeypatch)
    broken = _program_event(1, PROGRAMS[0], "added", "Broken")
    broken["source_url"] = "javascript:alert(1)"
    unnamed = {"id": "bad id with spaces", "kind": "added"}
    valid = _program_event(2, PROGRAMS[0], "added", "Valid")

    response = _post_batch(client, [broken, unnamed, "not-an-object", valid])

    assert response.status_code == 200
    assert _states(response) == {
        "event-batch-000001": "schema_rejected",
        "event-batch-000002": "sent",
    }
    assert len(calls) == 1
    assert "Valid" in calls[0][2]
    assert "Broken" not in calls[0][2]


def test_changed_digest_for_sent_id_is_conflict(owner_client, monkeypatch):
    client, _settings_value = owner_client
    calls = _record_sends(monkeypatch)
    event = _program_event(1, PROGRAMS[0], "added", "Venue")
    _post_batch(client, [event])
    changed = json.loads(json.dumps(event))
    changed["changes"][0]["after"] = "Different"

    response = _post_batch(client, [changed])

    assert _states(response) == {"event-batch-000001": "conflict"}
    assert response.json()["results"][0]["error_code"] == "digest_conflict"
    assert len(calls) == 1


def test_duplicate_id_within_batch_is_conflict(owner_client, monkeypatch):
    client, _settings_value = owner_client
    calls = _record_sends(monkeypatch)
    event = _program_event(1, PROGRAMS[0], "added", "Venue")

    response = _post_batch(client, [event, event])

    assert [item["state"] for item in response.json()["results"]] == ["sent", "conflict"]
    assert len(calls) == 1


def test_bad_auth_precedes_validation_with_no_side_effects(owner_client, monkeypatch):
    client, settings = owner_client
    calls = _record_sends(monkeypatch)

    wrong = _post_batch(client, [_event()], token="wrong")
    missing = client.post("/api/owner-alerts/batch", json={"events": [_event()]})
    malformed = client.post(
        "/api/owner-alerts/batch",
        content=b"not-json",
        headers={"Authorization": "Bearer wrong", "Content-Type": "application/json"},
    )
    authorized_malformed = client.post(
        "/api/owner-alerts/batch",
        content=b"not-json",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )

    assert wrong.status_code == 401
    assert missing.status_code == 401
    assert malformed.status_code == 401
    assert authorized_malformed.status_code == 422
    assert calls == []
    conn = db.connect(settings.db_path)
    try:
        assert owner_alert_store.get(
            conn, "event-12345678", settings.telegram_owner_chat_id
        ) is None
    finally:
        conn.close()


@pytest.mark.parametrize(
    "body",
    [{"events": "nope"}, {"events": [], "chat_id": 1}, {"events": [{}] * 501}, []],
)
def test_batch_envelope_is_bounded(owner_client, body):
    client, _settings_value = owner_client
    response = client.post(
        "/api/owner-alerts/batch",
        json=body,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 422


def test_empty_batch_sends_nothing(owner_client, monkeypatch):
    client, _settings_value = owner_client
    calls = _record_sends(monkeypatch)
    response = _post_batch(client, [])
    assert response.json() == {"ok": True, "results": [], "message_count": 0}
    assert calls == []


def test_disabled_batch_ingress_returns_503(tmp_path: Path):
    settings = replace(_settings(tmp_path / "disabled.db"), owner_alerts_enabled=False)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/owner-alerts/batch",
                content=b"not-json",
                headers={"Content-Type": "application/json"},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503


def test_telegram_429_exposes_retry_after(monkeypatch):
    def rate_limited(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {},
            io.BytesIO(b'{"ok":false,"parameters":{"retry_after":33}}'),
        )

    monkeypatch.setattr(telegram.urllib.request, "urlopen", rate_limited)

    with pytest.raises(TelegramDeliveryError) as exc_info:
        telegram.send_message("123:abcdefghijklmnopqrstuvwxyz", -1001234567890, "x")
    assert exc_info.value.state == "retry"
    assert exc_info.value.retry_after == 33


def test_single_event_failure_logs_at_warning(owner_client, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")
    client, _settings_value = owner_client

    def fail(*_args):
        raise TelegramDeliveryError("telegram_http_503", "retry")

    monkeypatch.setattr("app.owner_alert_routes.telegram.send_message", fail)
    client.post(
        "/api/owner-alerts/events",
        json={"event": _event()},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    records = [r for r in caplog.records if '"event":"owner_alert_delivery"' in r.getMessage()]
    assert records[-1].levelno == logging.WARNING
