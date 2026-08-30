#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "fetch_tft_menus.py"
spec = importlib.util.spec_from_file_location("menus_mod", MODULE_PATH)
menus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(menus)


def main() -> None:
    assert menus.MENU_FILENAME_RE.match("HighHouse-Menu_Platinum.pdf")
    assert menus.MENU_FILENAME_RE.match("HighHouse-Menu_Centurion.pdf")
    assert menus.MENU_FILENAME_RE.match("Osteria-Mozza-Menu-Centurion.pdf")
    assert menus.filename_stem("Feather-Blade_Menu.pdf") == "Feather-Blade"
    assert menus.filename_stem("Osteria-Mozza-Menu-Centurion.pdf") == "Osteria-Mozza"
    assert menus.match_venue_to_filename("HighHouse", ["HighHouse-Menu_Centurion.pdf"]) == "HighHouse-Menu_Centurion.pdf"
    assert menus.direct_menu_candidate_filenames("Kaya", "platinum")[0] == "Kaya-Menu_Platinum.pdf"
    assert "CapitolBistro-Menu.pdf" in menus.direct_menu_candidate_filenames("CapitolBistro", "centurion")
    assert menus.has_buffet_tag({"category": "buffet"})
    assert menus.has_buffet_tag({"app_tags": ["Table for Two", "Buffet"]})
    assert not menus.has_buffet_tag({"category": "restaurant"})


if __name__ == "__main__":
    main()
