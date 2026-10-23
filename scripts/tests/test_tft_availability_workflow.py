from pathlib import Path


WORKFLOW = Path(".github/workflows/table-for-two-alerts.yml")
LIVE_DATA = "/tmp/table-for-two-live.json"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def step_block(text: str, name: str, next_name: str) -> str:
    start = text.index(f"      - name: {name}")
    end = text.index(f"      - name: {next_name}", start)
    return text[start:end]


def test_alerts_read_railway_live_snapshot_instead_of_scraping() -> None:
    text = workflow_text()
    live = step_block(text, "Read live Table for Two availability", "Track first-seen release patterns")
    assert "scripts/tft_live_availability.py" in live
    assert "secrets.REMINDERS_API_BASE" in live
    assert "scrape_table_for_two.py" not in text
    for name, next_name in (
        ("Track first-seen release patterns", "Rebuild Telegram release catalogue"),
        ("Send matching alert emails", "Commit alert state and new release observations"),
    ):
        block = step_block(text, name, next_name)
        assert f"--data {LIVE_DATA}" in block
        assert "steps.live_availability.outcome == 'success'" in block


def test_commit_is_limited_to_alert_and_release_state() -> None:
    text = workflow_text()
    assert "group: table-for-two-availability-refresh" in text
    assert "cancel-in-progress: false" in text
    block = step_block(
        text,
        "Commit alert state and new release observations",
        "Fail after preserving alert evidence",
    )
    must_stage = block.split("MUST_STAGE:", 1)[1].split("KEEP_LOCAL_ON_CONFLICT:", 1)[0].split()
    assert must_stage == [
        "|",
        "data/table-for-two-alert-sent.json",
        "data/table-for-two-release-history.json",
        "reminders/app/tft_guide_catalog.json",
    ]
    for daily_only in ("data/table-for-two.json", "data/table-for-two-slots.json", "data/source-health.json", "data/updates.json"):
        assert daily_only not in text


def test_independent_stages_survive_partial_failure_and_final_gate_is_last() -> None:
    text = workflow_text()
    stages = (
        ("Read live Table for Two availability", "Track first-seen release patterns"),
        ("Track first-seen release patterns", "Rebuild Telegram release catalogue"),
        ("Rebuild Telegram release catalogue", "Send matching alert emails"),
        ("Send matching alert emails", "Commit alert state and new release observations"),
        ("Commit alert state and new release observations", "Fail after preserving alert evidence"),
    )
    for name, next_name in stages:
        assert "continue-on-error: true" in step_block(text, name, next_name)
    gate = text[text.index("      - name: Fail after preserving alert evidence"):]
    assert "      - name:" not in gate[len("      - name:"):]
    assert "LIVE_AVAILABILITY_OUTCOME" in gate
    assert "DATA_COMMIT_OUTCOME" in gate
