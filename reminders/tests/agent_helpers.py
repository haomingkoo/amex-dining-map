"""Scripted LLM, slot snapshots and catalogue for guide agent tests."""

from __future__ import annotations

import copy
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from app import tft_agent

_FIXTURE = Path(__file__).parent / "fixtures" / "tft_guide_catalog-2026-09-24.json"
_CATALOG = json.loads(_FIXTURE.read_text(encoding="utf-8"))
NOW = max(
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    for value in (
        _CATALOG["release_source"]["updated_at"],
        _CATALOG["menu_source"]["checked_at"],
        _CATALOG["roster_checked_at"],
    )
) + timedelta(hours=1)
TODAY = NOW.astimezone(tft_agent.SGT).date()
INFO = {
    "tft-colony": {
        "description": "Buffet restaurant with seven open kitchens.",
        "cuisines": ["International"],
        "area": "Marina Bay/Boat Quay",
        "opening_hours": "Monday 6:30–10:30 am, 6:30–10:30 pm",
        "google": {"rating": 4.6, "review_count": 3131, "checked_on": "2026-08-30"},
    },
}


def catalog() -> dict:
    payload = copy.deepcopy(_CATALOG)
    for venue in payload["venues"]:
        if venue["id"] in INFO:
            venue["info"] = copy.deepcopy(INFO[venue["id"]])
    return payload


def next_weekday(weekday: int, after: date = TODAY) -> date:
    """The first given weekday strictly after `after`."""
    return after + timedelta(days=(weekday - after.weekday() - 1) % 7 + 1)


def snapshot(venue_id: str, slots: list[tuple[date, str, str, int]]) -> dict:
    """A fresh AMEXPlatSG snapshot: slots are (date, HH:MM, Lunch|Dinner, max seats)."""
    meals: dict[str, list[dict]] = {}
    for slot_date, slot_time, meal, seats in slots:
        meals.setdefault(meal, []).append(
            {"date": slot_date.isoformat(), "time": slot_time, "max_seats": seats}
        )
    return {
        "schema_version": 1,
        "source_project": "AMEXPlatSG",
        "generated_at": NOW.isoformat(),
        "venues": [
            {
                "id": venue_id,
                "project": "AMEXPlatSG",
                "status": "live_available",
                "checked_at": (NOW - timedelta(minutes=5)).isoformat(),
                "meals": [
                    {"meal": meal, "status": "available", "slots": items}
                    for meal, items in meals.items()
                ],
            }
        ],
    }


def call(name: str, **args: Any) -> dict:
    return {"tool_calls": [{"id": f"call-{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def calls(*items: tuple[str, dict]) -> dict:
    return {
        "tool_calls": [
            {"id": f"call-{index}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            for index, (name, args) in enumerate(items)
        ]
    }


def text(content: str) -> dict:
    return {"content": content}


Step = dict | Callable[[list[dict]], dict] | Exception


class ScriptedChat:
    """Plays back assistant messages and records what the agent sent."""

    def __init__(self, *steps: Step) -> None:
        self.steps = list(steps)
        self.requests: list[dict] = []

    def __call__(self, messages: list[dict], tools: list[dict], tool_choice: str, timeout: float) -> dict:
        self.requests.append(
            {"messages": copy.deepcopy(messages), "tools": tools, "tool_choice": tool_choice, "timeout": timeout}
        )
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, Exception):
            raise step
        return step(messages) if callable(step) else step

    def tool_outputs(self) -> list[str]:
        last = self.requests[-1]["messages"]
        return [message["content"] for message in last if message["role"] == "tool"]


def web_result(url: str, title: str, snippet: str, page_age: str | None = None) -> dict:
    item = {"url": url, "title": title, "description": snippet}
    if page_age:
        item["page_age"] = page_age
    return item


class FakeSearch:
    def __init__(self, results: list[dict] | Exception) -> None:
        self.results = results
        self.queries: list[str] = []

    def __call__(self, query: str, timeout: float) -> list[dict]:
        self.queries.append(query)
        if isinstance(self.results, Exception):
            raise self.results
        return self.results
