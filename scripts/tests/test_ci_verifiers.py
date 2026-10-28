from pathlib import Path


TESTS = Path(".github/workflows/tests.yml")
PAGES = Path(".github/workflows/deploy-pages.yml")
PROJECT = Path("scripts/verify-project.mjs")
MANUAL = {"verify-project.mjs", "verify-tft-browser-evidence.mjs"}


def test_tests_workflow_runs_the_project_verifier() -> None:
    text = TESTS.read_text(encoding="utf-8")
    assert "node scripts/verify-project.mjs" in text
    assert "uv==" in text


def test_deploy_pages_never_runs_verifiers() -> None:
    assert "verify-" not in PAGES.read_text(encoding="utf-8")


def test_project_verifier_covers_every_automatable_verifier() -> None:
    text = PROJECT.read_text(encoding="utf-8")
    verifiers = {path.name for path in Path("scripts").glob("verify-*.mjs")} - MANUAL
    missing = sorted(name for name in verifiers if name not in text
                     and name not in {"verify-telegram-slots.mjs", "verify-telegram-reminders.mjs"})
    assert missing == []
    # Slots and reminders run inside verify-telegram-guide.mjs.
    guide = Path("scripts/verify-telegram-guide.mjs").read_text(encoding="utf-8")
    assert "verify-telegram-slots.mjs" in guide
    assert "verify-telegram-reminders.mjs" in guide


def test_claude_md_runs_scripts_suite_with_the_ci_dependencies() -> None:
    text = Path("CLAUDE.md").read_text(encoding="utf-8")
    assert "reminders/.venv/bin/python -m pytest scripts/tests -q" in text
    assert "reminders/requirements-dev.txt" in text
    assert "`python3 -m pytest scripts/tests -q`" not in text


def test_tests_workflow_runs_only_static_verifiers() -> None:
    text = TESTS.read_text(encoding="utf-8")
    assert "node scripts/verify-project.mjs --static-only" in text


def test_static_only_skips_suite_reruns_but_local_run_keeps_them() -> None:
    text = PROJECT.read_text(encoding="utf-8")
    assert 'process.argv.includes("--static-only")' in text
    gated = text.split("if (!staticOnly) {", 1)[1].split("\n}\n", 1)[0]
    assert '"pytest", "reminders/tests", "scripts/tests"' in gated
    assert "scripts/tests/${name}" in gated


def test_deploy_pages_ignores_gated_monitor_runs() -> None:
    text = PAGES.read_text(encoding="utf-8")
    changed_if = text.split("  changed:\n", 1)[1].split("\n    runs-on:", 1)[0]
    assert "github.event.workflow_run.name != 'Monitor Source Health'" in changed_if
    assert "github.event.workflow_run.event != 'workflow_run'" in changed_if


def test_deploy_pages_concurrency_is_on_the_deploy_job() -> None:
    text = PAGES.read_text(encoding="utf-8")
    # Workflow-level concurrency would let a skipped run cancel a live deploy.
    assert "\nconcurrency:" not in text
    deploy = text.split("\n  deploy:\n", 1)[1].split("\n    steps:", 1)[0]
    assert "concurrency:\n      group: pages\n      cancel-in-progress: true" in deploy
