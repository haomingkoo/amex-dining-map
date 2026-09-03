from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import watchdog_stale_sources as watchdog


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def source(source_id: str, *, freshness: str = "current", failure: str = "clear", review: str = "clear") -> dict:
    return {
        "id": source_id,
        "freshness_state": freshness,
        "failure_state": failure,
        "review_state": review,
        "checked_at": "2026-09-01T00:00:00Z",
        "stale_after_hours": 36,
    }


def test_review_required_is_not_treated_as_stale() -> None:
    pending = source("global-dining", review="required")

    assert watchdog.is_degraded(pending) is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"freshness": "stale"},
        {"freshness": "unavailable"},
        {"failure": "failing"},
    ],
)
def test_stale_or_failing_sources_need_attention(kwargs: dict) -> None:
    assert watchdog.is_degraded(source("japan-dining", **kwargs)) is True


def test_first_sighting_retries_the_owning_workflow() -> None:
    stale = [source("japan-dining", freshness="stale")]

    plans = watchdog.plan_actions(stale, {"Refresh Data": None}, NOW)

    assert [(plan.workflow, plan.action) for plan in plans] == [
        ("Refresh Data", watchdog.Action.DISPATCH)
    ]


def test_sources_sharing_a_workflow_dispatch_it_once() -> None:
    stale = [
        source("japan-dining", freshness="stale"),
        source("plat-stay", freshness="stale"),
    ]

    plans = watchdog.plan_actions(stale, {"Refresh Data": None}, NOW)

    assert len(plans) == 1
    assert plans[0].source_ids == ("japan-dining", "plat-stay")


def test_a_recent_retry_escalates_instead_of_dispatching_again() -> None:
    stale = [source("japan-dining", freshness="stale")]

    plans = watchdog.plan_actions(stale, {"Refresh Data": NOW - timedelta(hours=1)}, NOW)

    assert plans[0].action is watchdog.Action.ESCALATE


def test_a_retry_older_than_the_window_dispatches_again() -> None:
    stale = [source("japan-dining", freshness="stale")]

    plans = watchdog.plan_actions(stale, {"Refresh Data": NOW - timedelta(hours=7)}, NOW)

    assert plans[0].action is watchdog.Action.DISPATCH


def test_only_the_declared_manual_sources_lack_an_owning_workflow() -> None:
    health = json.loads((ROOT / "data/source-health.json").read_text())

    unowned = {s["id"] for s in health["sources"] if s["id"] not in watchdog.SOURCE_WORKFLOWS}

    assert unowned == watchdog.UNOWNED_SOURCES


def test_a_source_no_workflow_can_refresh_is_named_in_the_issue() -> None:
    stale = [source("tabelog-ratings", freshness="stale")]

    plans = watchdog.plan_actions(stale, {}, NOW)
    body = watchdog.issue_body(stale, plans, NOW)

    assert plans == []
    assert "no workflow refreshes this" in body


def test_every_mapped_workflow_exists_and_accepts_manual_dispatch() -> None:
    workflows = {
        path.read_text(encoding="utf-8").splitlines()[0].removeprefix("name: ").strip(): path
        for path in (ROOT / ".github/workflows").glob("*.yml")
    }

    for name in set(watchdog.SOURCE_WORKFLOWS.values()):
        assert name in workflows, f"{name} is not a workflow"
        assert "workflow_dispatch:" in workflows[name].read_text(encoding="utf-8")


def test_healthy_health_file_plans_nothing(tmp_path: Path) -> None:
    health = tmp_path / "health.json"
    health.write_text(json.dumps({"sources": [source("japan-dining")]}))

    assert watchdog.main(["--health", str(health), "--dry-run"]) == 0
    assert watchdog.degraded_sources(json.loads(health.read_text())) == []


def test_issue_body_names_the_source_and_the_decision() -> None:
    stale = [source("love-dining", freshness="stale")]
    plans = watchdog.plan_actions(stale, {"Refresh Love Dining": NOW - timedelta(hours=1)}, NOW)

    body = watchdog.issue_body(stale, plans, NOW)

    assert "love-dining" in body
    assert "Refresh Love Dining" in body
    assert "escalate" in body


def test_monitor_workflow_runs_the_watchdog_with_the_rights_it_needs() -> None:
    workflow = (ROOT / ".github/workflows/monitor-source-health.yml").read_text()

    assert "scripts/watchdog_stale_sources.py" in workflow
    assert "actions: write" in workflow
    assert "issues: write" in workflow


def test_tabelog_candidates_runs_on_a_schedule_with_usable_defaults() -> None:
    workflow = (ROOT / ".github/workflows/match-tabelog-candidates.yml").read_text()

    assert "schedule:" in workflow
    # A scheduled run carries no inputs, so every one needs a literal fallback.
    for field, default in (("offset", "0"), ("limit", "50"), ("top", "5"), ("pause", "0.2")):
        assert f"inputs.{field} || '{default}'" in workflow
