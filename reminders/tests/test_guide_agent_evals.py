"""CI subset of the guide agent evals: dataset cases replayed with a scripted LLM."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app import telegram_bot_routes, tft_agent
from evals import harness
from tests.agent_helpers import NOW, catalog
from tests.test_tft_agent_routes import llm_settings  # noqa: F401 - pytest fixture

TODAY = NOW.astimezone(tft_agent.SGT).date()
CASES = harness.load_cases()
MOCKED = [case for case in CASES if "mock" in case]


def test_dataset_is_well_formed():
    ids = [case["id"] for case in CASES]

    assert len(ids) == len(set(ids)) >= 60
    assert len(MOCKED) >= 15
    for case in CASES:
        harness.resolve(case, TODAY)


@pytest.mark.parametrize("case", MOCKED, ids=[case["id"] for case in MOCKED])
def test_mocked_case_passes(case):
    cat = catalog()

    result = harness.run_case(case, harness.mock_chat(case, TODAY), NOW, cat, harness.fixture_search(cat))

    assert result.passed, (result.checks, [(t.outcome, t.reply[:200]) for t in result.turns])


def test_scorecard_counts_refusals_and_guard_fallbacks():
    cat = catalog()
    picked = [case for case in MOCKED if case["id"] in {"refuse-integral", "guard-hallucinated-time", "colony-weekend"}]

    results = [harness.run_case(c, harness.mock_chat(c, TODAY), NOW, cat, None) for c in picked]
    card = harness.scorecard(results)

    assert card["refusal_precision"] == 1.0 and card["refusal_recall"] == 1.0
    assert card["guard_fallbacks"] == 1
    assert card["must_not_contain_violations"] == 0


def test_over_budget_case_is_basic_mode_without_llm(llm_settings, monkeypatch):  # noqa: F811
    case = next(case for case in MOCKED if case["id"] == "colony-weekend")
    monkeypatch.setattr(tft_agent, "groq_chat", lambda _key: pytest.fail("over budget must not call the LLM"))
    settings = replace(llm_settings, telegram_llm_user_limit_per_day=1)
    principal = "user:" + "e" * 64
    telegram_bot_routes._llm_allowed(settings, principal)

    reply = telegram_bot_routes._guide_answer(settings, principal, case["turns"][0])

    assert reply.startswith(telegram_bot_routes.BASIC_MODE)
    assert "UTC" not in reply
