# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Casus (al) — hetzelfde échte document (Spot Services 2026-608, casus c) binnen via het derde postvak
facturen@kempengroep.nl (kanaal `facturen_kempengroep`, migratie 0171; Peter 22-09) én uit de spam-map: de keten
verwerkt exact als via facturen@ak-nijenhuis.nl (toewijzing, extractie-stub, controlescherm), het intake-bericht draagt
kanaal + postvak-map, "Uit de e-mail" op het controlescherm zegt via welk postvak en dat het uit Spam kwam, en de
verwerkt-administratie kent het bericht. Gouden-set-aanraking voor de postvak-herziening (guard test_keten_guard)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.intake import verwerking, verwerkt
from tests.intake.conftest import bouw_eml
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import Keten, _mime

CASUS = Casus(casussen.C_SPOT)
PDF = CASUS.pdf_bestandsnaam()


@pytest.fixture
def via_kempengroep_uit_spam(keten: Keten) -> tuple[uuid.UUID, str]:
    pdf = CASUS.pdf()
    keten.ai.registreer(pdf, CASUS.ai_antwoord())
    mid = f"<kg-{uuid.uuid4()}@spotservices.example>"
    eml = bouw_eml(
        afzender=casussen.AFZENDER_UNIVERSAL,
        onderwerp="Factuur 2026-608",
        message_id=mid,
        bijlagen=[(PDF, pdf, *_mime(PDF))],
    )
    uitkomst = verwerking.verwerk_eml(
        eml, actor_id=keten.actor, bron="imap", opslag=keten.opslag, kanaal="facturen_kempengroep", postvak_map="[Gmail]/Spam"
    )
    assert [r.uitkomst for r in uitkomst.bijlagen] == ["toegewezen"], uitkomst.bijlagen
    verwerkt.registreer(
        kanaal="facturen_kempengroep", sleutel=mid, uid="77", postvak_map="[Gmail]/Spam", uitkomst="verwerkt",
        intake_bericht_id=uitkomst.bericht_id,
    )
    return uitkomst.bijlagen[0].document_id, mid


def test_zelfde_keten_via_kempengroep_en_herkomst_zegt_postvak_en_spam(keten: Keten, via_kempengroep_uit_spam) -> None:
    document_id, mid = via_kempengroep_uit_spam
    detail = keten.detail(document_id)
    herkomst = detail["herkomst_mail"]
    assert herkomst["kanaal"] == "facturen_kempengroep"
    assert herkomst["postvak_adres"] == "facturen@kempengroep.nl"
    assert herkomst["uit_spam"] is True
    # Dezelfde extractie-uitkomst als casus c via facturen@ (zelfde stub, zelfde prefill-pad).
    dto = keten.open_controlescherm(document_id)
    assert dto["referentie"] == "2026-608"
    with keten.admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT b.kanaal, b.detail->>'postvak_map' AS map, v.uitkomst FROM boekhouding.intake_bericht b "
                "JOIN boekhouding.intake_bericht_verwerkt v ON v.intake_bericht_id = b.id WHERE b.message_id = :m"
            ),
            {"m": mid},
        ).one()
    assert tuple(rij) == ("facturen_kempengroep", "[Gmail]/Spam", "verwerkt")
    assert mid in verwerkt.bekende_sleutels("facturen_kempengroep")
    assert mid in verwerkt.bekende_sleutels("facturen")  # de forward van hetzelfde bericht is bekend voor élk kanaal


def test_hetzelfde_bericht_nogmaals_via_facturen_is_al_verwerkt(keten: Keten, via_kempengroep_uit_spam) -> None:
    document_id, mid = via_kempengroep_uit_spam
    pdf = CASUS.pdf()
    r = keten.mail([(PDF, pdf)], message_id=mid, kanaal="facturen")
    assert r.al_eerder_verwerkt is True
    with keten.admin_engine.connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM boekhouding.document WHERE administratie_id = :a"), {"a": keten.administratie_id}).scalar_one()
    assert n == 1
