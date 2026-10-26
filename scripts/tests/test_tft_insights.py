import unittest
from datetime import date, timedelta

from scripts import tft_insights


RULES = tft_insights.load_rules()


def _obs(venue_id, meal, days):
    return [{"venue_id": venue_id, "meal": meal, "slot_date": d.isoformat()} for d in days]


class DaysLabelTests(unittest.TestCase):
    def test_wraps_around_the_week(self):
        self.assertEqual(tft_insights.days_label(["Sun", "Mon", "Tue", "Wed", "Thu"]), "Sun–Thu")

    def test_runs_and_pairs(self):
        self.assertEqual(tft_insights.days_label(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]), "Mon–Sat")
        self.assertEqual(tft_insights.days_label(["Sat", "Sun"]), "Sat, Sun")
        self.assertEqual(tft_insights.days_label(["Mon", "Wed"]), "Mon, Wed")
        self.assertEqual(tft_insights.days_label(tft_insights.WEEKDAYS), "Every day")
        self.assertEqual(tft_insights.days_label([]), "")


class BlackoutTests(unittest.TestCase):
    def test_program_holidays_and_eves(self):
        dates = {item["date"]: item["reason"] for item in tft_insights.blackout_dates("tft-x", RULES, date(2026, 11, 1))}
        self.assertEqual(dates["2026-11-07"], "Eve of Deepavali")
        self.assertEqual(dates["2026-11-09"], "Deepavali holiday")
        self.assertEqual(dates["2026-12-24"], "Christmas Eve")
        self.assertEqual(dates["2026-12-31"], "New Year's Eve")
        self.assertNotIn("2026-11-26", dates)

    def test_merchant_days_resolve_to_real_dates(self):
        stamford = {item["date"]: item["reason"] for item in tft_insights.blackout_dates("tft-15-stamford-restaurant", RULES, date(2026, 11, 1))}
        self.assertEqual(stamford["2026-11-26"], "Thanksgiving")
        self.assertEqual(stamford["2027-03-28"], "Easter Sunday")
        self.assertEqual(stamford["2027-05-09"], "Mother's Day")
        self.assertEqual(stamford["2027-06-20"], "Father's Day")
        colony = {item["date"]: item["reason"] for item in tft_insights.blackout_dates("tft-colony", RULES, date(2026, 11, 1))}
        self.assertEqual(colony["2027-02-09"], "Lunar New Year day 4")
        self.assertEqual(colony["2027-04-22"], "Secretaries' Week")
        brasserie = {item["date"]: item["reason"] for item in tft_insights.blackout_dates("tft-la-brasserie", RULES, date(2026, 11, 1))}
        self.assertEqual(brasserie["2027-05-08"], "Eve of Mother's Day")

    def test_undated_days_are_labelled_not_guessed(self):
        labels = tft_insights.merchant_blackout_labels("tft-vue", RULES)
        self.assertIn("Formula 1 (dates not given)", labels)

    def test_stale_terms_hide_blackout_dates(self):
        venue = {"id": "tft-colony"}
        result = tft_insights.venue_eligibility(venue, [], RULES, "0" * 64, date(2026, 11, 1))
        self.assertFalse(result["terms_current"])
        self.assertNotIn("blackout_dates", result)
        self.assertIsNone(result["published_days"])


class ObservedMealTests(unittest.TestCase):
    def test_regular_rare_and_never_days(self):
        start = date(2026, 8, 3)  # a Monday
        days = [start + timedelta(days=n) for n in range(56) if (start + timedelta(days=n)).weekday() in (6, 0, 1, 2, 3)]
        days.append(date(2026, 8, 7))  # one Friday
        venue = {"id": "v", "availability": {"meals": [{"meal": "Dinner", "slots": [{"time": "18:00"}, {"time": "20:30"}]}]}}
        [meal] = tft_insights.observed_meals(venue, _obs("v", "Dinner", days))
        self.assertEqual(meal["days_label"], "Sun–Thu")
        self.assertEqual(meal["rare_days"], ["Fri"])
        self.assertEqual(meal["never_days"], ["Sat"])
        self.assertEqual((meal["first_time"], meal["last_time"]), ("18:00", "20:30"))

    def test_too_few_dates_give_no_days(self):
        [meal] = tft_insights.observed_meals({"id": "v"}, _obs("v", "Lunch", [date(2026, 8, 3), date(2026, 8, 4)]))
        self.assertNotIn("days", meal)
        self.assertEqual(meal["dates_seen"], 2)


