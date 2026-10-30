from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scrape_global_dining.py"
SPEC = importlib.util.spec_from_file_location("scrape_global_dining", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

PDF = "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/2027_Platinum_TermsandConditions.pdf"


def test_terms_pdf_url_is_read_from_the_benefits_page():
    html = f'<a href="/en-sg/other.html">x</a><a href="{PDF}">Terms</a>'

    assert MODULE.terms_pdf_url(html) == PDF


def test_terms_pdf_url_resolves_relative_links():
    html = '<a href="/content/dam/amex/en-sg/benefits/the-platinum-card/2027_Platinum_TermsandConditions.pdf">T</a>'

    assert MODULE.terms_pdf_url(html) == PDF


@pytest.mark.parametrize("html", ["<p>no pdf</p>", f'<a href="{PDF}"></a><a href="{PDF.replace("2027", "2026")}"></a>'])
def test_terms_pdf_url_fails_closed_unless_exactly_one(html):
    with pytest.raises(RuntimeError, match="terms PDF link"):
        MODULE.terms_pdf_url(html)


def test_valid_until_comes_from_the_expiry_term():
    items = [
        {"number": 1, "title": "Maximum amount", "body": "The redemption period is from 2 March 2027 to 31 December 2027."},
        {"number": 8, "title": "Expiry or Withdrawal of Benefit", "body": "The benefit will expire on 31 December 2027. American Express can withdraw it."},
    ]

    assert MODULE.terms_valid_until(items) == "2027-12-31"


def test_valid_until_fails_closed_without_an_expiry_date():
    with pytest.raises(RuntimeError, match="expiry date"):
        MODULE.terms_valid_until([{"number": 8, "title": "Expiry", "body": "Ends soon."}])
