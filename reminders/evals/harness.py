"""Guide agent eval harness: relative dates, fixtures, case runner and scorecard.

Only the LLM is live in an eval run. Slots come from a synthetic snapshot built
around the injected clock, and web search replays recorded Brave results.
"""

from __future__ import annotations

import json
import re
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from app import db, telegram_bot_store, telegram_reminders, tft_agent, tft_guide

EVALS = Path(__file__).parent
CASES_PATH = EVALS / "guide_agent_cases.jsonl"
WEB_FIXTURE_PATH = EVALS / "fixtures" / "web_results.json"
PRINCIPAL = "user:eval"
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SLOT_DAYS = 35
GLOBAL_FORBIDDEN = ("UTC",)
# venue id -> (weekday, time, meal, max seats); venues not listed are live with no seats.
SLOT_PLAN: dict[str, list[tuple[int, str, str, int]]] = {
    "tft-colony": [(5, "12:00", "Lunch", 4), (5, "19:00", "Dinner", 4), (6, "19:00", "Dinner", 2), (2, "19:30", "Dinner", 2)],
    "tft-sarai": [(5, "12:30", "Lunch", 2), (6, "12:30", "Lunch", 4), (3, "12:00", "Lunch", 2)],
    "tft-kaya-at-the-standard": [(5, "19:00", "Dinner", 2), (4, "19:30", "Dinner", 4)],
    "tft-tanoke": [(day, "12:00", "Lunch", 4) for day in range(7)],
    "tft-estate": [(5, "12:00", "Lunch", 6), (6, "12:00", "Lunch", 6)],
    "tft-one-ninety": [(4, "19:00", "Dinner", 6)],
}
WEB_RECORD_KEYS = [
    ("tft-vue", "web", "dress code"),
    ("tft-polo-bar-steakhouse", "web", "dress code"),
    ("tft-colony", "web", "parking"),
    ("tft-kaya-at-the-standard", "web", "parking"),
    ("tft-colony", "community", "worth it"),
    ("tft-vue", "community", "set menu review"),
    ("tft-sarai", "community", "food review"),
    ("tft-tanoke", "community", "date night"),
]
TOKEN_RE = re.compile(r"\{@(\w+):([^}]+)\}")


# ---------------------------------------------------------------- relative dates


def resolve_token(name: str, today: date) -> Any:
    this_weekend, next_weekend = tft_agent.weekends(today)
    fixed = {
        "today": today,
        "tomorrow": today + timedelta(days=1),
        "past": today - timedelta(days=2),
        "this_weekend_start": this_weekend[0],
        "this_weekend_end": this_weekend[1],
        "next_weekend_start": next_weekend[0],
        "next_weekend_end": next_weekend[1],
    }
    if name in fixed:
        return fixed[name].isoformat()
    if "+" in name:
        base, _, days = name.partition("+")
        return (date.fromisoformat(resolve_token(base, today)) + timedelta(days=int(days))).isoformat()
    if name.startswith("plus_"):
        return (today + timedelta(days=int(name[5:]))).isoformat()
    prefix, _, weekday = name.partition("_")
    if prefix in {"next", "coming"} and weekday in WEEKDAYS:
        # coming_* may be today; next_* is strictly after today.
        offset = (WEEKDAYS.index(weekday) - today.weekday()) % 7
        if prefix == "next" and offset == 0:
            offset = 7
        return (today + timedelta(days=offset)).isoformat()
    if name == "sats_next_month":
        first = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        days = [first + timedelta(days=offset) for offset in range(31)]
        return [day.isoformat() for day in days if day.month == first.month and day.weekday() == 5]
    raise ValueError(f"unknown date token @{name}")


def resolve(value: Any, today: date) -> Any:
    if isinstance(value, str):
        if value.startswith("@"):
            return resolve_token(value[1:], today)
        return TOKEN_RE.sub(
            lambda match: date.fromisoformat(resolve_token(match.group(1), today)).strftime(match.group(2)),
            value,
        )
    if isinstance(value, list):
        return [resolve(item, today) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, today) for key, item in value.items()}
    return value


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------- fixtures


