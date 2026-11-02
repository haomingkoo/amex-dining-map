from __future__ import annotations

import pytest

from scripts import tft_tiers


def test_tier_table_maps_both_projects() -> None:
    assert tft_tiers.TIER_ORDER == ("platinum", "centurion")
    assert tft_tiers.project_for("platinum") == "AMEXPlatSG"
    assert tft_tiers.project_for("centurion") == "AMEXCentSG"
    assert tft_tiers.tier_for_project("AMEXCentSG") == "centurion"
    assert tft_tiers.tier_for_project("AMEXNewSG") is None
    assert tft_tiers.TIERS["centurion"]["project_title"] == "AMEX Centurion SG"
    assert tft_tiers.roster_basis_for("platinum") == "diningcity_booking_project_confirmed"
    assert tft_tiers.roster_basis_for("centurion") == "diningcity_centurion_project_confirmed"
    with pytest.raises(KeyError):
        tft_tiers.project_for("gold")
