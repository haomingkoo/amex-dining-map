import socket
import sys
import urllib.error
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import match_tabelog_candidates as matcher
from scripts import source_health, sync_plat_stay


def outage(_url: str) -> list[dict]:
    raise urllib.error.URLError("network down")


@pytest.fixture(autouse=True)
def reset_search_stats(monkeypatch):
    monkeypatch.setitem(matcher.SEARCH_STATS, "attempted", 0)
    monkeypatch.setitem(matcher.SEARCH_STATS, "failed", 0)


def test_fetch_search_logged_network_error_counts_failure_not_empty_result():
    result = matcher.fetch_search_logged(outage, "ddg_name", "https://example.test")

    assert result is None
    assert matcher.SEARCH_STATS == {"attempted": 1, "failed": 1}


def test_raise_if_searches_failed_all_failed_exits_nonzero():
    matcher.fetch_search_logged(outage, "ddg_name", "https://example.test")

    with pytest.raises(SystemExit):
        matcher.raise_if_searches_failed()


def test_raise_if_searches_failed_partial_outage_only_warns():
    matcher.fetch_search_logged(outage, "ddg_name", "https://example.test")
    matcher.fetch_search_logged(lambda _url: [], "yahoo_name", "https://example.test")

    matcher.raise_if_searches_failed()


def test_fetch_search_logged_non_network_error_propagates():
    def broken(_url: str) -> list[dict]:
        raise KeyError("parser bug")

    with pytest.raises(KeyError):
        matcher.fetch_search_logged(broken, "ddg_name", "https://example.test")


def test_retry_ddg_yahoo_search_outage_is_counted(monkeypatch):
    previous_timeout = socket.getdefaulttimeout()
    import retry_rejects_cached  # sets a global socket timeout on import

    socket.setdefaulttimeout(previous_timeout)
    monkeypatch.setattr(retry_rejects_cached, "fetch_ddg_search_candidates", outage)
    monkeypatch.setattr(retry_rejects_cached, "fetch_yahoo_search_candidates", outage)
    monkeypatch.setattr(retry_rejects_cached, "fetch_search_logged", matcher.fetch_search_logged)
    record = {"id": "r1", "name": "Sushi Test", "city": "Minato", "prefecture": "Tokyo"}

    assert retry_rejects_cached.ddg_yahoo_search(record, pause=0) == []
    assert matcher.SEARCH_STATS["failed"] == matcher.SEARCH_STATS["attempted"] > 0


def test_nominatim_429_exhausted_raises_instead_of_caching_miss(monkeypatch):
    error = urllib.error.HTTPError("https://x", 429, "Too Many Requests", {}, None)
    monkeypatch.setattr(sync_plat_stay.time, "sleep", lambda _s: None)

    with mock.patch.object(sync_plat_stay.urllib.request, "urlopen", side_effect=error) as urlopen:
        with pytest.raises(urllib.error.HTTPError):
            sync_plat_stay.geocode_query("Hotel Test, Singapore")

    assert urlopen.call_count == sync_plat_stay.NOMINATIM_ATTEMPTS


def test_source_health_load_json_corrupt_file_raises(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError):
        source_health.load_json(path, {})