def slot_loader(now: datetime, catalog: dict) -> Callable[[], dict]:
    today = now.astimezone(tft_agent.SGT).date()
    venues = []
    for venue in catalog.get("venues") or []:
        plan = SLOT_PLAN.get(str(venue["id"]), [])
        meals: dict[str, list[dict]] = {}
        for offset in range(SLOT_DAYS):
            day = today + timedelta(days=offset)
            for weekday, slot_time, meal, seats in plan:
                if day.weekday() == weekday:
                    meals.setdefault(meal, []).append({"date": day.isoformat(), "time": slot_time, "max_seats": seats})
        venues.append(
            {
                "id": venue["id"],
                "project": "AMEXPlatSG",
                "status": "live_available" if meals else "live_no_seats",
                "checked_at": (now - timedelta(minutes=5)).isoformat(),
                "meals": [{"meal": meal, "status": "available", "slots": slots} for meal, slots in meals.items()],
            }
        )
    snapshot = {"schema_version": 1, "source_project": "AMEXPlatSG", "generated_at": now.isoformat(), "venues": venues}
    return lambda: snapshot


def _topic_class(topic: str) -> str:
    lowered = topic.casefold()
    if "dress" in lowered:
        return "dress"
    if "park" in lowered:
        return "parking"
    return "general"


def fixture_key(venue_id: str, source: str, topic: str) -> str:
    return f"{venue_id}|{source}|{_topic_class(topic)}"


def fixture_search(catalog: dict, path: Path = WEB_FIXTURE_PATH) -> tft_agent.Search:
    recorded = json.loads(path.read_text()) if path.exists() else {}
    names = sorted(((str(v["name"]), str(v["id"])) for v in catalog.get("venues") or []), key=lambda item: -len(item[0]))

    def search(query: str, _timeout: float) -> list[dict]:
        source = "community" if "site:" in query else "web"
        for name, venue_id in names:
            if query.startswith(f"{name} Singapore "):
                topic = query[len(name) + len(" Singapore "):]
                return recorded.get(fixture_key(venue_id, source, topic)) or recorded.get(
                    f"{venue_id}|{source}|general", []
                )
        return []

    return search


def record_web_fixtures(search: tft_agent.Search, catalog: dict, path: Path = WEB_FIXTURE_PATH) -> int:
    """Record real Brave results for the keys the cases use."""
    by_id = {str(v["id"]): str(v["name"]) for v in catalog.get("venues") or []}
    recorded = {}
    for venue_id, source, topic in WEB_RECORD_KEYS:
        query = tft_agent._search_queries(by_id[venue_id], topic, source)[0]
        recorded[fixture_key(venue_id, source, topic)] = [
            {key: item.get(key) for key in ("title", "url", "description", "page_age") if item.get(key)}
            for item in search(query, 10)
        ]
        time.sleep(1.1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recorded, ensure_ascii=False, indent=2) + "\n")
    return len(recorded)


# ---------------------------------------------------------------- running


@dataclass
class TurnRecord:
    text: str
    reply: str
    outcome: str
    tools: list[tuple[str, dict]]
    llm_calls: int
    latency_ms: float
    rejected_draft: str | None = None


@dataclass
class CaseResult:
    id: str
    turns: list[TurnRecord]
    checks: dict[str, bool | None]
    refuse_expected: bool | None
    refused: bool
    violations: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(value is not False for value in self.checks.values())


def run_case(
    case: dict,
    chat: tft_agent.Chat,
    now: datetime,
    catalog: dict,
    search: tft_agent.Search | None,
) -> CaseResult:
    today = now.astimezone(tft_agent.SGT).date()
    loader = slot_loader(now, catalog)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "eval.db"
        telegram_bot_store.init_db(path)
        conn = db.connect(path)
        try:
            telegram_reminders.init_db(conn)
            turns = _play(case, chat, now, catalog, search, loader, conn)
            return _evaluate(case, turns, conn, catalog, today)
        finally:
            conn.close()


