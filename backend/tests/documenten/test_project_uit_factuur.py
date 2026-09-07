"""Project uit de factuur in de boekvoorstel-prefill (blok 10 07-09, casus Spot Services: óns projectnummer staat op
de factuur). Kop-`proj` = default voor alle regels, regel-`proj` wint; exacte code = groen "uit factuur"; een
leveranciers-werknummer is de eerste keer oranje en ná één boeking groen (`leverancier_werknummer`, bron 'factuur');
meerduidig vult niets; de mens wint altijd; het loopt via het A10-autosave-pad (checks zien het project); zonder
projectplicht gebeurt er niets."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, text

from app.beheer import service as beheer_service
from app.config import settings
from app.db.session import scoped_session
from app.documenten import boeken, boekvoorstel, service
from app.documenten.models import DocumentGebeurtenis, DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld
from app.projecten import kantoor as projecten_kantoor
from app.projecten import match as project_match
from app.projecten.models import LeverancierWerknummer
from app.sync.models import ProjectCache, TaxRateCache, VendorCache
from tests.documenten.fake_rlz_client import FakeBoekClient

VENDOR_SPOT = uuid.UUID("33333333-0000-0000-0000-00000000570a")
HOOG_ID = uuid.UUID("55555555-0000-0000-0000-000000000021")
GB_KOSTEN = uuid.UUID("44444444-0000-0000-0000-000000004500")
P_TILBURG = uuid.UUID("aaaaaaaa-0000-0000-0000-000000026127")
P_KONING = uuid.UUID("aaaaaaaa-0000-0000-0000-000000026140")
P_DUBBEL = uuid.UUID("aaaaaaaa-0000-0000-0000-000000026141")
P_INACTIEF = uuid.UUID("aaaaaaaa-0000-0000-0000-000000025001")


def _veld(waarde: str | None, zekerheid: float = 0.93) -> AiVeld:
    return AiVeld(waarde=waarde, zekerheid=zekerheid)


class Scenario:
    """Wat de 'AI' voor de volgende upload leest — per test gezet (kop-proj + regel-proj's)."""

    kop_proj: str | None = None
    regel_proj: tuple[str | None, ...] = (None, None)
    # Uniek factuurnummer per upload: dezelfde crediteur + nummer + bedrag zou anders (terecht) als duplicaat
    # worden afgevoerd (medewerker-wens A 04-09, standaard AAN) — dat is niet wat deze tests toetsen.
    volgnummer: int = 0


def _extractie() -> AiFactuurExtractie:
    regels = [
        AiRegel(
            omschrijving="Steigerhuur week 34",
            netto_bedrag="1000.00",
            btw_bedrag="210.00",
            hoeveelheid="1",
            zekerheid=0.93,
            project_tekst=Scenario.regel_proj[0],
        ),
        AiRegel(
            omschrijving="Transport",
            netto_bedrag="150.00",
            btw_bedrag="31.50",
            hoeveelheid="1",
            zekerheid=0.93,
            project_tekst=Scenario.regel_proj[1],
        ),
    ]
    Scenario.volgnummer += 1
    return AiFactuurExtractie(
        kop={
            "leverancier_naam": _veld("Spot Services"),
            "factuurnummer": _veld(f"SS-2026-{Scenario.volgnummer:04d}"),
            "factuurdatum": _veld("2026-08-28"),
            "valuta": _veld("EUR"),
            "totaal_excl": _veld("1150.00"),
            "totaal_incl": _veld("1391.50"),
            "btw_bedrag": _veld("241.50"),
            "project_tekst": _veld(Scenario.kop_proj, zekerheid=0.9 if Scenario.kop_proj else 0.0),
        },
        regels=regels,
        bsn_verwijderd=0,
        volledig=True,
    )


@pytest.fixture
def omgeving(administratie_id: uuid.UUID, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    """AI-gate aan, projectplicht aan, stamgegevens (crediteur, btw, vier projecten waarvan één inactief)."""
    Scenario.kop_proj = None
    Scenario.regel_proj = (None, None)
    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )
    beheer_service.zet_project_verplicht(actor_id=beheerder_id, administratie_id=administratie_id, verplicht=True)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr("app.geheugen.regel_gb._client_voor", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.extractie.service.extraheer_inkoopfactuur",
        lambda pdf_bytes, *, client=None, verbruik_referentie=None, mail_context=None: _extractie(),
    )
    with scoped_session(administratie_id) as session:
        session.add(VendorCache(id=VENDOR_SPOT, administratie_id=administratie_id, naam="Spot Services", brondata={}))
        session.add(
            TaxRateCache(
                id=HOOG_ID,
                administratie_id=administratie_id,
                naam="NL, Hoog Tarief",
                percentage=Decimal("0.2100"),
                brondata={},
            )
        )
        for pid, naam, actief in (
            (P_TILBURG, "26127 Tilburg (Heijmans)", True),
            (P_KONING, "26140 Koningstraat (Confide)", True),
            (P_INACTIEF, "25001 Afgerond werk (Oud)", False),
        ):
            session.add(
                ProjectCache(id=pid, administratie_id=administratie_id, naam=naam, is_actief=actief, brondata={})
            )


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"spot-{uuid.uuid4()}.pdf",
        inhoud=f"%PDF-1.4 {uuid.uuid4()}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    ).document_id


def _open(
    administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> tuple[bool, boekvoorstel.BoekvoorstelData]:
    geschreven = boekvoorstel.persisteer_prefill_bij_openen(
        administratie_id=administratie_id, document_id=document_id, geopend_door=actor_id
    )
    return geschreven, boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)


def _snapshots(administratie_id: uuid.UUID, document_id: uuid.UUID) -> list[dict]:
    with scoped_session(administratie_id) as session:
        return [
            g.detail[boekvoorstel.PREFILL_SNAPSHOT_SLEUTEL]
            for g in session.scalars(
                select(DocumentGebeurtenis)
                .where(DocumentGebeurtenis.document_id == document_id)
                .order_by(DocumentGebeurtenis.tijdstip)
            )
            if g.detail and boekvoorstel.PREFILL_SNAPSHOT_SLEUTEL in g.detail
        ]


def _werknummers(administratie_id: uuid.UUID) -> list[LeverancierWerknummer]:
    with scoped_session(administratie_id) as session:
        rijen = session.scalars(select(LeverancierWerknummer).order_by(LeverancierWerknummer.werknummer)).all()
        session.expunge_all()
        return list(rijen)


def _sla_op_met_project(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    data: boekvoorstel.BoekvoorstelData,
    project_id: uuid.UUID,
) -> None:
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        vendor_id=data.vendor_id,
        referentie=data.referentie,
        factuurdatum=data.factuurdatum,
        totaalbedrag=data.totaalbedrag,
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=GB_KOSTEN,
                taxrate_id=HOOG_ID,
                project_id=project_id,
                netto_bedrag=r.netto_bedrag,
                btw_bedrag=r.btw_bedrag,
                omschrijving=r.omschrijving,
            )
            for r in data.regels
        ],
        regels_samenvoegen=False,
    )


