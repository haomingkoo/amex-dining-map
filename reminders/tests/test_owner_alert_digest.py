from __future__ import annotations

import io
import json
import logging
import re
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


def test_digest_groups_by_program_with_counts_and_shows_all_that_fit():
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

    assert message.splitlines()[0] == "Amex Explorer · 10 updates"
    assert "Japan Dining · 4 added, 2 removed, 3 details updated" in message
    assert "Plat Stay · 1 added" in message
    japan = message.split("Japan Dining ·")[1].split("Plat Stay ·")[0]
    item_lines = [line for line in japan.splitlines() if line[:2] in {"+ ", "− ", "~ "}]
    assert len(item_lines) == 9
    assert "more" not in japan
    assert f"Explorer: {EXPLORER}/#/japan" in japan
    assert f"Explorer: {EXPLORER}/#/stays" in message
    assert "Before:" not in message


def test_digest_shares_budget_fairly_and_shows_every_kind():
    kinds = ["details_updated"] * 60 + ["added", "source_updated"]
    raw = [
        _program_event(i, PROGRAMS[0], kind, f"Japan venue {i} " + "x" * 120)
        for i, kind in enumerate(kinds)
    ] + [
        _program_event(100 + i, PROGRAMS[2], "removed", f"Global venue {i} " + "y" * 120)
        for i in range(60)
    ]
    for i, event in enumerate(raw[:60]):
        event["changes"] = [{"field": f"Field {i}", "before": "a", "after": "b"}]
    raw[61]["subject"] = "Japan Dining source"
    raw[61]["changes"] = [{"field": "Record count", "before": 863, "after": 865}]
    events = [OwnerAlertEvent.model_validate(event) for event in raw]

    message = format_owner_digest(events, EXPLORER)

    assert len(message) <= 3900
    japan = message.split("Japan Dining ·")[1]
    global_ = message.split("Global Dining ·")[1].split("Japan Dining ·")[0]
    japan_items = [line for line in japan.splitlines() if line[:2] in {"+ ", "~ "}]
    global_items = [line for line in global_.splitlines() if line.startswith("− ")]
    assert abs(len(japan_items) - len(global_items)) <= 1
    assert len(japan_items) >= 3
    assert japan_items[0].startswith("+ Japan venue 60")
    assert japan_items[1].startswith("~ Japan venue 0")
    assert "~ Source: 863 → 865 records" in japan
    assert f"…and {62 - len(japan_items)} more" in japan
    assert f"…and {60 - len(global_items)} more" in global_


def test_digest_source_line_shows_numbers_and_hides_hashes():
    raw = _program_event(1, PROGRAMS[0], "source_updated", "Japan Dining source")
    raw["changes"] = [
        {"field": "Record count", "before": 863, "after": 865},
        {"field": "Hotel outlet count", "before": 94, "after": 95},
        {"field": "Official records SHA-256", "before": "7ba16603e169", "after": "4ce966fa3074"},
    ]
    only_hash = _program_event(2, PROGRAMS[5], "source_updated", "Plat Stay source")
    only_hash["changes"] = [
        {"field": "Hotel T&C PDF hash", "before": "0d32857cf380", "after": "040b0e309127"}
    ]
    ratings = _program_event(3, PROGRAMS[3], "source_review_required", "Tabelog ratings")
    ratings["changes"] = [{"field": "Review items", "before": 0, "after": 2}]
    events = [OwnerAlertEvent.model_validate(event) for event in (raw, only_hash, ratings)]

    message = format_owner_digest(events, EXPLORER)

    assert "~ Source: 863 → 865 records, 94 → 95 hotel outlets" in message
    assert "~ Source: official records changed" in message
    assert "~ Tabelog ratings: 0 → 2 review items" in message
    assert "SHA" not in message and "hash" not in message
    assert "7ba16603e169" not in message
    assert "Japan Dining source" not in message


def test_digest_collapses_bulk_identical_changes_into_one_warning():
    raw = [
        _program_event(i, PROGRAMS[0], "details_updated", f"Venue {i}") for i in range(25)
    ] + [_program_event(50 + i, PROGRAMS[2], "details_updated", f"Global {i}") for i in range(19)]
    for event in raw[:25]:
        event["changes"] = [
            {"field": "Name", "before": "Den", "after": "傳"},
            {"field": "District", "before": "Jingumae", "after": "神宮前"},
        ]
    events = [OwnerAlertEvent.model_validate(event) for event in raw]

    message = format_owner_digest(events, EXPLORER)

    japan = message.split("Japan Dining ·")[1]
    assert (
        "⚠ 25 restaurants changed Name, District at once. "
        "Possible source glitch; check before trusting." in japan
    )
    assert "~ Venue 0: Name Den → 傳, District Jingumae → 神宮前" in japan
    assert "~ Venue 1: Name Den → 傳" in japan
    assert "Venue 2:" not in japan
    assert "more" not in japan
    global_ = message.split("Global Dining ·")[1].split("Japan Dining ·")[0]
    assert "⚠" not in global_
    assert global_.count("~ Global") == 19


