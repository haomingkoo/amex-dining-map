from __future__ import annotations

import json
import logging
import logging.config
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_uvicorn_info_uses_stdout_not_error_stream(capsys):
    config = json.loads((ROOT / "uvicorn-log-config.json").read_text())
    logging.config.dictConfig(config)

    logging.getLogger("uvicorn.error").info("startup-ready")

    captured = capsys.readouterr()
    assert "startup-ready" in captured.out
    assert captured.err == ""
