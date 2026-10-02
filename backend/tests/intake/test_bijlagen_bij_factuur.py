# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Bijlagen bij de factuur (Peter 02-10 "één mail = één document — alle bijlagen blijven bij de factuur, scheelt heel veel
werk"; migratie 0174; `app/intake/bijlage_herkenning.py`, `app/intake/verwerking.py::_verwerk_items_met_bijlagen`,
`app/documenten/bijlagen.py`, nazorg `app/intake/bijlagen_nabundelen.py`).

Casus: de Universal-Nederland-verhuurmail — één UBL-factuur (+ PDF-beeld) mét een huurstaat-PDF (tekstlaag zonder
factuursignalen) en een specificatie-xlsx. Doel: één document, twee bijlage-rijen (status samengevoegd, rol bijlage),
zichtbaar via de detail-route + bestand-route, mee naar RLZ bij boeken; meerdere facturen → sleutel-match of
"niet eenduidig" bij alle; nul facturen → bestaand gedrag; verzamelbak-toewijzing neemt de bijlagen mee; nazorg-CLI
koppelt al gesplitste documenten; ongedaan = terug; dagteller `bijlagen_gebundeld`."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app import cli
from app.config import settings
from app.db.session import scoped_session
from app.documenten import bijlagen as bijlagen_module
from app.documenten import boeken, boekvoorstel
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentBron, DocumentStatus
from app.extractie.splitsing import FactuurSegment
from app.intake import bijlage_herkenning as bh
from app.intake import bijlagen_nabundelen as nb
from app.intake import verwerking, verzamelbak
from app.intake.models import IntakeBericht
from app.main import app
from app.reconciliatie import automatiseringen
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.extractie.pdf_helper import maak_tekst_pdf
from tests.intake.conftest import administratie_heet_blow, bouw_eml, bouw_pdf, bouw_ubl, intake_ai_aan  # noqa: F401

client = TestClient(app)

FACTUURNUMMER = "RLZ-2080142625"
HUURSTAAT = maak_tekst_pdf(["Huurstaat week 27", "Project 26084 Opdrachtgever A", "Steigermateriaal 120 m2"])
WERKBON = maak_tekst_pdf(["Werkbon 7731", "Uren montage 8", "Getekend door uitvoerder"])
FACTUUR_PDF = maak_tekst_pdf(["FACTUUR", f"Factuurnummer {FACTUURNUMMER}", "Totaal te betalen € 908,89", "BTW 21% € 157,74"])
XLSX = b"PK\x03\x04specificatie-niet-omzetbron"


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "boekhouding") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _rij(admin_engine: Engine, document_id: uuid.UUID) -> dict:
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT administratie_id, status, soort, bestandsnaam, samengevoegd_in_id, samenvoeg_rol, opslag_pad "
                "FROM boekhouding.document WHERE id = :id"
            ),
            {"id": document_id},
        ).one()
    return dict(rij._mapping)


def _bijlagen_van(admin_engine: Engine, factuur_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            dict(r._mapping)
            for r in conn.execute(
                text(
                    "SELECT id, bestandsnaam, status, samenvoeg_rol, administratie_id FROM boekhouding.document "
                    "WHERE samengevoegd_in_id = :id ORDER BY bestandsnaam"
                ),
                {"id": factuur_id},
            )
        ]