def test_digest_keeps_venue_route_for_single_item_section():
    venue = _program_event(1, (*PROGRAMS[0][:2], "#/japan?venue=den"), "added", "Den")
    pair = [
        _program_event(2, (*PROGRAMS[2][:2], "#/global?venue=a"), "added", "A"),
        _program_event(3, (*PROGRAMS[2][:2], "#/global?venue=b"), "added", "B"),
    ]
    events = [OwnerAlertEvent.model_validate(event) for event in (venue, *pair)]

    message = format_owner_digest(events, EXPLORER)

    assert f"Explorer: {EXPLORER}/#/japan?venue=den" in message
    assert f"Explorer: {EXPLORER}/#/global\n" in message + "\n"


def test_digest_updates_list_changed_fields():
    raw = _program_event(1, PROGRAMS[1], "details_updated", "VUE")
    raw["changes"] = [
        {"field": "Address", "before": "A", "after": "B"},
        {"field": "Phone", "before": "1", "after": "2"},
    ]
    message = format_owner_digest([OwnerAlertEvent.model_validate(raw)], EXPLORER)

    assert "~ VUE: Address, Phone" in message
    assert message.splitlines()[0] == "Amex Explorer · 1 update"


def test_digest_stays_under_telegram_limit_for_huge_batches():
    kinds = ["added", "removed", "details_updated", "source_updated", "renamed"]
    raw = [
        _program_event(i, PROGRAMS[i % len(PROGRAMS)], kinds[i % len(kinds)], "S" * 500)
        for i in range(500)
    ]
    events = [OwnerAlertEvent.model_validate(event) for event in raw]

    message = format_owner_digest(events, EXPLORER)

    assert len(message) < 4000
    assert message.splitlines()[0] == "Amex Explorer · 500 updates"
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


def test_digest_link_uses_most_common_route_regardless_of_order():
    ratings = ("Explorer ratings", "explorer-ratings", "#/ratings")
    raw = [
        _program_event(1, ratings, "details_updated", "A"),
        _program_event(2, (*ratings[:2], "#/japan?venue=b"), "details_updated", "B"),
        _program_event(3, (*ratings[:2], "#/japan"), "details_updated", "C"),
    ]
    events = [OwnerAlertEvent.model_validate(event) for event in raw]

    for ordered in (events, events[::-1]):
        assert f"Explorer: {EXPLORER}/#/japan" in format_owner_digest(ordered, EXPLORER)


def test_digest_route_tie_breaks_by_sorted_route():
    ratings = ("Explorer ratings", "explorer-ratings", "#/ratings")
    raw = [
        _program_event(1, ratings, "details_updated", "A"),
        _program_event(2, (*ratings[:2], "#/japan"), "details_updated", "B"),
    ]
    events = [OwnerAlertEvent.model_validate(event) for event in raw]

    for ordered in (events, events[::-1]):
        assert f"Explorer: {EXPLORER}/#/japan" in format_owner_digest(ordered, EXPLORER)


def test_digest_golden_text_for_mixed_batch():
    japan, global_dining, love = PROGRAMS[0], PROGRAMS[2], PROGRAMS[4]
    raw = (
        [
            _program_event(1, japan, "added", "Sushi Saito"),
            _program_event(2, japan, "added", "Den"),
            _program_event(3, japan, "removed", "Kanda"),
        ]
        + [
            _program_event(10 + i, japan, "details_updated", f"Japan venue {i}")
            for i in range(12)
        ]
        + [
            _program_event(30 + i, global_dining, "removed", f"Global venue {i}")
            for i in range(9)
        ]
        + [_program_event(50, love, "source_updated", "Love Dining venue list")]
    )
    raw[3]["changes"] = [
        {"field": "Address", "before": "A", "after": "B"},
        {"field": "Phone", "before": "1", "after": "2"},
    ]
    events = [OwnerAlertEvent.model_validate(event) for event in raw]

    assert format_owner_digest(events, EXPLORER) == "\n".join(
        [
            "Amex Explorer · 25 updates",
            "",
            "Global Dining · 9 removed",
            *(f"− Global venue {i}" for i in range(9)),
            f"Explorer: {EXPLORER}/#/global",
            "",
            "Japan Dining · 2 added, 1 removed, 12 details updated",
            "+ Sushi Saito",
            "− Kanda",
            "~ Japan venue 0: Address, Phone",
            "+ Den",
            *(f"~ Japan venue {i}: Listing" for i in range(1, 12)),
            f"Explorer: {EXPLORER}/#/japan",
            "",
            "Love Dining · 1 source updated",
            "~ Venue list: Listing Not listed → Listed",
            f"Explorer: {EXPLORER}/#/love-dining",
        ]
    )


