"""Factuurmatch fase 2 — pipeline-integratie (akkoord Peter 2026-08-21): match-run ná
extractie/voorstel-opslag/staat-goedkeuring, boeken-mét-expliciete-bevestiging ("geboekt
ondanks match-afwijking"), staten-verrekening ín de boek-transactie, weigering van de oude
per-leverancier-autoboek-opt-in voor gekoppelde crediteuren, werkvoorraad-teller en de
concept-mail aan de veldwerker."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import autoboeken, boeken, service as documenten_service
from app.documenten.afwijzen import wijs_af
from app.documenten.boekvoorstel import BoekvoorstelRegelData, sla_boekvoorstel_op
from app.documenten.storage import LokaleBestandsopslag
from app.sync.models import VendorCache
from app.uren import factuurmatch_mail, factuurmatch_pipeline, service as uren_service
from app.uren.models import Factuurmatch
from app.uren.service import OngeldigeInvoer, OngeldigeOvergang
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.documenten.test_ubl import _VOORBEELD_UBL
from tests.uren.test_factuurmatch import (
    FACTUURDATUM,
    koppel_crediteur,
    maak_goedgekeurde_staat,
)

VENDOR_ID = uuid.UUID("33333333-3333-3333-3333-333333333331")


@pytest.fixture(autouse=True)
def _opslag_naar_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """boek_document leest de bijlage via service._standaard_opslag() (settings-basismap) —
    dezelfde tmp-wissel als tests/documenten/conftest.py, via monkeypatch (vaste-testconfig)."""
    from app.config import settings

    monkeypatch.setattr(settings, "document_opslag_basismap", str(tmp_path / "documenten"))


@pytest.fixture
def opslag(tmp_path: Path) -> LokaleBestandsopslag:
    return LokaleBestandsopslag(tmp_path / "documenten")


@pytest.fixture
def boeken_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)


@pytest.fixture
def fake_rlz(monkeypatch: pytest.MonkeyPatch) -> FakeBoekClient:
    client = FakeBoekClient()
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: client)
    return client


@pytest.fixture
def vendor_bouwmaat(administratie_id: uuid.UUID) -> uuid.UUID:
    """De leverancier uit _VOORBEELD_UBL in de vendor-cache (exacte naammatch bij upload)."""
    with scoped_session(administratie_id) as session:
        session.add(
            VendorCache(
                id=VENDOR_ID, administratie_id=administratie_id, naam="Bouwmaat Nederland B.V.", brondata={}
            )
        )
    return VENDOR_ID


def maak_boekbare_factuur(
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    vendor_id: uuid.UUID,
    *,
    nettos: tuple[str, ...],
    factuurdatum: date = FACTUURDATUM,
) -> uuid.UUID:
    """Als test_factuurmatch.maak_factuur, maar mét GB/btw per regel zodat de harde checks
    (verplichte velden) 'm doorlaten en het document echt geboekt kan worden."""
    referentie = f"ZZP-{uuid.uuid4().hex[:8]}"
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"factuur-{referentie}.pdf",
        inhoud=f"%PDF-1.4 {referentie}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    )
    sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor_id,
        vendor_id=vendor_id,
        referentie=referentie,
        factuurdatum=factuurdatum,
        totaalbedrag=sum((Decimal(n) for n in nettos), Decimal("0")),
        regels=[
            BoekvoorstelRegelData(
                ledger_id=uuid.uuid4(),
                taxrate_id=uuid.uuid4(),
                project_id=None,
                netto_bedrag=Decimal(n),
                btw_bedrag=Decimal("0"),
                omschrijving="Uren",
            )
            for n in nettos
        ],
    )
    return resultaat.document_id


def _match_rij(admin_engine: Engine, document_id: uuid.UUID) -> dict | None:
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT uitkomst, staten_som_uren, factuur_bedrag, afwijking_bevestigd_door, "
                "afwijking_bevestigd_op FROM boekhouding.factuurmatch WHERE document_id = :id"
            ),
            {"id": document_id},
        ).mappings().one_or_none()
    return dict(rij) if rij else None