def _audits(admin_engine: Engine, actie: str) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            dict(r._mapping)
            for r in conn.execute(
                text("SELECT record_id, nieuwe_waarde, administratie_id FROM platform.audit_event WHERE actie = :a ORDER BY tijdstip"),
                {"a": actie},
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


def _verhuurmail(*, klant: str = "BLOW B.V.", extra: list[tuple[str, bytes, str, str]] | None = None, message_id: str | None = None) -> bytes:
    return bouw_eml(
        afzender="administratie@universal-nederland.nl",
        onderwerp="Facturen verhuur week 27",
        message_id=message_id,
        bijlagen=[
            (f"{FACTUURNUMMER}.xml", bouw_ubl(factuurnummer=FACTUURNUMMER, klant=klant, leverancier="Universal Nederland B.V."), "application", "xml"),
            ("huurstaat-wk27.pdf", HUURSTAAT, "application", "pdf"),
            ("specificatie.xlsx", XLSX, "application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            *(extra or []),
        ],
    )


class TestHerkenning:
    def test_ubl_is_factuur_pdf_zonder_signalen_is_bijlage_scan_is_kandidaat(self) -> None:
        assert bh.herken_pdf(HUURSTAAT).klasse == bh.KLASSE_BIJLAGE
        assert bh.herken_pdf(WERKBON).klasse == bh.KLASSE_BIJLAGE
        assert bh.herken_pdf(FACTUUR_PDF).klasse == bh.KLASSE_FACTUUR
        assert bh.herken_pdf(bouw_pdf(1)).klasse == bh.KLASSE_KANDIDAAT  # geen tekstlaag: alleen de AI kan het zeggen
        from app.intake.eml import IntakeBijlage

        assert bh.herken_bijlage(IntakeBijlage("f.xml", b"<x/>", "application/xml")).klasse == bh.KLASSE_FACTUUR
        assert bh.herken_bijlage(IntakeBijlage("s.xlsx", XLSX, "application/octet-stream")).klasse == bh.KLASSE_BIJLAGE
        assert bh.herken_bijlage(IntakeBijlage("s.csv", b"a;b", "text/csv")).klasse == bh.KLASSE_BIJLAGE
        assert bh.herken_bijlage(IntakeBijlage("k.vcf", b"BEGIN", "text/vcard")).klasse == bh.KLASSE_KANDIDAAT
        assert bh.herken_bijlage(IntakeBijlage("logo.png", b"\x89PNG", "image/png", inline=True)).klasse == bh.KLASSE_KANDIDAAT

    def test_sleutels_en_treffer(self) -> None:
        sleutels = bh.sleutels_uit_ubl(bouw_ubl(factuurnummer=FACTUURNUMMER))
        assert "rlz-2080142625" in sleutels
        assert bh.bijlage_draagt_sleutel("specificatie RLZ-2080142625.pdf", None, sleutels)
        assert bh.bijlage_draagt_sleutel("specificatie.pdf", maak_tekst_pdf([f"Bij factuur {FACTUURNUMMER}"]), sleutels)
        assert not bh.bijlage_draagt_sleutel("huurstaat.pdf", HUURSTAAT, sleutels)
        assert bh.sleutels_uit_tekst("F-1") == frozenset()  # te kort = nooit een sleutel


class TestIntakeEenMailEenDocument:
    def test_een_factuur_bijlagen_hangen_eraan_niet_geextraheerd(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine, monkeypatch
    ) -> None:
        # Guard: de AI mag voor de bijlagen nooit aangeroepen worden (ook niet als de gate aan zou staan).
        def faal(*a, **k):
            raise AssertionError("AI aangeroepen voor een bijlage")

        monkeypatch.setattr(verwerking.splitsing_extractie, "detecteer_facturen", faal)
        resultaat = verwerking.verwerk_eml(_verhuurmail(), actor_id=gescoopte_gebruiker)
        per_naam = {r.bestandsnaam: r for r in resultaat.bijlagen}
        factuur = per_naam[f"{FACTUURNUMMER}.xml"]
        assert factuur.uitkomst == "toegewezen" and factuur.document_id is not None
        assert per_naam["huurstaat-wk27.pdf"].uitkomst == verwerking.UITKOMST_BIJLAGE
        assert per_naam["specificatie.xlsx"].uitkomst == verwerking.UITKOMST_BIJLAGE
        assert per_naam["huurstaat-wk27.pdf"].document_id == factuur.document_id
        bijlagen = _bijlagen_van(admin_engine, factuur.document_id)
        assert [b["bestandsnaam"] for b in bijlagen] == ["huurstaat-wk27.pdf", "specificatie.xlsx"]
        assert all(b["status"] == "samengevoegd" and b["samenvoeg_rol"] == "bijlage" for b in bijlagen)
        assert all(b["administratie_id"] == administratie_heet_blow for b in bijlagen)
        # Tijdlijn op de factuur (één regel per bijlage) + audit per bijlage → dagteller.
        regels = [g for g in _tijdlijn(admin_engine, factuur.document_id) if g["detail"].get(bijlagen_module.TIJDLIJN_SLEUTEL)]
        assert len(regels) == 2 and all("bijlage gekoppeld" in g["detail"]["reden"] for g in regels)
        audits = _audits(admin_engine, bijlagen_module.AUDIT_BIJLAGE_GEKOPPELD)
        assert len(audits) == 2 and all(a["nieuwe_waarde"]["factuur_document_id"] == str(factuur.document_id) for a in audits)
        # Intake-bericht: élke bijlage verantwoord ("niets verdwijnt stil").
        with scoped_session(None) as session:
            bericht = session.get(IntakeBericht, resultaat.bericht_id)
            uitkomsten = {r["bestandsnaam"]: r["uitkomst"] for r in bericht.detail["bijlagen"]}
        assert uitkomsten["huurstaat-wk27.pdf"] == "bijlage" and uitkomsten["specificatie.xlsx"] == "bijlage"
        # Werkvoorraad: alleen de factuur telt; de bijlagen zijn samengevoegd (geen werk).
        with admin_engine.connect() as conn:
            open_docs = conn.execute(
                text("SELECT count(*) FROM boekhouding.document WHERE administratie_id = :a AND status NOT IN ('samengevoegd')"),
                {"a": administratie_heet_blow},
            ).scalar_one()
        assert open_docs == 1
        # Herverwerking (idempotent): geen tweede set bijlagen.
        verwerking.verwerk_eml(_verhuurmail(), actor_id=gescoopte_gebruiker)
        assert len(_bijlagen_van(admin_engine, factuur.document_id)) == 2

    def test_detail_en_bestand_routes(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        resultaat = verwerking.verwerk_eml(_verhuurmail(), actor_id=gescoopte_gebruiker)
        factuur_id = next(r.document_id for r in resultaat.bijlagen if r.uitkomst == "toegewezen")
        headers = _bearer(gescoopte_gebruiker)
        detail = client.get(f"/administraties/{administratie_heet_blow}/documenten/{factuur_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        bijlagen = detail.json()["bijlagen"]
        assert [b["bestandsnaam"] for b in bijlagen] == ["huurstaat-wk27.pdf", "specificatie.xlsx"]
        assert bijlagen[0]["content_type"] == "application/pdf" and bijlagen[0]["niet_eenduidig"] is False
        bestand = client.get(
            f"/administraties/{administratie_heet_blow}/documenten/{factuur_id}/bijlagen/{bijlagen[0]['id']}/bestand",
            headers=headers,
        )
        assert bestand.status_code == 200 and bestand.content == HUURSTAAT
        assert bestand.headers["content-type"].startswith("application/pdf")
        # Een bijlage van een ánder document = 404 (nooit stil een verkeerd bestand).
        fout = client.get(
            f"/administraties/{administratie_heet_blow}/documenten/{uuid.uuid4()}/bijlagen/{bijlagen[0]['id']}/bestand",
            headers=headers,
        )
        assert fout.status_code == 404
        # Lijst: factuur draagt `bijlagen: 2`, niet als exemplaren; de bijlage-rij draagt haar rol.
        lijst = client.get(
            f"/administraties/{administratie_heet_blow}/documenten?toon_afgehandeld=true", headers=headers
        ).json()["documenten"]
        per_id = {d["id"]: d for d in lijst}
        assert per_id[str(factuur_id)]["bijlagen"] == 2 and per_id[str(factuur_id)]["samengevoegde_exemplaren"] == 0
        assert per_id[bijlagen[0]["id"]]["samenvoeg_rol"] == "bijlage"
        assert per_id[bijlagen[0]["id"]]["samengevoegd_in"]["document_id"] == str(factuur_id)

    def test_meerdere_facturen_sleutel_match_anders_bij_alle_niet_eenduidig(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        tweede_nummer = "RLZ-2080142626"
        eml = bouw_eml(
            afzender="administratie@universal-nederland.nl",
            bijlagen=[
                (f"{FACTUURNUMMER}.xml", bouw_ubl(factuurnummer=FACTUURNUMMER, leverancier="Universal Nederland B.V."), "application", "xml"),
                (f"{tweede_nummer}.xml", bouw_ubl(factuurnummer=tweede_nummer, leverancier="Universal Nederland B.V."), "application", "xml"),
                (f"specificatie {tweede_nummer}.pdf", HUURSTAAT, "application", "pdf"),  # treffer op naam
                ("werkbon.pdf", WERKBON, "application", "pdf"),  # geen treffer → bij alle
            ],
        )
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        per_naam = {r.bestandsnaam: r for r in resultaat.bijlagen}
        eerste = per_naam[f"{FACTUURNUMMER}.xml"].document_id
        tweede = per_naam[f"{tweede_nummer}.xml"].document_id
        assert eerste and tweede and eerste != tweede
        b1 = _bijlagen_van(admin_engine, eerste)
        b2 = _bijlagen_van(admin_engine, tweede)
        assert [b["bestandsnaam"] for b in b1] == ["werkbon.pdf"]
        assert [b["bestandsnaam"] for b in b2] == [f"specificatie {tweede_nummer}.pdf", "werkbon.pdf"]
        assert b1[0]["samenvoeg_rol"] == "bijlage_niet_eenduidig"
        assert {b["bestandsnaam"]: b["samenvoeg_rol"] for b in b2} == {
            f"specificatie {tweede_nummer}.pdf": "bijlage",
            "werkbon.pdf": "bijlage_niet_eenduidig",
        }
        assert "niet eenduidig" in (per_naam["werkbon.pdf"].detail or "")

    def test_nul_facturen_bestaand_gedrag(self, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine) -> None:
        """Alleen een huurstaat (PDF zonder factuursignalen) → de oude route: verzamelbak (AI-gate uit)."""
        eml = bouw_eml(bijlagen=[("huurstaat-wk27.pdf", HUURSTAAT, "application", "pdf"), ("spec.xlsx", XLSX, "application", "octet-stream")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        per_naam = {r.bestandsnaam: r for r in resultaat.bijlagen}
        assert per_naam["huurstaat-wk27.pdf"].uitkomst == "verzamelbak"
        assert "intake_ai_uitgeschakeld" in (per_naam["huurstaat-wk27.pdf"].detail or "")
        assert per_naam["spec.xlsx"].uitkomst == "overgeslagen"  # spreadsheet zonder omzetbron, zoals vóór 02-10
        assert _audits(admin_engine, bijlagen_module.AUDIT_BIJLAGE_GEKOPPELD) == []

    def test_scan_zonder_tekstlaag_blijft_de_ai_route_en_wordt_tweede_factuur(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, intake_ai_aan: None, admin_engine: Engine, monkeypatch
    ) -> None:
        """Een PDF zonder tekstlaag is geen bijlage maar een kandidaat: de AI beslist (bestaand); zegt die "factuur", dan
        zijn er twee facturen en hangt de huurstaat niet eenduidig aan beide."""
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        monkeypatch.setattr(
            verwerking.splitsing_extractie,
            "detecteer_facturen",
            lambda inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None: [
                FactuurSegment(1, 1, "BLOW B.V.", "Bouwmaat", "F-2026-0099", 0.95)
            ],
        )
        resultaat = verwerking.verwerk_eml(
            _verhuurmail(extra=[("scan.pdf", bouw_pdf(1), "application", "pdf")]), actor_id=gescoopte_gebruiker
        )
        per_naam = {r.bestandsnaam: r for r in resultaat.bijlagen}
        assert per_naam["scan.pdf"].uitkomst == "toegewezen"
        assert per_naam["huurstaat-wk27.pdf"].uitkomst == verwerking.UITKOMST_BIJLAGE
        scan_bijlagen = _bijlagen_van(admin_engine, per_naam["scan.pdf"].document_id)
        assert {b["bestandsnaam"] for b in scan_bijlagen} == {"huurstaat-wk27.pdf", "specificatie.xlsx"}
        assert all(b["samenvoeg_rol"] == "bijlage_niet_eenduidig" for b in scan_bijlagen)

    def test_verzamelbak_factuur_neemt_bijlagen_mee_bij_toewijzen(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        resultaat = verwerking.verwerk_eml(_verhuurmail(klant="Onbekende Klant B.V."), actor_id=gescoopte_gebruiker)
        per_naam = {r.bestandsnaam: r for r in resultaat.bijlagen}
        factuur_id = per_naam[f"{FACTUURNUMMER}.xml"].document_id
        assert per_naam[f"{FACTUURNUMMER}.xml"].uitkomst == "verzamelbak"
        assert per_naam["huurstaat-wk27.pdf"].uitkomst == verwerking.UITKOMST_BIJLAGE
        voor = _bijlagen_van(admin_engine, factuur_id)
        assert len(voor) == 2 and all(b["administratie_id"] is None for b in voor)
        verzamelbak.wijs_toe(document_id=factuur_id, administratie_id=administratie_id, actor_id=gescoopte_gebruiker)
        na = _bijlagen_van(admin_engine, factuur_id)
        assert len(na) == 2 and all(b["administratie_id"] == administratie_id for b in na)
        assert _rij(admin_engine, factuur_id)["administratie_id"] == administratie_id


def _regel() -> boekvoorstel.BoekvoorstelRegelData:
    return boekvoorstel.BoekvoorstelRegelData(
        ledger_id=uuid.uuid4(), taxrate_id=uuid.uuid4(), project_id=None, netto_bedrag=Decimal("100.00"),
        btw_bedrag=Decimal("21.00"), omschrijving="Huur",
    )


class TestBoekenMetBijlagen:
    def test_bijlagen_gaan_als_extra_uploads_mee_naar_rlz(
        self,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.beheer import service as beheer_service

        beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_heet_blow, ingeschakeld=True)
        resultaat = verwerking.verwerk_eml(_verhuurmail(), actor_id=gescoopte_gebruiker)
        factuur_id = next(r.document_id for r in resultaat.bijlagen if r.uitkomst == "toegewezen")
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_heet_blow,
            document_id=factuur_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=uuid.uuid4(),
            referentie=FACTUURNUMMER,
            factuurdatum=date(2026, 7, 1),
            totaalbedrag=Decimal("121.00"),
            regels=[_regel()],
        )
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
        uitkomst = boeken.boek_document(administratie_id=administratie_heet_blow, document_id=factuur_id, actor_id=gescoopte_gebruiker)
        assert uitkomst.status == DocumentStatus.GEBOEKT
        namen = sorted(u["filename"] for u in fake_client.uploads)
        # Factuurbeeld (de UBL zelf — geen PDF-beeld in deze mail) + de twee bijlagen, alle op hetzelfde RLZ-document.
        assert namen == sorted([f"{FACTUURNUMMER}.xml", "huurstaat-wk27.pdf", "specificatie.xlsx"])
        assert len({str(u["entity_id"]) for u in fake_client.uploads}) == 1
        assert len({str(u["upload_id"]) for u in fake_client.uploads}) == 3  # deterministisch, per bijlage uniek

    def test_mislukte_extra_bijlage_is_zichtbaar_maar_geen_boekfout(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        from app.backends.port import ExtraBijlage
        from app.backends.rlz_inkoop import RlzInkoopPort
        from app.rlz.client import RlzApiError

        class Client(FakeBoekClient):
            def upload_bijlage(self, entity_path, entity_id, *, upload_id, filename, content_base64):
                if filename == "kapot.pdf":
                    raise RlzApiError(500, "PUT", "Uploads", "mislukt (simulatie)")
                return super().upload_bijlage(entity_path, entity_id, upload_id=upload_id, filename=filename, content_base64=content_base64)

        voorstel = boekvoorstel.BoekvoorstelData(
            document_id=uuid.uuid4(), vendor_id=uuid.uuid4(), referentie="F-1", factuurdatum=date(2026, 7, 1),
            totaalbedrag=Decimal("121.00"), rlz_boekstuknummer=None, opgeslagen=True, regels=[_regel()],
        )
        uitkomst = RlzInkoopPort(Client()).boek_inkoopfactuur(
            document_id=voorstel.document_id,
            voorstel=voorstel,
            bestand=b"%PDF",
            bestandsnaam="f.pdf",
            extra_bijlagen=[
                ExtraBijlage(uuid.uuid4(), "kapot.pdf", b"x", "application/pdf", uuid.uuid4()),
                ExtraBijlage(uuid.uuid4(), "goed.pdf", b"y", "application/pdf", uuid.uuid4()),
            ],
        )
        assert uitkomst.boekstuknummer is not None
        per = {u["bestandsnaam"]: u["uitkomst"] for u in uitkomst.detail["extra_bijlagen"]}
        assert per == {"kapot.pdf": "mislukt", "goed.pdf": "geupload"}
        assert "kapot.pdf" in uitkomst.detail["waarschuwing"]


class TestNazorgBijlagenNabundelen:
    def _gesplitste_mail(self, actor: uuid.UUID, aid: uuid.UUID, admin_engine: Engine, *, bericht_id: uuid.UUID | None = None, status_bijlage: str | None = None) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
        """De productiesituatie van vóór 02-10: factuur-UBL én huurstaat-PDF als losse documenten uit dezelfde mail."""
        bericht_id = bericht_id or uuid.uuid4()
        with scoped_session(None, actor_id=actor) as session:
            session.add(
                IntakeBericht(
                    id=bericht_id, message_id=f"<{bericht_id}@universal.test>", afzender="administratie@universal-nederland.nl",
                    onderwerp="Facturen verhuur", verwerkt_door=actor, detail={"bijlagen": []},
                )
            )
        factuur_id = documenten_service.upload_document(
            administratie_id=aid, bestandsnaam=f"{FACTUURNUMMER}.xml",
            inhoud=bouw_ubl(factuurnummer=FACTUURNUMMER, leverancier="Universal Nederland B.V."),
            actor_id=actor, bron=DocumentBron.EMAIL, intake_bericht_id=bericht_id,
        ).document_id
        bijlage_id = documenten_service.upload_document(
            administratie_id=aid, bestandsnaam="huurstaat-wk27.pdf", inhoud=HUURSTAAT, actor_id=actor,
            bron=DocumentBron.EMAIL, intake_bericht_id=bericht_id,
        ).document_id
        with scoped_session(None, actor_id=actor) as session:
            bericht = session.get(IntakeBericht, bericht_id)
            assert bericht is not None
            bericht.detail = {"bijlagen": [
                {"bestandsnaam": f"{FACTUURNUMMER}.xml", "uitkomst": "toegewezen", "document_id": str(factuur_id), "detail": f"tenaamstelling → {aid}"},
                {"bestandsnaam": "huurstaat-wk27.pdf", "uitkomst": "toegewezen", "document_id": str(bijlage_id), "detail": f"afzender → {aid}"},
            ]}
        if status_bijlage:
            with admin_engine.begin() as conn:
                conn.execute(text("UPDATE boekhouding.document SET status = :s WHERE id = :id"), {"s": status_bijlage, "id": bijlage_id})
        return bericht_id, factuur_id, bijlage_id

    def test_dry_run_toont_factuur_bijlagen_en_schrijft_niets(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine, capsys
    ) -> None:
        _, factuur_id, bijlage_id = self._gesplitste_mail(gescoopte_gebruiker, administratie_id, admin_engine)
        voor = _rij(admin_engine, bijlage_id)
        telling = nb.nabundel_alle(dry_run=True, administratie_id=administratie_id)
        assert telling.berichten == 1 and telling.kandidaten == 1 and telling.gekoppeld == 0
        assert telling.uitkomsten[0].uitkomst == nb.UITKOMST_KANDIDAAT and "zou koppelen" in (telling.uitkomsten[0].reden or "")
        assert _rij(admin_engine, bijlage_id) == voor
        # Élke CLI-vorm uit het meetrecept letterlijk (regel 19-09 poging 2).
        assert cli.main(["bijlagen-nabundelen", "--dry-run"]) == 0
        assert cli.main(["bijlagen-nabundelen", "--dry-run", "--administratie", str(administratie_id)]) == 0
        assert cli.main(["bijlagen-nabundelen", "--dry-run", "--sinds", "2026-01-01"]) == 0
        uit = capsys.readouterr().out
        assert "DRY-RUN" in uit and f"{FACTUURNUMMER}.xml ← huurstaat-wk27.pdf" in uit and "TOTAAL:" in uit
        assert cli.main(["bijlagen-nabundelen", "--dry-run", "--uitvoeren"]) == 2
        assert cli.main(["bijlagen-nabundelen", "--dry-run", "--sinds", "gisteren"]) == 2

    def test_echte_run_koppelt_idempotent_en_ongedaan(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, factuur_id, bijlage_id = self._gesplitste_mail(gescoopte_gebruiker, administratie_id, admin_engine)
        telling = nb.nabundel_alle(dry_run=False, administratie_id=administratie_id)
        assert telling.gekoppeld == 1 and telling.mislukt == 0
        rij = _rij(admin_engine, bijlage_id)
        assert rij["status"] == "samengevoegd" and rij["samengevoegd_in_id"] == factuur_id and rij["samenvoeg_rol"] == "bijlage"
        laatste = _tijdlijn(admin_engine, bijlage_id)[-1]
        assert laatste["detail"]["vorige_status"] == "te_controleren" and laatste["detail"]["herkomst"] == nb_herkomst()
        assert len(_audits(admin_engine, bijlagen_module.AUDIT_BIJLAGE_GEKOPPELD)) == 1
        # Idempotent: tweede run vindt niets.
        assert nb.nabundel_alle(dry_run=False, administratie_id=administratie_id).kandidaten == 0
        # Ongedaan via de CLI: terug naar te_controleren, verwijzing weg, audit.
        assert cli.main(["bijlagen-nabundelen", "--uitvoeren", "--ongedaan", str(bijlage_id), "--reden", "toch een factuur", "--administratie", str(administratie_id)]) == 0
        rij = _rij(admin_engine, bijlage_id)
        assert rij["status"] == "te_controleren" and rij["samengevoegd_in_id"] is None and rij["samenvoeg_rol"] is None
        assert len(_audits(admin_engine, bijlagen_module.AUDIT_BIJLAGE_ONGEDAAN)) == 1
        assert cli.main(["bijlagen-nabundelen", "--ongedaan", str(bijlage_id), "--reden", "x"]) == 2  # schrijvend zonder --uitvoeren

    def test_mens_oordeel_wordt_overgeslagen_met_reden(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        self._gesplitste_mail(gescoopte_gebruiker, administratie_id, admin_engine, status_bijlage="ter_accordering")
        telling = nb.nabundel_alle(dry_run=False, administratie_id=administratie_id)
        assert telling.kandidaten == 0 and telling.overgeslagen == 1
        assert "mens heeft al geoordeeld" in (telling.uitkomsten[0].reden or "")

    def test_geboekte_factuur_krijgt_bijlage_als_rlz_upload(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, factuur_id, bijlage_id = self._gesplitste_mail(gescoopte_gebruiker, administratie_id, admin_engine)
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.document SET status = 'geboekt' WHERE id = :id"), {"id": factuur_id})
        fake = FakeBoekClient()
        telling = nb.nabundel_alle(dry_run=False, administratie_id=administratie_id, client_factory=lambda aid: fake)
        assert telling.gekoppeld == 1
        assert telling.uitkomsten[0].uitkomst == nb.UITKOMST_GEKOPPELD and "geüpload op PurchaseInvoices/" in (telling.uitkomsten[0].upload or "")
        assert [u["filename"] for u in fake.uploads] == ["huurstaat-wk27.pdf"]


def nb_herkomst() -> str:
    return bijlagen_module.HERKOMST_NAZORG


class TestDagteller:
    def test_bijlagen_gebundeld_telt_audit_bijlage_gekoppeld(self) -> None:
        from datetime import UTC, datetime, timedelta

        nu = datetime.now(UTC)
        feiten = automatiseringen.Feiten(
            audit=[
                automatiseringen.AuditFeit(actie="bijlage_gekoppeld", tijdstip=nu - timedelta(hours=1), nieuwe_waarde={"niet_eenduidig": False}, administratie_id=None),
                automatiseringen.AuditFeit(actie="bijlage_gekoppeld", tijdstip=nu - timedelta(hours=2), nieuwe_waarde={"niet_eenduidig": True}, administratie_id=None),
            ]
        )
        tellers = {t.sleutel: t for t in automatiseringen.bereken(feiten, nu=nu)}
        t = tellers[automatiseringen.BIJLAGEN_GEBUNDELD]
        assert t.dag.gedaan == 2 and t.dag.overgeslagen.get(automatiseringen.BIJLAGE_NIET_EENDUIDIG) == 1
