# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Intussen buiten de module geboekt (Peter 22-09, casus Bouwadvies Oost Nederland / Beter Assemblage F/2026/01235 →
RLZ-04-00000518 buiten de module geboekt terwijl drie accordeurs nog klikten).

Dekt de vijf eisen uit de opdracht: (1) hercontrole vindt treffer → bevinding `intussen_extern_geboekt` mét boekstuk/bedrag/
datum; geen treffer → niets; storing → géén bevinding maar zichtbaar overgeslagen; (2) accordeur-app: wachtrij-item mét
banner-kern, uit de aan-de-beurt-bron van de herinneringen, akkoord/afwijzen/herinnering = 409 (guard-tests); (3) boeken ná het
laatste akkoord: de boekfout draagt de externe kern (knoppen i.p.v. proza); (4) de twee handelingen: afwijzen als al geboekt
(ronde vervalt mét "niet meer nodig: al geboekt in Reeleezee", document afgewezen mét voorgevulde reden) en toch verschillend
(tijdlijn + audit, uitgezonderd in hercontrole én harde check); (5) leesbare tekst + registry in `actie`."""

from __future__ import annotations

import argparse
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app import cli
from app.accordering import herinnering
from app.accordering import service as accordering_service
from app.accordering.models import AccorderingStatus
from app.berichten import mail
from app.db.models import GebruikerRol
from app.documenten import boeken, intussen_extern_geboekt, reconciliatie
from app.documenten.checks import CheckRapport, CheckResultaat, check_duplicaat
from app.documenten.models import DocumentStatus
from app.documenten.rlz_ids import rlz_herboeking_id
from app.main import app
from app.reconciliatie import run as run_service
from app.reconciliatie import soort_stand, teksten
from app.security.tokens import create_access_token
from tests.accordering.conftest import (  # noqa: F401
    accordeur_1,
    accordeur_2,
    boeken_aan,
    document_status,
    klaar_document,
    maak_klaar_document,
    zet_schema,
)
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.documenten.fake_rlz_client import FakeBoekClient

client = TestClient(app)
EXTERN_ID = "ffb1f1f3-0000-4000-8000-000000000518"
BOEKSTUK = "RLZ-04-00000518"


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture(autouse=True)
def _geen_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail, "verzend_mail", lambda **kw: None)


def _laag(volgnummer: int, accordeur: uuid.UUID) -> accordering_service.LaagInput:
    return accordering_service.LaagInput(volgnummer=volgnummer, accordeur_gebruiker_id=accordeur, bedrag_drempel=None)


def _fake_met_treffer(referentie: str | None = None, *, status: int = 2) -> FakeBoekClient:
    fake = FakeBoekClient()
    fake.duplicaten = [
        {
            "id": EXTERN_ID,
            "Reference": referentie or "F/2026/01235",
            "ReceiptNumber": BOEKSTUK,
            "BaseInvoiceAmount": 121.00,
            "Status": status,
            "Date": "2026-08-26T00:00:00",
        }
    ]
    return fake


class _StoringClient(FakeBoekClient):
    def find_purchase_invoices_by_reference(self, **kw):  # noqa: ANN003, ANN201
        raise ConnectionError("RLZ 503 — even niet bereikbaar")


def _referentie(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT referentie FROM boekhouding.boekvoorstel WHERE document_id = :id"), {"id": document_id}
        ).scalar_one()


def _zet_gewijzigd(admin_engine: Engine, document_id: uuid.UUID, *, dagen_terug: int) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE boekhouding.document SET laatst_gewijzigd_op = :t WHERE id = :id"),
            {"id": document_id, "t": datetime.now(UTC) - timedelta(days=dagen_terug)},
        )


def _ter_accordering(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur, document_id, *lagen) -> None:
    zet_schema(
        administratie_id=administratie_id,
        beheerder_id=beheerder_id,
        lagen=[_laag(i + 1, a) for i, a in enumerate((accordeur, *lagen))],
    )
    accordering_service.bied_ter_accordering_aan(
        administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker, actor_rol="boekhouding"
    )


def _run_documentenblok(monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID, fake: FakeBoekClient) -> None:
    """Eén échte run van het documenten-blok (CLI-plumbing incl. detail-dict) tegen de fake client."""
    monkeypatch.setattr(
        cli.reconciliatie,
        "reconcilieer_alle_administraties",
        lambda: {administratie_id: reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=fake)},
    )
    monkeypatch.setattr(cli.storno_detectie, "detecteer_en_meld_gestorneerd_alle", lambda: {})
    run_service.voer_uit(
        blokken=[("documenten", cli._reconciliatie)], args=argparse.Namespace(), bron="cli", stdout=lambda t: None
    )


def _tijdlijn(admin_engine: Engine, document_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT van_status, naar_status, detail FROM boekhouding.document_gebeurtenis "
                "WHERE document_id = :id ORDER BY tijdstip, id"
            ),
            {"id": document_id},
        ).all()
    return [{"van": r[0], "naar": r[1], "detail": r[2] or {}} for r in rijen]


def _audit_aantal(admin_engine: Engine, actie: str) -> int:
    with admin_engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM platform.audit_event WHERE actie = :a"), {"a": actie}).scalar_one()


# ---- 1. hercontrole ---------------------------------------------------------------------------------------------------


class TestHercontrole:
    def test_ter_accordering_met_treffer_buiten_de_module_geeft_bevinding(
        self, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, admin_engine
    ) -> None:
        _ter_accordering(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document)
        fake = _fake_met_treffer(_referentie(admin_engine, klaar_document))
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=fake)
        assert rapport.aantal_gecontroleerd == 0 and rapport.hercontrole_getoetst == 1
        [a] = rapport.afwijkingen
        assert a.soort == "intussen_extern_geboekt" and a.document_id == klaar_document
        assert a.detail == f"al geboekt in Reeleezee: {BOEKSTUK} (referentie {_referentie(admin_engine, klaar_document)}, buiten de module)"
        assert a.context["extern_boekstuk"] == BOEKSTUK and a.context["extern_id"] == EXTERN_ID
        assert a.context["bedrag_extern"] == "121.0" and a.context["extern_datum"] == "2026-08-26"
        assert a.context["document_status"] == "ter_accordering" and a.context["extern_stand"] == "geboekt"
        assert a.context["leverancier_naam"] == "Energieleverancier B.V."
        # De leesbare laag (titel/wat/doe) benoemt boekstuk en beide handelingen.
        b = cli._afwijking_detail(
            "documenten",
            type("B", (), {"record_id": a.document_id, "soort": a.soort, "detail": a.detail, "telt_mee": True})(),
            None,
            document_id=a.document_id,
            **a.context,
        )
        lees = teksten.leesbaar(
            run_service.Bevinding(blok="documenten", soort="afwijking", administratie_id=administratie_id, vingerafdruk="v", tekst=a.detail, detail=b)
        )
        assert "Al geboekt in RLZ buiten de module" in lees.titel
        assert BOEKSTUK in lees.wat and "klant-akkoord" in lees.wat
        assert "al geboekt" in lees.doe and "Toch verschillend" in lees.doe

    def test_geen_treffer_geeft_niets(
        self, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1
    ) -> None:
        _ter_accordering(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document)
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=FakeBoekClient())
        assert rapport.afwijkingen == () and rapport.hercontrole_getoetst == 1 and rapport.hercontrole_overgeslagen == ()

    def test_storing_is_geen_bevinding_maar_zichtbaar_overgeslagen(
        self, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, capsys, monkeypatch
    ) -> None:
        _ter_accordering(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document)
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=_StoringClient())
        assert rapport.afwijkingen == () and rapport.hercontrole_getoetst == 0
        [(doc, reden)] = rapport.hercontrole_overgeslagen
        assert doc == klaar_document and "controle mislukt" in reden and "503" in reden
        # CLI-regel zichtbaar (principe 4).
        monkeypatch.setattr(cli.reconciliatie, "reconcilieer_alle_administraties", lambda: {administratie_id: rapport})
        monkeypatch.setattr(cli.storno_detectie, "detecteer_en_meld_gestorneerd_alle", lambda: {})
        cli._reconciliatie(argparse.Namespace(), verzamelaar=None)
        uit = capsys.readouterr().out
        assert f"HERCONTROLE {administratie_id}: 0 open document(en)" in uit and "OVERGESLAGEN document=" in uit

    def test_geen_credential_is_zichtbaar_overgeslagen_zonder_crash(
        self, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, monkeypatch
    ) -> None:
        from app.rlz.credentials import GeenRlzCredentials

        _ter_accordering(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document)

        def _geen(*a, **k):  # noqa: ANN002, ANN003, ANN202
            raise GeenRlzCredentials("geen webservice-login")

        monkeypatch.setattr(reconciliatie, "inkoop_port_voor", _geen)
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id)
        assert rapport.afwijkingen == ()
        [(doc, reden)] = rapport.hercontrole_overgeslagen
        assert doc == klaar_document and "geen webservice-login" in reden

    def test_klaar_om_te_boeken_telt_pas_na_een_dag_en_wacht_op_iban_altijd(
        self, administratie_id, gescoopte_gebruiker, admin_engine, opslag
    ) -> None:
        vers = maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam="vers.pdf")
        oud = maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam="oud.pdf")
        _zet_gewijzigd(admin_engine, oud, dagen_terug=2)
        fake = FakeBoekClient()
        fake.duplicaten = [
            {"id": EXTERN_ID, "Reference": _referentie(admin_engine, oud), "ReceiptNumber": BOEKSTUK, "BaseInvoiceAmount": 121.0, "Status": 2},
            {"id": str(uuid.uuid4()), "Reference": _referentie(admin_engine, vers), "ReceiptNumber": "RLZ-04-00000999", "BaseInvoiceAmount": 121.0, "Status": 2},
        ]
        nu = datetime.now(UTC)
        open_docs = reconciliatie._open_documenten(administratie_id, nu=nu)
        assert [d.document_id for d in open_docs] == [oud]
        verwacht = {DocumentStatus.TER_ACCORDERING, DocumentStatus.WACHT_OP_IBAN_ACCORDERING, DocumentStatus.KLAAR_OM_TE_BOEKEN}
        assert verwacht == reconciliatie.HERCONTROLE_STATUSSEN

    def test_eigen_boekketen_en_afgemeld_extern_stuk_tellen_niet(
        self, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, admin_engine
    ) -> None:
        _ter_accordering(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document)
        ref = _referentie(admin_engine, klaar_document)
        fake = FakeBoekClient()
        fake.duplicaten = [
            # eigen concept-huls (herboeking-GUID) = nooit een treffer
            {"id": str(rlz_herboeking_id(klaar_document, 0)), "Reference": ref, "ReceiptNumber": "RLZ-04-1", "BaseInvoiceAmount": 121.0, "Status": 1},
            {"id": EXTERN_ID, "Reference": ref, "ReceiptNumber": BOEKSTUK, "BaseInvoiceAmount": 121.0, "Status": 2},
        ]
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=fake)
        assert [a.context["extern_id"] for a in rapport.afwijkingen] == [EXTERN_ID]
        intussen_extern_geboekt.toch_verschillend(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            rol=GebruikerRol.BOEKHOUDING,
            extern_id=EXTERN_ID,
            extern_boekstuk=BOEKSTUK,
            reden="creditnota met hetzelfde nummer, ander bedrag — écht een andere factuur",
        )
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=fake)
        assert rapport.afwijkingen == () and rapport.hercontrole_getoetst == 1


# ---- 2. accordeur-app + herinneringen ----------------------------------------------------------------------------------


class TestAccordeurKant:
    def _met_open_bevinding(self, monkeypatch, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, admin_engine, *lagen):
        _ter_accordering(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document, *lagen)
        _run_documentenblok(monkeypatch, administratie_id, _fake_met_treffer(_referentie(admin_engine, klaar_document)))

    def test_wachtrij_item_draagt_banner_en_valt_uit_de_herinneringsbron(
        self, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, admin_engine, monkeypatch
    ) -> None:
        self._met_open_bevinding(monkeypatch, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, admin_engine)
        [item] = accordering_service.wachtrij_voor_accordeur(actor_id=accordeur_1, administratie_ids=[administratie_id])
        assert item.extern_geboekt is not None and item.extern_geboekt.extern_boekstuk == BOEKSTUK
        assert intussen_extern_geboekt.banner_tekst(item.extern_geboekt) == (
            f"Al geboekt in Reeleezee ({BOEKSTUK}) — kantoor beoordeelt; akkoord niet nodig"
        )
        # Herinneringen (09:00-job, bundelmelding) lezen dezelfde bron: het document telt niet meer.
        assert accordering_service.documenten_aan_de_beurt(administratie_id=administratie_id) == {}
        assert accordering_service.aantallen_aan_de_beurt(administratie_id=administratie_id) == {}
        # De app-route levert de banner-kern mee.
        from app.auth import voorwaarden

        voorwaarden.leg_akkoord_vast(gebruiker_id=accordeur_1)
        r = client.get("/accordering/wachtrij", headers=_bearer(accordeur_1, rol="klant_accordeur"))
        assert r.status_code == 200, r.text
        [dto] = r.json()["items"]
        assert dto["extern_geboekt"] == {
            "boekstuk": BOEKSTUK,
            "systeem": "Reeleezee",
            "stand": "geboekt",
            "tekst": f"Al geboekt in Reeleezee ({BOEKSTUK}) — kantoor beoordeelt; akkoord niet nodig",
        }

    def test_akkoord_afwijzen_en_handmatige_herinnering_zijn_409(
        self, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, admin_engine, monkeypatch
    ) -> None:
        self._met_open_bevinding(monkeypatch, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, admin_engine)
        with pytest.raises(accordering_service.WachtOpKantoor):
            accordering_service.geef_akkoord(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1)
        with pytest.raises(accordering_service.WachtOpKantoor):
            accordering_service.wijs_af(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1, reden="x")
        with pytest.raises(accordering_service.WachtOpKantoor) as exc:
            herinnering.stuur_handmatige_herinnering(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker, actor_rol="boekhouding"
            )
        assert "Geen herinnering gestuurd" in str(exc.value) and BOEKSTUK in str(exc.value)
        r = client.post(
            f"/administraties/{administratie_id}/accordering/documenten/{klaar_document}/herinneren",
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert r.status_code == 409, r.text
        assert document_status(admin_engine, klaar_document) == "ter_accordering"

    def test_zonder_bevinding_blijft_alles_zoals_het_was(
        self, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, admin_engine
    ) -> None:
        _ter_accordering(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document)
        [item] = accordering_service.wachtrij_voor_accordeur(actor_id=accordeur_1, administratie_ids=[administratie_id])
        assert item.extern_geboekt is None
        assert accordering_service.documenten_aan_de_beurt(administratie_id=administratie_id) == {accordeur_1: [klaar_document]}


# ---- 3. boeken ná het laatste akkoord --------------------------------------------------------------------------------


class TestBoekFoutKern:
    def test_duplicaatcheck_buiten_de_module_reist_als_kern_mee(
        self, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, boeken_aan, admin_engine, monkeypatch
    ) -> None:
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        _ter_accordering(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document)
        rood = check_duplicaat(
            client=_fake_met_treffer(_referentie(admin_engine, klaar_document)),
            vendor_id=uuid.uuid4(),
            referentie=_referentie(admin_engine, klaar_document),
            totaalbedrag=Decimal("121.00"),
            eigen_rlz_document_id=rlz_herboeking_id(klaar_document, 0),
        )
        assert not rood.ok and rood.data == {
            "extern_geboekt": {
                "extern_id": EXTERN_ID,
                "extern_boekstuk": BOEKSTUK,
                "extern_referentie": _referentie(admin_engine, klaar_document),
                "extern_stand": "geboekt",
                "bedrag_extern": "121.0",
                "extern_datum": "2026-08-26",
            }
        }
        monkeypatch.setattr(boeken, "voer_checks_uit", lambda **kwargs: CheckRapport(resultaten=(rood,)))
        resultaat = accordering_service.geef_akkoord(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1)
        assert resultaat.alles_akkoord and not resultaat.geboekt
        assert resultaat.accordering.boek_fout_extern_geboekt == {
            "extern_id": EXTERN_ID,
            "extern_boekstuk": BOEKSTUK,
            "extern_referentie": _referentie(admin_engine, klaar_document),
            "extern_stand": "geboekt",
            "bedrag_extern": "121.0",
            "extern_datum": "2026-08-26",
            "systeem": "Reeleezee",
        }
        r = client.get(
            f"/administraties/{administratie_id}/accordering/documenten/{klaar_document}",
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert r.status_code == 200 and r.json()["boek_fout_extern_geboekt"]["extern_boekstuk"] == BOEKSTUK

    def test_andere_boekfout_draagt_geen_kern(
        self, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, boeken_aan, monkeypatch
    ) -> None:
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        _ter_accordering(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document)
        rood = CheckRapport(resultaten=(CheckResultaat(naam="Verplichte velden", ok=False, melding="Regel 1 mist grootboek"),))
        monkeypatch.setattr(boeken, "voer_checks_uit", lambda **kwargs: rood)
        resultaat = accordering_service.geef_akkoord(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1)
        assert resultaat.accordering.boek_fout and resultaat.accordering.boek_fout_extern_geboekt is None


# ---- 4. de twee handelingen -----------------------------------------------------------------------------------------


class TestHandelingen:
    def _bevinding(self, headers: dict[str, str]) -> dict:
        d = client.get("/reconciliatie/bevindingen", headers=headers).json()
        [rij] = [r for r in d["rijen"] if (r.get("detail") or {}).get("afwijking_soort") == "intussen_extern_geboekt"]
        return rij

    def test_afwijzen_al_geboekt_trekt_de_ronde_in_en_wijst_af(
        self, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, accordeur_2, admin_engine, monkeypatch
    ) -> None:
        _ter_accordering(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document, accordeur_2)
        # Eén laag al akkoord (zoals bij Bouwadvies) — dat akkoord blijft historie, de ronde vervalt.
        accordering_service.geef_akkoord(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1)
        _run_documentenblok(monkeypatch, administratie_id, _fake_met_treffer(_referentie(admin_engine, klaar_document)))
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        rij = self._bevinding(headers)
        assert rij["detail"]["extern_boekstuk"] == BOEKSTUK and rij["doel_pad"].endswith(f"document={klaar_document}")
        r = client.post(
            f"/reconciliatie/documenten/{klaar_document}/extern-geboekt/afwijzen",
            headers=headers,
            json={"administratie_id": str(administratie_id), "extern_id": rij["detail"]["extern_id"], "extern_boekstuk": BOEKSTUK, "systeem": "Reeleezee"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "afgewezen" and body["accordering_vervallen"] is True
        assert body["reden"] == f"Al geboekt in Reeleezee als {BOEKSTUK} (buiten de module)"
        assert document_status(admin_engine, klaar_document) == "afgewezen"
        tijdlijn = _tijdlijn(admin_engine, klaar_document)
        vervallen = [g for g in tijdlijn if g["detail"].get("accordering_vervallen")]
        assert len(vervallen) == 1 and vervallen[0]["detail"]["reden"] == f"niet meer nodig: al geboekt in Reeleezee ({BOEKSTUK})"
        assert vervallen[0]["detail"].get(intussen_extern_geboekt.VERVALLEN_MARKER) is True
        assert (vervallen[0]["van"], vervallen[0]["naar"]) == ("ter_accordering", "klaar_om_te_boeken")
        assert tijdlijn[-1]["naar"] == "afgewezen" and tijdlijn[-1]["detail"]["duplicaat_van_rlz_document_id"] == EXTERN_ID
        with admin_engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM boekhouding.document_accordering WHERE document_id = :d"), {"d": klaar_document}
            ).scalar_one()
        assert status == AccorderingStatus.VERVALLEN.value
        # Geen herstelwerk-banner "opnieuw aanbieden" voor deze bewuste keuze.
        assert accordering_service.vervallen_meldingen(administratie_id=administratie_id) == []
        # Wachtrij accordeur 2 leeg, herinneringsbron leeg.
        assert accordering_service.wachtrij_voor_accordeur(actor_id=accordeur_2, administratie_ids=[administratie_id]) == []
        assert _audit_aantal(admin_engine, "document_afgewezen") == 1

    def test_afwijzen_op_klaar_om_te_boeken_zonder_ronde(
        self, klaar_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        r = client.post(
            f"/reconciliatie/documenten/{klaar_document}/extern-geboekt/afwijzen",
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
            json={"administratie_id": str(administratie_id), "extern_id": EXTERN_ID, "extern_boekstuk": BOEKSTUK, "toelichting": "gezien in RLZ"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["accordering_vervallen"] is False and r.json()["reden"].endswith("— gezien in RLZ")
        assert document_status(admin_engine, klaar_document) == "afgewezen"

    def test_poorten_wacht_op_iban_geboekt_en_accordeur(
        self, klaar_document, administratie_id, gescoopte_gebruiker, accordeur_1, admin_engine
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.document SET status = 'wacht_op_iban_accordering' WHERE id = :id"), {"id": klaar_document})
        body = {"administratie_id": str(administratie_id), "extern_id": EXTERN_ID, "extern_boekstuk": BOEKSTUK}
        r = client.post(f"/reconciliatie/documenten/{klaar_document}/extern-geboekt/afwijzen", headers=_bearer(gescoopte_gebruiker, rol="boekhouding"), json=body)
        assert r.status_code == 409 and "IBAN-accordering" in r.json()["detail"]
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.document SET status = 'geboekt' WHERE id = :id"), {"id": klaar_document})
        r = client.post(f"/reconciliatie/documenten/{klaar_document}/extern-geboekt/afwijzen", headers=_bearer(gescoopte_gebruiker, rol="boekhouding"), json=body)
        assert r.status_code == 409 and "geboekt" in r.json()["detail"]
        # De accordeur-rol heeft hier niets te zoeken (kantoor-router).
        r = client.post(f"/reconciliatie/documenten/{klaar_document}/extern-geboekt/afwijzen", headers=_bearer(accordeur_1, rol="klant_accordeur"), json=body)
        assert r.status_code == 403
        r = client.post(f"/reconciliatie/documenten/{uuid.uuid4()}/extern-geboekt/afwijzen", headers=_bearer(gescoopte_gebruiker, rol="boekhouding"), json=body)
        assert r.status_code == 404

    def test_toch_verschillend_tijdlijn_audit_en_uitzondering_in_de_harde_check(
        self, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, admin_engine, monkeypatch
    ) -> None:
        _ter_accordering(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document)
        _run_documentenblok(monkeypatch, administratie_id, _fake_met_treffer(_referentie(admin_engine, klaar_document)))
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        rij = self._bevinding(headers)
        r = client.post(
            f"/reconciliatie/documenten/{klaar_document}/extern-geboekt/toch-verschillend",
            headers=headers,
            json={"administratie_id": str(administratie_id), "extern_id": EXTERN_ID, "extern_boekstuk": BOEKSTUK, "reden": "kort", "bevinding_id": rij["id"]},
        )
        assert r.status_code == 422, r.text
        r = client.post(
            f"/reconciliatie/documenten/{klaar_document}/extern-geboekt/toch-verschillend",
            headers=headers,
            json={"administratie_id": str(administratie_id), "extern_id": EXTERN_ID, "extern_boekstuk": BOEKSTUK, "reden": "andere levering, zelfde nummerreeks — gecontroleerd met de leverancier", "bevinding_id": rij["id"]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["extern_ids"] == [EXTERN_ID] and r.json()["bevinding_geaccepteerd"] is False  # boekhouding ≠ Beheerder
        tijdlijn = _tijdlijn(admin_engine, klaar_document)
        [regel] = [g for g in tijdlijn if g["detail"].get(intussen_extern_geboekt.TOCH_VERSCHILLEND_SLEUTEL)]
        assert regel["van"] == regel["naar"] == "ter_accordering" and regel["detail"]["extern_ids"] == [EXTERN_ID]
        assert _audit_aantal(admin_engine, intussen_extern_geboekt.AUDIT_TOCH_VERSCHILLEND) == 1
        assert document_status(admin_engine, klaar_document) == "ter_accordering"
        # Tweede keer = 409 (al vastgelegd), nooit stil dubbel.
        r2 = client.post(
            f"/reconciliatie/documenten/{klaar_document}/extern-geboekt/toch-verschillend",
            headers=headers,
            json={"administratie_id": str(administratie_id), "extern_id": EXTERN_ID, "reden": "nog een keer dezelfde reden"},
        )
        assert r2.status_code == 409
        # De harde check Duplicaatcheck ziet dit stuk niet meer als treffer (zelfde uitzonderingsmechanisme als de keten).
        from app.db.session import scoped_session

        with scoped_session(administratie_id) as session:
            afgemeld = intussen_extern_geboekt.afgemelde_extern_ids(session, klaar_document)
        assert afgemeld == frozenset({EXTERN_ID})
        groen = check_duplicaat(
            client=_fake_met_treffer(_referentie(admin_engine, klaar_document)),
            vendor_id=uuid.uuid4(),
            referentie=_referentie(admin_engine, klaar_document),
            totaalbedrag=Decimal("121.00"),
            eigen_rlz_document_id=rlz_herboeking_id(klaar_document, 0),
            uitgezonderde_rlz_document_ids=afgemeld,
        )
        assert groen.ok
        # Hercontrole geeft geen nieuwe bevinding meer; de accordeur is weer gewoon aan de beurt.
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=_fake_met_treffer(_referentie(admin_engine, klaar_document)))
        assert rapport.afwijkingen == ()
        _run_documentenblok(monkeypatch, administratie_id, _fake_met_treffer(_referentie(admin_engine, klaar_document)))
        assert accordering_service.documenten_aan_de_beurt(administratie_id=administratie_id) == {accordeur_1: [klaar_document]}

    def test_toch_verschillend_als_beheerder_accepteert_de_bevinding_direct(
        self, klaar_document, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, admin_engine, monkeypatch
    ) -> None:
        _ter_accordering(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document)
        _run_documentenblok(monkeypatch, administratie_id, _fake_met_treffer(_referentie(admin_engine, klaar_document)))
        headers = _bearer(beheerder_id, rol="beheerder")
        rij = self._bevinding(headers)
        r = client.post(
            f"/reconciliatie/documenten/{klaar_document}/extern-geboekt/toch-verschillend",
            headers=headers,
            json={"administratie_id": str(administratie_id), "extern_id": EXTERN_ID, "extern_boekstuk": BOEKSTUK, "reden": "andere levering — gecontroleerd", "bevinding_id": rij["id"]},
        )
        assert r.status_code == 200 and r.json()["bevinding_geaccepteerd"] is True
        d = client.get("/reconciliatie/bevindingen?soort=alle", headers=headers).json()
        [na] = [x for x in d["rijen"] if x["id"] == rij["id"]]
        assert na["soort"] == "geaccepteerd" and na["acceptatie"]["reden"].startswith("Toch verschillend — ")
        # Direct ook uit de accordeur-app-vlag (live acceptatie-stand).
        [item] = accordering_service.wachtrij_voor_accordeur(actor_id=accordeur_1, administratie_ids=[administratie_id])
        assert item.extern_geboekt is None


# ---- 5. registry, actiemail, urgentie ---------------------------------------------------------------------------------


class TestRegistryEnMail:
    def test_soort_start_direct_in_actie_met_reden_en_komt_in_de_actiemail(self) -> None:
        d = soort_stand.REGISTRY["intussen_extern_geboekt"]
        assert d.default == soort_stand.ACTIE and d.blok == "documenten" and "Peter 22-09" in (d.direct_actie_reden or "")
        b = run_service.Bevinding(
            blok="documenten",
            soort="afwijking",
            administratie_id=uuid.uuid4(),
            vingerafdruk="x1",
            tekst="AFWIJKING document=… soort=intussen_extern_geboekt: al geboekt in Reeleezee: RLZ-04-00000518",
            detail={
                "bron": "documenten",
                "record_id": str(uuid.uuid4()),
                "afwijking_soort": "intussen_extern_geboekt",
                "detail": "al geboekt in Reeleezee: RLZ-04-00000518 (referentie F/2026/01235, buiten de module)",
                "leverancier_naam": "Beter Assemblage B.V.",
                "factuurnummer": "F/2026/01235",
                "administratie_naam": "Bouwadvies Oost Nederland B.V.",
                "extern_boekstuk": "RLZ-04-00000518",
                "bedrag_extern": "173.84",
                "extern_datum": "2026-08-26",
                "document_status": "ter_accordering",
                "backend": "rlz",
            },
        )
        assert not soort_stand.in_meting(b, None)
        regel = run_service.actie_regel(b, "Bouwadvies Oost Nederland B.V.")
        assert "Bouwadvies" in regel and "Al geboekt in RLZ buiten de module" in regel
        assert not teksten.bevat_technische_sleutel(regel)

    def test_urgentie_direct_onder_verdwenen(self) -> None:
        from app.reconciliatie import kantoorbreed

        assert kantoorbreed._URGENTIE_AFWIJKING_SOORT["intussen_extern_geboekt"] == 1
