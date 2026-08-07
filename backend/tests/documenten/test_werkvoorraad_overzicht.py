"""Werkvoorraad-klantenlijst met tellers + kopgegevens in de documentenlijst (mockup
#werkvoorraad "Overzicht per klant" → #klantpagina; browserreview 2026-08-07 punt 3)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.documenten import service
from app.documenten.models import Boekvoorstel
from app.documenten.storage import LokaleBestandsopslag
from app.sync.models import VendorCache


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, naam: str, inhoud: bytes):
    return service.upload_document(
        administratie_id=administratie_id, bestandsnaam=naam, inhoud=inhoud, actor_id=actor_id, opslag=opslag
    )


class TestWerkvoorraadOverzicht:
    def test_tellers_per_administratie_en_lege_administratie_telt_nul(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        _upload(administratie_id, gescoopte_gebruiker, opslag, "a.pdf", b"%PDF-1.4 a")  # te_controleren
        _upload(administratie_id, gescoopte_gebruiker, opslag, "b.pdf", b"%PDF-1.4 b")  # te_controleren

        lege_administratie = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Leeg', :rlz)"),
                {"id": lege_administratie, "rlz": f"rlz-{lege_administratie}"},
            )

        overzicht = service.werkvoorraad_overzicht(
            administratie_ids_met_naam=[(administratie_id, "Vol"), (lege_administratie, "Leeg")]
        )

        vol = next(k for k in overzicht if k.administratie_id == administratie_id)
        leeg = next(k for k in overzicht if k.administratie_id == lege_administratie)
        assert vol.te_controleren == 2
        assert vol.heeft_openstaand_werk is True
        assert leeg.heeft_openstaand_werk is False

    def test_geboekt_en_verwijderd_tellen_niet_als_openstaand(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        resultaat = _upload(administratie_id, gescoopte_gebruiker, opslag, "c.pdf", b"%PDF-1.4 c")
        # Terminale status rechtstreeks als schema-owner — de statusmachine-route is hier niet
        # de kern van de test.
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.document SET status = 'geboekt' WHERE id = :id"),
                {"id": resultaat.document_id},
            )

        overzicht = service.werkvoorraad_overzicht(administratie_ids_met_naam=[(administratie_id, "Adm")])
        assert overzicht[0].heeft_openstaand_werk is False


class TestLijstKopgegevens:
    def test_lijst_draagt_leverancier_totaalbedrag_en_factuurdatum(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        resultaat = _upload(administratie_id, gescoopte_gebruiker, opslag, "d.pdf", b"%PDF-1.4 d")
        vendor_id = uuid.uuid4()
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            session.add(
                VendorCache(
                    id=vendor_id,
                    administratie_id=administratie_id,
                    naam="Bouwmaat Nederland B.V.",
                    brondata={},
                )
            )
            session.add(
                Boekvoorstel(
                    document_id=resultaat.document_id,
                    vendor_id=vendor_id,
                    totaalbedrag=Decimal("1847.23"),
                    factuurdatum=date(2026, 6, 29),
                )
            )

        items = service.lijst_documenten(administratie_id=administratie_id)
        item = next(i for i in items if i.document.id == resultaat.document_id)
        assert item.leverancier == "Bouwmaat Nederland B.V."
        assert item.totaalbedrag == Decimal("1847.23")
        assert item.factuurdatum == date(2026, 6, 29)

    def test_zonder_boekvoorstel_blijven_kopgegevens_leeg(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        resultaat = _upload(administratie_id, gescoopte_gebruiker, opslag, "e.pdf", b"%PDF-1.4 e")
        items = service.lijst_documenten(administratie_id=administratie_id)
        item = next(i for i in items if i.document.id == resultaat.document_id)
        assert item.leverancier is None
        assert item.totaalbedrag is None
        assert item.factuurdatum is None

    def test_zonder_boekvoorstel_valt_terug_op_extractie_veldvoorstel(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        """Mockup: "Bedrag (uit extractie)" — de kolommen moeten al gevuld zijn vóórdat iemand
        het controlescherm opent (dus vóór er een opgeslagen Boekvoorstel-rij bestaat)."""
        resultaat = _upload(administratie_id, gescoopte_gebruiker, opslag, "f.pdf", b"%PDF-1.4 f")
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.document_gebeurtenis "
                    "(id, document_id, van_status, naar_status, actor_id, detail) "
                    "VALUES (:id, :doc, 'extractie_bezig', 'te_controleren', :actor, "
                    "CAST(:detail AS jsonb))"
                ),
                {
                    "id": uuid.uuid4(),
                    "doc": resultaat.document_id,
                    "actor": gescoopte_gebruiker,
                    "detail": (
                        '{"veldvoorstel": {"leverancier_naam": "Eneco Zakelijk", '
                        '"totaal_incl": "486.20", "factuurdatum": "2026-06-27"}}'
                    ),
                },
            )

        items = service.lijst_documenten(administratie_id=administratie_id)
        item = next(i for i in items if i.document.id == resultaat.document_id)
        assert item.leverancier == "Eneco Zakelijk"
        assert item.totaalbedrag == Decimal("486.20")
        assert item.factuurdatum == date(2026, 6, 27)
