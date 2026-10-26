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
