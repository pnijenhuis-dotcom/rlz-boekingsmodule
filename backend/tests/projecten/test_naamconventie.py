from __future__ import annotations

import pytest

from app.projecten.naamconventie import MAX_NAAM_LENGTE, OngeldigeProjectnaam, vorm_projectnaam


def test_whitespace_wordt_genormaliseerd() -> None:
    assert vorm_projectnaam("  Pand   Dorpsstraat\t1 \n") == "Pand Dorpsstraat 1"


def test_gewone_naam_blijft_ongewijzigd() -> None:
    assert vorm_projectnaam("Dorpsstraat 1, Zwolle") == "Dorpsstraat 1, Zwolle"


def test_lege_invoer_is_fout() -> None:
    with pytest.raises(OngeldigeProjectnaam, match="leeg"):
        vorm_projectnaam("   ")


def test_bag_id_wordt_geweigerd() -> None:
    # §2.1 hard: geen BAG-id in RLZ-projectnamen — 16-cijferige reeks = weigeren, nooit strippen.
    with pytest.raises(OngeldigeProjectnaam, match="BAG"):
        vorm_projectnaam("Pand 0193010000123456 Dorpsstraat")


def test_korte_cijferreeksen_zijn_gewoon_toegestaan() -> None:
    # Huisnummers/postcodes/jaartallen zijn legitiem — alleen de BAG-lengte is verdacht.
    assert vorm_projectnaam("Dorpsstraat 12-14 (8011AB) 2026") == "Dorpsstraat 12-14 (8011AB) 2026"


def test_te_lange_naam_wordt_geweigerd_niet_afgekapt() -> None:
    with pytest.raises(OngeldigeProjectnaam, match="te lang"):
        vorm_projectnaam("P" * (MAX_NAAM_LENGTE + 1))