if __name__ == "__main__":
    unittest.main()


def _release_obs(n, lead, hour_utc, window_minutes, start=date(2026, 9, 1), meal="Lunch"):
    from datetime import datetime, timezone
    items = []
    for i in range(n):
        seen = datetime.combine(start + timedelta(days=i), datetime.min.time(), timezone.utc).replace(hour=hour_utc, minute=30)
        after = seen - timedelta(minutes=window_minutes)
        items.append({
            "venue_id": "v", "meal": meal, "lead_days": lead,
            "slot_date": (start + timedelta(days=i + lead)).isoformat(),
            "first_seen_at": seen.isoformat().replace("+00:00", "Z"),
            "checked_after": after.isoformat().replace("+00:00", "Z"),
        })
    return items


class ReleasePatternTests(unittest.TestCase):
    def test_rolling_window_with_precise_time(self):
        obs = _release_obs(10, 61, 4, 30)  # 12:15 SGT midpoint
        pattern = tft_insights.venue_release({"id": "v"}, obs, date(2026, 9, 11))
        [meal] = pattern["meals"]
        self.assertEqual(meal["rolling_lead_days"], 61)
        self.assertEqual(meal["time_of_day"]["label"], "between 11 am and 1 pm")
        self.assertEqual(pattern["lines"], [
            "New lunch dates open one day at a time, 61 days ahead, usually first seen between 11 am and 1 pm."
        ])
        self.assertEqual(pattern["best_time"], "lunch between 11 am and 1 pm, 61 days ahead")
        self.assertEqual(sum(pattern["hour_counts"]), 10)

    def test_wide_check_windows_never_give_a_time_of_day(self):
        obs = _release_obs(10, 61, 4, 240)
        pattern = tft_insights.venue_release({"id": "v"}, obs, date(2026, 9, 11))
        self.assertIsNone(pattern["meals"][0]["time_of_day"])
        self.assertEqual(pattern["precise_sightings"], 0)
        self.assertEqual(pattern["lines"], ["New lunch dates open one day at a time, 61 days ahead."])

    def test_quiet_venue_is_described_in_the_past(self):
        obs = _release_obs(10, 61, 4, 30)
        pattern = tft_insights.venue_release({"id": "v"}, obs, date(2026, 10, 30))
        self.assertTrue(pattern["lines"][0].startswith("Until 10 Sep, new lunch dates opened"))
        self.assertTrue(pattern["lines"][0].endswith("None since."))
        self.assertIsNone(pattern["best_time"])

    def test_scattered_leads_are_not_called_rolling(self):
        obs = [dict(item, lead_days=lead) for item, lead in zip(_release_obs(8, 0, 4, 30), [3, 9, 15, 20, 33, 40, 50, 61])]
        pattern = tft_insights.venue_release({"id": "v"}, obs, date(2026, 9, 10))
        self.assertIsNone(pattern["meals"][0]["rolling_lead_days"])
        self.assertEqual(pattern["lines"], [])

    def test_batches_are_reported(self):
        obs = _release_obs(6, 30, 4, 30)
        for item in obs:
            item["first_seen_at"] = obs[0]["first_seen_at"]
        pattern = tft_insights.venue_release({"id": "v"}, obs, date(2026, 9, 2))
        self.assertIn("6 new dates appeared at once on 1 Sep.", pattern["lines"])


