from scripts import send_table_for_two_alerts as alerts


def subscription(name="Alice"):
    return alerts.subscription_from_row(
        {"email": "a@example.com", "name": name, "party_size": 2, "sessions": ["Dinner"], "venues": ["any"]}, {}, "test"
    )


def slot(venue, day, time, meal="Dinner"):
    return {"venue_name": venue, "date": day, "time": time, "meal": meal, "max_seats": 4}


def test_slots_group_by_date_and_venue_with_capped_times():
    slots = [slot("Park90", "2026-10-27", t) for t in ("17:00", "17:30", "18:00", "18:30", "19:00", "19:30")]

    rows = alerts.slot_rows(slots)

    assert rows == [("Park90", "2026-10-27", "Dinner", ["17:00", "17:30", "18:00", "18:30", "19:00", "19:30"])]
    assert alerts.times_text(rows[0][3]) == "17:00, 17:30, 18:00, 18:30 +2 more"


def test_email_lists_a_capped_number_of_dates_then_counts_the_rest():
    days = [f"2026-11-{day:02d}" for day in range(1, 13)]
    message = alerts.build_email(subscription(), [slot("VUE", d, "19:00") for d in days], "s@example.com", "https://site/#/table-for-two")
    text = message.get_body(("plain",)).get_content()

    assert text.count("- VUE:") == alerts.EMAIL_DATES_SHOWN
    assert f"and {len(days) - alerts.EMAIL_DATES_SHOWN} more" in text
    assert "Sun, 1 Nov" in text


def test_subject_names_one_or_two_venues_and_counts_more():
    assert alerts.alert_subject([slot("Park90", "2026-10-27", "17:00")]) == "Table for Two: Park90 has tables open"
    assert alerts.alert_subject([slot("A", "d", "t"), slot("B", "d", "t")]) == "Table for Two: A and B have tables open"
    assert alerts.alert_subject([slot(v, "d", "t") for v in "ABC"]) == "Table for Two: 3 venues have tables open"


def test_html_escapes_venue_names_and_keeps_unsubscribe_link():
    message = alerts.build_email(
        subscription(), [slot("<b>Kee's</b>", "2026-10-27", "12:00")], "s@example.com", "https://site", unsubscribe_url="https://u/x"
    )
    html_body = message.get_body(("html",)).get_content()

    assert "<b>Kee" not in html_body and "&lt;b&gt;Kee" in html_body
    assert 'href="https://u/x"' in html_body


def test_alert_footer_links_privacy_and_contact():
    message = alerts.build_email(
        subscription(), [slot("VUE", "2026-10-27", "19:00")], "s@example.com", "https://site", unsubscribe_url="https://u/x"
    )

    assert alerts.PRIVACY_URL in message.get_body(("html",)).get_content()
    assert "privacy@kooexperience.com" in message.get_body(("plain",)).get_content()


def test_one_click_unsubscribe_header_is_on_by_default(monkeypatch):
    monkeypatch.delenv("ALERT_ONE_CLICK_UNSUBSCRIBE", raising=False)
    config = alerts.resend_config_from_env()

    message = alerts.build_email(
        subscription(), [slot("VUE", "2026-10-27", "19:00")], "s@example.com", "https://site",
        unsubscribe_url="https://u/x", one_click_unsubscribe=config["one_click_unsubscribe"],
    )

    assert message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
