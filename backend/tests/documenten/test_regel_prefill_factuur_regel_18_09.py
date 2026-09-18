"""BUG 18-09 (Peter, casus Zilver Horeca Fac-25-022711, BLOW): (1) de btw-code uit de btw-KOLOM van de factuurregel
(`btw_bron='factuur_regel'`) komt met het kolom-percentage in de prefill terecht — het geheugen vult alleen een lege btw en
kan 'm dus nooit overschrijven; (2) één waarheid voor de modus: zegt de leverancier-voorkeur "samenvoegen" maar staan er > 1
regel OPGESLAGEN, dan volgt de leesroute de data (`regels_samenvoegen` False, `regels_modus_hersteld` True) en schrijft het
openen van het controlescherm één tijdlijnregel "weergave hersteld" (idempotent); (3) totaal-herkomst uit de pinbon."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.documenten import boekvoorstel, service
from app.documenten.boekvoorstel import BTW_BRON_FACTUUR_REGEL, _pinbon_velden, _regels_prefill
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token

client = TestClient(app)
NUL = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000000")
LAAG = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000009")


def _bearer(gebruiker_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='boekhouding')}"}


class TestFactuurRegelPrefill:
    def test_kolomtarief_en_percentage_reizen_mee_in_de_regelprefill(self) -> None:
        veldvoorstel = {
            "regels": [
                {
                    "omschrijving": "Emballage ( 24 Stuks )",
                    "netto_bedrag": "10.80",
                    "btw_bedrag": "0.00",
                    "taxrate_id": str(NUL),
                    "btw_bron": BTW_BRON_FACTUUR_REGEL,
                    "btw_kolom_percentage": "0.0000",
                    "bedrag_niet_gelezen": False,
                },
                {
                    "omschrijving": "Balisto Yobbery 20 x 37 Gr",
                    "netto_bedrag": None,
                    "btw_bedrag": None,
                    "taxrate_id": None,
                    "btw_bron": None,
                    "btw_afleiding_reden": "onbepaalbaar",
                    "btw_kolom_percentage": "0.0900",
                    "bedrag_niet_gelezen": True,
                },
            ]
        }
        emballage, balisto = _regels_prefill(veldvoorstel)
        assert (emballage.taxrate_id, emballage.btw_bron, emballage.factuur_btw_percentage) == (
            NUL,
            BTW_BRON_FACTUUR_REGEL,
            Decimal("0.0000"),
        )
        assert emballage.bedrag_niet_gelezen is False
        # Zonder bedrag: geen btw-code (nooit raden), wél de kolom en de "niet gelezen"-vlag voor de chip.
        assert balisto.taxrate_id is None and balisto.factuur_btw_percentage == Decimal("0.0900")
        assert balisto.bedrag_niet_gelezen is True

    def test_pinbon_velden_volgen_de_waarde_gelijkheid(self) -> None:
        vv = {"totaal_bron": "pinbon", "totaal_pinbon": "30.37", "totaal_pinbon_status": "groen"}
        assert _pinbon_velden(vv, totaalbedrag=Decimal("30.37")) == {
            "totaal_bron": "pinbon",
            "totaal_pinbon": Decimal("30.37"),
            "totaal_pinbon_status": "groen",
        }
        # De mens wijzigde het totaal: herkomst weg, de bon-toets blijft informatief.
        assert _pinbon_velden(vv, totaalbedrag=Decimal("31.00"))["totaal_bron"] is None
        assert _pinbon_velden(
            {"totaal_pinbon": "738.27", "totaal_pinbon_status": "niet_toetsbaar"}, totaalbedrag=None
        ) == {
            "totaal_bron": None,
            "totaal_pinbon": Decimal("738.27"),
            "totaal_pinbon_status": "niet_toetsbaar",
        }
        assert _pinbon_velden(None, totaalbedrag=None)["totaal_pinbon"] is None


def _regel(omschrijving: str, netto: str) -> boekvoorstel.BoekvoorstelRegelData:
    return boekvoorstel.BoekvoorstelRegelData(
        ledger_id=uuid.UUID("bbbbbbbb-0000-0000-0000-000000007049"),
        taxrate_id=LAAG,
        project_id=None,
        netto_bedrag=Decimal(netto),
        btw_bedrag=None,
        omschrijving=omschrijving,
    )


class TestModusVolgtDeData:
    def test_voorkeur_samenvoegen_met_meerdere_opgeslagen_regels_wordt_gesplitst_gelezen_met_tijdlijnregel(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        document_id = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="2025-12-17_Zilver Horeca B.V._25-022711.pdf",
            inhoud=b"%PDF-1.4 zilver 25-022711 modus",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        ).document_id
        vendor_id = uuid.uuid4()
        # De mens slaat 3 losse regels op TERWIJL de voorkeur "samenvoegen" wordt (de PUT onthoudt die per leverancier) —
        # precies de productiestand van 18-09 (21 gesplitste regels, voorkeur true, geen samengevoegde variant).
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=vendor_id,
            referentie="Fac-25-022711",
            factuurdatum=date(2025, 12, 17),
            totaalbedrag=None,
            regels=[
                _regel("Twix 32 x 50 gram", "17.95"),
                _regel("Snicker 32 x 50 Gram", "18.95"),
                _regel("Emballage", "10.80"),
            ],
            regels_samenvoegen=True,
        )
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert len(data.regels) == 3
        assert data.regels_samenvoegen is False, "de modus volgt de data: 3 opgeslagen regels zijn nooit 'samengevoegd'"
        assert data.regels_modus_hersteld is True
        assert data.samenvoegen_toegestaan is True

        # Openen van het controlescherm: DTO consistent + één tijdlijnregel, ook bij een tweede opening.
        for _ in range(2):
            resp = client.get(
                f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
                headers=_bearer(gescoopte_gebruiker),
            )
            assert resp.status_code == 200, resp.text
            dto = resp.json()
            assert dto["regels_samenvoegen"] is False and dto["regels_modus_hersteld"] is True
            assert len(dto["regels"]) == 3
        with admin_engine.connect() as conn:
            regels = [
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT detail->>'reden' FROM boekhouding.document_gebeurtenis "
                        "WHERE document_id = :id AND detail ? 'weergave_hersteld'"
                    ),
                    {"id": document_id},
                )
            ]
        assert regels == ["weergave hersteld: 3 opgeslagen regels, modus stond op samengevoegd"]

    def test_een_opgeslagen_regel_met_voorkeur_samenvoegen_blijft_samengevoegd(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        document_id = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="een-regel.pdf",
            inhoud=b"%PDF-1.4 een regel samengevoegd",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        ).document_id
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            factuurdatum=date(2026, 9, 1),
            totaalbedrag=Decimal("19.57"),
            regels=[_regel("Factuur F-1 — samengevoegd (2 regels)", "17.95")],
            regels_samenvoegen=True,
        )
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert (data.regels_samenvoegen, data.regels_modus_hersteld) == (True, False)
