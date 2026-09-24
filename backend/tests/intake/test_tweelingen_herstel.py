# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Vastly-PDF-tweelingen achteraf bundelen (blok 1 bundelrun 24-09; `app/intake/tweelingen_herstel.py`) —
kandidaten-motor, herstel (PDF → beeld van het UBL-verkoopfactuur-document, PDF-document → samengevoegd, tijdlijn + audit
`gebundeld_achteraf`, RLZ-bijlage bij een geboekt UBL), dry-run schrijft niets, idempotent, twijfel = overgeslagen mét
reden, reconciliatie-soort `ubl_pdf_ongebundeld` in meten, actie-route "Bundelen" 200/404/409, élke CLI-argumentvorm."""

from __future__ import annotations

import argparse
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app import cli
from app.db.session import scoped_session
from app.documenten import reconciliatie
from app.documenten import service as documenten_service
from app.documenten.models import DocumentBron, DocumentSoort
from app.intake import tweelingen_herstel as tw
from app.intake.models import IntakeBericht
from app.main import app
from app.reconciliatie import run as run_service
from app.reconciliatie import soort_stand, teksten
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.intake.conftest import bouw_pdf, bouw_ubl

client = TestClient(app)

UBL_NAAM = "factuur-RUB-2026-0031-ubl.xml"
PDF_NAAM = "factuur-RUB-2026-0031.pdf"
NUMMER = "RUB-2026-0031"


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "boekhouding") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _bericht(actor: uuid.UUID) -> uuid.UUID:
    bericht_id = uuid.uuid4()
    with scoped_session(None, actor_id=actor) as session:
        session.add(
            IntakeBericht(
                id=bericht_id,
                message_id=f"<{bericht_id}@vastly.test>",
                afzender="facturen@vastly.software",
                onderwerp="Facturen oktober",
                verwerkt_door=actor,
                detail={"bijlagen": []},
            )
        )
    return bericht_id


def _tweeling(
    actor: uuid.UUID,
    aid: uuid.UUID,
    *,
    ubl_naam: str = UBL_NAAM,
    pdf_naam: str = PDF_NAAM,
    nummer: str = NUMMER,
    bericht_id: uuid.UUID | None = None,
    pdf_inhoud: bytes | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """De productiesituatie van 23-09: UBL als verkoopfactuur-document, PDF als losse inkoopfactuur, zelfde e-mail."""
    bericht_id = bericht_id or _bericht(actor)
    ubl_id = documenten_service.upload_document(
        administratie_id=aid,
        bestandsnaam=ubl_naam,
        inhoud=bouw_ubl(factuurnummer=nummer, klant="Rubicon Investments B.V.", leverancier="Vastly Verhuur"),
        actor_id=actor,
        bron=DocumentBron.EMAIL,
        soort=DocumentSoort.VERKOOPFACTUUR,
        intake_bericht_id=bericht_id,
    ).document_id
    pdf_id = documenten_service.upload_document(
        administratie_id=aid,
        bestandsnaam=pdf_naam,
        inhoud=pdf_inhoud if pdf_inhoud is not None else bouw_pdf(1) + pdf_naam.encode(),
        actor_id=actor,
        bron=DocumentBron.EMAIL,
        intake_bericht_id=bericht_id,
    ).document_id
    return bericht_id, ubl_id, pdf_id


def _rij(admin_engine: Engine, document_id: uuid.UUID) -> dict:
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT status, soort, bestandsnaam, bron_opslag_pad, bron_bestandsnaam, bron_content_type, "
                "samengevoegd_in_id, opslag_pad FROM boekhouding.document WHERE id = :id"
            ),
            {"id": document_id},
        ).one()
    return dict(rij._mapping)


def _audits(admin_engine: Engine, record_id: uuid.UUID, actie: str) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            dict(r._mapping)
            for r in conn.execute(
                text(
                    "SELECT actor_id, oude_waarde, nieuwe_waarde FROM platform.audit_event WHERE record_id = :id AND actie = :a"
                ),
                {"id": record_id, "a": actie},
            )
        ]


def _tijdlijn(admin_engine: Engine, document_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            {"van": r[0], "naar": r[1], "detail": r[2] or {}}
            for r in conn.execute(
                text(
                    "SELECT van_status, naar_status, detail FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :id ORDER BY tijdstip, id"
                ),
                {"id": document_id},
            )
        ]


def _boek_verkoop(admin_engine: Engine, aid: uuid.UUID, ubl_id: uuid.UUID, actor: uuid.UUID) -> uuid.UUID:
    """Simuleert een geboekt UBL-document (casus RUB-2026-0031): verkoop_boeking-rij + status geboekt."""
    rlz_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.verkoop_boeking (id, administratie_id, document_id, factuurnummer, is_creditnota, "
                "totaalbedrag_incl, debiteur_customer_id, debiteur_naam, verkoop_rlz_id, status, geboekt_door) VALUES "
                "(:id, :aid, :doc, :nr, false, :tot, :cust, 'Huurder', :rlz, 'geboekt', :actor)"
            ),
            {
                "id": uuid.uuid4(),
                "aid": aid,
                "doc": ubl_id,
                "nr": NUMMER,
                "tot": Decimal("121.00"),
                "cust": uuid.uuid4(),
                "rlz": rlz_id,
                "actor": actor,
            },
        )
        conn.execute(text("UPDATE boekhouding.document SET status = 'geboekt' WHERE id = :id"), {"id": ubl_id})
    return rlz_id


class TestKandidaten:
    def test_vastly_tweeling_is_eenduidige_kandidaat_op_naamstam(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        bericht_id, ubl_id, pdf_id = _tweeling(gescoopte_gebruiker, administratie_id)
        assert _rij(admin_engine, pdf_id)["status"] == "te_controleren"
        [k] = tw.vind_kandidaten(administratie_id=administratie_id)
        assert k.eenduidig and k.pdf_document_id == pdf_id and k.ubl_document_id == ubl_id
        assert k.match_basis == "naamstam" and k.intake_bericht_id == bericht_id and k.ubl_geboekt is False

    def test_factuurnummer_in_pdf_naam_is_tweede_basis(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        _tweeling(
            gescoopte_gebruiker, administratie_id, ubl_naam="vastly-export-7.xml", pdf_naam="Factuur RUB-2026-0031.pdf"
        )
        [k] = tw.vind_kandidaten(administratie_id=administratie_id)
        assert k.eenduidig and k.match_basis == "factuurnummer" and k.factuurnummer == NUMMER

    def test_twee_pdfs_op_een_ubl_is_twijfel(self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
        bericht_id, _, _ = _tweeling(gescoopte_gebruiker, administratie_id)
        documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur-RUB-2026-0031-xml.pdf",
            inhoud=bouw_pdf(2) + b"tweede",
            actor_id=gescoopte_gebruiker,
            bron=DocumentBron.EMAIL,
            intake_bericht_id=bericht_id,
        )
        kandidaten = tw.vind_kandidaten(administratie_id=administratie_id)
        assert len(kandidaten) == 2 and not any(k.eenduidig for k in kandidaten)
        assert all("meerdere PDF" in (k.twijfel_reden or "") for k in kandidaten)
        # Dry-run toont ze als overgeslagen, schrijft niets.
        telling = tw.herstel_alle(dry_run=True, administratie_id=administratie_id)
        assert telling.kandidaten == 2 and telling.overgeslagen == 2 and telling.gebundeld == 0

    def test_ander_bericht_of_upload_bron_is_geen_kandidaat(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        _tweeling(gescoopte_gebruiker, administratie_id, bericht_id=_bericht(gescoopte_gebruiker), pdf_naam="los.pdf")
        # UBL uit bericht A, PDF met dezelfde stam uit bericht B → geen paar.
        documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam=PDF_NAAM,
            inhoud=bouw_pdf(1) + b"b",
            actor_id=gescoopte_gebruiker,
            bron=DocumentBron.EMAIL,
            intake_bericht_id=_bericht(gescoopte_gebruiker),
        )
        assert tw.vind_kandidaten(administratie_id=administratie_id) == []


class TestHerstel:
    def test_dry_run_schrijft_niets(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, ubl_id, pdf_id = _tweeling(gescoopte_gebruiker, administratie_id)
        voor_pdf, voor_ubl = _rij(admin_engine, pdf_id), _rij(admin_engine, ubl_id)
        telling = tw.herstel_alle(dry_run=True, administratie_id=administratie_id)
        assert telling.kandidaten == 1 and telling.gebundeld == 0
        assert telling.uitkomsten[0].uitkomst == tw.UITKOMST_KANDIDAAT and "zou bundelen" in (
            telling.uitkomsten[0].reden or ""
        )
        assert _rij(admin_engine, pdf_id) == voor_pdf and _rij(admin_engine, ubl_id) == voor_ubl
        assert _audits(admin_engine, pdf_id, tw.AUDIT_GEBUNDELD_ACHTERAF) == []

    def test_echte_run_bundelt_met_tijdlijn_en_audit_en_is_idempotent(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, ubl_id, pdf_id = _tweeling(gescoopte_gebruiker, administratie_id)
        pdf_voor = _rij(admin_engine, pdf_id)
        telling = tw.herstel_alle(dry_run=False, administratie_id=administratie_id)
        assert telling.kandidaten == 1 and telling.gebundeld == 1 and telling.mislukt == 0
        assert telling.uitkomsten[0].uitkomst == tw.UITKOMST_GEBUNDELD and telling.uitkomsten[0].bijlage is None
        pdf, ubl = _rij(admin_engine, pdf_id), _rij(admin_engine, ubl_id)
        assert pdf["status"] == "samengevoegd" and pdf["samengevoegd_in_id"] == ubl_id
        assert pdf["bestandsnaam"] == PDF_NAAM  # nooit verwijderd, nooit hernoemd
        assert (ubl["bron_opslag_pad"], ubl["bron_bestandsnaam"], ubl["bron_content_type"]) == (
            pdf_voor["opslag_pad"],
            PDF_NAAM,
            "application/pdf",
        )
        assert ubl["status"] == "te_controleren" and ubl["soort"] == "verkoopfactuur"
        # Tijdlijn beide kanten, audit beide rijen (systeem-actor).
        laatste = _tijdlijn(admin_engine, pdf_id)[-1]
        assert laatste["naar"] == "samengevoegd" and laatste["detail"][tw.TIJDLIJN_SLEUTEL] is True
        assert (
            laatste["detail"]["samengevoegd_in"] == str(ubl_id) and "achteraf gebundeld" in laatste["detail"]["reden"]
        )
        ubl_regels = [g for g in _tijdlijn(admin_engine, ubl_id) if g["detail"].get(tw.TIJDLIJN_SLEUTEL)]
        assert len(ubl_regels) == 1 and ubl_regels[0]["detail"]["beeld_van"] == str(pdf_id)
        assert len(_audits(admin_engine, pdf_id, tw.AUDIT_GEBUNDELD_ACHTERAF)) == 1
        [ubl_audit] = _audits(admin_engine, ubl_id, tw.AUDIT_GEBUNDELD_ACHTERAF)
        assert ubl_audit["nieuwe_waarde"]["beeld_document_id"] == str(pdf_id)
        # Het beeld van het UBL-document is nu de PDF (documenten/beeld.py).
        from app.documenten.beeld import HERKOMST_BRON, bepaal_beeld
        from app.documenten.models import Document
        from app.documenten.service import _standaard_opslag

        with scoped_session(administratie_id) as session:
            beeld = bepaal_beeld(session.get(Document, ubl_id), opslag=_standaard_opslag())
        assert beeld.herkomst == HERKOMST_BRON and beeld.bestandsnaam == PDF_NAAM
        # Idempotent: tweede run vindt niets.
        tweede = tw.herstel_alle(dry_run=False, administratie_id=administratie_id)
        assert tweede.kandidaten == 0

    def test_geboekt_ubl_stuurt_pdf_als_rlz_bijlage_mee(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, ubl_id, pdf_id = _tweeling(gescoopte_gebruiker, administratie_id)
        rlz_id = _boek_verkoop(admin_engine, administratie_id, ubl_id, gescoopte_gebruiker)
        fake = FakeBoekClient()
        fake._invoices[str(rlz_id)] = {"id": str(rlz_id), "Status": 2}
        [k] = tw.vind_kandidaten(administratie_id=administratie_id)
        assert k.ubl_geboekt is True
        telling = tw.herstel_alle(dry_run=False, administratie_id=administratie_id, client_factory=lambda aid: fake)
        [u] = telling.uitkomsten
        assert u.uitkomst == tw.UITKOMST_GEBUNDELD and u.bijlage == f"geüpload op SalesInvoices/{rlz_id}"
        assert [up["entity_id"] for up in fake.uploads] == [rlz_id]
        assert fake.uploads[0]["filename"] == PDF_NAAM and fake.uploads[0]["upload_id"] == tw.upload_id_voor(pdf_id)
        assert _rij(admin_engine, pdf_id)["status"] == "samengevoegd"

    def test_bijlage_fout_is_zichtbaar_en_bundeling_staat(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, ubl_id, pdf_id = _tweeling(gescoopte_gebruiker, administratie_id)
        rlz_id = _boek_verkoop(admin_engine, administratie_id, ubl_id, gescoopte_gebruiker)
        fake = FakeBoekClient(faal_op="upload")
        fake._invoices[str(rlz_id)] = {"id": str(rlz_id), "Status": 2}
        telling = tw.herstel_alle(dry_run=False, administratie_id=administratie_id, client_factory=lambda aid: fake)
        [u] = telling.uitkomsten
        assert u.uitkomst == tw.UITKOMST_GEBUNDELD_BIJLAGE_FOUT and "mislukt" in (u.bijlage or "")
        assert telling.gebundeld == 1 and _rij(admin_engine, pdf_id)["status"] == "samengevoegd"

    def test_pdf_intussen_verder_verwerkt_wordt_overgeslagen(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, _, pdf_id = _tweeling(gescoopte_gebruiker, administratie_id)
        [k] = tw.vind_kandidaten(administratie_id=administratie_id)
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.document SET status = 'ter_accordering' WHERE id = :id"), {"id": pdf_id}
            )
        u = tw.herstel_een(k, dry_run=False)
        assert u.uitkomst == tw.UITKOMST_OVERGESLAGEN and "ter accordering" in (u.reden or "")
        assert _rij(admin_engine, pdf_id)["status"] == "ter_accordering"


class TestReconciliatieEnActie:
    def test_soort_start_in_meten_en_heeft_leesbare_tekst(self) -> None:
        assert soort_stand.code_default(tw.SOORT_ONGEBUNDELD) == "meten"
        assert soort_stand.REGISTRY[tw.SOORT_ONGEBUNDELD].blok == "documenten"
        lees = teksten.leesbaar(
            run_service.Bevinding(
                blok="documenten",
                soort="afwijking",
                administratie_id=uuid.uuid4(),
                vingerafdruk="v",
                tekst="x",
                detail={
                    "afwijking_soort": tw.SOORT_ONGEBUNDELD,
                    "bestandsnaam": PDF_NAAM,
                    "ubl_bestandsnaam": UBL_NAAM,
                    "match_basis": "naamstam",
                    "ubl_geboekt": "ja",
                    "document_id": str(uuid.uuid4()),
                },
            )
        )
        assert "hoort bij een verkoopfactuur" in lees.titel and UBL_NAAM in lees.wat and "al geboekt" in lees.wat
        assert "Bundelen" in lees.doe

    def test_documentenblok_produceert_bevinding_en_actie_bundelt(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch
    ) -> None:
        _, ubl_id, pdf_id = _tweeling(gescoopte_gebruiker, administratie_id)
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=FakeBoekClient())
        [a] = [x for x in rapport.afwijkingen if x.soort == tw.SOORT_ONGEBUNDELD]
        assert a.document_id == pdf_id and a.context["ubl_document_id"] == str(ubl_id)
        assert a.context["match_basis"] == "naamstam" and a.context["bestandsnaam"] == PDF_NAAM
        # Eén échte run van het documenten-blok → rij in de kantoorbrede lijst mét deeplink naar het document.
        monkeypatch.setattr(
            cli.reconciliatie,
            "reconcilieer_alle_administraties",
            lambda: {
                administratie_id: reconciliatie.reconcilieer_administratie(
                    administratie_id=administratie_id, client=FakeBoekClient()
                )
            },
        )
        monkeypatch.setattr(cli.storno_detectie, "detecteer_en_meld_gestorneerd_alle", lambda: {})
        run_service.voer_uit(
            blokken=[("documenten", cli._reconciliatie)], args=argparse.Namespace(), bron="cli", stdout=lambda t: None
        )
        headers = _bearer(gescoopte_gebruiker)
        d = client.get("/reconciliatie/bevindingen?soort=meten", headers=headers).json()
        [rij] = [r for r in d["rijen"] if (r.get("detail") or {}).get("afwijking_soort") == tw.SOORT_ONGEBUNDELD]
        assert rij["detail"]["ubl_document_id"] == str(ubl_id) and rij["doel_pad"].endswith(f"document={pdf_id}")
        # Actie "Bundelen" (mens-actor) → 200; daarna 404 (geen paar meer) en de bevinding verdwijnt uit de volgende toets.
        r = client.post(
            f"/reconciliatie/documenten/{pdf_id}/bundelen",
            headers=headers,
            json={"administratie_id": str(administratie_id)},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ubl_document_id"] == str(ubl_id) and body["status"] == tw.UITKOMST_GEBUNDELD
        assert body["doel_pad"] == f"/verkoop/{administratie_id}/{ubl_id}" and body["match_basis"] == "naamstam"
        pdf = _rij(admin_engine, pdf_id)
        assert pdf["status"] == "samengevoegd" and pdf["samengevoegd_in_id"] == ubl_id
        [audit] = _audits(admin_engine, pdf_id, tw.AUDIT_GEBUNDELD_ACHTERAF)
        assert audit["actor_id"] == gescoopte_gebruiker  # mens-actor, niet het systeem
        r2 = client.post(
            f"/reconciliatie/documenten/{pdf_id}/bundelen",
            headers=headers,
            json={"administratie_id": str(administratie_id)},
        )
        assert r2.status_code == 404
        na = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=FakeBoekClient())
        assert [x for x in na.afwijkingen if x.soort == tw.SOORT_ONGEBUNDELD] == []

    def test_actie_op_twijfel_is_409_en_buiten_scope_403(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        bericht_id, _, pdf_id = _tweeling(gescoopte_gebruiker, administratie_id)
        documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur-RUB-2026-0031_UBL.xml",
            inhoud=bouw_ubl(factuurnummer=NUMMER, klant="Rubicon Investments B.V.") + b"<!-- 2 -->",
            actor_id=gescoopte_gebruiker,
            bron=DocumentBron.EMAIL,
            soort=DocumentSoort.VERKOOPFACTUUR,
            intake_bericht_id=bericht_id,
        )
        r = client.post(
            f"/reconciliatie/documenten/{pdf_id}/bundelen",
            headers=_bearer(gescoopte_gebruiker),
            json={"administratie_id": str(administratie_id)},
        )
        assert r.status_code == 409 and "meerdere UBL" in r.json()["detail"]
        andere = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere', :rlz)"),
                {"id": andere, "rlz": f"rlz-{andere}"},
            )
        r = client.post(
            f"/reconciliatie/documenten/{pdf_id}/bundelen",
            headers=_bearer(gescoopte_gebruiker),
            json={"administratie_id": str(andere)},
        )
        assert r.status_code == 403
        assert _rij(admin_engine, pdf_id)["status"] == "te_controleren"


class TestCli:
    @pytest.mark.parametrize(
        "argv",
        [
            ["vastly-pdf-tweelingen-herstel"],
            ["vastly-pdf-tweelingen-herstel", "--dry-run"],
            ["vastly-pdf-tweelingen-herstel", "--dry-run", "--administratie", "Scope-test"],
        ],
    )
    def test_dry_run_vormen_uit_het_meetrecept_letterlijk(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine, argv: list[str], capsys
    ) -> None:
        _, _, pdf_id = _tweeling(gescoopte_gebruiker, administratie_id)
        assert cli.main(argv) == 0
        uit = capsys.readouterr().out
        assert "DRY-RUN (niets geschreven)" in uit and "TOTAAL: 1 kandidaten, 0 gebundeld" in uit and PDF_NAAM in uit
        assert _rij(admin_engine, pdf_id)["status"] == "te_controleren"

    def test_uitvoeren_bundelt_en_tweede_run_is_leeg(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine, capsys
    ) -> None:
        _, _, pdf_id = _tweeling(gescoopte_gebruiker, administratie_id)
        assert cli.main(["vastly-pdf-tweelingen-herstel", "--uitvoeren", "--administratie", str(administratie_id)]) == 0
        assert "UITGEVOERD" in capsys.readouterr().out and _rij(admin_engine, pdf_id)["status"] == "samengevoegd"
        assert cli.main(["vastly-pdf-tweelingen-herstel", "--uitvoeren"]) == 0
        assert "TOTAAL: 0 kandidaten" in capsys.readouterr().out

    def test_dry_run_en_uitvoeren_samen_is_fout(self) -> None:
        assert cli.main(["vastly-pdf-tweelingen-herstel", "--dry-run", "--uitvoeren"]) == 2