def _verrekende_staten(admin_engine: Engine, document_id: uuid.UUID) -> int:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM boekhouding.weekstaat WHERE verrekend_met_document_id = :id"),
            {"id": document_id},
        ).scalar_one()


class TestMatchRunPipeline:
    def test_voorstel_opslag_berekent_match_automatisch(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag, admin_engine
    ):
        """Fase 2: sla_boekvoorstel_op triggert de match-run zelf — geen expliciete
        bereken_match-aanroep meer nodig (dat was fase 1)."""
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="50")

        document_id = maak_boekbare_factuur(
            administratie_id, beheerder_id, opslag, vendor_id, nettos=("800.00",)
        )

        rij = _match_rij(admin_engine, document_id)
        assert rij is not None
        assert rij["uitkomst"] == "match"  # 16 uur × € 50 = € 800

    def test_ubl_upload_berekent_match_direct_na_extractie(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        vendor_bouwmaat,
        admin_engine,
    ):
        """De match bestaat al vóór er een boekvoorstel opgeslagen is: de ná-extractie-hook
        draait op het veldvoorstel-prefill (vendor-raad + UBL-totalen)."""
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_bouwmaat, beheerder_id, uurtarief="50")

        resultaat = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.xml",
            inhoud=_VOORBEELD_UBL,
            actor_id=beheerder_id,
            opslag=opslag,
        )

        rij = _match_rij(admin_engine, resultaat.document_id)
        assert rij is not None
        assert rij["factuur_bedrag"] is not None  # UBL-totalen leveren een toetsbaar bedrag

    def test_weekstaat_goedkeuring_herberekent_bestaande_match(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag, admin_engine
    ):
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="50")
        # Factuur vóór er een getekende staat is: 0 staten-uren vs € 800 = afwijking.
        document_id = maak_boekbare_factuur(
            administratie_id, beheerder_id, opslag, vendor_id, nettos=("800.00",)
        )
        assert _match_rij(admin_engine, document_id)["uitkomst"] == "afwijking"

        # Goedkeuring van de week (16 uur) triggert de herberekening → match.
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        rij = _match_rij(admin_engine, document_id)
        assert rij["uitkomst"] == "match"
        assert rij["staten_som_uren"] == Decimal("16.00")

    def test_expliciete_selectie_valideert_en_vervangt(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag, admin_engine
    ):
        """De "periode-keuze" (herbereken-endpoint): een expliciete weekstaat-selectie vervangt
        de default; een staat van een ander dan de betrokken ZZP'er wordt hard geweigerd."""
        staat_1 = maak_goedgekeurde_staat(
            administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder, week=30
        )
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder, week=31)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="50")
        document_id = maak_boekbare_factuur(
            administratie_id, beheerder_id, opslag, vendor_id, nettos=("800.00",)
        )
        # Default: beide weken (32 uur) → afwijking; selectie week 30 (16 uur) → match.
        assert _match_rij(admin_engine, document_id)["uitkomst"] == "afwijking"
        data = factuurmatch_pipeline.draai_match_voor_document(
            administratie_id=administratie_id, document_id=document_id, weekstaat_ids=[staat_1]
        )
        assert data.uitkomst == "match"

        vreemde = uuid.uuid4()
        with pytest.raises(Exception):  # noqa: B017 — NietGevonden (onbekende staat)
            factuurmatch_pipeline.draai_match_voor_document(
                administratie_id=administratie_id, document_id=document_id, weekstaat_ids=[vreemde]
            )


