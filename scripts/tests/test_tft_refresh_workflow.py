from pathlib import Path


WORKFLOW = Path(".github/workflows/refresh-table-for-two.yml")


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def step_block(text: str, name: str, next_name: str) -> str:
    start = text.index(f"      - name: {name}")
    end = text.index(f"      - name: {next_name}", start)
    return text[start:end]


def test_document_verifier_runs_as_a_module() -> None:
    text = workflow_text()
    block = step_block(
        text,
        "Verify reviewed official document pages",
        "Refresh and retain official menu versions",
    )
    assert "python3 -m scripts.verify_tft_official_documents" in block
    assert "python3 scripts/verify_tft_official_documents.py" not in block


def test_document_verifier_installs_the_patched_pypdf_version() -> None:
    text = workflow_text()
    block = step_block(
        text,
        "Verify reviewed official document pages",
        "Refresh and retain official menu versions",
    )

    assert "pypdf==6.16.2" in block
    assert "pypdf==6.15.0" not in block


def test_independent_observations_continue_after_a_failure() -> None:
    text = workflow_text()
    stages = (
        ("Refresh public roster snapshot", "Verify reviewed official document pages"),
        ("Verify reviewed official document pages", "Refresh and retain official menu versions"),
        ("Refresh and retain official menu versions", "Build Telegram guide catalogue"),
        ("Build Telegram guide catalogue", "Build Table for Two source alert"),
        ("Build Table for Two source alert", "Commit refreshed Table for Two data"),
        ("Commit refreshed Table for Two data", "Finalize Table for Two roster health"),
    )
    for name, next_name in stages:
        assert "continue-on-error: true" in step_block(text, name, next_name)

    for name, next_name in stages[1:]:
        assert "if: always()" in step_block(text, name, next_name)


def test_source_health_uses_the_actual_stage_outcomes() -> None:
    text = workflow_text()
    block = step_block(
        text,
        "Finalize Table for Two roster health",
        "Finalize Table for Two menu health",
    )
    assert 'steps.roster_refresh.outcome' in block
    assert 'steps.document_verify.outcome' in block
    assert 'job.status' not in block
    menu_block = step_block(
        text,
        "Finalize Table for Two menu health",
        "Commit source health",
    )
    assert 'steps.menu_refresh.outcome' in menu_block
    assert 'job.status' not in menu_block


def test_workflow_fails_only_after_alert_and_owner_delivery_attempts() -> None:
    text = workflow_text()
    fail_at = text.index("      - name: Fail after preserving refresh evidence")
    assert fail_at > text.index("      - name: Dispatch published owner updates")
    assert fail_at > text.index("      - name: Open Table for Two alert issue")
    assert "Table for Two refresh completed with failures" in text[fail_at:]
    assert "OWNER_DISPATCH_OUTCOME" in text[fail_at:]
    assert "RECEIPT_COMMIT_OUTCOME" in text[fail_at:]


def test_refresh_commit_uses_the_conflict_safe_helper() -> None:
    text = workflow_text()
    block = step_block(
        text,
        "Commit refreshed Table for Two data",
        "Finalize Table for Two roster health",
    )
    assert "bash scripts/commit_and_push.sh" in block
    assert "data/table-for-two.json" in block
    assert "data/reviews/tft-menu-pdfs" in block
    assert "KEEP_LOCAL_ON_CONFLICT" in block