class CheckedAfterTests(unittest.TestCase):
    def test_previous_check_bounds_each_sighting(self):
        from datetime import datetime, timezone
        from scripts import track_table_for_two_releases as tracker
        t = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        obs = [
            {"first_seen_at": "2026-10-25T12:15:00Z"},
            {"first_seen_at": "2026-08-20T00:00:00Z", "baseline": True},
        ]
        checks = [(t("2026-10-25T12:00:00"), t("2026-10-25T11:54:00")), (t("2026-10-25T12:16:00"), t("2026-10-25T12:10:00"))]
        self.assertEqual(tracker.annotate_checked_after(obs, checks), 1)
        self.assertEqual(obs[0]["checked_after"], "2026-10-25T11:54:00Z")
        self.assertNotIn("checked_after", obs[1])

    def test_new_observations_record_the_window(self):
        from datetime import datetime, timezone
        from scripts import track_table_for_two_releases as tracker
        seen = datetime(2026, 10, 26, 4, 0, tzinfo=timezone.utc)
        item = tracker.build_observation(("v", "V", "Lunch", "2026-12-26"), seen, seen - timedelta(minutes=21))
        self.assertEqual(item["checked_after"], "2026-10-26T03:39:00Z")
        later = tracker.build_observation(("v", "V", "Lunch", "2026-12-26"), seen, seen + timedelta(minutes=1))
        self.assertNotIn("checked_after", later)


def _entry(vid, amount, basis="++", per="person", serving="each"):
    return {"venue_id": vid, "menu_sha256": vid, "serving": serving,
            "extra_diner": {"amount": amount, "basis": basis, "per": per}}


class VerdictTests(unittest.TestCase):
    def setUp(self):
        self.entries = {e["venue_id"]: e for e in [
            _entry("a", 100), _entry("b", 100), _entry("c", 100), _entry("d", 128),
            _entry("e", 100, "nett"), _entry("f", 180, "nett", "pair_at_10_percent_off"),
        ]}
        self.typical = tft_insights.program_typical(self.entries)

    def test_typical_is_the_median_and_most_common_label(self):
        self.assertEqual(self.typical["label"], "S$100++")
        self.assertAlmostEqual(self.typical["per_head_nett"], 119.9, places=1)

    def test_tiers_and_lines(self):
        v = lambda vid: tft_insights.venue_verdict({"category": "restaurant"}, self.entries[vid], self.typical, None)
        self.assertEqual(v("d")["tier"], "higher")
        self.assertTrue(v("d")["line"].startswith("Good value: extra diners pay S$128++ a head"))
        self.assertEqual(v("a")["line"], "Typical value: extra diners pay S$100++ a head, the usual Table for Two price.")
        self.assertEqual(v("e")["tier"], "lower")
        self.assertIn("before a 10% discount", v("f")["line"])
        self.assertIn("so S$100 nett a head before the discount.", " ".join(v("f")["facts"]))

    def test_no_price_means_no_value_call(self):
        buffet = tft_insights.venue_verdict({"category": "buffet"}, None, self.typical, {"rating": 4.6, "review_count": 3131})
        self.assertIsNone(buffet["tier"])
        self.assertIn("no value call", buffet["line"])
        self.assertIn("Google 4.6 from 3,131 reviews", buffet["line"])
        shared = tft_insights.venue_verdict({"category": "restaurant"}, {"venue_id": "s", "serving": "shared", "extra_diner": None}, self.typical, None)
        self.assertEqual(shared["line"], "One set is shared between two, and Amex publishes no price to compare it with.")

    def test_changed_menu_drops_its_reviewed_price(self):
        prices = {"menus": [_entry("a", 100)]}
        self.assertEqual(tft_insights.reviewed_prices(prices, {"a": "a"}).keys(), {"a"})
        self.assertEqual(tft_insights.reviewed_prices(prices, {"a": "new-hash"}), {})
