# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels
"""Blok 2 feedbackrun A 25-09 (FV-21 "crediteurnamen in meerdere schrijfwijzen"): een cluster dat uitsluitend op de
genormaliseerde naam matcht is ORANJE (twijfel — mens bevestigt, nooit automatisch samengevoegd), een gelijkende-maar-
andere naam is géén cluster, KvK-conflict = nooit; ná bevestiging koppelt een nieuwe factuur met een andere
schrijfwijze aan de voorkeur; lees-only CLI `crediteuren-naamclusters` in élke vorm uit het meetrecept."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import Engine, select, text

from app import cli
from app.crediteuren import afhandeling, naamclusters_cli, service
from app.crediteuren.voorkeur import voorkeur_van
from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.documenten import boekvoorstel as boekvoorstel_module
from app.documenten.crediteur_kenmerk import dubbele_crediteuren, kandidaten_met_kenmerken
from app.documenten.models import CrediteurKenmerk
from app.extractie.controle import match_vendor_met_waarschuwing
from app.sync.models import VendorCache
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.crediteuren.test_crediteuren_dubbelen import _vendor, andere_administratie  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401

FLOOR_A = uuid.UUID("f1000000-0000-0000-0000-000000000001")
FLOOR_B = uuid.UUID("f1000000-0000-0000-0000-000000000002")
UNI_NL = uuid.UUID("f1000000-0000-0000-0000-000000000003")
UNI_NL_2 = uuid.UUID("f1000000-0000-0000-0000-000000000004")
UNI_VERKOOP = uuid.UUID("f1000000-0000-0000-0000-000000000005")
OOST = uuid.UUID("f1000000-0000-0000-0000-000000000006")
WEST = uuid.UUID("f1000000-0000-0000-0000-000000000007")
HK_SON = uuid.UUID("f1000000-0000-0000-0000-000000000008")
HK_DUIVEN = uuid.UUID("f1000000-0000-0000-0000-000000000009")


def _actor(gebruiker_id: uuid.UUID) -> service.Actor:
    return service.Actor(id=gebruiker_id, rol=GebruikerRol.BEHEERDER)


@pytest.fixture
def naamclusters(
    admin_engine: Engine, administratie_id: uuid.UUID, andere_administratie: uuid.UUID, beheerder_id: uuid.UUID
) -> None:
    """Casus Floor (twee schrijfwijzen, adm 1), Universal Nederland (twee schrijfwijzen, adm 2) náást Universal
    Verkoop (gelijkend, anders), Bouwadvies Oost/West (gelijkend, anders), Hello Kitchen (zelfde naam, KvK-conflict)."""
    _vendor(admin_engine, administratie_id, FLOOR_A, "Floor Bouwliftenservice")
    _vendor(admin_engine, administratie_id, FLOOR_B, "Floor bouwliftenservice")
    _vendor(admin_engine, administratie_id, OOST, "Bouwadvies Oost")
    _vendor(admin_engine, administratie_id, WEST, "Bouwadvies West")
    _vendor(admin_engine, administratie_id, HK_SON, "Hello Kitchen Son")
    _vendor(admin_engine, administratie_id, HK_DUIVEN, "Hello Kitchen Son")
    _vendor(admin_engine, andere_administratie, UNI_NL, "Universal Nederland B.V.")
    _vendor(admin_engine, andere_administratie, UNI_NL_2, "Universal nederland B.V.")
    _vendor(admin_engine, andere_administratie, UNI_VERKOOP, "Universal Verkoop B.V.")
    with scoped_session(administratie_id, actor_id=beheerder_id) as session:
        session.add(
            CrediteurKenmerk(
                administratie_id=administratie_id, vendor_id=HK_SON, kvk_nummer="11111111", kvk_nummer_bron="factuur"
            )
        )
        session.add(
            CrediteurKenmerk(
                administratie_id=administratie_id, vendor_id=HK_DUIVEN, kvk_nummer="22222222", kvk_nummer_bron="factuur"
            )
        )


class TestNaamclusterIsOranje:
    def test_casus_floor_en_universal_een_oranje_cluster(
        self, naamclusters, administratie_id, andere_administratie, beheerder_id
    ) -> None:
        groepen = {
            (g.soort, g.sleutel): {c.vendor_id for c in g.crediteuren}
            for g in dubbele_crediteuren(administratie_id=administratie_id)
        }
        assert groepen[("naam", "floorbouwliftenservice")] == {FLOOR_A, FLOOR_B}
        clusters = {
            c.sleutel: c for c in service._clusters_voor_administratie(_actor(beheerder_id), administratie_id, "S")
        }
        floor = clusters["floorbouwliftenservice"]
        assert floor.soort == "naam" and service.CHIP_NAAM_BEVESTIG in floor.chips and not floor.kvk_verschilt
        assert not floor.eenduidig and afhandeling.REDEN_ALLEEN_NAAM in floor.classificatie_reden
        assert not floor.afmelden_primair  # bevestigen (Voorkeur kiezen…) is de primaire handeling
        uni = {
            c.sleutel: c for c in service._clusters_voor_administratie(_actor(beheerder_id), andere_administratie, "A")
        }
        assert set(uni) == {"universalnederland"}
        assert {k.vendor_id for k in uni["universalnederland"].crediteuren} == {UNI_NL, UNI_NL_2}
        assert not uni["universalnederland"].eenduidig

    def test_gelijkende_maar_andere_naam_is_geen_cluster(
        self, naamclusters, administratie_id, andere_administratie
    ) -> None:
        sleutels_1 = {g.sleutel for g in dubbele_crediteuren(administratie_id=administratie_id) if g.soort == "naam"}
        assert "bouwadviesoost" not in sleutels_1 and "bouwadvieswest" not in sleutels_1
        assert not any(
            OOST in {c.vendor_id for c in g.crediteuren} for g in dubbele_crediteuren(administratie_id=administratie_id)
        )
        sleutels_2 = {
            g.sleutel for g in dubbele_crediteuren(administratie_id=andere_administratie) if g.soort == "naam"
        }
        assert sleutels_2 == {"universalnederland"}  # Universal Verkoop hoort er niet bij

    def test_kvk_conflict_is_nooit_een_dubbel(self, naamclusters, administratie_id, beheerder_id) -> None:
        clusters = {
            c.sleutel: c for c in service._clusters_voor_administratie(_actor(beheerder_id), administratie_id, "S")
        }
        hk = clusters["hellokitchenson"]
        assert hk.kvk_verschilt and hk.afmelden_primair and service.CHIP_KVK_VERSCHILT in hk.chips
        assert service.CHIP_NAAM_BEVESTIG not in hk.chips
        assert not hk.eenduidig and "verschillend KvK-nummer" in hk.classificatie_reden

    def test_auto_afhandelen_slaat_naam_only_over_met_reden(self, naamclusters, administratie_id, beheerder_id) -> None:
        uit = afhandeling.auto_afhandelen(None, dry_run=False, administratie_id=administratie_id)
        stand = next(a for a in uit.administraties if a.administratie_id == administratie_id)
        assert stand.eenduidig == 0 and stand.afgehandeld == 0 and stand.twijfel >= 2
        # Niets gemarkeerd: beide Floor-records blijven bruikbaar.
        with scoped_session(administratie_id) as session:
            assert voorkeur_van(session, administratie_id=administratie_id, vendor_id=FLOOR_B) == FLOOR_B
            assert {k.id for k in kandidaten_met_kenmerken(session, administratie_id=administratie_id)} >= {
                FLOOR_A,
                FLOOR_B,
            }


class TestBevestigingKoppeltNieuweFactuur:
    def test_voor_bevestiging_geen_suggestie_bij_twee_schrijfwijzen_na_bevestiging_de_voorkeur(
        self, naamclusters, administratie_id, beheerder_id
    ) -> None:
        with scoped_session(administratie_id) as session:
            kandidaten = kandidaten_met_kenmerken(session, administratie_id=administratie_id)
        # Twee bruikbare records mét dezelfde sleutel: geen gok (nooit auto-toewijzen bij twijfel).
        assert match_vendor_met_waarschuwing("FLOOR BOUWLIFTENSERVICE B.V.", kandidaten)[0] is None
        # De mens bevestigt het cluster (bestaande afhandel-route: voorkeur FLOOR_A, verliezer FLOOR_B).
        service.afhandelen(
            _actor(beheerder_id),
            administratie_id=administratie_id,
            voorkeur_vendor_id=FLOOR_A,
            verliezer_vendor_ids=[FLOOR_B],
        )
        with scoped_session(administratie_id) as session:
            assert voorkeur_van(session, administratie_id=administratie_id, vendor_id=FLOOR_B) == FLOOR_A
            kandidaten = kandidaten_met_kenmerken(session, administratie_id=administratie_id)
            assert FLOOR_B not in {k.id for k in kandidaten}
            # Nieuwe factuur met afwijkende schrijfwijze → de voorkeur, geen nieuwe crediteur.
            assert match_vendor_met_waarschuwing("FLOOR BOUWLIFTENSERVICE B.V.", kandidaten)[0] == FLOOR_A
            assert (
                boekvoorstel_module._raad_vendor_id(
                    session, administratie_id=administratie_id, leverancier_naam="Floor Bouwliftenservice"
                )
                == FLOOR_A
            )
            rij = session.get(VendorCache, (FLOOR_B, administratie_id))
            assert rij is not None and rij.voorkeur_vendor_id == FLOOR_A  # gemarkeerd, nooit verwijderd
        # Het cluster is weg uit de lijst; de CLI telt 'm als bevestigd.
        telling = naamclusters_cli.telling_voor(administratie_id, "S")
        assert telling.bevestigd == 1 and "floorbouwliftenservice" not in {r.sleutel for r in telling.rijen}


class TestCliAlleVormenUitHetMeetrecept:
    def test_alles_detail_administratie_json_en_onbekend(
        self, naamclusters, administratie_id, andere_administratie, beheerder_id, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Vorm 1 — het nameting-onderdeel: kantoorbreed mét --detail.
        assert cli.main(["crediteuren-naamclusters", "--alles", "--detail"]) == 0
        uit = capsys.readouterr().out
        assert "Crediteuren-naamclusters —" in uit and "lees-only, geen RLZ-call" in uit
        assert "[open] Floor Bouwliftenservice / Floor bouwliftenservice" in uit
        assert "[kvk_conflict] Hello Kitchen Son / Hello Kitchen Son" in uit
        assert "TOTAAL 3 naam-cluster(s) in 2 van" in uit and "KvK-conflict 1" in uit
        assert "automatisch samengevoegd op naam: 0 (nooit)" in uit
        # Vorm 2 — één administratie op naamdeel, zonder detail.
        assert cli.main(["crediteuren-naamclusters", "--administratie", "Andere"]) == 0
        uit = capsys.readouterr().out
        assert "1 administratie(s)" in uit and "[open]" not in uit and "TOTAAL 1 naam-cluster(s) in 1 van 1" in uit
        # Vorm 3 — JSON op uuid, mét detail.
        assert (
            cli.main(
                ["crediteuren-naamclusters", "--administratie", str(andere_administratie), "--json-uit", "--detail"]
            )
            == 0
        )
        data = json.loads(capsys.readouterr().out)
        assert data["totaal"] == {"clusters": 1, "crediteuren": 2, "kvk_conflict": 0, "afgemeld": 0, "bevestigd": 0}
        assert sorted(data["administraties"][0]["rijen"][0]["namen"]) == [
            "Universal Nederland B.V.",
            "Universal nederland B.V.",
        ]
        assert data["fouten"] == []
        # Afmelden telt als afgemeld, cluster uit 'open'.
        service.afmelden(
            _actor(beheerder_id),
            administratie_id=andere_administratie,
            vendor_ids=[UNI_NL, UNI_NL_2],
            reden="twee vestigingen",
        )
        assert cli.main(["crediteuren-naamclusters", "--administratie", str(andere_administratie)]) == 0
        assert "afgemeld 1" in capsys.readouterr().out
        # Onbekende administratie = exit 2, zichtbaar.
        assert cli.main(["crediteuren-naamclusters", "--administratie", "bestaat-niet-xyz"]) == 2
        assert "onbekend" in capsys.readouterr().err

    def test_kapotte_administratie_stopt_de_rest_niet(
        self, naamclusters, administratie_id, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        echte = naamclusters_cli.telling_voor

        def kapot(aid: uuid.UUID, naam: str):  # noqa: ANN202
            if aid == administratie_id:
                raise RuntimeError("scope kapot")
            return echte(aid, naam)

        monkeypatch.setattr(naamclusters_cli, "telling_voor", kapot)
        meting = naamclusters_cli.meet(administratie=None)
        assert meting is not None and any("scope kapot" in f for f in meting.fouten)
        assert "fouten 1" in naamclusters_cli.totaalregel(meting)
        # Niets geschreven — geen afhandelingslog-rij, geen markering.
        with scoped_session(administratie_id) as session:
            assert (
                session.execute(select(VendorCache.voorkeur_vendor_id).where(VendorCache.id == FLOOR_B)).scalar_one()
                is None
            )
            assert (
                session.execute(text("SELECT count(*) FROM boekhouding.crediteur_dubbel_afhandeling")).scalar_one() == 0
            )