def _play(case, chat, now, catalog, search, loader, conn) -> list[TurnRecord]:
    def drafter(fields: dict) -> str:
        return telegram_reminders.start_from_fields(conn, PRINCIPAL, catalog, now, fields)

    history: list[tuple[str, str]] = []
    turns = []
    for text in resolve(case["turns"], now.astimezone(tft_agent.SGT).date()):
        runs: list[tft_agent.AgentRun] = []
        paused_before = getattr(chat, "paused", 0.0)
        started = time.perf_counter()
        reply = telegram_reminders.handle_message(conn, PRINCIPAL, 1, text, catalog, now)
        if reply is None:
            def agent(message: str) -> str | None:
                runs.append(
                    tft_agent.run_detailed(
                        message, catalog, now, history=history, chat=chat,
                        search=search, drafter=drafter, slot_loader=loader,
                    )
                )
                return runs[-1].reply

            reply = tft_guide.handle_message(text, catalog, now, slot_loader=loader, agent=agent)
        elapsed = (time.perf_counter() - started - (getattr(chat, "paused", 0.0) - paused_before)) * 1000
        run = runs[-1] if runs else None
        turns.append(
            TurnRecord(
                text=text,
                reply=reply,
                outcome=run.outcome if run else "deterministic",
                tools=run.tools if run else [],
                llm_calls=run.llm_calls if run else 0,
                latency_ms=round(elapsed, 1),
                rejected_draft=run.rejected_draft if run else None,
            )
        )
        history = (history + [(text, reply[:telegram_bot_store.CONTEXT_TEXT_LIMIT])])[-3:]
    return turns


# ---------------------------------------------------------------- scoring


def _venue_id(value: Any, catalog: dict) -> str | None:
    if value in (None, "", "any"):
        return None
    matches = tft_guide.resolve_venue(str(value), catalog)
    return str(matches[0]["id"]) if len(matches) == 1 else f"unresolved:{value}"


def _effective_args(name: str, payload: dict, catalog: dict, today: date) -> dict | None:
    if name == "find_slots":
        try:
            args = tft_agent.SlotArgs.model_validate(payload)
            request = tft_agent._slot_request(args, today)
        except (ValueError, tft_agent.AgentError):
            return None
        return {
            "venue": _venue_id(args.venue, catalog),
            "party": request.party_size,
            "meal": args.meal,
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "weekend_only": request.weekend_only,
            "preferred_time": args.preferred_time,
        }
    effective = dict(payload)
    if "venue" in effective:
        effective["venue"] = _venue_id(effective["venue"], catalog)
    if name == "web_search":
        effective.setdefault("source", "web")
    return effective


def _tool_matches(expected: dict, calls: list[tuple[str, dict]], catalog: dict, today: date) -> bool:
    for name, payload in calls:
        if name != expected["name"]:
            continue
        actual = _effective_args(name, payload, catalog, today)
        if actual is not None and all(actual.get(key) == value for key, value in (expected.get("args") or {}).items()):
            return True
    return False


def _draft_ok(expected: dict, conn) -> bool:
    if expected.get("not_confirm"):
        confirm = conn.execute("SELECT 1 FROM telegram_reminder_conversations WHERE state = 'confirm'").fetchone()
        active = conn.execute("SELECT 1 FROM telegram_reminders").fetchone()
        return confirm is None and active is None
    table = "telegram_reminders" if expected.get("state") == "active" else "telegram_reminder_conversations"
    row = conn.execute(f"SELECT * FROM {table}").fetchone()  # noqa: S608 - fixed table names
    if row is None:
        return False
    actual = dict(row)
    actual["dates"] = json.loads(actual.get("dates") or "[]")
    return all(actual.get(key) == value for key, value in expected.items())


