# ruff: noqa: F811 — pytest-fixtures als parameters
"""Casus (an) — Vastly's SAMENGESTELDE webhook-antwoord in de keten (herzending 11 kostenevents, 24-09 avond, OPEN_ITEMS
regel 13): de module boekt de échte BDO-UBL (casus h) in een vastgoed-administratie → outbox-rij `factuur_geboekt` → de
afleveraar verstuurt 'm naar een ontvanger in Vastly's vorm (`rlz_webhook.py`: topniveau = verkoopfactuur-badge, dus
voor een inkoopfactuur altijd `genegeerd`/`onbekend_document`; de kostenuitkomst genest onder `kostenvoorstellen`).
Poging 1 van 24-09 17:55 UTC zette zes Rubicon-rijen op zo'n antwoord ten onrechte `mislukt`. Gespeeld door de echte
servicelaag:
intake → prefill → boekvoorstel → boeken (outbox) → afleveren → herzenden mét directe afleverronde."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.documenten import boeken, boekvoorstel
from app.documenten.models import DocumentStatus, WebhookStatus
from app.documenten.webhook_afleveraar import herzend_afgeleverd, lever_rijen_direct_af, verwerk_openstaande_webhooks
from tests.auth.conftest import beheerder_id  # noqa: F401
from tests.documenten.test_webhook_afleveraar import aflevering_aan  # noqa: F401
from tests.documenten.test_webhook_herzenden import VastlyOntvanger
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_ADVIES, PROJECT_26084, TAXRATE_HOOG, Keten

CASUS = Casus(casussen.H_BDO)


@pytest.fixture
def bdo_geboekt_vastgoed(keten: Keten) -> uuid.UUID:
    """BDO via de mail, geprefilld, opgeslagen en geboekt in een VASTGOED-administratie (is_vastgoed = true vóór het
    boeken → boeken.py::_sla_webhook_op maakt de outbox-rij)."""
    with keten.admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :id"), {"id": keten.administratie_id}
        )
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
    boeken.boek_document(administratie_id=keten.administratie_id, document_id=document_id, actor_id=keten.actor)
    assert keten.status(document_id) == DocumentStatus.GEBOEKT
    return document_id


def _outbox(keten: Keten, document_id: uuid.UUID) -> dict:
    with keten.admin_engine.connect() as conn:
        return dict(
            conn.execute(
                text(
                    "SELECT id, status, pogingen, laatste_fout, payload -> 'data' ->> 'referentie' AS referentie "
                    "FROM boekhouding.webhook_uitgaand WHERE document_id = :d AND event = 'factuur_geboekt'"
                ),
                {"d": document_id},
            )
            .mappings()
            .one()
        )


def _laatste_audit(keten: Keten, rij_id: uuid.UUID) -> dict:
    with keten.admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT actie, nieuwe_waarde FROM platform.audit_event WHERE tabel = 'webhook_uitgaand' "
                "AND record_id = :id ORDER BY tijdstip DESC LIMIT 1"
            ),
            {"id": rij_id},
        ).mappings().one()


class TestSamengesteldAntwoordInDeKeten:
    def test_geboekte_inkoopfactuur_kostenintake_uit_is_afgeleverd_zonder_verwerking_en_herzendbaar_met_bewijs(
        self, keten: Keten, bdo_geboekt_vastgoed: uuid.UUID, beheerder_id: uuid.UUID, aflevering_aan: None
    ) -> None:
        rij = _outbox(keten, bdo_geboekt_vastgoed)
        assert rij["status"] == WebhookStatus.OPENSTAAND.value and rij["referentie"]
        # Vastly 24-09 17:55 UTC (Rubicon): badge zegt genegeerd, kostenregel-verwerker zegt kostenintake_uit.
        ontvanger = VastlyOntvanger(
            [
                {
                    "resultaat": "genegeerd",
                    "reden": "onbekend_document",
                    "kostenvoorstellen": {"resultaat": "kostenintake_uit"},
                }
            ]
        )
        rapport = verwerk_openstaande_webhooks(transport=ontvanger.transport)
        assert rapport.afgeleverd == 1 and rapport.genegeerd == 0 and rapport.zonder_verwerking == 1
        assert ontvanger.ontvangen[0]["data"]["referentie"] == rij["referentie"]
        rij = _outbox(keten, bdo_geboekt_vastgoed)
        assert rij["status"] == WebhookStatus.AFGELEVERD.value and rij["laatste_fout"] is None
        audit = _laatste_audit(keten, rij["id"])
        assert audit["actie"] == "webhook_afgeleverd"
        assert audit["nieuwe_waarde"]["resultaat"] == "kostenintake_uit"
        assert audit["nieuwe_waarde"]["topniveau_resultaat"] == "genegeerd"
        assert "kostenintake_uit" in audit["nieuwe_waarde"]["ontvanger_antwoord"]

        # De klant zet de kostenintake aan Vastly-kant aan → herzenden mét directe afleverronde bewijst zichzelf.
        uit = herzend_afgeleverd(
            actor_id=beheerder_id,
            administratie_id=keten.administratie_id,
            referenties=[rij["referentie"]],
            reden="kostenintake bij Vastly aangezet — TEST gouden set an",
            dry_run=False,
        )
        assert [r.uitkomst for r in uit] == ["herzonden"]
        ontvanger = VastlyOntvanger(
            [
                {
                    "resultaat": "genegeerd",
                    "reden": "onbekend_document",
                    "kostenvoorstellen": {"resultaat": "voorstellen", "aangemaakt": 1, "al_aanwezig": 0},
                }
            ]
        )
        rapport = lever_rijen_direct_af(
            rij_ids=[rij["id"]], administratie_id=keten.administratie_id, transport=ontvanger.transport
        )
        assert rapport.per_rij[rij["id"]] == "afgeleverd — resultaat voorstellen"
        assert rapport.zonder_verwerking == 0 and rapport.let_op == []
        # Zelfde rlz_document_id/volgnummer, verse nonce.
        assert ontvanger.ontvangen[0]["data"]["referentie"] == rij["referentie"]
        assert ontvanger.ontvangen[0]["data"]["volgnummer"] == 1
        rij = _outbox(keten, bdo_geboekt_vastgoed)
        assert rij["status"] == WebhookStatus.AFGELEVERD.value and rij["pogingen"] == 1
        assert _laatste_audit(keten, rij["id"])["nieuwe_waarde"]["resultaat"] == "voorstellen"
