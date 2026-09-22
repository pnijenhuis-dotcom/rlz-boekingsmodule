"""Checks-cache — invalidatie op de bron (BUG Peter 21-09, Meyer/Belastingdienst 0015.21.664.V.51.0112).

Feit: "IBAN-wissel" stond Blokkerend "gecontroleerd 09:15 (ongewijzigd)" terwijl het IBAN ná 09:15 via de vier-ogen-
accordering al vertrouwd was — het gecachte externe rapport (0165) droeg de oude vertrouwde set en bleef 15 min geldig,
óók voor boeken.

Twee sloten + het boeken-pad:
- élk schrijfpad naar `leverancier_iban` (akkoord, bevestig_iban, seed/baseline, crediteur-samenvoegen) maakt in
  dezelfde transactie de cache-rijen van álle documenten van die crediteur ongeldig
  (`checks_extern.maak_ongeldig_voor_vendor`);
- de vingerafdruk draagt een hash van de gesorteerde vertrouwde set — een verouderd rapport matcht nooit meer;
- `voer_checks_uit` toetst de IBAN-wissel altijd tegen de LIVE set; boeken direct ná het akkoord slaagt binnen de
  15 min.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.documenten import boeken, boekvoorstel, checks_extern, iban_accordering, leverancier_iban
from app.documenten.models import DocumentStatus, IbanSoort
from app.documenten.storage import LokaleBestandsopslag
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.documenten.test_iban_wissel import ANDER_IBAN, VERTROUWD_IBAN, _document_met_iban, _iban_resultaat
from tests.documenten.test_vragen import _extra_gebruiker


def _cache_rij(admin_engine: Engine, document_id: uuid.UUID) -> tuple[str, int] | None:
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text("SELECT vingerafdruk FROM boekhouding.check_extern_cache WHERE document_id = :d"), {"d": document_id}
        ).first()
    return (rij.vingerafdruk, 1) if rij else None


def _is_ongeldig(admin_engine: Engine, document_id: uuid.UUID) -> bool:
    rij = _cache_rij(admin_engine, document_id)
    assert rij is not None, "verwacht een cache-rij"
    return rij[0].startswith(checks_extern.ONGELDIG_PREFIX)


@pytest.fixture
def vendor_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def geblokkeerd_document(
    administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag: LokaleBestandsopslag, vendor_id: uuid.UUID
) -> uuid.UUID:
    """Crediteur mét vertrouwde baseline, factuur mét een ANDER IBAN → de checks-run blokkeert en cachet het rapport
    (zoals het controlescherm om 09:15 deed)."""
    leverancier_iban.leg_baseline_vast(
        administratie_id=administratie_id, vendor_id=vendor_id, iban=VERTROUWD_IBAN, actor_id=gescoopte_gebruiker
    )
    document_id = _document_met_iban(
        administratie_id=administratie_id,
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
        vendor_id=vendor_id,
        factuur_iban=ANDER_IBAN,
    )
    rapport = boekvoorstel.voer_checks_uit(
        administratie_id=administratie_id, document_id=document_id, client=FakeBoekClient()
    )
    assert not _iban_resultaat(rapport).ok and rapport.geblokkeerd and rapport.extern_uit_cache is False
    return document_id


class TestVingerafdrukTweedeSlot:
    def test_vertrouwde_set_zit_in_de_vingerafdruk_gesorteerd_en_genormaliseerd(self) -> None:
        basis = dict(
            vendor_id=uuid.uuid4(), referentie="F-1", factuurdatum=None, totaalbedrag=Decimal("1"), factuur_iban=None
        )
        leeg = checks_extern.vingerafdruk(**basis)
        een = checks_extern.vingerafdruk(**basis, vertrouwde_ibans=[VERTROUWD_IBAN])
        twee = checks_extern.vingerafdruk(**basis, vertrouwde_ibans=[ANDER_IBAN, VERTROUWD_IBAN])
        assert leeg != een != twee
        # volgorde en spaties/hoofdletters doen er niet toe
        assert twee == checks_extern.vingerafdruk(
            **basis, vertrouwde_ibans=[VERTROUWD_IBAN.lower(), f"{ANDER_IBAN[:4]} {ANDER_IBAN[4:]}"]
        )


class TestInvalidatieOpDeBron:
    def test_vier_ogen_akkoord_maakt_de_cache_ongeldig_en_de_volgende_run_is_ok(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        geblokkeerd_document: uuid.UUID,
    ) -> None:
        assert not _is_ongeldig(admin_engine, geblokkeerd_document)
        accordeur = _extra_gebruiker(admin_engine, met_scope_op=administratie_id, beheerder_id=beheerder_id)
        iban_accordering.zet_accordeurs(
            administratie_id=administratie_id, actor_id=beheerder_id, accordeurs=[accordeur]
        )
        aanvraag = iban_accordering.bied_aan(
            administratie_id=administratie_id,
            document_id=geblokkeerd_document,
            actor_id=gescoopte_gebruiker,
            nieuw_iban=ANDER_IBAN,
            soort=IbanSoort.REGULIER,
        )
        data = iban_accordering.accordeer(
            administratie_id=administratie_id, accordering_id=aanvraag.id, actor_id=accordeur
        )
        assert data.document_status == DocumentStatus.TE_CONTROLEREN
        # Slot 1: de cache-rij is in de akkoord-transactie ongeldig gemarkeerd.
        assert _is_ongeldig(admin_engine, geblokkeerd_document)
        # De volgende run (binnen de 15 min) leest niet uit de cache en ziet het akkoord.
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=geblokkeerd_document, client=FakeBoekClient()
        )
        assert rapport.extern_uit_cache is False
        assert _iban_resultaat(rapport).ok, _iban_resultaat(rapport).melding
        # … en daarna cachet de verse run weer gewoon (vingerafdruk mét de nieuwe set is stabiel).
        rapport2 = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=geblokkeerd_document, client=FakeBoekClient()
        )
        assert rapport2.extern_uit_cache is True and _iban_resultaat(rapport2).ok

    def test_bevestig_iban_maakt_de_cache_ongeldig(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        geblokkeerd_document: uuid.UUID,
        vendor_id: uuid.UUID,
    ) -> None:
        leverancier_iban.bevestig_iban(
            administratie_id=administratie_id, vendor_id=vendor_id, iban=ANDER_IBAN, actor_id=gescoopte_gebruiker
        )
        assert _is_ongeldig(admin_engine, geblokkeerd_document)
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=geblokkeerd_document, client=FakeBoekClient()
        )
        assert rapport.extern_uit_cache is False and _iban_resultaat(rapport).ok

    def test_zelfs_met_oude_geldige_cache_rij_wint_de_live_set(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        geblokkeerd_document: uuid.UUID,
        vendor_id: uuid.UUID,
    ) -> None:
        """Slot 2 + boeken-pad: als een invalidatie-pad ooit vergeten wordt (hier gesimuleerd door de markering weg te
        halen), maakt de set-hash in de vingerafdruk het oude rapport tóch ongeldig; en zou zelfs dát falen, dan toetst
        de IBAN-wissel tegen de live set."""
        oud = _cache_rij(admin_engine, geblokkeerd_document)
        assert oud is not None
        leverancier_iban.bevestig_iban(
            administratie_id=administratie_id, vendor_id=vendor_id, iban=ANDER_IBAN, actor_id=gescoopte_gebruiker
        )
        # Simuleer een vergeten invalidatie: zet de oude vingerafdruk terug.
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.check_extern_cache SET vingerafdruk = :v WHERE document_id = :d"),
                {"v": oud[0], "d": geblokkeerd_document},
            )
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=geblokkeerd_document, client=FakeBoekClient()
        )
        assert rapport.extern_uit_cache is False  # set-hash verschilt → geen cache-hit
        assert _iban_resultaat(rapport).ok

    def test_maak_ongeldig_raakt_alleen_documenten_van_die_crediteur(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        geblokkeerd_document: uuid.UUID,
        vendor_id: uuid.UUID,
    ) -> None:
        andere_vendor = uuid.uuid4()
        ander_document = _document_met_iban(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=andere_vendor,
            factuur_iban=None,
        )
        boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=ander_document, client=FakeBoekClient()
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            n = checks_extern.maak_ongeldig_voor_vendor(session, administratie_id=administratie_id, vendor_id=vendor_id)
            assert n == 1
            # idempotent: een tweede keer markeert niets opnieuw
            assert (
                checks_extern.maak_ongeldig_voor_vendor(session, administratie_id=administratie_id, vendor_id=vendor_id)
                == 0
            )
        assert _is_ongeldig(admin_engine, geblokkeerd_document)
        assert not _is_ongeldig(admin_engine, ander_document)

    def test_al_vertrouwd_melding_noemt_de_vertrouwde_set(self) -> None:
        """De frontend herkent de 409 van `bied_aan` aan deze tekst en draait dan de checks vers (één bron voor de
        check-rij en het paneel eronder) — de tekst is daarmee een contract."""
        import inspect

        bron = inspect.getsource(iban_accordering.bied_aan)
        assert 'IbanAlVertrouwd("Dit IBAN staat al in de vertrouwde set van deze crediteur")' in bron


class TestBoekenDirectNaAkkoord:
    def test_boeken_binnen_de_15_min_na_bevestiging_slaagt(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        geblokkeerd_document: uuid.UUID,
        vendor_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.beheer import service as beheer_service

        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        # Vóór het akkoord: boeken blokkeert op de IBAN-wissel (uit de cache, modus AUTO).
        with pytest.raises(boeken.BoekenGeblokkeerdDoorChecks):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=geblokkeerd_document, actor_id=gescoopte_gebruiker
            )
        assert fake.puts == []
        leverancier_iban.bevestig_iban(
            administratie_id=administratie_id, vendor_id=vendor_id, iban=ANDER_IBAN, actor_id=gescoopte_gebruiker
        )
        # Direct daarna (ver binnen de 15 min): de boekactie ziet het akkoord en schrijft naar RLZ.
        resultaat = boeken.boek_document(
            administratie_id=administratie_id, document_id=geblokkeerd_document, actor_id=gescoopte_gebruiker
        )
        assert resultaat.rlz_boekstuknummer and len(fake.puts) == 1


class TestCliChecksCacheLegen:
    def test_cli_markeert_alle_rijen_van_de_administratie_en_dry_run_niet(
        self,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
        geblokkeerd_document: uuid.UUID,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from app.cli import main

        assert main(["checks-cache-legen", "--administratie", str(administratie_id), "--dry-run"]) == 0
        assert not _is_ongeldig(admin_engine, geblokkeerd_document)
        uit = capsys.readouterr().out
        assert "dry-run" in uit and "1 geldig" in uit
        assert main(["checks-cache-legen", "--administratie", str(administratie_id)]) == 0
        assert _is_ongeldig(admin_engine, geblokkeerd_document)
        assert "1 ongeldig gemaakt" in capsys.readouterr().out
        # Een tweede echte run vindt niets meer.
        assert main(["checks-cache-legen", "--administratie", str(administratie_id)]) == 0
        assert "0 ongeldig gemaakt" in capsys.readouterr().out

    def test_cli_eist_administratie_of_alles(self) -> None:
        from app.cli import main

        assert main(["checks-cache-legen"]) == 2

    def test_cli_alles_vorm_uit_het_meetrecept_dry_run_echt_dry_run(
        self,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
        geblokkeerd_document: uuid.UUID,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Regel 19-09: élke CLI-vorm die een meetrecept noemt is in de suite gedraaid. De nazorg van 22-09 draaide
        `--alles --dry-run` → `--alles` → `--alles --dry-run` op de job-image (productie: 78 administraties, 129 → 0);
        vóór deze test kende de suite alleen de `--administratie`-vorm."""
        from app.cli import main

        assert main(["checks-cache-legen", "--alles", "--dry-run"]) == 0
        uit = capsys.readouterr().out
        assert "dry-run" in uit and "administratie(s)" in uit and " 0 ongeldig gemaakt" in uit
        assert not _is_ongeldig(admin_engine, geblokkeerd_document)
        assert main(["checks-cache-legen", "--alles"]) == 0
        uit = capsys.readouterr().out
        assert _is_ongeldig(admin_engine, geblokkeerd_document)
        assert "dry-run" not in uit and " 0 ongeldig gemaakt" not in uit.splitlines()[-1]
        assert main(["checks-cache-legen", "--alles", "--dry-run"]) == 0
        assert capsys.readouterr().out.splitlines()[-1].endswith("0 geldig, 0 ongeldig gemaakt")