class TestBoekenMetBevestiging:
    def _setup_afwijking(
        self, administratie_id, project_id, zzper, uitvoerder, beheerder_id, opslag
    ) -> uuid.UUID:
        """Getekende staat van 16 uur × € 50, factuur van € 900 → afwijking van € 100."""
        maak_goedgekeurde_staat(administratie_id, zzper, project_id, uitvoerder)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, zzper, vendor_id, beheerder_id, uurtarief="50")
        return maak_boekbare_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("900.00",))

    def test_afwijking_zonder_bevestiging_weigert(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        boeken_aan,
        fake_rlz,
    ):
        document_id = self._setup_afwijking(
            administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
        )
        with pytest.raises(boeken.MatchAfwijkingBevestigingVereist) as excinfo:
            boeken.boek_document(
                administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id
            )
        assert excinfo.value.match_info["verschil_bedrag"] == "100.00"
        assert not fake_rlz.puts  # geweigerd vóór enige RLZ-schrijfactie

    def test_afwijking_met_bevestiging_boekt_en_markeert(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        boeken_aan,
        fake_rlz,
        admin_engine,
    ):
        document_id = self._setup_afwijking(
            administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
        )
        resultaat = boeken.boek_document(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=beheerder_id,
            match_afwijking_bevestigd=True,
        )
        assert resultaat.status.value == "geboekt"

        rij = _match_rij(admin_engine, document_id)
        assert rij["afwijking_bevestigd_door"] is not None
        with admin_engine.connect() as conn:
            detail_aanwezig = conn.execute(
                text(
                    "SELECT count(*) FROM boekhouding.document_gebeurtenis WHERE document_id = :id "
                    "AND naar_status = 'geboekt' AND detail ? 'geboekt_ondanks_match_afwijking'"
                ),
                {"id": document_id},
            ).scalar_one()
            audit = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event WHERE actie = 'match_afwijking_bevestigd' "
                    "AND record_id = :id"
                ),
                {"id": document_id},
            ).scalar_one()
        assert detail_aanwezig == 1
        assert audit == 1
        assert _verrekende_staten(admin_engine, document_id) == 1

    def test_match_boekt_zonder_poort_en_verrekent_staten(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        boeken_aan,
        fake_rlz,
        admin_engine,
    ):
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="50")
        document_id = maak_boekbare_factuur(
            administratie_id, beheerder_id, opslag, vendor_id, nettos=("800.00",)
        )
        boeken.boek_document(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id)
        assert _verrekende_staten(admin_engine, document_id) == 1

        # Dubbeltelling-preventie: een tweede identieke factuur ziet de verrekende staat niet
        # meer — 0 staten-uren vs € 800 = afwijking.
        tweede = maak_boekbare_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("800.00",))
        assert _match_rij(admin_engine, tweede)["uitkomst"] == "afwijking"

    def test_herberekening_wist_bevestiging(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        admin_engine,
    ):
        document_id = self._setup_afwijking(
            administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
        )
        # Bevestiging via de poort (zonder te boeken): direct op de rij zetten via de poort-API.
        boeken.toets_match_afwijking_poort(
            administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id, bevestigd=True
        )
        assert _match_rij(admin_engine, document_id)["afwijking_bevestigd_door"] is not None

        factuurmatch_pipeline.draai_match_voor_document(
            administratie_id=administratie_id, document_id=document_id
        )
        assert _match_rij(admin_engine, document_id)["afwijking_bevestigd_door"] is None

    def test_boeken_geblokkeerd_als_staat_elders_verrekend(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        boeken_aan,
        fake_rlz,
        admin_engine,
    ):
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="50")
        eerste = maak_boekbare_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("800.00",))
        tweede = maak_boekbare_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("800.00",))
        # Beide matches zagen dezelfde (onverrekende) staat; de eerste boekt en verrekent.
        boeken.boek_document(administratie_id=administratie_id, document_id=eerste, actor_id=beheerder_id)

        # De tweede leunt op een intussen elders verrekende staat → zichtbare 409, herberekenen.
        with pytest.raises(boeken.OngeldigeBoekpoging, match="herbereken"):
            boeken.boek_document(
                administratie_id=administratie_id,
                document_id=tweede,
                actor_id=beheerder_id,
                match_afwijking_bevestigd=True,
            )


