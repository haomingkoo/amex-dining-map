"""Monitor and refresh runs share no concurrency group, so their pushes must merge."""

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
HEALTH = "data/source-health.json"
LEDGER = "data/updates.json"
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def stamp(minutes_ago: int) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")

pytestmark = pytest.mark.skipif(
    subprocess.run(["bash", "-c", "type mapfile"], capture_output=True).returncode != 0,
    reason="commit_and_push.sh needs bash 4+ (CI runs ubuntu)",
)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def event(event_id: str) -> dict:
    return {
        "id": event_id,
        "stream_id": f"stream-{event_id}",
        "transition_id": f"transition-{event_id}",
        "occurrence": 1,
        "detected_at": stamp(60),
        "status": "published",
        "kind": "source_updated",
    }


def source(health: dict, source_id: str) -> dict:
    return next(item for item in health["sources"] if item["id"] == source_id)


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(tmp_path, "init", "-q", "-b", "main", str(seed))
    shutil.copytree(ROOT / "scripts", seed / "scripts", ignore=shutil.ignore_patterns("tests", "__pycache__"))
    (seed / "data").mkdir()
    health = read_json(ROOT / HEALTH)
    write_json(seed / HEALTH, health)
    write_json(
        seed / LEDGER,
        {"schema_version": 1, "updated_at": stamp(120), "updates": [event("seed")]},
    )
    git(seed, "add", ".")
    git(seed, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "seed")
    git(seed, "push", "-q", str(bare), "main")
    return bare


def clone(remote: Path, name: str) -> Path:
    path = remote.parent / name
    git(remote.parent, "clone", "-q", str(remote), str(path))
    git(path, "config", "user.name", name)
    git(path, "config", "user.email", f"{name}@example.com")
    return path


def edit(repo: Path, source_id: str, field: str, value: str, event_id: str) -> None:
    health = read_json(repo / HEALTH)
    source(health, source_id)[field] = value
    write_json(repo / HEALTH, health)
    ledger = read_json(repo / LEDGER)
    ledger["updates"].insert(0, event(event_id))
    ledger["updated_at"] = stamp(0)
    write_json(repo / LEDGER, ledger)


def commit_and_push(repo: Path, message: str) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(repo),
        "COMMIT_MESSAGE": message,
        "MUST_STAGE": f"{HEALTH}\n{LEDGER}\n",
        "MAX_ATTEMPTS": "1",
    }
    return subprocess.run(
        ["bash", "scripts/commit_and_push.sh"], cwd=repo, env=env, capture_output=True, text=True
    )


def test_monitor_and_refresh_pushes_keep_both_writers_changes(remote: Path) -> None:
    refresh = clone(remote, "refresh")
    monitor = clone(remote, "monitor")
    edit(refresh, "global-dining", "last_success_at", stamp(5), "refresh-event")
    edit(monitor, "table-for-two-availability", "checked_at", stamp(1), "monitor-event")

    assert commit_and_push(monitor, "chore: update source health").returncode == 0
    pushed = commit_and_push(refresh, "chore: refresh global dining data")
    assert pushed.returncode == 0, pushed.stdout + pushed.stderr

    final = clone(remote, "final")
    health = read_json(final / HEALTH)
    assert source(health, "global-dining")["last_success_at"] == stamp(5)
    assert source(health, "table-for-two-availability")["checked_at"] == stamp(1)
    ids = {item["id"] for item in read_json(final / LEDGER)["updates"]}
    assert ids == {"seed", "refresh-event", "monitor-event"}


def test_same_field_health_conflict_fails_loudly_without_overwriting(remote: Path) -> None:
    refresh = clone(remote, "refresh")
    monitor = clone(remote, "monitor")
    edit(refresh, "global-dining", "status", "refreshed", "refresh-event")
    edit(monitor, "global-dining", "status", "stale", "monitor-event")

    assert commit_and_push(monitor, "chore: update source health").returncode == 0
    pushed = commit_and_push(refresh, "chore: refresh global dining data")
    assert pushed.returncode != 0
    assert "unresolved conflict in data/source-health.json" in pushed.stderr
    assert not (refresh / ".git" / "rebase-merge").exists()

    final = clone(remote, "final")
    assert source(read_json(final / HEALTH), "global-dining")["status"] == "stale"