class TestExacteCodeOpDeFactuur:
    def test_kop_proj_vult_alle_regels_groen_en_persisteert_bij_openen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        omgeving: None,
    ) -> None:
        Scenario.kop_proj = "Project 26140"
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)

        prefill = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert prefill.opgeslagen is False and prefill.vendor_id == VENDOR_SPOT
        assert [r.project_id for r in prefill.regels] == [P_KONING, P_KONING]  # kop = default voor álle regels
        assert all(r.project_bron == "factuur" for r in prefill.regels)
        assert all((r.prefill_herkomst or {}).get("project") == "factuur" for r in prefill.regels)
        assert (
            "26140" in (prefill.regels[0].project_bron_detail or "")
            and "Koningstraat" in prefill.regels[0].project_bron_detail
        )

        # Openen = autosave via het A10-pad (het project triggert), chip hersteld uit het snapshot.
        geschreven, data = _open(administratie_id, document_id, gescoopte_gebruiker)
        assert geschreven is True and data.opgeslagen is True and data.prefill_automatisch is True
        assert [r.project_id for r in data.regels] == [P_KONING, P_KONING]
        assert [r.project_bron for r in data.regels] == ["factuur", "factuur"]
        (snapshot,) = _snapshots(administratie_id, document_id)
        assert "project regel 1: factuur" in snapshot["triggers"] and "project regel 2: factuur" in snapshot["triggers"]
        assert snapshot["regels"][0]["project_bron"] == "factuur"

        # De projectplicht-check meldt geen ontbrekend project meer.
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=FakeBoekClient()
        )
        verplicht = next(r for r in rapport.resultaten if r.naam == "Verplichte velden")
        assert "project" not in verplicht.melding, verplicht.melding

        # Geen werknummer geleerd nodig — de eigen code is al groen; er staat niets in leverancier_werknummer.
        assert _werknummers(administratie_id) == []

    def test_regel_proj_wint_van_kop_proj(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        Scenario.kop_proj = "26140"
        Scenario.regel_proj = (None, "26127")
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert [r.project_id for r in prefill.regels] == [P_KONING, P_TILBURG]
        assert [r.project_tekst for r in prefill.regels] == ["26140", "26127"]

    def test_inactief_project_is_geen_kandidaat(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        Scenario.kop_proj = "25001"
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert all(r.project_id is None and r.project_bron is None for r in prefill.regels)

    def test_zonder_projectplicht_wordt_niets_gevuld(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        omgeving: None,
    ) -> None:
        beheer_service.zet_project_verplicht(actor_id=beheerder_id, administratie_id=administratie_id, verplicht=False)
        Scenario.kop_proj = "26140"
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert all(r.project_id is None and r.project_bron is None for r in prefill.regels)
        assert _open(administratie_id, document_id, gescoopte_gebruiker)[0] is False  # niets te persisteren


class TestMeerduidig:
    def test_twee_projecten_met_dezelfde_code_vult_niets_maar_noemt_ze(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        with scoped_session(administratie_id) as session:
            session.add(
                ProjectCache(
                    id=P_DUBBEL,
                    administratie_id=administratie_id,
                    naam="26140 Koningstraat fase 2 (Confide)",
                    is_actief=True,
                    brondata={},
                )
            )
        Scenario.kop_proj = "26140"
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        regel = prefill.regels[0]
        assert regel.project_id is None and regel.project_bron == "factuur_meerduidig"
        assert "Koningstraat (Confide)" in regel.project_bron_detail and "fase 2" in regel.project_bron_detail
        assert regel.prefill_herkomst is None or "project" not in regel.prefill_herkomst
        # Niets ingevuld = geen autosave-trigger vanuit het project.
        assert _open(administratie_id, document_id, gescoopte_gebruiker)[0] is False


class TestWerknummerEersteKeerOranjeDaarnaGroen:
    def test_onbekend_werknummer_geen_match_handmatige_koppeling_oranje_bevestigd_groen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        omgeving: None,
    ) -> None:
        Scenario.kop_proj = "SPOT-4711"
        # 1. Onbekend werknummer: geen code, geen mapping, geen fuzzy → leeg (de mens kiest).
        doc1 = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=doc1)
        assert all(r.project_id is None and r.project_bron is None for r in prefill.regels)

        # 2. Een (nog niet bevestigde) mapping — bv. door de kantoormodule als voorstel gezet — is ORANJE.
        werknummer_id = projecten_kantoor.voeg_werknummer_toe(
            administratie_id=administratie_id,
            project_id=P_KONING,
            actor_id=beheerder_id,
            vendor_id=VENDOR_SPOT,
            werknummer="SPOT-4711",
            bron="factuur",
            bevestigd=False,
        )
        doc2 = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=doc2)
        assert [r.project_id for r in prefill.regels] == [P_KONING, P_KONING]
        assert prefill.regels[0].project_bron == "factuur_onbevestigd"
        assert (prefill.regels[0].prefill_herkomst or {}).get("project") == "factuur_onbevestigd"
        assert "nog niet bevestigd" in prefill.regels[0].project_bron_detail
        geschreven, data = _open(administratie_id, doc2, gescoopte_gebruiker)
        assert geschreven is True and data.regels[0].project_bron == "factuur_onbevestigd"  # oranje triggert óók

        # 3. Ná bevestiging: groen.
        projecten_kantoor.bevestig_werknummer(
            administratie_id=administratie_id, werknummer_id=werknummer_id, actor_id=beheerder_id
        )
        doc3 = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=doc3)
        assert prefill.regels[0].project_id == P_KONING and prefill.regels[0].project_bron == "factuur"

    def test_boeken_leert_de_mapping_en_de_volgende_factuur_is_groen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        omgeving: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """De échte weg: de mens kiest het project bij een onbekend werknummer en boekt — boeken ís de bevestiging."""
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        Scenario.kop_proj = "Werk 4711-B"
        doc1 = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=doc1)
        assert all(r.project_id is None for r in prefill.regels)
        _sla_op_met_project(administratie_id, doc1, gescoopte_gebruiker, prefill, P_TILBURG)

        resultaat = boeken.boek_document(
            administratie_id=administratie_id, document_id=doc1, actor_id=gescoopte_gebruiker
        )
        assert resultaat.status == DocumentStatus.GEBOEKT

        (rij,) = _werknummers(administratie_id)
        assert (rij.vendor_id, rij.project_id, rij.werknummer, rij.bron, rij.bevestigd) == (
            VENDOR_SPOT,
            P_TILBURG,
            "Werk 4711-B",
            "factuur",
            True,
        )
        assert rij.bevestigd_door == gescoopte_gebruiker
        with admin_engine.connect() as conn:
            acties = (
                conn.execute(
                    text("SELECT actie FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip"),
                    {"id": rij.id},
                )
                .scalars()
                .all()
            )
        assert acties == ["werknummer_geleerd_uit_factuur"]

        # Volgende factuur van Spot Services met hetzelfde werknummer (andere schrijfwijze): groen.
        Scenario.kop_proj = "werk 4711 b"
        doc2 = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=doc2)
        assert [r.project_id for r in prefill.regels] == [P_TILBURG, P_TILBURG]
        assert prefill.regels[0].project_bron == "factuur"

        # Boekt de mens hem op een ánder project, dan wint de mens: de mapping wordt herschreven (audit oud→nieuw).
        _sla_op_met_project(administratie_id, doc2, gescoopte_gebruiker, prefill, P_KONING)
        boeken.boek_document(administratie_id=administratie_id, document_id=doc2, actor_id=gescoopte_gebruiker)
        (rij2,) = _werknummers(administratie_id)
        assert rij2.id == rij.id and rij2.project_id == P_KONING and rij2.bevestigd is True
        with admin_engine.connect() as conn:
            acties = (
                conn.execute(
                    text("SELECT actie FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip"),
                    {"id": rij.id},
                )
                .scalars()
                .all()
            )
        assert acties == ["werknummer_geleerd_uit_factuur", "werknummer_bevestigd_uit_factuur"]

    def test_eigen_projectcode_wordt_niet_als_werknummer_onthouden(
        self, administratie_id: uuid.UUID, omgeving: None, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            n = project_match.leer_werknummers_uit_boeking(
                session,
                administratie_id=administratie_id,
                document_id=uuid.uuid4(),
                vendor_id=VENDOR_SPOT,
                actor_id=gescoopte_gebruiker,
                regel_projecten=[
                    (P_KONING, "26140"),
                    (P_KONING, "26140 Koningstraat (Confide)"),
                    (None, "X-1"),
                    (P_KONING, None),
                ],
            )
        assert n == 0 and _werknummers(administratie_id) == []


class TestMensWint:
    def test_opgeslagen_keuze_van_de_mens_blijft_zonder_chip(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        Scenario.kop_proj = "26140"
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        _, data = _open(administratie_id, document_id, gescoopte_gebruiker)
        assert data.regels[0].project_id == P_KONING and data.regels[0].project_bron == "factuur"
        # De controleur kiest een ander project en slaat op.
        _sla_op_met_project(administratie_id, document_id, gescoopte_gebruiker, data, P_TILBURG)
        opnieuw = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert [r.project_id for r in opnieuw.regels] == [P_TILBURG, P_TILBURG]
        # Geen project-chip meer (de btw-chip "uit factuur" mag blijven: die waarde is ongewijzigd — A10-regel).
        assert all(r.project_bron is None and "project" not in (r.prefill_herkomst or {}) for r in opnieuw.regels)
        # Nog eens openen overschrijft de mens nooit.
        assert _open(administratie_id, document_id, gescoopte_gebruiker)[0] is False
        assert (
            boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
            .regels[0]
            .project_id
            == P_TILBURG
        )


class TestProjectTekstenPerRegel:
    def test_regel_wint_kop_default_en_samengevoegd_neemt_de_kop(self) -> None:
        regels = [
            boekvoorstel.BoekvoorstelRegelData(GB_KOSTEN, HOOG_ID, P_KONING, Decimal(1), Decimal(0), "a")
            for _ in range(2)
        ]
        veldvoorstel = {"project_tekst": "26140", "regels": [{"project_tekst": "26127"}, {"project_tekst": None}]}
        assert boeken._project_teksten_per_regel(veldvoorstel, regels, False) == [
            (P_KONING, "26127"),
            (P_KONING, "26140"),
        ]
        assert boeken._project_teksten_per_regel(veldvoorstel, regels, True) == [
            (P_KONING, "26140"),
            (P_KONING, "26140"),
        ]
        assert boeken._project_teksten_per_regel(None, regels, False) == [(P_KONING, None), (P_KONING, None)]
        # Aantal regels ≠ extractie (mens voegde een regel toe): alleen de kop is nog betrouwbaar.
        assert boeken._project_teksten_per_regel(veldvoorstel, regels[:1], False) == [(P_KONING, "26140")]