def test_digest_merges_identical_lines_with_count():
    raw = [
        _program_event(i, PROGRAMS[0], "source_updated", "Japan Dining source") for i in range(10)
    ]
    for event in raw:
        event["changes"] = [{"field": "Official records SHA-256", "before": "aaa", "after": "bbb"}]
    raw.append(_program_event(20, PROGRAMS[0], "added", "Den"))
    raw.append(_program_event(21, PROGRAMS[0], "added", "Den"))
    events = [OwnerAlertEvent.model_validate(event) for event in raw]

    message = format_owner_digest(events, EXPLORER)

    assert "~ Source: official records changed (×10)" in message
    assert "+ Den (×2)" in message
    assert message.count("official records changed") == 1
    assert "more" not in message


def test_digest_review_lines_use_plain_wording():
    love, tft = PROGRAMS[4], PROGRAMS[1]
    required = _program_event(1, love, "source_review_required", "Love Dining")
    required["changes"] = [
        {"field": "Source state", "before": "current", "after": "review_required"},
        {"field": "Review", "before": "clear", "after": "required"},
        {"field": "Review items", "before": 0, "after": 2},
        {
            "field": "Coverage",
            "before": "80/80 (100%), 0 unavailable",
            "after": "78/78 (100%), 0 unavailable",
        },
    ]
    cleared = _program_event(2, tft, "source_review_cleared", "Table for Two menus")
    cleared["changes"] = [
        {"field": "Source state", "before": "review_required", "after": "current"},
        {"field": "Review", "before": "required", "after": "clear"},
        {"field": "Review items", "before": 9, "after": 0},
        {
            "field": "Coverage",
            "before": {"covered": 18, "total": 32, "unavailable": 14, "percent": 56.2},
            "after": {"covered": 19, "total": 32, "unavailable": 13, "percent": 59.4},
        },
    ]
    roster = _program_event(3, tft, "source_review_required", "Table for Two roster")
    roster["changes"] = [
        {"field": "Review", "before": "clear", "after": "required"},
        {"field": "Review items", "before": 0, "after": 1},
    ]
    events = [OwnerAlertEvent.model_validate(event) for event in (required, cleared, roster)]

    message = format_owner_digest(events, EXPLORER)

    assert "~ Source: needs review (2 items), 80/80 → 78/78 covered" in message
    assert "~ Menus: review cleared, 18/32 → 19/32 covered" in message
    assert "~ Roster: needs review (1 item)" in message
    assert "review_required" not in message and "unavailab" not in message


def test_digest_truncates_long_lines_at_a_boundary():
    raw = _program_event(1, PROGRAMS[0], "details_updated", "Venue")
    raw["changes"] = [
        {"field": f"Field number {i}", "before": "a", "after": "b"} for i in range(20)
    ]
    message = format_owner_digest([OwnerAlertEvent.model_validate(raw)], EXPLORER)

    line = next(line for line in message.splitlines() if line.startswith("~ Venue"))
    assert len(line) <= 160
    assert re.search(r", Field number \d+…$", line)


def test_digest_bulk_warning_names_hotels_for_plat_stay():
    raw = [_program_event(i, PROGRAMS[5], "details_updated", f"Hotel {i}") for i in range(20)]
    for event in raw:
        event["changes"] = [{"field": "Blackout dates", "before": "a", "after": "b"}]
    events = [OwnerAlertEvent.model_validate(event) for event in raw]

    message = format_owner_digest(events, EXPLORER)

    assert "⚠ 20 hotels changed Blackout dates at once." in message


BURST = json.loads(
    (Path(__file__).parent / "fixtures" / "owner_alert_burst-2026-10-28.json").read_text()
)


