from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_failed_dispatch_preserves_run_receipt_without_secret(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' '{\"ok\":false,\"run_id\":\"run-failure-1234\"}'\nexit 22\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    summary = tmp_path / "summary.md"
    secret = "dispatch-secret-that-must-not-appear-in-summary"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GITHUB_STEP_SUMMARY": str(summary),
        "REMINDERS_API_BASE": "https://reminders.example.test",
        "TELEGRAM_REMINDER_DISPATCH_TOKEN": secret,
    }

    result = subprocess.run(
        ["bash", "scripts/dispatch-telegram-reminders.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 22
    receipt = summary.read_text(encoding="utf-8")
    assert "run-failure-1234" in receipt
    assert secret not in receipt
    assert secret not in result.stdout
    assert secret not in result.stderr
