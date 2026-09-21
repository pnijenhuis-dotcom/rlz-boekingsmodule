# ruff: noqa: F811 — pytest-fixtures als parameters
"""Casus (ai) — "Wordt geboekt…" dat blijft hangen (BUG 21-09: job rlz-boek-wachtrij startte van 18-09 tot 21-09
niet — geen `--command python`; vijf boekingen hingen tot drie dagen op wordt_geboekt zonder één signaal, de rij
toonde een eeuwige grijze stip). De module boekt de échte BDO-UBL (casus h) via de 202-route, de verwerker start NIET
(zoals in productie), de boeking veroudert voorbij de herstelgrens → de lijst-DTO draagt de stand waarop de rij "loopt
vast" zegt, de reconciliatie maakt er een regressie-LET-OP van mét de trigger-reden, "Opnieuw indienen" (API) laat de
boeking staan en start de verwerker opnieuw, en de verwerker rondt precies één boeking af. Gespeeld door de echte
servicelaag + API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.config import settings
from app.documenten import boek_wachtrij, boekvoorstel
from app.documenten.models import DocumentStatus
from app.reconciliatie import automatiseringen as auto
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_ADVIES, PROJECT_26084, TAXRATE_HOOG, Keten

CASUS = Casus(casussen.H_BDO)


class _VerwerkerStartNiet:
    """De Cloud-wachtrij van 18→21-09: de trigger 'slaagt' (run.jobs.run), maar er wordt niets verwerkt."""

    def __init__(self) -> None:
        self.triggers = 0

    def enqueue(self, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> str | None:
        self.triggers += 1
        return None


@pytest.fixture
def bdo_klaar(keten: Keten) -> uuid.UUID:
    pdf = CASUS.pdf()
    resultaat = keten.mail([(CASUS.xml_bestandsnaam(), CASUS.xml(ingesloten_pdf=pdf)), (CASUS.pdf_bestandsnaam(), pdf)])
    document_id = resultaat.bijlagen[0].document_id
    keten.open_controlescherm(document_id)
    voorstel = keten.prefill(document_id)
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=keten.administratie_id,
        document_id=document_id,
        actor_id=keten.actor,
        vendor_id=voorstel.vendor_id,
        referentie=voorstel.referentie,
        factuurdatum=voorstel.factuurdatum,
        totaalbedrag=voorstel.totaalbedrag,
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=GB_ADVIES,
                taxrate_id=TAXRATE_HOOG,
                project_id=PROJECT_26084,
                netto_bedrag=Decimal("5500.00"),
                btw_bedrag=Decimal("1155.00"),
                omschrijving="Samenstellen jaarrekening 2025",
            )
        ],
    )
    return document_id


class TestWordtGeboektLooptVastInDeKeten:
    def test_hangende_boeking_is_zichtbaar_let_op_en_opnieuw_indienen_rondt_af(
        self, keten: Keten, bdo_klaar: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wachtrij = _VerwerkerStartNiet()
        monkeypatch.setattr(boek_wachtrij, "_standaard_wachtrij", lambda: wachtrij)

        # 1. "Boeken in RLZ" = 202 wordt_geboekt; de verwerker start niet (productie 18→21-09).
        resp = keten.api.post(
            f"/administraties/{keten.administratie_id}/documenten/{bdo_klaar}/boeken", headers=keten.headers, json={}
        )
        assert resp.status_code == 202, resp.text
        assert wachtrij.triggers == 1
        rij = keten.lijst_rij(bdo_klaar)
        assert rij is not None and rij["status"] == "wordt_geboekt" and rij["laatst_gewijzigd_op"]
        assert keten.rlz.puts == []  # niets naar RLZ zolang de verwerker niet liep

        # 2. Vers ingediend: geen LET-OP, geen probe-fout (geen valse meldingen binnen de grens).
        assert auto.boek_wachtrij_gestrand_bevindingen(nu=datetime.now(UTC)) == []

        #  3. Voorbij de herstelgrens (10 min): de lijst-DTO draagt de stand voor "loopt vast — N min"
        # (laatst_gewijzigd_op),
        #    de reconciliatie maakt één regressie-LET-OP mét de trigger-reden en de deeplink naar het document.
        oud = datetime.now(UTC) - timedelta(minutes=settings.boek_wachtrij_herstel_minuten + 36)
        with keten.admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.document_gebeurtenis SET tijdstip = :t WHERE document_id = :id "
                    "AND naar_status = 'wordt_geboekt' AND van_status <> 'wordt_geboekt'"
                ),
                {"t": oud, "id": bdo_klaar},
            )
            conn.execute(
                text("UPDATE boekhouding.document SET laatst_gewijzigd_op = :t WHERE id = :id"),
                {"t": oud, "id": bdo_klaar},
            )
        rij = keten.lijst_rij(bdo_klaar)
        assert rij is not None and rij["status"] == "wordt_geboekt"
        minuten = (datetime.now(UTC) - datetime.fromisoformat(rij["laatst_gewijzigd_op"])).total_seconds() // 60
        assert minuten >= 5  # frontend: WORDT_GEBOEKT_VAST_MINUTEN → "Wordt geboekt… (loopt vast — N min)"

        kws = auto.boek_wachtrij_gestrand_bevindingen(nu=datetime.now(UTC))
        assert len(kws) == 1 and kws[0]["soort"] == "let_op" and kws[0]["blok"] == auto.BLOK
        assert kws[0]["administratie_id"] == keten.administratie_id
        assert kws[0]["detail"]["reden"] == auto.BOEK_WACHTRIJ_GESTRAND
        assert kws[0]["detail"]["document_id"] == str(bdo_klaar)
        assert kws[0]["detail"]["doel_pad"] == f"/?administratie={keten.administratie_id}&document={bdo_klaar}"
        assert "geen trigger-spoor" in kws[0]["tekst"]  # lokale wachtrij: geen job-resource, geen trigger-audit
        assert auto.REGRESSIE_TEKST in kws[0]["tekst"]

        # 4. "Opnieuw indienen" via de API: zelfde boeking, tijdlijnregel, verwerker opnieuw gestart, uitkomst terug.
        resp = keten.api.post(
            f"/administraties/{keten.administratie_id}/documenten/{bdo_klaar}/boek-wachtrij/opnieuw-indienen",
            headers=keten.headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "wordt_geboekt" and resp.json()["sleutel"] == boek_wachtrij.sleutel(
            bdo_klaar, 0
        )
        assert wachtrij.triggers == 2
        assert keten.status(bdo_klaar) == DocumentStatus.WORDT_GEBOEKT
        assert any("Opnieuw ingediend" in str(d.get("reden")) for d in keten.tijdlijn(bdo_klaar))
        # Het indienmoment verschuift niet door de tijdlijnregel: de LET-OP blijft (zelfde vingerafdruk).
        assert (
            auto.boek_wachtrij_gestrand_bevindingen(nu=datetime.now(UTC))[0]["vingerafdruk"] == kws[0]["vingerafdruk"]
        )

        # 5. De verwerker (job/scheduler) rondt precies één boeking af → geboekt, LET-OP weg, RLZ één document.
        assert boek_wachtrij.verwerk_boek_wachtrij(verwerker="job") == 1
        assert keten.status(bdo_klaar) == DocumentStatus.GEBOEKT
        assert auto.boek_wachtrij_gestrand_bevindingen(nu=datetime.now(UTC)) == []
        rij = keten.lijst_rij(bdo_klaar, groep="afgehandeld")
        assert rij is not None and rij["status"] == "geboekt" and rij["geboekt_in_rlz"]["boekstuknummer"]
        # Opnieuw indienen ná afronding = 409, nooit stil.
        resp = keten.api.post(
            f"/administraties/{keten.administratie_id}/documenten/{bdo_klaar}/boek-wachtrij/opnieuw-indienen",
            headers=keten.headers,
        )
        assert resp.status_code == 409
