"""Blok 4 herstelrun "Basis eerst" 08-09 — duplicaat-/RLZ-bestaanscheck op het JUISTE moment.

(a) De RLZ-bestaanscheck (Entity + Reference + bedrag, cent-exact) draait zodra crediteur + referentie bekend zijn
    (UBL: bij intake; PDF: ná extractie) — een GEBOEKTE treffer buiten de module voert het document DIRECT af met
    reden "Al geboekt in RLZ (buiten de module) — boekstuk …", terugvindbaar in het archief (status
    afgevoerd_duplicaat, Afwijzing mét rlz-id, tijdlijn, audit). Een concept-treffer blijft het twijfelgeval onder de
    dagrem. Geen credential = zichtbaar overgeslagen (tijdlijnregel + log), nooit een blokkade.
(b) De module-check categorie (b) (genormaliseerde referentie + bedrag over álle crediteur-records) wordt ná de
    extractie van een PDF (wachtrij-worker) opnieuw geëvalueerd — zelfde afvoerregels als bij upload.
(c) De lijst telt afgevoerde duplicaten op het origineel (`afgevoerde_exemplaren`).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.config import settings
from app.db.session import scoped_session
from app.documenten import boekvoorstel, duplicaat_afvoer, duplicaatsignaal, service
from app.documenten.models import CrediteurKenmerk, DocumentStatus, DuplicaatSignaal, DuplicaatSignaalUitkomst
from app.documenten.storage import LokaleBestandsopslag
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld
from app.sync.models import VendorCache
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.intake.conftest import bouw_pdf

NLCIUS = (Path(__file__).parent.parent / "intake" / "fixtures" / "nlcius_accountant_ubl.xml").read_bytes()
REF = "F-2026-0042"
TOTAAL = Decimal("121.00")


@pytest.fixture
def standaard_aan(beheerder_id: uuid.UUID) -> None:
    beheer_service.zet_duplicaat_autoafvoer_platform(actor_id=beheerder_id, ingeschakeld=True)


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


def _afwijzing(admin_engine: Engine, document_id: uuid.UUID) -> dict | None:
    with admin_engine.connect() as conn:
        rij = (
            conn.execute(
                text(
                    "SELECT reden, automatisch, duplicaat_van_document_id, duplicaat_van_rlz_document_id, "
                    "duplicaat_van_referentie "
                    "FROM boekhouding.afwijzing WHERE document_id = :id ORDER BY afgewezen_op DESC LIMIT 1"
                ),
                {"id": document_id},
            )
            .mappings()
            .first()
        )
    return dict(rij) if rij else None


def _tijdlijn_details(admin_engine: Engine, document_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            d or {}
            for d in conn.execute(
                text(
                    "SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :id ORDER BY tijdstip, id"
                ),
                {"id": document_id},
            ).scalars()
        ]


def _audit_redenen(admin_engine: Engine, document_id: uuid.UUID, actie: str) -> list[str]:
    with admin_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT nieuwe_waarde->>'reden' FROM platform.audit_event WHERE tabel = 'document' "
                    "AND record_id = :id "
                    "AND actie = :actie ORDER BY tijdstip"
                ),
                {"id": document_id, "actie": actie},
            )
            .scalars()
            .all()
        )


def _upload_met_kop(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    vendor_id: uuid.UUID | None,
    referentie: str = REF,
    totaal: Decimal = TOTAAL,
) -> uuid.UUID:
    r = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=b"%PDF-1.4 " + uuid.uuid4().bytes,
        actor_id=actor_id,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=r.document_id,
        actor_id=actor_id,
        vendor_id=vendor_id,
        referentie=referentie,
        factuurdatum=date(2026, 8, 20),
        totaalbedrag=totaal,
        regels=[],
    )
    return r.document_id


def _treffer(rlz_id: uuid.UUID, *, status: int | None, referentie: str = REF, nummer: str = "RLZ-04-00004352") -> dict:
    t = {"id": str(rlz_id), "Reference": referentie, "InvoiceNumber": nummer}
    if status is not None:
        t["Status"] = {"id": status}
    return t


class TestRlzBestaanscheckAfvoer:
    def test_geboekte_treffer_buiten_de_module_voert_direct_af_buiten_de_dagrem_met_boekstuk(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        standaard_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            settings, "max_duplicaat_afvoer_per_dag_per_administratie", 0
        )  # rem dicht: alleen 'hard' gaat af
        vendor_id = uuid.uuid4()
        document_id = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        rlz_id = uuid.uuid4()
        duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id,
            document_id=document_id,
            client=FakeBoekClient(duplicaten=[_treffer(rlz_id, status=2)]),
        )
        assert duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=document_id) == [
            document_id
        ]
        assert _status(admin_engine, document_id) == DocumentStatus.AFGEVOERD_DUPLICAAT.value
        rij = _afwijzing(admin_engine, document_id)
        assert rij is not None and rij["automatisch"] is True
        assert rij["duplicaat_van_rlz_document_id"] == rlz_id and rij["duplicaat_van_document_id"] is None
        assert rij["reden"] == (
            f"Duplicaat — al geboekt in RLZ (buiten de module), boekstuk RLZ-04-00004352, referentie {REF}"
        )
        assert _audit_redenen(admin_engine, document_id, "duplicaat_afgevoerd") == [rij["reden"]]
        # Terugvindbaar in het archief: standaard uit de lijst, mét toggle erbij.
        standaard = {i.document.id for i in service.lijst_documenten(administratie_id=administratie_id)}
        assert document_id not in standaard
        met = {
            i.document.id for i in service.lijst_documenten(administratie_id=administratie_id, toon_afgehandeld=True)
        }
        assert document_id in met

    def test_concept_treffer_blijft_twijfelgeval_onder_de_dagrem_met_eigen_reden(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        standaard_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "max_duplicaat_afvoer_per_dag_per_administratie", 0)
        vendor_id = uuid.uuid4()
        document_id = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id,
            document_id=document_id,
            client=FakeBoekClient(duplicaten=[_treffer(uuid.uuid4(), status=1)]),
        )
        assert duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=document_id) == []
        assert _status(admin_engine, document_id) == DocumentStatus.TE_CONTROLEREN.value
        assert any("Volumerem" in r for r in _audit_redenen(admin_engine, document_id, "duplicaat_afvoer_geweigerd"))
        # Mét ruimte in de rem gaat het concept wél af — met de eerlijke reden "als concept".
        monkeypatch.setattr(settings, "max_duplicaat_afvoer_per_dag_per_administratie", 20)
        assert duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=document_id) == [
            document_id
        ]
        assert _afwijzing(admin_engine, document_id)["reden"].startswith(
            "Duplicaat — al aanwezig in RLZ als concept (buiten de module)"
        )

    def test_geboekte_treffer_wint_van_concept_bij_de_keuze_van_het_origineel(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        standaard_aan: None,
        admin_engine: Engine,
    ) -> None:
        document_id = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=uuid.uuid4()
        )
        geboekt = uuid.uuid4()
        duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id,
            document_id=document_id,
            client=FakeBoekClient(
                duplicaten=[
                    _treffer(uuid.uuid4(), status=1, nummer="CONCEPT"),
                    _treffer(geboekt, status=3, nummer="RLZ-04-9"),
                ]
            ),
        )
        duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=document_id)
        rij = _afwijzing(admin_engine, document_id)
        assert rij["duplicaat_van_rlz_document_id"] == geboekt and "boekstuk RLZ-04-9" in rij["reden"]

    def test_zonder_treffer_gebeurt_niets(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        standaard_aan: None,
        admin_engine: Engine,
    ) -> None:
        document_id = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=uuid.uuid4()
        )
        duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id, document_id=document_id, client=FakeBoekClient(duplicaten=[])
        )
        assert duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=document_id) == []
        assert _status(admin_engine, document_id) == DocumentStatus.TE_CONTROLEREN.value
        with scoped_session(administratie_id) as session:
            assert session.get(DuplicaatSignaal, document_id).uitkomst == DuplicaatSignaalUitkomst.GEEN.value
        assert _afwijzing(admin_engine, document_id) is None

    def test_zonder_credential_zichtbaar_overgeslagen_een_keer_en_geen_blokkade(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        standaard_aan: None,
        admin_engine: Engine,
    ) -> None:
        """De testadministratie heeft geen RLZ-credential: de opslag-hook kan de bestaanscheck niet draaien →
        uitkomst 'onbekend' + één tijdlijnregel (niet bij élke volgende veldopslag); het document blijft gewoon
        staan."""
        document_id = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=uuid.uuid4()
        )
        assert _status(admin_engine, document_id) == DocumentStatus.TE_CONTROLEREN.value
        with scoped_session(administratie_id) as session:
            rij = session.get(DuplicaatSignaal, document_id)
            assert rij.uitkomst == DuplicaatSignaalUitkomst.ONBEKEND.value and "niet te berekenen" in rij.melding
        notities = [
            d
            for d in _tijdlijn_details(admin_engine, document_id)
            if d.get(duplicaatsignaal.RLZ_BESTAANSCHECK_OVERGESLAGEN)
        ]
        assert len(notities) == 1
        assert notities[0]["reden"].startswith("RLZ-bestaanscheck (duplicaat buiten de module) overgeslagen:")
        # Tweede veldopslag: zelfde uitkomst → geen tweede notitie (geen tijdlijnruis).
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=uuid.uuid4(),
            referentie=REF,
            factuurdatum=date(2026, 8, 21),
            totaalbedrag=TOTAAL,
            regels=[],
        )
        assert (
            len(
                [
                    d
                    for d in _tijdlijn_details(admin_engine, document_id)
                    if d.get(duplicaatsignaal.RLZ_BESTAANSCHECK_OVERGESLAGEN)
                ]
            )
            == 1
        )

    def test_ubl_bij_intake_al_geboekt_in_rlz_wordt_direct_afgevoerd_zonder_openen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        standaard_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Blok 3 + 4a samen: UBL → crediteur op KvK → boekvoorstel gepersisteerd → RLZ-bestaanscheck in dezelfde
        intake → geboekte treffer → afgevoerd. Niemand hoeft het document te openen."""
        vendor_id = uuid.uuid4()
        with scoped_session(administratie_id) as session:
            session.add(VendorCache(id=vendor_id, administratie_id=administratie_id, naam="Andere naam", brondata={}))
            session.add(
                CrediteurKenmerk(
                    administratie_id=administratie_id,
                    vendor_id=vendor_id,
                    kvk_nummer="87654321",
                    kvk_nummer_bron="handmatig",
                )
            )
        rlz_id = uuid.uuid4()
        fake = FakeBoekClient(duplicaten=[_treffer(rlz_id, status=2, referentie="6099001", nummer="RLZ-04-00004400")])
        monkeypatch.setattr(duplicaatsignaal, "client_voor_rlz_admin_id", lambda admin_id: fake)
        r = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="6099001.xml",
            inhoud=NLCIUS,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        assert _status(admin_engine, r.document_id) == DocumentStatus.AFGEVOERD_DUPLICAAT.value
        rij = _afwijzing(admin_engine, r.document_id)
        assert rij["duplicaat_van_rlz_document_id"] == rlz_id
        assert rij["reden"] == (
            "Duplicaat — al geboekt in RLZ (buiten de module), boekstuk RLZ-04-00004400, referentie 6099001"
        )


