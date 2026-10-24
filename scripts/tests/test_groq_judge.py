from scripts import match_tabelog_candidates as matcher


def test_groq_judge_requests_a_model_with_room_to_reason(monkeypatch):
    sent = {}

    def fake_post(url, payload, headers):
        sent.update(payload)
        return {"choices": [{"message": {"content": "1"}}]}

    monkeypatch.setattr(matcher, "load_env_value", lambda name: "test-key")
    monkeypatch.setattr(matcher, "post_json", fake_post)
    record = {"name": "Sushi Saito", "address": "Minato-ku", "phone": "03-3589-4412"}
    candidates = [{"name": "Sushi Saito", "address": "Minato", "url": "https://tabelog.com/x/", "confidence": 40}]

    matcher.groq_judge_match(record, candidates)

    assert sent["model"] == matcher.GROQ_MODEL
    assert sent["max_tokens"] >= 256 and sent["reasoning_effort"] == "low"
