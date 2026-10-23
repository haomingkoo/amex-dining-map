from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.check_tft_live_health import validate_health


NOW = datetime(2026, 9, 2, 0, 20, tzinfo=timezone.utc)


def payload() -> dict:
    return {
        "ok": True,
        "deployment_id": "deployment-1",
        "feature_state": {"tft_live_refresh_enabled": True},
        "tft_live": {
            "status": "success",
            "generated_at": "2026-09-02T00:19:00Z",
            "age_seconds": 60,
            "counts": {"eligible": 21, "succeeded": 21, "failed": 0, "retained": 0},
        },
    }


def test_accepts_a_current_complete_refresh():
    assert validate_health(payload(), now=NOW) == {
        "deployment_id": "deployment-1",
        "generated_at": "2026-09-02T00:19:00Z",
        "age_seconds": 60,
        "eligible": 21,
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda row: row.update(ok=False), "service health is not ok"),
        (
            lambda row: row["tft_live"].update(status="partial"),
            "live refresh status is not success",
        ),
        (
            lambda row: row["tft_live"].update(
                generated_at="2026-09-01T23:49:59Z", age_seconds=1_801
            ),
            "outside the freshness window",
        ),
        (
            lambda row: row["tft_live"]["counts"].update(succeeded=20, failed=1),
            "did not cover every eligible venue",
        ),
        (
            lambda row: row["tft_live"].update(age_seconds=500),
            "does not match generated time",
        ),
    ],
)
def test_rejects_degraded_or_inconsistent_health(mutation, message):
    candidate = payload()
    mutation(candidate)

    with pytest.raises(ValueError, match=message):
        validate_health(candidate, now=NOW)


def load_build_source_health():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import build_source_health

    return build_source_health


def test_source_health_records_the_live_snapshot_as_a_successful_check(monkeypatch):
    module = load_build_source_health()
    monkeypatch.setattr(module, "fetch_health", lambda url: payload())

    live, outcome = module.read_tft_live("https://example.test/healthz")

    assert (live["generated_at"], outcome) == ("2026-09-02T00:19:00Z", "success")


def test_source_health_marks_an_unreachable_service_as_a_failed_check(monkeypatch):
    module = load_build_source_health()

    def unreachable(url):
        raise OSError("connection refused")

    monkeypatch.setattr(module, "fetch_health", unreachable)

    assert module.read_tft_live("https://example.test/healthz") == ({"status": "unavailable"}, "failure")
