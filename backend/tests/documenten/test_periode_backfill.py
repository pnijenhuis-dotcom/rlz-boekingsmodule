# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Backfill factuurperiode (blok 7 bundel 08-09; BESLISSINGEN "FACTUURPERIODE WEEKNIVEAU" beslispunt 4):

- dry-run rapporteert de cijfers per administratie en schrijft NIETS (kolommen, tijdlijn, audit);
- echte run vult lege kolommen: AI-veld `periode` uit het laatste veldvoorstel → `factuur`; zonder tekst → ISO-week van
  de factuurdatum (`afgeleid_van_factuurdatum`); één tijdlijn-notitie (systeem-actor, status ongewijzigd) + één
  audit-event per gewijzigd document;
- idempotent: een tweede run vindt alles "al gevuld" en schrijft niets;
- een gevulde stand — `mens` voorop — wordt nooit overschreven;
- standaard alleen GEBOEKT; `alle_statussen` neemt open documenten mee; zonder factuurdatum = overgeslagen mét reden."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, text

from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import boekvoorstel, periode_backfill, service
from app.documenten.models import Boekvoorstel, DocumentGebeurtenis, DocumentStatus
from app.documenten.periode import HERKOMST_AFGELEID_FACTUURDATUM, HERKOMST_FACTUUR, HERKOMST_MENS
from app.documenten.storage import LokaleBestandsopslag

FACTUURDATUM = date(2026, 9, 1)  # ISO-week 36 van 2026


def _document_met_voorstel(
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    admin_engine: Engine,
    *,
    factuurdatum: date | None = FACTUURDATUM,
    periode_tekst: str | None = None,
    status: DocumentStatus = DocumentStatus.GEBOEKT,
    herkomst_mens: bool = False,
) -> uuid.UUID:
    """Document + opgeslagen boekvoorstel, daarna 'zoals vóór 0120': periode-kolommen leeg (via SQL), status gezet.
    `periode_tekst` = een veldvoorstel in de tijdlijn mét het AI-veld; `herkomst_mens` = een mens-correctie die moet
    blijven staan."""
    document_id = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"factuur-{uuid.uuid4()}.pdf",
        inhoud=f"%PDF-1.4 {uuid.uuid4()}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    ).document_id
    if periode_tekst is not None:
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            session.add(
                DocumentGebeurtenis(
                    document_id=document_id,
                    van_status=DocumentStatus.ONTVANGEN,
                    naar_status=DocumentStatus.TE_CONTROLEREN,
                    actor_id=actor_id,
                    detail={"veldvoorstel": {"factuurnummer": "F-1", "periode_tekst": periode_tekst}},
                )
            )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        vendor_id=None,
        referentie="F-1",
        factuurdatum=factuurdatum,
        totaalbedrag=Decimal("121.00"),
        regels=[],
    )
    with admin_engine.begin() as conn:
        if herkomst_mens:
            conn.execute(
                text(
                    "UPDATE boekhouding.boekvoorstel SET periode_jaar = 2026, periode_week_van = 10, periode_week_tot = 10, "
                    "periode_herkomst = 'mens', periode_tekst = NULL WHERE document_id = :id"
                ),
                {"id": document_id},
            )
        else:
            conn.execute(
                text(
                    "UPDATE boekhouding.boekvoorstel SET periode_jaar = NULL, periode_week_van = NULL, "
                    "periode_week_tot = NULL, periode_herkomst = NULL, periode_tekst = NULL WHERE document_id = :id"
                ),
                {"id": document_id},
            )
        conn.execute(
            text("UPDATE boekhouding.document SET status = :s WHERE id = :id"), {"s": status.value, "id": document_id}
        )
    return document_id


def _kolommen(administratie_id: uuid.UUID, document_id: uuid.UUID) -> tuple:
    with scoped_session(administratie_id) as session:
        rij = session.get(Boekvoorstel, document_id)
        assert rij is not None
        return (rij.periode_jaar, rij.periode_week_van, rij.periode_week_tot, rij.periode_herkomst, rij.periode_tekst)


def _tijdlijn_backfill(administratie_id: uuid.UUID, document_id: uuid.UUID) -> list[DocumentGebeurtenis]:
    with scoped_session(administratie_id) as session:
        rijen = session.scalars(
            select(DocumentGebeurtenis)
            .where(DocumentGebeurtenis.document_id == document_id)
            .order_by(DocumentGebeurtenis.tijdstip)
        ).all()
        return [g for g in rijen if g.detail and periode_backfill.TIJDLIJN_SLEUTEL in g.detail]


