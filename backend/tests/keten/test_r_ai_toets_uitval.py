# ruff: noqa: F811 — pytest-fixtures als parameters
"""Gouden set — casus r: AI-plausibiliteitstoets, uitval = doorlopen, zichtbaar (blok 4 vervolgrun 10-09 avond;
besluit Peter 10-09; geen migratie). Basis = casus h (BDO-UBL) met per exemplaar een ander factuurnummer, zelfde recept
als casus q.

Doelgedrag: leverancier-opt-in aan + geheugen app-bevestigd (drie mens-boekingen) → het vierde exemplaar loopt bij
intake door het autoboekpad; de AI-plausibiliteitstoets (B3, platformbreed aan) kan niet draaien omdat de AVG-gate uit
staat → het document wordt tóch GEBOEKT, mét `zonder_ai_toets` + oorzaak in de tijdlijn, chip in de lijst-DTO en de
twee audit-sporen. Een 'twijfel'-oordeel houdt de boeking wél tegen (regressie)."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import Engine, text

from app.aitoets import plausibiliteit
from app.documenten import autoboeken, boeken, boekvoorstel
from app.documenten.models import DocumentStatus
from tests.aitoets.stub import StubPlausibiliteitClient, zet_ai_toets_stub, zet_intake_ai
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_ADVIES, PROJECT_26049, TAXRATE_HOOG, Keten
from tests.keten.pdf import maak_pdf

BASIS = Casus(casussen.H_BDO)
BASIS_NUMMER = "6088744"


def _exemplaar(n: int) -> tuple[str, bytes, str, bytes]:
    nummer = f"60888{50 + n}"
    paginas = json.loads(
        json.dumps(json.loads((BASIS.map / "pdf_tekst.json").read_text())).replace(BASIS_NUMMER, nummer)
    )
    pdf = maak_pdf(paginas)
    xml = BASIS.xml(ingesloten_pdf=pdf).replace(BASIS_NUMMER.encode(), nummer.encode())
    return (f"BDO - {nummer}.xml", xml, f"BDO - {nummer}.pdf", pdf)


def _intake(keten: Keten, n: int) -> uuid.UUID:
    xml_naam, xml, pdf_naam, pdf = _exemplaar(n)
    resultaat = keten.mail([(xml_naam, xml), (pdf_naam, pdf)], message_id=f"<r-bdo-{n}@test>")
    return {r.bestandsnaam: r for r in resultaat.bijlagen}[xml_naam].document_id


def _boek_als_mens(keten: Keten, document_id: uuid.UUID) -> None:
    voorstel = keten.prefill(document_id)
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=keten.administratie_id,
        document_id=document_id,
        actor_id=keten.actor,
        vendor_id=voorstel.vendor_id,
        referentie=voorstel.referentie,
        factuurdatum=voorstel.factuurdatum,
        vervaldatum=voorstel.vervaldatum,
        totaalbedrag=voorstel.totaalbedrag,
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=GB_ADVIES,
                taxrate_id=r.taxrate_id or TAXRATE_HOOG,
                project_id=PROJECT_26049,
                netto_bedrag=r.netto_bedrag,
                btw_bedrag=r.btw_bedrag,
                omschrijving=r.omschrijving or "regel",
            )
            for r in voorstel.regels
        ],
    )
    boeken.boek_document(administratie_id=keten.administratie_id, document_id=document_id, actor_id=keten.actor)


def _audit(admin_engine: Engine, actie: str, record_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = :a AND record_id = :id"),
                {"a": actie, "id": record_id},
            ).all()
        ]


@pytest.fixture
def optin_bdo(keten: Keten, monkeypatch: pytest.MonkeyPatch) -> None:
    """Leverancier-opt-in aan + de B3-toets platformbreed AAN (de suite-conftest leest 'm buiten tests/aitoets als
    UIT)."""
    monkeypatch.setattr(plausibiliteit, "ai_toets_facturen_ingeschakeld", lambda: True)
    autoboeken.zet_leverancier_autoboeken(
        administratie_id=keten.administratie_id, vendor_id=keten.vendors["bdo"], actor_id=keten.actor, ingeschakeld=True
    )


class TestUitvalDoorlopen:
    def test_avg_gate_uit_boekt_door_zonder_ai_toets_zichtbaar(
        self, keten: Keten, optin_bdo: None, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        zet_intake_ai(admin_engine, False)
        stub = zet_ai_toets_stub(monkeypatch)
        docs = [_intake(keten, n) for n in range(3)]
        for d in docs:
            _boek_als_mens(keten, d)

        vierde = _intake(keten, 3)

        assert keten.status(vierde) == DocumentStatus.GEBOEKT
        assert stub.aanroepen == []  # AVG-gate uit: geen byte naar de API — en tóch geboekt
        geboekt = next(r for r in keten.tijdlijn(vierde) if "rlz_boekstuknummer" in (r or {}))
        assert geboekt["automatisch_geboekt"] is True and geboekt["zonder_ai_toets"] is True
        assert geboekt["ai_toets_oorzaak"] == "avg_gate"
        rij = keten.lijst_rij(vierde, toon_afgehandeld="true")
        assert rij is not None and rij["status"] == "geboekt"
        assert (
            rij["automatisch_geboekt"] is True
            and rij["zonder_ai_toets"] is True
            and rij["ai_toets_oorzaak"] == "avg_gate"
        )
        toets = _audit(admin_engine, "ai_plausibiliteitstoets", vierde)
        assert len(toets) == 1 and toets[0]["uitkomst"] == "overgeslagen" and toets[0]["oorzaak"] == "avg_gate"
        zonder = _audit(admin_engine, "automatisch_geboekt_zonder_ai_toets", vierde)
        assert len(zonder) == 1 and zonder[0]["soort"] == "factuur_autoboeking" and zonder[0]["oorzaak"] == "avg_gate"
        assert _audit(admin_engine, "autoboeken_geweigerd", vierde) == []
        assert len(keten.rlz.puts) == 4

    def test_twijfel_houdt_de_boeking_tegen(
        self, keten: Keten, optin_bdo: None, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        zet_intake_ai(admin_engine, True)
        zet_ai_toets_stub(monkeypatch, StubPlausibiliteitClient(standaard=("twijfel", "accountantskosten op advies?")))
        docs = [_intake(keten, n) for n in range(3)]
        for d in docs:
            _boek_als_mens(keten, d)

        vierde = _intake(keten, 3)

        assert keten.status(vierde) == DocumentStatus.TE_CONTROLEREN
        geweigerd = _audit(admin_engine, "autoboeken_geweigerd", vierde)
        assert len(geweigerd) == 1 and geweigerd[0]["reden"].startswith("AI-plausibiliteitstoets: twijfel — ")
        assert _audit(admin_engine, "automatisch_geboekt_zonder_ai_toets", vierde) == []
        rij = keten.lijst_rij(vierde)
        assert rij is not None and rij["zonder_ai_toets"] is False and rij["ai_toets_oorzaak"] is None
