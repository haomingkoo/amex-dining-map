"""Amex card tiers and the DiningCity Table for Two project each one books through."""

from __future__ import annotations

TIER_ORDER: tuple[str, ...] = ("platinum", "centurion")

TIERS: dict[str, dict] = {
    "platinum": {
        "project": "AMEXPlatSG",
        "project_title": "AMEX Platinum SG",
        "label": "Platinum",
        "roster_basis": "diningcity_booking_project_confirmed",
    },
    "centurion": {
        "project": "AMEXCentSG",
        "project_title": "AMEX Centurion SG",
        "label": "Centurion",
        "roster_basis": "diningcity_centurion_project_confirmed",
    },
}


def project_for(tier: str) -> str:
    return TIERS[tier]["project"]


def tier_for_project(code: str) -> str | None:
    return next((tier for tier, info in TIERS.items() if info["project"] == code), None)


def roster_basis_for(tier: str) -> str:
    return TIERS[tier]["roster_basis"]