def _audit(admin_engine: Engine, document_id: uuid.UUID) -> list[tuple]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT actor_id, oude_waarde, nieuwe_waarde FROM platform.audit_event WHERE record_id = :id AND actie = :actie "
                "ORDER BY tijdstip"
            ),
            {"id": document_id, "actie": periode_backfill.AUDIT_ACTIE},
        ).all()


def _run(
    administratie_id: uuid.UUID, *, dry_run: bool, alle_statussen: bool = False
) -> periode_backfill.PeriodeBackfillAdministratie:
    uitkomsten = periode_backfill.backfill(
        dry_run=dry_run, administratie_id=administratie_id, alle_statussen=alle_statussen
    )
    assert len(uitkomsten) == 1 and uitkomsten[0].administratie_id == administratie_id
    return uitkomsten[0]


class TestPeriodeBackfill:
    def test_dry_run_rapporteert_en_schrijft_niets(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        met_tekst = _document_met_voorstel(
            administratie_id, gescoopte_gebruiker, opslag, admin_engine, periode_tekst="Periode: week 34-35"
        )
        zonder_tekst = _document_met_voorstel(administratie_id, gescoopte_gebruiker, opslag, admin_engine)
        zonder_datum = _document_met_voorstel(
            administratie_id, gescoopte_gebruiker, opslag, admin_engine, factuurdatum=None
        )

        u = _run(administratie_id, dry_run=True)
        assert (u.toetsbaar, u.al_gevuld, u.uit_ai_veld, u.uit_terugval, u.gevuld) == (3, 0, 1, 1, 0)
        assert u.te_vullen == 2
        assert u.overgeslagen == {periode_backfill.REDEN_GEEN_FACTUURDATUM: 1}
        assert any("wk 34–35 · 2026 (factuur)" in r for r in u.regels)
        assert any("wk 36 · 2026 (afgeleid_van_factuurdatum)" in r for r in u.regels)
        for document_id in (met_tekst, zonder_tekst, zonder_datum):
            assert _kolommen(administratie_id, document_id) == (None, None, None, None, None)
            assert _tijdlijn_backfill(administratie_id, document_id) == []
            assert _audit(admin_engine, document_id) == []

    def test_echte_run_vult_uit_ai_veld_en_terugval_met_tijdlijn_en_audit_en_is_idempotent(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        met_tekst = _document_met_voorstel(
            administratie_id, gescoopte_gebruiker, opslag, admin_engine, periode_tekst="wk 34"
        )
        zonder_tekst = _document_met_voorstel(administratie_id, gescoopte_gebruiker, opslag, admin_engine)
        zonder_datum = _document_met_voorstel(
            administratie_id, gescoopte_gebruiker, opslag, admin_engine, factuurdatum=None
        )

        u = _run(administratie_id, dry_run=False)
        assert (u.toetsbaar, u.al_gevuld, u.uit_ai_veld, u.uit_terugval, u.gevuld) == (3, 0, 1, 1, 2)
        assert _kolommen(administratie_id, met_tekst) == (2026, 34, 34, HERKOMST_FACTUUR, "wk 34")
        assert _kolommen(administratie_id, zonder_tekst) == (2026, 36, 36, HERKOMST_AFGELEID_FACTUURDATUM, None)
        assert _kolommen(administratie_id, zonder_datum) == (None, None, None, None, None)

        # Tijdlijn: één notitie per gewijzigd document, systeem-actor, status ongewijzigd (geboekt → geboekt).
        (notitie,) = _tijdlijn_backfill(administratie_id, met_tekst)
        assert notitie.actor_id == SYSTEEM_ACTOR_ID
        assert (notitie.van_status, notitie.naar_status) == (DocumentStatus.GEBOEKT, DocumentStatus.GEBOEKT)
        assert notitie.detail[periode_backfill.TIJDLIJN_SLEUTEL] == {
            "periode": {"jaar": 2026, "week_van": 34, "week_tot": 34, "herkomst": HERKOMST_FACTUUR, "tekst": "wk 34"},
            "bron": "ai_veld",
        }
        assert (
            _tijdlijn_backfill(administratie_id, zonder_tekst)[0].detail[periode_backfill.TIJDLIJN_SLEUTEL]["bron"]
            == "factuurdatum"
        )
        assert _tijdlijn_backfill(administratie_id, zonder_datum) == []
        # Audit: append-only, systeem-actor, oud leeg → nieuw de stand.
        ((actor, oud, nieuw),) = _audit(admin_engine, zonder_tekst)
        assert actor == SYSTEEM_ACTOR_ID
        assert oud == {"periode": None}
        assert nieuw["periode"]["herkomst"] == HERKOMST_AFGELEID_FACTUURDATUM and nieuw["bron"] == "factuurdatum"
        assert _audit(admin_engine, zonder_datum) == []

        # Idempotent: tweede run vindt alles al gevuld (behalve de datumloze, die blijft overgeslagen) en schrijft niets.
        u2 = _run(administratie_id, dry_run=False)
        assert (u2.toetsbaar, u2.al_gevuld, u2.te_vullen, u2.gevuld) == (3, 2, 0, 0)
        assert u2.overgeslagen == {periode_backfill.REDEN_GEEN_FACTUURDATUM: 1}
        assert len(_tijdlijn_backfill(administratie_id, met_tekst)) == 1
        assert len(_audit(admin_engine, zonder_tekst)) == 1

    def test_mens_override_wint_en_wordt_nooit_overschreven(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        mens = _document_met_voorstel(
            administratie_id, gescoopte_gebruiker, opslag, admin_engine, periode_tekst="week 34", herkomst_mens=True
        )
        u = _run(administratie_id, dry_run=False)
        assert (u.toetsbaar, u.al_gevuld, u.mens, u.te_vullen, u.gevuld) == (1, 1, 1, 0, 0)
        assert _kolommen(administratie_id, mens) == (2026, 10, 10, HERKOMST_MENS, None)
        assert _tijdlijn_backfill(administratie_id, mens) == []
        assert _audit(admin_engine, mens) == []

    def test_standaard_alleen_geboekt_alle_statussen_neemt_open_documenten_mee(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        open_doc = _document_met_voorstel(
            administratie_id, gescoopte_gebruiker, opslag, admin_engine, status=DocumentStatus.KLAAR_OM_TE_BOEKEN
        )
        verwijderd = _document_met_voorstel(
            administratie_id, gescoopte_gebruiker, opslag, admin_engine, status=DocumentStatus.VERWIJDERD
        )

        u = _run(administratie_id, dry_run=False)
        assert (u.toetsbaar, u.gevuld) == (0, 0)
        assert _kolommen(administratie_id, open_doc) == (None, None, None, None, None)

        u_alle = _run(administratie_id, dry_run=False, alle_statussen=True)
        assert (u_alle.toetsbaar, u_alle.uit_terugval, u_alle.gevuld) == (1, 1, 1)  # verwijderd blijft buiten beeld
        assert _kolommen(administratie_id, open_doc) == (2026, 36, 36, HERKOMST_AFGELEID_FACTUURDATUM, None)
        assert _kolommen(administratie_id, verwijderd) == (None, None, None, None, None)
        (notitie,) = _tijdlijn_backfill(administratie_id, open_doc)
        assert (notitie.van_status, notitie.naar_status) == (
            DocumentStatus.KLAAR_OM_TE_BOEKEN,
            DocumentStatus.KLAAR_OM_TE_BOEKEN,
        )

    def test_onbekende_administratie_geeft_lege_uitkomst(self) -> None:
        assert periode_backfill.backfill(dry_run=True, administratie_id=uuid.uuid4()) == []


@pytest.mark.usefixtures("gescoopte_gebruiker")
def test_cli_dry_run_print_cijfers_per_administratie(
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    opslag: LokaleBestandsopslag,
    admin_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app import cli

    _document_met_voorstel(administratie_id, gescoopte_gebruiker, opslag, admin_engine)
    assert cli.main(["periode-backfill", "--dry-run", "--administratie", str(administratie_id)]) == 0
    uit = capsys.readouterr().out
    assert (
        "periode-backfill [dry-run]: 1 administratie(s), 1 toetsbaar, 0 al gevuld, 1 te vullen (0 uit AI-veld, 1 uit terugval)"
        in uit
    )
    assert "1 toetsbaar, 0 al gevuld (waarvan 0 mens), 0 uit AI-veld, 1 uit terugval, 0 gevuld" in uit
    assert _kolommen(administratie_id, _laatste_document_id(administratie_id)) == (None, None, None, None, None)
    assert cli.main(["periode-backfill", "--administratie", "geen-uuid"]) == 2


def _laatste_document_id(administratie_id: uuid.UUID) -> uuid.UUID:
    with scoped_session(administratie_id) as session:
        return session.scalars(select(Boekvoorstel.document_id)).one()