def _fake_extractie(referentie: str, totaal: str) -> AiFactuurExtractie:
    netto = str((Decimal(totaal) / Decimal("1.21")).quantize(Decimal("0.01")))
    btw = str((Decimal(totaal) - Decimal(netto)).quantize(Decimal("0.01")))
    return AiFactuurExtractie(
        kop={
            "leverancier_naam": AiVeld("Onbekende Leverancier BV", 0.9),
            "factuurnummer": AiVeld(referentie, 0.95),
            "factuurdatum": AiVeld("2026-08-20", 0.95),
            "totaal_excl": AiVeld(netto, 0.9),
            "totaal_incl": AiVeld(totaal, 0.95),
            "btw_bedrag": AiVeld(btw, 0.9),
        },
        regels=[AiRegel(omschrijving="Werk", netto_bedrag=netto, btw_bedrag=btw, hoeveelheid=None, zekerheid=0.9)],
        bsn_verwijderd=0,
        volledig=True,
    )


class TestModuleCheckNaExtractie:
    def test_pdf_via_de_wachtrij_wordt_na_extractie_op_categorie_b_afgevoerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        standaard_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Bij upload is de referentie van een PDF nog leeg (geen (b) mogelijk); ná de worker-extractie levert de AI
        dezelfde referentie + hetzelfde totaal als een ouder document → direct afgevoerd (b), buiten de rem, mét
        kruisverwijzing naar het app-origineel; de lijst telt 'm op het origineel."""
        beheer_service.zet_ai_extractie_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        monkeypatch.setattr(settings, "max_duplicaat_afvoer_per_dag_per_administratie", 0)
        monkeypatch.setattr(
            "app.extractie.service.extraheer_inkoopfactuur",
            lambda pdf_bytes, *, client=None, verbruik_referentie=None, mail_context=None: _fake_extractie(
                "2026-0042", "121.00"
            ),
        )
        origineel = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=uuid.uuid4(),
            referentie="Factuur 2026-0042",
        )
        r = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="nakomer.pdf",
            inhoud=bouw_pdf(),
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        assert r.status == DocumentStatus.EXTRACTIE_WACHTRIJ  # upload zelf: nog geen referentie → geen (b)
        assert (
            _status(admin_engine, r.document_id) == DocumentStatus.AFGEVOERD_DUPLICAAT.value
        )  # worker (direct in de suite)
        statussen = [d for d in _tijdlijn_details(admin_engine, r.document_id)]
        assert any("veldvoorstel" in d for d in statussen)
        rij = _afwijzing(admin_engine, r.document_id)
        assert rij["duplicaat_van_document_id"] == origineel and rij["automatisch"] is True
        assert _status(admin_engine, origineel) == DocumentStatus.TE_CONTROLEREN.value
        # (c) lijst-teller op het origineel.
        items = {i.document.id: i for i in service.lijst_documenten(administratie_id=administratie_id)}
        assert items[origineel].afgevoerde_exemplaren == 1 and items[origineel].samengevoegde_exemplaren == 1
        assert r.document_id not in items
