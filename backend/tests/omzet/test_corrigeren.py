# ruff: noqa: F811, E501
""" "Corrigeren…" op een GEBOEKT kassarapport (opdracht Peter 21-09): actie 19 op het kostprijsmemoriaal én de Receipt
(memoriaal eerst), registratie `gestorneerd` (de periode is weer vrij), KLAAR_OM_TE_BOEKEN; de herboeking her-PUT op
dezelfde GUID's en registreert een nieuwe geboekte rij. Geen afgeletterd-poort (entity-loze Receipt, geen open post);
aangifte op één van beide stukken blokkeert alles; faalt de Receipt-storno ná het memoriaal → HALF_GEBOEKT zichtbaar."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, select, text

from app.db.session import scoped_session
from app.documenten import corrigeren
from app.documenten.models import DocumentStatus
from app.omzet import boeken
from app.omzet.models import OmzetBoeking
from tests.omzet.conftest import (
    FakeOmzetClient,
    administratie_id,  # noqa: F401
    beheerder_id,  # noqa: F401
    boeken_aan,  # noqa: F401
    gescoopte_gebruiker,  # noqa: F401
    kassarapport_document,  # noqa: F401
    opslag,  # noqa: F401
    taxrate_vrijgesteld,  # noqa: F401
)
from tests.omzet.test_boeken import _patch_client, boekbaar_document  # noqa: F401

REDEN = "omzetcategorie 'punten' stond op vrijgesteld in plaats van 21 %"
AANGIFTE_INGEDIEND = {"Status": 3, "StartDate": "2025-07-01T00:00:00", "Date": "2025-09-30T00:00:00"}


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


@pytest.fixture
def geboekt_kassarapport(
    boekbaar_document, administratie_id, gescoopte_gebruiker, boeken_aan, monkeypatch
) -> tuple[uuid.UUID, FakeOmzetClient, boeken.OmzetBoekResultaat]:
    client = FakeOmzetClient()
    _patch_client(monkeypatch, client)
    r = boeken.boek_omzet_document(
        administratie_id=administratie_id, document_id=boekbaar_document, actor_id=gescoopte_gebruiker
    )
    return boekbaar_document, client, r


class TestCorrigeerKassarapport:
    def test_storno_beide_stukken_en_herboeking(
        self, geboekt_kassarapport, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, client, geboekt = geboekt_kassarapport
        verkoop, memoriaal = str(geboekt.verkoop_rlz_id), str(geboekt.memoriaal_rlz_id)
        assert client.sales_invoices[verkoop]["Status"] == 2 and client.manual_journals[memoriaal]["Status"] == 3

        t = corrigeren.toets(administratie_id=administratie_id, document_id=document_id, client=client)
        assert t.beschikbaar and [s.label for s in t.stukken] == ["omzetboeking (Receipt)", "kostprijsmemoriaal"]

        r = corrigeren.corrigeer(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            reden=REDEN,
            client=client,
        )
        assert (
            r.status is DocumentStatus.KLAAR_OM_TE_BOEKEN and r.doel_pad == f"/omzet/{administratie_id}/{document_id}"
        )
        assert client.correcties == [memoriaal, verkoop]  # memoriaal eerst, dan de Receipt
        assert client.sales_invoices[verkoop]["Status"] == 1 and client.manual_journals[memoriaal]["Status"] == 1
        assert _status(admin_engine, document_id) == "klaar_om_te_boeken"
        with scoped_session(administratie_id) as session:
            [reg] = session.scalars(select(OmzetBoeking).where(OmzetBoeking.document_id == document_id)).all()
            assert reg.status == "gestorneerd" and reg.storno_reden == REDEN

        with pytest.raises(corrigeren.AlGecorrigeerd):
            corrigeren.corrigeer(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden=REDEN,
                client=client,
            )
        assert len(client.correcties) == 2

        # Herboeking op dezelfde GUID's (concept → geboekt); nieuwe geboekte registratierij, de oude blijft als historie.
        r2 = boeken.boek_omzet_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        assert r2.status is DocumentStatus.GEBOEKT and str(r2.verkoop_rlz_id) == verkoop
        assert client.sales_invoices[verkoop]["Status"] == 2 and client.manual_journals[memoriaal]["Status"] == 3
        with scoped_session(administratie_id) as session:
            statussen = sorted(
                b.status for b in session.scalars(select(OmzetBoeking).where(OmzetBoeking.document_id == document_id))
            )
        assert statussen == ["geboekt", "gestorneerd"]

    def test_aangifte_op_het_memoriaal_blokkeert_alles(
        self, geboekt_kassarapport, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, client, _ = geboekt_kassarapport
        client.aangiften = [AANGIFTE_INGEDIEND]  # periode-einde 21-09-2025 valt in Q3 2025
        t = corrigeren.toets(administratie_id=administratie_id, document_id=document_id, client=client)
        assert not t.beschikbaar and {b.code for b in t.blokkades} == {"aangifte"}
        assert all(b.actie is None and "creditnota" in b.melding for b in t.blokkades)
        with pytest.raises(corrigeren.CorrigerenNietToegestaan):
            corrigeren.corrigeer(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden=REDEN,
                client=client,
            )
        assert client.correcties == [] and _status(admin_engine, document_id) == "geboekt"

    def test_geen_afgeletterd_poort_voor_een_receipt(self, geboekt_kassarapport, administratie_id) -> None:
        document_id, client, geboekt = geboekt_kassarapport
        client.sales_invoices[str(geboekt.verkoop_rlz_id)]["BasePaidAmount"] = 22463.36
        t = corrigeren.toets(administratie_id=administratie_id, document_id=document_id, client=client)
        assert t.beschikbaar

    def test_receipt_storno_faalt_na_memoriaal_is_half_geboekt(
        self, geboekt_kassarapport, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, client, geboekt = geboekt_kassarapport
        client.faal_op = "storno_verkoop"
        with pytest.raises(corrigeren.CorrigerenMislukt, match="al wél teruggedraaid"):
            corrigeren.corrigeer(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden=REDEN,
                client=client,
            )
        assert client.manual_journals[str(geboekt.memoriaal_rlz_id)]["Status"] == 1
        assert client.sales_invoices[str(geboekt.verkoop_rlz_id)]["Status"] == 2
        assert _status(admin_engine, document_id) == "geboekt"
        with scoped_session(administratie_id) as session:
            [reg] = session.scalars(select(OmzetBoeking).where(OmzetBoeking.document_id == document_id)).all()
            assert reg.status == "half_geboekt" and "half gelukt" in reg.half_geboekt_detail["reden"]
        with admin_engine.connect() as conn:
            n = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event WHERE record_id = :id AND actie = 'document_correctie_mislukt'"
                ),
                {"id": document_id},
            ).scalar_one()
        assert n == 1
