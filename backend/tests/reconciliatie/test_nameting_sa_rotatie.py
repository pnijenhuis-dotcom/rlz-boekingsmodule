"""Blok 1 nametingen-run 10-09 (GCP_UITROL §F7 route A): jaarlijkse key-rotatie van het nameting-serviceaccount als
eenvoudige datum-check op `settings.nameting_sa_aangemaakt_op` — LET-OP (beheer-signaal → systeemmail) vanaf 30 dagen
vóór 12 maanden ná aanmaak, geen signaal zonder geregistreerde key."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.reconciliatie import automatiseringen as auto
from app.reconciliatie import teksten
from app.reconciliatie.run import Bevinding, is_beheer_signaal


def _b(kw: dict) -> Bevinding:
    return Bevinding(
        blok=kw["blok"],
        soort=kw["soort"],
        administratie_id=kw["administratie_id"],
        vingerafdruk=kw["vingerafdruk"],
        tekst=kw["tekst"],
        detail=kw["detail"],
    )


def test_geen_key_geen_signaal() -> None:
    assert auto.sa_key_rotatie_bevinding(nu=datetime(2027, 9, 1, tzinfo=UTC), aangemaakt_op=None) is None


def test_signaal_vanaf_30_dagen_voor_de_rotatiedatum_en_daarna_blijvend() -> None:
    aangemaakt = date(2026, 9, 10)
    assert auto.sa_key_rotatie_bevinding(nu=datetime(2027, 8, 1, tzinfo=UTC), aangemaakt_op=aangemaakt) is None
    kw = auto.sa_key_rotatie_bevinding(nu=datetime(2027, 8, 15, tzinfo=UTC), aangemaakt_op=aangemaakt)
    assert kw is not None and kw["soort"] == "let_op" and kw["administratie_id"] is None
    assert "rotatie 10-09-2027 (vervalt over 26 dagen)" in kw["tekst"]
    assert kw["detail"]["reden"] == auto.SA_KEY_ROTATIE and kw["detail"]["rotatie_op"] == "2027-09-10"
    laat = auto.sa_key_rotatie_bevinding(nu=datetime(2027, 10, 1, tzinfo=UTC), aangemaakt_op=aangemaakt)
    assert laat is not None and "21 dagen over de rotatiedatum" in laat["tekst"]
    # Vingerafdruk stabiel over dagen: de delta-motor mailt één keer.
    assert kw["vingerafdruk"] == laat["vingerafdruk"]
    # Beheer-signaal (systeemmail), leesbaar zonder technische sleutels.
    b = _b(kw)
    assert is_beheer_signaal(b)
    lees = teksten.leesbaar(b, administratie_naam=None)
    assert lees.titel.startswith("Nameting-serviceaccount") and "2027-09-10" in lees.wat and "§F7" in lees.doe
    assert not teksten.bevat_technische_sleutel(lees.titel + lees.wat + lees.doe)


def test_dag_29_of_meer_klemt_naar_28_bij_de_jaarsprong() -> None:
    kw = auto.sa_key_rotatie_bevinding(nu=datetime(2029, 2, 1, tzinfo=UTC), aangemaakt_op=date(2028, 2, 29))
    assert kw is not None and kw["detail"]["rotatie_op"] == "2029-02-28"