def _evaluate(case: dict, turns: list[TurnRecord], conn, catalog: dict, today: date) -> CaseResult:
    expect = resolve(case.get("expect") or {}, today)
    last = turns[-1]
    all_calls = [call for turn in turns[-1:] for call in turn.tools]
    expected_tools = expect.get("tools") or []
    checks: dict[str, bool | None] = {"tools": None, "args": None, "draft": None, "outcome": None}
    if expected_tools:
        names = {name for name, _ in all_calls}
        checks["tools"] = all(item["name"] in names for item in expected_tools)
        checks["args"] = all(_tool_matches(item, all_calls, catalog, today) for item in expected_tools)
    if expect.get("no_tools"):
        checks["tools"] = not all_calls or all(name == "off_topic" for name, _ in all_calls)
    if expect.get("draft_reminder") is not None:
        checks["draft"] = _draft_ok(expect["draft_reminder"], conn)
    if expect.get("outcome"):
        allowed = expect["outcome"] if isinstance(expect["outcome"], list) else [expect["outcome"]]
        checks["outcome"] = any(last.outcome == item or last.outcome.startswith(f"{item}:") for item in allowed)
    refused = last.outcome == "refused"
    refuse_expected = expect.get("refuse")
    if refuse_expected is not None:
        checks["refusal"] = refused == refuse_expected
    forbidden = [*GLOBAL_FORBIDDEN, *(expect.get("must_not_contain") or [])]
    violations = [item for turn in turns for item in forbidden if item.casefold() in turn.reply.casefold()]
    checks["must_not_contain"] = not violations
    return CaseResult(case["id"], turns, checks, refuse_expected, refused, violations)


def _mean(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(share * len(ordered)))], 1)


def scorecard(results: list[CaseResult]) -> dict[str, Any]:
    agent_turns = [turn for result in results for turn in result.turns if turn.outcome != "deterministic"]
    written = [turn for turn in agent_turns if turn.outcome == "agent" or turn.outcome.startswith(("guard:", "fallback:guard"))]
    guarded = [turn for turn in written if "guard:" in turn.outcome]
    refusal_cases = [r for r in results if r.refuse_expected is not None]
    tp = sum(r.refused and r.refuse_expected for r in refusal_cases)
    fp = sum(r.refused and not r.refuse_expected for r in refusal_cases)
    fn = sum(not r.refused and r.refuse_expected for r in refusal_cases)
    return {
        "cases": len(results),
        "case_pass_rate": _mean([r.passed for r in results]),
        "tool_selection": _mean([r.checks["tools"] for r in results if r.checks["tools"] is not None]),
        "argument_accuracy": _mean([r.checks["args"] for r in results if r.checks["args"] is not None]),
        "guard_pass_rate": _mean([turn not in guarded for turn in written]),
        "guard_fallbacks": len(guarded),
        "refusal_precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "refusal_recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "draft_accuracy": _mean([r.checks["draft"] for r in results if r.checks["draft"] is not None]),
        "must_not_contain_violations": sum(len(r.violations) for r in results),
        "agent_messages": len(agent_turns),
        "latency_p50_ms": _percentile([t.latency_ms for t in agent_turns], 0.5),
        "latency_p95_ms": _percentile([t.latency_ms for t in agent_turns], 0.95),
        "llm_calls_per_message": round(statistics.mean(t.llm_calls for t in agent_turns), 2) if agent_turns else None,
    }


def result_json(results: list[CaseResult], card: dict, meta: dict) -> dict:
    return {"meta": meta, "scorecard": card, "cases": [asdict(result) | {"passed": result.passed} for result in results]}


class MockChat:
    """Scripted assistant steps from a case's `mock` list; the last step repeats."""

    def __init__(self, steps: list[dict]) -> None:
        self.steps = list(steps)
        self.requests = 0

    def __call__(self, messages: list[dict], tools: list[dict], tool_choice: str, timeout: float) -> dict:
        self.requests += 1
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if "error" in step:
            raise tft_agent.AgentError(step["error"])
        if "text" in step:
            return {"content": step["text"]}
        return {
            "tool_calls": [
                {
                    "id": f"mock-{self.requests}",
                    "type": "function",
                    "function": {"name": step["tool"], "arguments": json.dumps(step.get("args") or {})},
                }
            ]
        }


def mock_chat(case: dict, today: date) -> MockChat:
    return MockChat(resolve(case["mock"], today))
