"""Repository paths for tests that read files outside reminders/.

Found by walking up rather than counting parents, so the tests also run from
mutmut's copy at reminders/mutants/tests/, one level deeper than usual.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = next(path for path in Path(__file__).resolve().parents if (path / ".railway").is_dir())
REMINDERS = REPO_ROOT / "reminders"
