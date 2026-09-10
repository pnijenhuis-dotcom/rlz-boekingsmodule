"""AI-plausibiliteitstoets als poort (blok B bundel 10-09): vier poorten → `overgeslagen` mét oorzaak, plausibel/twijfel
via de stub, audit-record zonder prompt, schema in live_schemas (0 unions), kostenregistratie via de client-laag."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.aitoets import plausibiliteit as pl
from app.extractie.schema_poort import live_schemas, tel_union_parameters
from tests.aitoets.stub import (
    StubPlausibiliteitClient,
    audit_toetsen,
    zet_ai_toets_geen_key,
    zet_ai_toets_stub,
    zet_intake_ai,
)


def _invoer(
    administratie_id: uuid.UUID, *, referentie_id: uuid.UUID | None = None, soort: str = pl.SOORT_BANK_HISTORIE
):
    return pl.PlausibiliteitInvoer(
        administratie_id=administratie_id,
        soort=soort,
        omschrijving="Huur kantoor september",
        tegenpartij="Vastgoed Beheer Oost B.V.",
        bedrag=Decimal("-1250.00"),
        rekening_code="4400",
        rekening_naam="Huur",
        btw_omschrijving="NL, Hoog",
        historie_samenvatting="12 eerdere mutaties, 12× 4400 Huur · NL, Hoog (100 %)",
        referentie_id=referentie_id or uuid.uuid4(),
    )


def test_schema_is_sentinel_gebaseerd_zonder_unions_en_geregistreerd() -> None:
    assert tel_union_parameters(pl.PLAUSIBILITEIT_SCHEMA) == 0
    assert live_schemas()["aitoets PLAUSIBILITEIT_SCHEMA"] is pl.PLAUSIBILITEIT_SCHEMA
    assert pl.PLAUSIBILITEIT_SCHEMA["properties"]["uitkomst"]["enum"] == ["plausibel", "twijfel"]


def test_poort_1_avg_gate_uit_is_overgeslagen_zonder_call(
    administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch
) -> None:
    zet_intake_ai(admin_engine, False)
    stub = zet_ai_toets_stub(monkeypatch)
    rid = uuid.uuid4()
    uitkomst = pl.toets_plausibiliteit(_invoer(administratie_id, referentie_id=rid))
    assert uitkomst.uitkomst == "overgeslagen" and uitkomst.reden.startswith("avg_gate")
    assert not uitkomst.boeken_toegestaan
    assert stub.aanroepen == []
    audit = audit_toetsen(admin_engine, rid)
    assert len(audit) == 1 and audit[0]["uitkomst"] == "overgeslagen" and audit[0]["tabel"] == "bank_mutatie"
    assert "prompt" not in audit[0] and "Huur kantoor" not in str(audit[0])


def test_poort_2_geen_api_key(administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch) -> None:
    zet_intake_ai(admin_engine, True)
    zet_ai_toets_geen_key(monkeypatch)
    uitkomst = pl.toets_plausibiliteit(_invoer(administratie_id))
    assert uitkomst.uitkomst == "overgeslagen" and uitkomst.reden.startswith("api_key")


def test_poort_3_kostengrens(administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch) -> None:
    zet_intake_ai(admin_engine, True)
    zet_ai_toets_stub(
        monkeypatch, StubPlausibiliteitClient(kostenfout="AI-maandlimiet bereikt (€ 100,00 van € 100,00)")
    )
    uitkomst = pl.toets_plausibiliteit(_invoer(administratie_id))
    assert uitkomst.uitkomst == "overgeslagen" and uitkomst.reden.startswith("kostengrens")
    assert "maandlimiet" in uitkomst.reden


@pytest.mark.parametrize(
    "stub",
    [
        StubPlausibiliteitClient(fout="Claude API-timeout na 120s"),
        StubPlausibiliteitClient(afgekapt=True),
        StubPlausibiliteitClient(rauw={"uitkomst": "misschien", "reden": "x"}),
    ],
    ids=["timeout", "afgekapt", "onbekende_uitkomst"],
)
def test_poort_4_ai_fout_varianten(
    administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch, stub: StubPlausibiliteitClient
) -> None:
    zet_intake_ai(admin_engine, True)
    zet_ai_toets_stub(monkeypatch, stub)
    uitkomst = pl.toets_plausibiliteit(_invoer(administratie_id))
    assert uitkomst.uitkomst == "overgeslagen" and uitkomst.reden.startswith("ai_fout")


def test_plausibel_en_twijfel_via_stub_met_audit(
    administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch
) -> None:
    zet_intake_ai(admin_engine, True)
    stub = zet_ai_toets_stub(
        monkeypatch,
        StubPlausibiliteitClient(
            antwoorden={"Vastgoed Beheer Oost": ("twijfel", "huur op een kostenrekening zonder btw?")}
        ),
    )
    rid = uuid.uuid4()
    twijfel = pl.toets_plausibiliteit(_invoer(administratie_id, referentie_id=rid))
    assert twijfel.uitkomst == "twijfel" and "huur" in twijfel.reden
    assert not twijfel.boeken_toegestaan

    stub.antwoorden = {}
    plausibel = pl.toets_plausibiliteit(_invoer(administratie_id, referentie_id=rid))
    assert plausibel.uitkomst == "plausibel" and plausibel.boeken_toegestaan

    audit = audit_toetsen(admin_engine, rid)
    assert [a["uitkomst"] for a in audit] == ["twijfel", "plausibel"]
    assert audit[0]["soort"] == "bank_historie" and audit[0]["model"] == "stub-model"
    # De prompt zelf staat nooit in het audit_event; wél soort/uitkomst/reden/model.
    assert set(audit[0]) == {"tabel", "soort", "uitkomst", "reden", "model"}
    # De opdracht draagt het voorstel en de samenvatting, nooit een keuzelijst van rekeningen.
    assert "4400 Huur" in stub.aanroepen[0]["opdracht"] and "12 eerdere mutaties" in stub.aanroepen[0]["opdracht"]


def test_factuur_soort_audit_op_document(administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch) -> None:
    zet_intake_ai(admin_engine, True)
    zet_ai_toets_stub(monkeypatch)
    rid = uuid.uuid4()
    pl.toets_plausibiliteit(_invoer(administratie_id, referentie_id=rid, soort=pl.SOORT_FACTUUR_AUTOBOEKING))
    assert audit_toetsen(admin_engine, rid)[0]["tabel"] == "document"


@pytest.mark.afwezig_pad("boeken_instelling.ai_toets_facturen_ingeschakeld")
def test_facturen_setting_uit_geeft_uit_en_laat_boeken_door(
    administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch
) -> None:
    """Platformbrede schakelaar UIT = de poort is er niet ('uit', boeken_toegestaan) — het autoboekpad van blok A loopt
    door zoals vóór 10-09; geen AI-call, geen audit."""
    stub = zet_ai_toets_stub(monkeypatch)
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE platform.boeken_instelling SET ai_toets_facturen_ingeschakeld = false"))
    try:
        uitkomst = pl.toets_factuur_autoboeking(
            administratie_id=administratie_id, document_id=uuid.uuid4(), invoer_velden={}
        )
    finally:
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE platform.boeken_instelling SET ai_toets_facturen_ingeschakeld = true"))
    assert uitkomst == pl.PlausibiliteitUitkomst("uit", "AI-toets facturen staat platformbreed uit")
    assert uitkomst.boeken_toegestaan and stub.aanroepen == []


def test_facturen_setting_aan_zonder_leesbaar_boekvoorstel_is_overgeslagen(
    administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch
) -> None:
    """Default AAN; een onbekend document = boekvoorstel niet leesbaar = 'overgeslagen ai_fout' — nooit doorlaten."""
    zet_intake_ai(admin_engine, True)
    zet_ai_toets_stub(monkeypatch)
    uitkomst = pl.toets_factuur_autoboeking(
        administratie_id=administratie_id, document_id=uuid.uuid4(), invoer_velden={}
    )
    assert uitkomst.uitkomst == "overgeslagen" and uitkomst.reden.startswith("ai_fout")
    assert not uitkomst.boeken_toegestaan
