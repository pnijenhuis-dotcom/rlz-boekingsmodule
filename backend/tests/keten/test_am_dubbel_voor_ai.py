# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Casus (am) — hetzelfde échte document (Spot Services 2026-608, casus c) komt een TWEEDE keer binnen via een ander
bericht (forward / herstelrun — de situatie van 23-09 waarin de kempengroep-herstelrun mail herlas die al via de forward
was verwerkt): de byte-identieke dubbelencheck VÓÓR de AI-stap (BUG Peter 24-09, `app/intake/dubbel_voor_ai.py`) herkent
het bestand kantoorbreed, doet géén splitsings- of extractie-AI-call, registreert het exemplaar en voert het in de
administratie van het origineel direct af als duplicaat (categorie (a), kruisverwijzing — zoals casus g) en laat het spoor na op beide tijdlijnen + audit. Gouden-set-aanraking voor de
intake-wijziging (guard test_keten_guard)."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import Keten

CASUS = Casus(casussen.C_SPOT)
PDF = CASUS.pdf_bestandsnaam()


def test_tweede_exemplaar_via_ander_bericht_kost_geen_ai_en_wordt_huls(keten: Keten) -> None:
    pdf = CASUS.pdf()
    keten.ai.registreer(pdf, CASUS.ai_antwoord())
    eerste = keten.mail([(PDF, pdf)], message_id=f"<eerste-{uuid.uuid4()}@spotservices.example>")
    assert [r.uitkomst for r in eerste.bijlagen] == ["toegewezen"], eerste.bijlagen
    origineel = eerste.bijlagen[0].document_id
    ai_calls, splits_calls = len(keten.ai.aanroepen), len(keten.splitsing.aanroepen)
    assert ai_calls == 1 and splits_calls == 1

    tweede = keten.mail(
        [(f"Fwd {PDF}", pdf)],
        afzender="facturen@kempengroep.nl",
        onderwerp="Fwd: Factuur 2026-608",
        message_id=f"<tweede-{uuid.uuid4()}@kempengroep.example>",
        kanaal="facturen_kempengroep",
    )
    b = tweede.bijlagen[0]
    assert b.uitkomst == "dubbel" and b.document_id is not None and b.document_id != origineel, tweede.bijlagen
    assert (len(keten.ai.aanroepen), len(keten.splitsing.aanroepen)) == (ai_calls, splits_calls), (
        "geen AI-call voor het dubbel"
    )

    with keten.admin_engine.connect() as conn:
        huls = conn.execute(
            text(
                "SELECT administratie_id, status, samengevoegd_in_id, intake_bericht_id FROM boekhouding.document WHERE id = :id"
            ),
            {"id": b.document_id},
        ).one()
        n_docs = conn.execute(
            text(
                "SELECT count(*) FROM boekhouding.document WHERE sha256_hash = (SELECT sha256_hash FROM boekhouding.document WHERE id = :id)"
            ),
            {"id": origineel},
        ).scalar_one()
        audit = conn.execute(
            text("SELECT count(*) FROM platform.audit_event WHERE actie = 'ai_dubbel_voor_extractie'")
        ).scalar_one()
    assert (huls.administratie_id, huls.status, huls.samengevoegd_in_id, huls.intake_bericht_id) == (
        keten.administratie_id,
        "afgevoerd_duplicaat",
        None,
        tweede.bericht_id,
    )
    afwijzing = keten.afwijzing(b.document_id)
    assert (
        afwijzing is not None
        and afwijzing["duplicaat_van_document_id"] == origineel
        and afwijzing["automatisch"] is True
    )
    assert n_docs == 2 and audit == 1  # exemplaar geregistreerd (nooit stil), precies één bespaarde AI-call geteld

    # Het origineel blijft hét document (ongewijzigde stand, controlescherm draait) en draagt de tijdlijnregel.
    assert keten.status(origineel).value == "te_controleren"
    redenen = [g.get("reden") or "" for g in keten.tijdlijn(origineel)]
    assert any("dubbel vóór extractie herkend (bespaard)" in r for r in redenen), redenen
    dto = keten.open_controlescherm(origineel)
    assert dto["referentie"] == "2026-608"
    # Het exemplaar staat niet in de standaardlijst maar is terugvindbaar onder afgehandeld ("duplicaat van …").
    assert str(b.document_id) not in keten.standaardlijst_ids()
    rij = keten.lijst_rij(b.document_id, toon_afgehandeld="true")
    assert rij is not None and rij["status"] == "afgevoerd_duplicaat"