def test_real_burst_posts_in_one_request_and_one_message(owner_client, monkeypatch):
    client, _settings_value = owner_client
    calls = _record_sends(monkeypatch)
    assert len(BURST) == 101
    assert len(json.dumps({"events": BURST}).encode()) > 16_384

    response = _post_batch(client, BURST)

    assert response.status_code == 200
    assert set(_states(response).values()) == {"sent"}
    assert len(calls) == 1
    text = calls[0][2]
    assert text.splitlines()[0] == "Amex Explorer · 101 updates"
    assert text == "\n".join(
        [
            "Amex Explorer · 101 updates",
            "",
            "Japan Dining · 100 details updated, 1 source updated",
            "⚠ 100 restaurants changed Name, District, Cuisine at once. "
            "Possible source glitch; check before trusting.",
            "~ 南青山エッセンス / Tokyo: Name MINAMIAOYAMA Essence → 南青山エッセンス, "
            "District Minamiaoyama → 南青山, Cuisine Chinese → 中華",
            "~ 日本料理　伯雲（はくうん） / Tokyo: Name Hakuun → 日本料理　伯雲（はくうん）, "
            "District Minamiaoyama → 南青山, Cuisine Japanese, Kaiseki, Washoku → 和食",
            "~ Source: official records changed",
            f"Explorer: {EXPLORER}/#/dining/japan/top",
        ]
    )


def test_padded_500_event_batch_fits_authenticated_limit(owner_client, monkeypatch):
    client, _settings_value = owner_client
    calls = _record_sends(monkeypatch)
    events = []
    for i in range(500):
        event = _program_event(i, PROGRAMS[i % 6], "details_updated", f"Venue {i}")
        event["review_note"] = "n" * 500
        event["after"]["fields"] = {f"F{j}": "v" * 450 for j in range(4)}
        events.append(event)
    body = json.dumps({"events": events}).encode()
    assert 1_300_000 < len(body) < 2 * 1024 * 1024

    response = client.post(
        "/api/owner-alerts/batch",
        content=body,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert len(calls) == 1


def test_oversized_bodies_without_bearer_or_on_other_routes_stay_413(owner_client, monkeypatch):
    client, _settings_value = owner_client
    calls = _record_sends(monkeypatch)
    body = json.dumps({"events": BURST}).encode()
    json_header = {"Content-Type": "application/json"}

    anonymous = client.post("/api/owner-alerts/batch", content=body, headers=json_header)
    basic = client.post(
        "/api/owner-alerts/batch",
        content=body,
        headers={**json_header, "Authorization": "Basic abc"},
    )
    wrong_bearer = client.post(
        "/api/owner-alerts/batch",
        content=body,
        headers={**json_header, "Authorization": "Bearer wrong"},
    )
    other_route = client.post(
        "/api/subscribe",
        content=b"x" * 20_000,
        headers={**json_header, "Authorization": f"Bearer {TOKEN}"},
    )
    too_big = client.post(
        "/api/owner-alerts/batch",
        content=b"x" * (2 * 1024 * 1024 + 1),
        headers={**json_header, "Authorization": f"Bearer {TOKEN}"},
    )

    assert anonymous.status_code == 413
    assert basic.status_code == 413
    assert wrong_bearer.status_code == 401
    assert other_route.status_code == 413
    assert too_big.status_code == 413
    assert calls == []


def test_stale_sending_counts_as_unknown_and_warns(owner_client, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")
    client, settings = owner_client
    calls = _record_sends(monkeypatch)
    stuck = _program_event(1, PROGRAMS[0], "added", "Stuck")
    delivered = _program_event(2, PROGRAMS[0], "added", "Delivered")
    _post_batch(client, [delivered])
    conn = db.connect(settings.db_path)
    try:
        owner_alert_store.claim(
            conn,
            stuck["id"],
            settings.telegram_owner_chat_id,
            OwnerAlertEvent.model_validate(stuck).digest(),
        )
        conn.execute(
            "UPDATE owner_alert_deliveries SET updated_ts = '2000-01-01T00:00:00+00:00' "
            "WHERE event_id = ?",
            (stuck["id"],),
        )
        conn.commit()
    finally:
        conn.close()
    caplog.clear()

    response = _post_batch(client, [stuck, delivered])

    assert _states(response) == {
        "event-batch-000001": "unknown",
        "event-batch-000002": "sent",
    }
    assert len(calls) == 1
    record = next(r for r in caplog.records if '"event":"owner_alert_digest"' in r.getMessage())
    logged = json.loads(record.getMessage())
    assert record.levelno == logging.WARNING
    assert logged["unknown"] == 1
    assert logged["deduplicated"] == 1


def test_sent_replay_logs_info(owner_client, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="amex_reminders.delivery")
    client, _settings_value = owner_client
    _record_sends(monkeypatch)
    event = _program_event(1, PROGRAMS[0], "added", "Venue")
    _post_batch(client, [event])
    caplog.clear()

    _post_batch(client, [event])

    record = next(r for r in caplog.records if '"event":"owner_alert_digest"' in r.getMessage())
    assert record.levelno == logging.INFO
    assert json.loads(record.getMessage())["deduplicated"] == 1