class TestWeekstaatAfkeurBlokkade:
    def test_verrekende_staat_kan_niet_meer_afgekeurd(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        boeken_aan,
        fake_rlz,
        admin_engine,
    ):
        staat_id = maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="50")
        document_id = maak_boekbare_factuur(
            administratie_id, beheerder_id, opslag, vendor_id, nettos=("800.00",)
        )
        boeken.boek_document(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id)

        with pytest.raises(OngeldigeOvergang, match="verrekend"):
            uren_service.keur_week_af(
                administratie_id=administratie_id,
                weekstaat_id=staat_id,
                actor_id=gekoppelde_uitvoerder,
                reden="toch fout",
            )


class TestAutoboekWeigering:
    def test_optin_aanzetten_geweigerd_bij_veldwerker_koppeling(
        self, administratie_id, gekoppelde_zzper, beheerder_id, vendor_bouwmaat
    ):
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_bouwmaat, beheerder_id, uurtarief="50")
        with pytest.raises(autoboeken.VeldwerkerKoppelingBlokkeertOptIn):
            autoboeken.zet_leverancier_autoboeken(
                administratie_id=administratie_id,
                vendor_id=vendor_bouwmaat,
                actor_id=beheerder_id,
                ingeschakeld=True,
            )
        # UITzetten mag altijd (terugweg nooit blokkeren).
        assert (
            autoboeken.zet_leverancier_autoboeken(
                administratie_id=administratie_id,
                vendor_id=vendor_bouwmaat,
                actor_id=beheerder_id,
                ingeschakeld=False,
            )
            is False
        )

    def test_runtime_vangnet_weigert_oude_optin(
        self, administratie_id, gekoppelde_zzper, beheerder_id, vendor_bouwmaat, opslag, admin_engine
    ):
        """Een opt-in van vóór de koppeling (legacy) mag nooit stil doorwerken: de
        autoboek-poging weigert mét audit-reden."""
        autoboeken.zet_leverancier_autoboeken(
            administratie_id=administratie_id, vendor_id=vendor_bouwmaat, actor_id=beheerder_id, ingeschakeld=True
        )
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_bouwmaat, beheerder_id, uurtarief="50")

        documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.xml",
            inhoud=_VOORBEELD_UBL,
            actor_id=beheerder_id,
            opslag=opslag,
        )
        with admin_engine.connect() as conn:
            redenen = conn.execute(
                text("SELECT nieuwe_waarde->>'reden' FROM platform.audit_event WHERE actie = 'autoboeken_geweigerd'")
            ).scalars().all()
        assert any("veldwerker" in r for r in redenen)


class TestWerkvoorraadTeller:
    def test_match_afwijkingen_teller(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="50")
        maak_boekbare_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("800.00",))

        [klant] = documenten_service.werkvoorraad_overzicht(
            administratie_ids_met_naam=[(administratie_id, "Universal")]
        )
        assert klant.match_afwijkingen == 1  # geen staten → afwijking

        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        [klant] = documenten_service.werkvoorraad_overzicht(
            administratie_ids_met_naam=[(administratie_id, "Universal")]
        )
        assert klant.match_afwijkingen == 0  # herberekend → match


