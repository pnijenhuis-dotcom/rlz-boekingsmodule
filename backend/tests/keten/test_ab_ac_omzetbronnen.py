"""Casussen (ab) zonnestudio-dagstaat + kascheck en (ac) pilates-betalingsexport (Peter 15-09) — de omzetbronnen
door de echte keten: upload als kassarapport → deterministische parser (geen AI, geen AVG-gate) → veldvoorstel mét
bron-controles → bundeling van de wederhelft / splitsing per uitbetaling. De diepe asserts (cent-exact per categorie,
kasverschil, dedupe-sleutel) staan in tests/omzet/test_bronnen.py; hier alleen de keten-uitkomst per casus zodat de
gouden set meebeweegt (fixtures/ab_omzet_zonnestudio, fixtures/ac_omzet_pilates — bron.json beschrijft herkomst)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentSoort, DocumentStatus
from app.omzet.bronnen import BRON_PILATES, BRON_ZONNESTUDIO_DAGSTAAT
from app.omzet.bronnen import service as bronnen_service
from tests.omzet.test_bronnen import DAGSTAAT, EXPORT, KASCHECK, grid_naar_xlsx


def _upload(administratie_id: uuid.UUID, actor: uuid.UUID, opslag, naam: str, inhoud: bytes) -> uuid.UUID:  # noqa: ANN001
    return documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=naam,
        inhoud=inhoud,
        actor_id=actor,
        opslag=opslag,
        soort=DocumentSoort.KASSARAPPORT,
    ).document_id


def test_ab_dagstaat_plus_kascheck_wordt_een_gebundeld_kassarapport(
    administratie_id, gescoopte_gebruiker, opslag
) -> None:  # noqa: ANN001
    dag = _upload(administratie_id, gescoopte_gebruiker, opslag, "8-9-26.xlsx", grid_naar_xlsx(DAGSTAAT))
    kas = _upload(
        administratie_id,
        gescoopte_gebruiker,
        opslag,
        "kascheck-2026-09-08.xlsx",
        grid_naar_xlsx(KASCHECK, blad="Kascheck"),
    )
    with scoped_session(administratie_id) as session:
        kas_doc = session.get(Document, kas)
        assert (kas_doc.status, kas_doc.samengevoegd_in_id) == (DocumentStatus.SAMENGEVOEGD, dag)
        vv = bronnen_service._laatste_veldvoorstel(session, dag)  # noqa: SLF001
    assert vv["bron"] == BRON_ZONNESTUDIO_DAGSTAAT and vv["totaal_omzet"] == "1019.03"
    assert vv["bron_detail"]["wacht_op"] is None and vv["bron_detail"]["kas"]["contante_omzet"] == "87.80"
    rood = [c["naam"] for c in vv["bron_detail"]["controles"] if not c["ok"] and c["blokkerend"]]
    assert rood == ["Puntenwaarde bekend"]  # de STAP-0-vraag aan de klant; verder sluit de dag cent-exact


def test_ac_betalingsexport_wordt_gesplitst_per_uitbetaling(administratie_id, gescoopte_gebruiker, opslag) -> None:  # noqa: ANN001
    ouder = _upload(
        administratie_id,
        gescoopte_gebruiker,
        opslag,
        "betalingen-juli.xlsx",
        grid_naar_xlsx(EXPORT, blad="Standaardweergave"),
    )
    with scoped_session(administratie_id) as session:
        assert session.get(Document, ouder).status == DocumentStatus.GESPLITST
        kinderen = list(session.scalars(select(Document).where(Document.gesplitst_uit_id == ouder)))
        assert len(kinderen) == 23
        vvs = [bronnen_service._laatste_veldvoorstel(session, k.id) for k in kinderen]  # noqa: SLF001
    assert all(vv["bron"] == BRON_PILATES for vv in vvs)
    assert all(vv["bron_detail"]["controles"][0]["ok"] for vv in vvs)  # som regels = netto uitbetaling, per batch
