from scripts.refresh_tabelog_ratings import oldest_checked_first, refreshed_signal

OLD = {"score_raw": 3.74, "honest_stars": 4.5, "review_count": 352, "url": "https://tabelog.com/tokyo/A1/A2/1/",
       "match_confidence": "auto_verified_72", "last_checked_at": "2026-03-31", "notes": "n"}


def test_refreshed_signal_updates_score_count_and_date():
    signal = refreshed_signal(OLD, {"rating_value": "3.29", "rating_count": "357"}, "2026-09-27")

    assert (signal["score_raw"], signal["honest_stars"], signal["review_count"], signal["last_checked_at"]) == (
        3.29, 3, 357, "2026-09-27")
    assert signal["match_confidence"] == OLD["match_confidence"]


def test_refreshed_signal_without_rating_returns_none():
    assert refreshed_signal(OLD, {"name": "x"}, "2026-09-27") is None


def test_refreshed_signal_follows_moved_page():
    detail = {"rating_value": "3.5", "rating_count": "10", "moved_from": OLD["url"],
              "url": "https://tabelog.com/en/tokyo/A1/A2/2/"}

    assert refreshed_signal(OLD, detail, "2026-09-27")["url"] == "https://tabelog.com/tokyo/A1/A2/2/"


def test_oldest_checked_first_rotates_least_recent_current_venues():
    signals = {
        "b": {"tabelog": {"last_checked_at": "2026-09-01"}},
        "a": {"tabelog": {"last_checked_at": "2026-04-10"}},
        "gone": {"tabelog": {"last_checked_at": "2026-01-01"}},
        "no-tabelog": {},
    }

    assert oldest_checked_first(signals, {"a", "b", "no-tabelog"}) == ["a", "b"]