class TestMatchMail:
    def _setup(self, administratie_id, project_id, zzper, uitvoerder, beheerder_id, opslag) -> uuid.UUID:
        maak_goedgekeurde_staat(administratie_id, zzper, project_id, uitvoerder)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, zzper, vendor_id, beheerder_id, uurtarief="50")
        return maak_boekbare_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("900.00",))

    def test_concept_bevat_cijfers_en_afwijzingsreden(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        document_id = self._setup(
            administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
        )
        wijs_af(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=beheerder_id,
            reden="Bedrag sluit niet op de urenstaat",
            toegewezen_aan=beheerder_id,
        )
        concept = factuurmatch_mail.bouw_concept_mail(administratie_id=administratie_id, document_id=document_id)
        assert concept.ontvanger_e_mail.endswith("@test.local")
        assert "16,00 uur" in concept.tekst
        assert "€ 900,00" in concept.tekst
        assert "€ 100,00" in concept.tekst  # verschil
        assert "Bedrag sluit niet op de urenstaat" in concept.tekst
        assert "week 30" in concept.tekst

    def test_verzenden_legt_audit_en_tijdlijn_vast(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        admin_engine,
        monkeypatch: pytest.MonkeyPatch,
    ):
        document_id = self._setup(
            administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
        )
        verzonden: list[dict] = []
        monkeypatch.setattr(
            factuurmatch_mail.mail, "verzend_mail", lambda **kw: verzonden.append(kw)
        )
        naar = factuurmatch_mail.verzend_match_mail(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=beheerder_id,
            onderwerp="Vraag over uw factuur",
            tekst="Aangepaste tekst door kantoor.",
        )
        assert verzonden and verzonden[0]["naar"] == naar
        with admin_engine.connect() as conn:
            audit = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event WHERE actie = 'match_mail_verzonden' "
                    "AND record_id = :id"
                ),
                {"id": document_id},
            ).scalar_one()
            tijdlijn = conn.execute(
                text(
                    "SELECT count(*) FROM boekhouding.document_gebeurtenis WHERE document_id = :id "
                    "AND van_status = naar_status AND detail ? 'match_mail_verzonden'"
                ),
                {"id": document_id},
            ).scalar_one()
        assert audit == 1
        assert tijdlijn == 1

    def test_lege_tekst_weigert(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        document_id = self._setup(
            administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
        )
        with pytest.raises(OngeldigeInvoer):
            factuurmatch_mail.verzend_match_mail(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=beheerder_id,
                onderwerp="  ",
                tekst="",
            )


class TestKandidaatStaten:
    """Leesroute voor de periode-keuze in de match-sectie (fase 3): alle selecteerbare staten
    (goedgekeurd + onverrekend, zonder factuurdatum-grens) mét de markering welke in de
    huidige berekening meetellen."""

    def test_kandidaat_staten_met_in_match_markering(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        staat_1 = maak_goedgekeurde_staat(
            administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder, week=30
        )
        staat_2 = maak_goedgekeurde_staat(
            administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder, week=31
        )
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="50")
        document_id = maak_boekbare_factuur(
            administratie_id, beheerder_id, opslag, vendor_id, nettos=("800.00",)
        )
        # expliciete selectie: alleen week 30 telt mee in de huidige berekening
        factuurmatch_pipeline.draai_match_voor_document(
            administratie_id=administratie_id, document_id=document_id, weekstaat_ids=[staat_1]
        )
        staten = factuurmatch_pipeline.kandidaat_staten_voor_document(
            administratie_id=administratie_id, document_id=document_id
        )
        assert {s.weekstaat_id for s in staten} == {staat_1, staat_2}
        per_id = {s.weekstaat_id: s for s in staten}
        assert per_id[staat_1].in_match is True
        assert per_id[staat_2].in_match is False
        assert per_id[staat_1].uren == Decimal("16.00")
        assert per_id[staat_1].gebruiker_naam is not None

    def test_zonder_koppeling_lege_lijst(self, administratie_id, beheerder_id, opslag):
        document_id = maak_boekbare_factuur(
            administratie_id, beheerder_id, opslag, uuid.uuid4(), nettos=("100.00",)
        )
        assert (
            factuurmatch_pipeline.kandidaat_staten_voor_document(
                administratie_id=administratie_id, document_id=document_id
            )
            == []
        )
