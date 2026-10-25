#!/usr/bin/env python3
"""Run the guide agent eval cases against a live LLM and print a scorecard.

Only the LLM is live: slots use a synthetic snapshot around the clock and web
search replays reminders/evals/fixtures/web_results.json. Keys come from the
environment or an .env file and are never printed.

    reminders/.venv/bin/python scripts/eval_guide_agent.py --provider gemini --key-file PATH
    reminders/.venv/bin/python scripts/eval_guide_agent.py --provider gemini --model gemini-flash-latest
    reminders/.venv/bin/python scripts/eval_guide_agent.py --record-web --brave-env PATH
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reminders"))

from app import tft_agent, tft_guide  # noqa: E402
from evals import harness  # noqa: E402

PROVIDERS = {"gemini": ("GEMINI_API_KEY", tft_agent.gemini_chat)}
RATE_LIMIT_WAIT_SECONDS = 30
RATE_LIMIT_RETRIES = 3


def _env_value(name: str, path: Path) -> str:
    if os.getenv(name):
        return os.environ[name].strip()
    if not path.exists():
        return ""
    for line in path.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip("'\"")
    return ""


class PatientChat:
    """Retries provider rate limits and tracks the wait so latency excludes it."""

    def __init__(self, chat: tft_agent.Chat) -> None:
        self.chat = chat
        self.paused = 0.0
        self.rate_limited = 0

    def __call__(self, messages: list[dict], tools: list[dict], tool_choice: str, timeout: float) -> dict:
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                return self.chat(messages, tools, tool_choice, timeout)
            except tft_agent.AgentError as exc:
                if exc.code != "http_429" or attempt == RATE_LIMIT_RETRIES:
                    raise
                self.rate_limited += 1
                time.sleep(RATE_LIMIT_WAIT_SECONDS)
                self.paused += RATE_LIMIT_WAIT_SECONDS
        raise tft_agent.AgentError("http_429")


def _table(card: dict) -> str:
    rows = "\n".join(f"| {key} | {value} |" for key, value in card.items())
    return f"| Metric | Value |\n|---|---|\n{rows}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default="gemini")
    parser.add_argument("--model", default=tft_agent.GEMINI_MODEL)
    parser.add_argument("--key-file", type=Path, help="file holding only the provider key")
    parser.add_argument(
        "--http-timeout", type=float, default=0,
        help="override the per-call timeout (total budget = 2x) to score the model apart from latency",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between cases")
    parser.add_argument("--record-web", action="store_true")
    parser.add_argument("--brave-env", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    catalog = tft_guide.load_catalog()
    if args.record_web:
        key = _env_value("BRAVE_API_KEY", args.brave_env)
        if not key:
            raise SystemExit("BRAVE_API_KEY is not set")
        count = harness.record_web_fixtures(tft_agent.brave_search(key), catalog)
        print(f"Recorded {count} web fixtures to {harness.WEB_FIXTURE_PATH}")
        return 0
    key_name, factory = PROVIDERS[args.provider]
    key = args.key_file.read_text().strip() if args.key_file else _env_value(key_name, args.env)
    if not key:
        raise SystemExit(f"{key_name} is not set")
    chat = PatientChat(factory(key, args.model))
    if args.http_timeout:
        tft_agent.HTTP_TIMEOUT_SECONDS = args.http_timeout
        tft_agent.TOTAL_BUDGET_SECONDS = 2 * args.http_timeout
    now = datetime.now(timezone.utc)
    search = harness.fixture_search(catalog)
    # ci_only cases script adversarial model output and only run with the mock.
    cases = [case for case in harness.load_cases() if not case.get("ci_only")][: args.limit or None]
    results = []
    for index, case in enumerate(cases, start=1):
        result = harness.run_case(case, chat, now, catalog, search)
        results.append(result)
        last = result.turns[-1]
        failed = [name for name, value in result.checks.items() if value is False]
        print(f"[{index}/{len(cases)}] {case['id']}: {'pass' if result.passed else 'FAIL ' + ','.join(failed)} ({last.outcome})", flush=True)
        time.sleep(args.pause)
    card = harness.scorecard(results)
    card["rate_limit_retries"] = chat.rate_limited
    print(f"\n## Scorecard: {args.provider} {args.model} (timeout {tft_agent.HTTP_TIMEOUT_SECONDS:g}s)\n\n{_table(card)}")
    suffix = f"-t{args.http_timeout:g}" if args.http_timeout else ""
    out = ROOT / "reminders" / "evals" / "results" / f"{now.date().isoformat()}-{args.model}{suffix}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "provider": args.provider, "model": args.model, "now": now.isoformat(), "cases": len(cases),
        "http_timeout": tft_agent.HTTP_TIMEOUT_SECONDS,
    }
    out.write_text(json.dumps(harness.result_json(results, card, meta), ensure_ascii=False, indent=2, default=str))
    print(f"\nWrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
