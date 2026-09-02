from pathlib import Path


WORKFLOW = Path(".github/workflows/table-for-two-alerts.yml")


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def step_block(text: str, name: str, next_name: str) -> str:
    start = text.index(f"      - name: {name}")
    end = text.index(f"      - name: {next_name}", start)
    return text[start:end]


def test_membership_changes_are_checked_on_the_fast_cycle() -> None:
    text = workflow_text()
    block = step_block(
        text,
        "Build booking-project membership alert",
        "Build bounded Table for Two slot snapshot",
    )
    assert "source_change_alert.py" in block
    assert "data/updates.json" in block
    assert "continue-on-error: true" in block
    assert "if: always()" in block
    assert "issues: write" in text


def test_shared_update_ledger_never_overwrites_remote_events_on_conflict() -> None:
    text = workflow_text()
    assert "group: table-for-two-availability-refresh" in text
    assert "cancel-in-progress: false" in text
    block = step_block(
        text,
        "Commit refreshed availability and alert state",
        "Finalize source health",
    )
    must_stage, keep_local = block.split("KEEP_LOCAL_ON_CONFLICT:", 1)
    assert "data/updates.json" in must_stage
    assert "data/updates.json" not in keep_local
    helper = Path("scripts/commit_and_push.sh").read_text(encoding="utf-8")
    assert '[[ "$f" == "data/updates.json" ]]' in helper
    assert "scripts/merge_update_ledgers.py" in helper


def test_independent_availability_evidence_survives_partial_failure() -> None:
    text = workflow_text()
    stages = (
        ("Refresh Table for Two availability", "Build booking-project membership alert"),
        ("Build booking-project membership alert", "Build bounded Table for Two slot snapshot"),
        ("Build bounded Table for Two slot snapshot", "Track first-seen release patterns"),
        ("Track first-seen release patterns", "Rebuild Telegram release catalogue"),
        ("Rebuild Telegram release catalogue", "Send matching alert emails"),
        ("Commit refreshed availability and alert state", "Finalize source health"),
    )
    for name, next_name in stages:
        assert "continue-on-error: true" in step_block(text, name, next_name)


def test_health_uses_source_refresh_outcome_and_final_gate_is_last() -> None:
    text = workflow_text()
    health = step_block(text, "Finalize source health", "Commit source health")
    assert "steps.source_refresh.outcome" in health
    assert "job.status" not in health
    fail_at = text.index("      - name: Fail after preserving availability evidence")
    assert fail_at > text.index("      - name: Open Table for Two membership alert issue")
    assert "OWNER_DISPATCH_OUTCOME" in text[fail_at:]
    assert "RECEIPT_COMMIT_OUTCOME" in text[fail_at:]
