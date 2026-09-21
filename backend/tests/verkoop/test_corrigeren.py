# ruff: noqa: F811, E501
""" "Corrigeren…" op een GEBOEKTE Vastly-verkoopfactuur (opdracht Peter 21-09): actie 19 op de SalesInvoice, registratie
`gestorneerd`, kop-boekstuknummer leeg, KLAAR_OM_TE_BOEKEN; de herboeking her-PUT op hetzelfde GUID en maakt de
registratie weer de actieve geboekte rij. Aangifte = blokkade zonder tegenboek-knop (creditnota in RLZ); (deels)
betaald = blokkade mét bank-link; vastgoed-administratie krijgt `factuur_gestorneerd` in dezelfde reeks."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, select, text

from app.db.session import scoped_session
from app.documenten import corrigeren
from app.documenten.models import DocumentStatus
from app.documenten.rlz_ids import rlz_sales_invoice_id
from app.verkoop import boeken as verkoop_boeken
from app.verkoop.models import VerkoopBoeking, VerkoopVoorstel
from tests.verkoop.conftest import (
    FakeVerkoopClient,
    administratie_id,  # noqa: F401
    beheerder_id,  # noqa: F401
    boeken_aan,  # noqa: F401
    bouw_vastly_verkoop_ubl,
    gescoopte_gebruiker,  # noqa: F401
    opslag,  # noqa: F401
    rekeningschema,  # noqa: F401
)
from tests.verkoop.test_boeken import _patch_client, _upload_en_bevestig

REDEN = "verkeerde huurperiode op de factuur — opnieuw boeken met juiste omschrijving"
AANGIFTE_INGEDIEND = {"Status": 2, "StartDate": "2026-07-01T00:00:00", "Date": "2026-09-30T00:00:00"}


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


@pytest.fixture
def geboekte_verkoop(
    monkeypatch, gescoopte_gebruiker, administratie_id, opslag, rekeningschema, boeken_aan
) -> tuple[uuid.UUID, FakeVerkoopClient]:
    client = FakeVerkoopClient()
    _patch_client(monkeypatch, client)
    document_id = _upload_en_bevestig(
        administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=bouw_vastly_verkoop_ubl()
    )
    verkoop_boeken.boek_verkoop_document(
        administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
    )
    return document_id, client


class TestCorrigeerVerkoop:
    def test_storno_registratie_en_herboeking(
        self, geboekte_verkoop, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, client = geboekte_verkoop
        guid = str(rlz_sales_invoice_id(document_id))
        assert client.sales_invoices[guid]["Status"] == 2

        t = corrigeren.toets(administratie_id=administratie_id, document_id=document_id, client=client)
        assert t.beschikbaar and t.soort == "verkoopfactuur" and t.stukken[0].label == "verkoopfactuur"

        r = corrigeren.corrigeer(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            reden=REDEN,
            client=client,
        )
        assert r.status is DocumentStatus.KLAAR_OM_TE_BOEKEN and r.boek_cyclus is None
        assert r.gestorneerd == [guid] and r.doel_pad == f"/verkoop/{administratie_id}/{document_id}"
        assert client.correcties == [guid] and client.sales_invoices[guid]["Status"] == 1
        assert _status(admin_engine, document_id) == "klaar_om_te_boeken"
        with scoped_session(administratie_id) as session:
            [reg] = session.scalars(select(VerkoopBoeking).where(VerkoopBoeking.document_id == document_id)).all()
            assert reg.status == "gestorneerd" and reg.storno_reden == REDEN
            assert session.get(VerkoopVoorstel, document_id).rlz_boekstuknummer is None

        # Tweede klik = niets extra.
        with pytest.raises(corrigeren.AlGecorrigeerd):
            corrigeren.corrigeer(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden=REDEN,
                client=client,
            )
        assert len(client.correcties) == 1

        # Herboeking: her-PUT op hetzelfde GUID (concept → geboekt), registratie weer actief.
        verkoop_boeken.boek_verkoop_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        assert _status(admin_engine, document_id) == "geboekt"
        assert client.sales_invoices[guid]["Status"] == 2
        with scoped_session(administratie_id) as session:
            [reg] = session.scalars(select(VerkoopBoeking).where(VerkoopBoeking.document_id == document_id)).all()
            assert reg.status == "geboekt" and reg.storno_reden is None
            assert session.get(VerkoopVoorstel, document_id).rlz_boekstuknummer

    def test_aangifte_blokkeert_zonder_tegenboek_knop(
        self, geboekte_verkoop, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, client = geboekte_verkoop
        client.aangiften = [AANGIFTE_INGEDIEND]
        # De fake zet Date uit de PUT; de factuurdatum van de UBL valt in Q3 2026.
        guid = str(rlz_sales_invoice_id(document_id))
        assert client.sales_invoices[guid]["Date"].startswith("2026-0")
        t = corrigeren.toets(administratie_id=administratie_id, document_id=document_id, client=client)
        [b] = t.blokkades
        assert b.code == "aangifte" and b.actie is None and "creditnota" in b.melding
        assert t.tegenboeken_beschikbaar is False
        with pytest.raises(corrigeren.CorrigerenNietToegestaan):
            corrigeren.corrigeer(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden=REDEN,
                client=client,
            )
        assert _status(admin_engine, document_id) == "geboekt" and client.correcties == []

    def test_betaald_blokkeert(self, geboekte_verkoop, administratie_id, gescoopte_gebruiker) -> None:
        document_id, client = geboekte_verkoop
        client.sales_invoices[str(rlz_sales_invoice_id(document_id))]["BasePaidAmount"] = 1210.0
        t = corrigeren.toets(administratie_id=administratie_id, document_id=document_id, client=client)
        [b] = t.blokkades
        assert (
            b.code == "afgeletterd"
            and b.actie == "bank"
            and b.actie_pad == f"/bank/{administratie_id}?zoek=VF-2026-0042"
        )

    def test_vastgoed_webhook_gestorneerd(
        self, geboekte_verkoop, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, client = geboekte_verkoop
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :id"), {"id": administratie_id}
            )
        corrigeren.corrigeer(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            reden=REDEN,
            client=client,
        )
        verkoop_boeken.boek_verkoop_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        corrigeren.corrigeer(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            reden=REDEN,
            client=client,
        )
        with admin_engine.connect() as conn:
            events = [
                r.event
                for r in conn.execute(
                    text(
                        "SELECT event FROM boekhouding.webhook_uitgaand WHERE document_id = :id ORDER BY aangemaakt_op"
                    ),
                    {"id": document_id},
                ).all()
            ]
        assert events == ["factuur_geboekt", "factuur_gestorneerd"]
