# ruff: noqa: F811 — pytest-fixtures als parameters (patroon tests/accordering)
"""Voorraad-aansluiting fase 1 (bouwrun 28-08 blok D, mockup voorraad-aansluiting.html, migratie 0086,
mi-schema): volautomatische normalisatie (dienst-regel zonder AI, AI-voorstel direct toegepast,
onzeker telt mee mét vlag, geen AI = niet_genormaliseerd), instroom uit het veldvoorstel, uitstroom uit
verkoopregels, dagniveau-standen, aansluiting mét tolerantie, telling, correctie herrekent historie,
opt-in-poorten en rolpoorten. Code voor cijfers — geen echte AI-calls."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentGebeurtenis
from app.extractie.client import ClaudeAntwoord
from app.main import app
from app.security.tokens import create_access_token
from app.voorraad import normalisatie, service
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401

client = TestClient(app)
VENDOR_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


class _FakeAi:
    """Duck-typed client: `vraag_json` geeft per aangeboden regel een gescript voorstel."""

    def __init__(self, antwoorden: dict[str, tuple[str | None, str | None, float]]) -> None:
        self.antwoorden = antwoorden
        self.aanroepen: list[str] = []

    def vraag_json(self, *, system: str, opdracht: str, json_schema: dict) -> ClaudeAntwoord:
        self.aanroepen.append(opdracht)
        regels = [
            r for r in opdracht.split("Factuurregels:\n", 1)[1].split("\n\nGeef per regel")[0].splitlines() if r.strip()
        ]
        voorstellen = []
        for regel in regels:
            nr, tekst = regel.split(". ", 1)
            tekst = tekst.split(" (leverancier:")[0]
            g, e, z = self.antwoorden.get(tekst, (None, None, 0.9))
            voorstellen.append({"i": int(nr), "g": g, "e": e, "z": z})
        return ClaudeAntwoord(data={"voorstellen": voorstellen}, afgekapt=False, input_tokens=10, output_tokens=5)


@pytest.fixture
def voorraad_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    beheer_service.zet_voorraad_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )


@pytest.fixture
def fake_ai(monkeypatch: pytest.MonkeyPatch) -> _FakeAi:
    fake = _FakeAi(
        {
            "KOP.DR.48/48 SW22 gegalv.": ("Koppelingen 48mm", "st", 0.92),
            "Buis 48,3x3,2 L=3000": ("Steigerbuis 3m", "st", 0.88),
            "Alu plank div.": ("Vlonders alu 2,5m", "st", 0.61),
            "Koppeling draaibaar 48": ("Koppelingen 48mm", "st", 0.95),
        }
    )
    monkeypatch.setattr(normalisatie, "_client_voor", lambda administratie_id, document_id: fake)
    return fake


def _inkoop_document(
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    opslag,
    admin_engine: Engine,
    *,
    naam: str,
    factuurdatum: str,
    regels: list[dict],
) -> uuid.UUID:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                "VALUES (:id, :aid, 'Scafom B.V.', '{}') ON CONFLICT DO NOTHING"
            ),
            {"id": VENDOR_ID, "aid": administratie_id},
        )
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=naam,
        inhoud=f"%PDF-1.4 {naam}".encode(),
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    veldvoorstel = {
        "bron": "ai",
        "leverancier_naam": "Scafom B.V.",
        "factuurdatum": factuurdatum,
        "vendor_suggestie": {"vendor_id": str(VENDOR_ID), "match": "exact"},
        "regels": regels,
    }
    # Veldvoorstel als tijdlijn-gebeurtenis zonder statusovergang (het document staat al op
    # te_controleren ná de upload) — zelfde vorm als de extractie-afronding schrijft.
    with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
        document = session.get(Document, resultaat.document_id)
        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=resultaat.document_id,
                van_status=document.status,
                naar_status=document.status,
                actor_id=gescoopte_gebruiker,
                detail={"veldvoorstel": veldvoorstel},
            )
        )
    return resultaat.document_id


def _regel(o: str, h: str | None, n: str, e: str | None = "st", p: str | None = None) -> dict:
    return {"omschrijving": o, "hoeveelheid": h, "netto_bedrag": n, "eenheid": e, "stuksprijs": p}


class TestNormalisatiePuur:
    def test_tekstsleutel_en_dienstregel(self) -> None:
        assert normalisatie.normaliseer_tekst("  KOP.DR.48/48  SW22, gegalv. ") == "kop.dr.48/48 sw22. gegalv."
        assert normalisatie.is_dienst("Transportkosten zone 2") is True
        assert normalisatie.is_dienst("Koppeling 48mm") is False
        assert normalisatie.bepaal_status(Decimal("0.61"), uitgesloten=False, artikelgroep_id=uuid.uuid4()) == "onzeker"
        assert (
            normalisatie.bepaal_status(Decimal("0.92"), uitgesloten=False, artikelgroep_id=uuid.uuid4())
            == "genormaliseerd"
        )
        assert normalisatie.bepaal_status(None, uitgesloten=True, artikelgroep_id=None) == "uitgesloten"
        assert normalisatie.bepaal_status(None, uitgesloten=False, artikelgroep_id=None) == "niet_genormaliseerd"


class TestInstroom:
    def test_toggle_uit_registreert_niets(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, fake_ai
    ) -> None:
        doc = _inkoop_document(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            admin_engine,
            naam="a.pdf",
            factuurdatum="2026-03-01",
            regels=[_regel("Koppeling draaibaar 48", "10", "50.00")],
        )
        assert service.registreer_inkoopregels(administratie_id=administratie_id, document_id=doc) == 0
        assert fake_ai.aanroepen == []
        with pytest.raises(service.VoorraadUitgeschakeld):
            service.aansluiting(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))

    def test_volautomatische_normalisatie_direct_toegepast_dienst_uitgesloten_onzeker_gevlagd(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, voorraad_aan, fake_ai
    ) -> None:
        doc = _inkoop_document(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            admin_engine,
            naam="a.pdf",
            factuurdatum="2026-03-01",
            regels=[
                _regel("KOP.DR.48/48 SW22 gegalv.", "500", "1250.00"),
                _regel("Buis 48,3x3,2 L=3000", "120", "2400.00", p="20.00"),
                _regel("Alu plank div.", "40", "1600.00"),
                _regel("Transportkosten zone 2", "1", "85.00"),
            ],
        )
        assert service.registreer_inkoopregels(administratie_id=administratie_id, document_id=doc) == 4
        assert len(fake_ai.aanroepen) == 1  # één call voor de onbekende teksten; de dienst ging niet mee
        assert "Transportkosten" not in fake_ai.aanroepen[0]
        regels = service.regels(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        per = {r.artikeltekst: r for r in regels}
        assert per["KOP.DR.48/48 SW22 gegalv."].normalisatie_status == "genormaliseerd"
        assert per["KOP.DR.48/48 SW22 gegalv."].artikelgroep_naam == "Koppelingen 48mm"
        assert per["KOP.DR.48/48 SW22 gegalv."].prijs == Decimal("2.5000")  # netto/aantal als er geen stuksprijs staat
        assert per["Buis 48,3x3,2 L=3000"].prijs == Decimal("20.0000")
        assert per["Alu plank div."].normalisatie_status == "onzeker"  # telt mee mét vlag
        assert per["Alu plank div."].artikelgroep_naam == "Vlonders alu 2,5m"
        assert per["Transportkosten zone 2"].normalisatie_status == "uitgesloten"
        # Tweede document met dezelfde tekst: deterministisch, GEEN nieuwe AI-call.
        doc2 = _inkoop_document(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            admin_engine,
            naam="b.pdf",
            factuurdatum="2026-04-01",
            regels=[_regel("KOP.DR.48/48 SW22 gegalv.", "100", "250.00")],
        )
        service.registreer_inkoopregels(administratie_id=administratie_id, document_id=doc2)
        assert len(fake_ai.aanroepen) == 1
        groepen = {g.naam for g in service.groepen(administratie_id=administratie_id)}
        assert groepen == {"Koppelingen 48mm", "Steigerbuis 3m", "Vlonders alu 2,5m"}

    def test_geen_ai_beschikbaar_is_niet_genormaliseerd_nooit_stil(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, voorraad_aan, monkeypatch
    ) -> None:
        monkeypatch.setattr(normalisatie, "_client_voor", lambda administratie_id, document_id: None)
        doc = _inkoop_document(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            admin_engine,
            naam="a.pdf",
            factuurdatum="2026-03-01",
            regels=[_regel("Onbekend artikel X", "5", "10.00")],
        )
        service.registreer_inkoopregels(administratie_id=administratie_id, document_id=doc)
        a = service.aansluiting(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        assert a.niet_genormaliseerd_in == 1
        assert a.groepen == []


class TestAansluiting:
    def test_begin_in_uit_theoretisch_telling_tolerantie_en_dagstanden(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, voorraad_aan, fake_ai
    ) -> None:
        # Vóór de periode: 1.240 in (beginstand); in de periode: 3.600 in en 3.410 uit (via correctie-
        # pad hieronder gesimuleerd als 'uit'-regels), telling 1.428 → −2 = binnen 1% (mockup rij 1).
        doc0 = _inkoop_document(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            admin_engine,
            naam="0.pdf",
            factuurdatum="2025-12-15",
            regels=[_regel("Koppeling draaibaar 48", "1240", "3100.00")],
        )
        doc1 = _inkoop_document(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            admin_engine,
            naam="1.pdf",
            factuurdatum="2026-02-10",
            regels=[_regel("Koppeling draaibaar 48", "3600", "9000.00")],
        )
        for d in (doc0, doc1):
            service.registreer_inkoopregels(administratie_id=administratie_id, document_id=d)
        groep = next(g for g in service.groepen(administratie_id=administratie_id) if g.naam == "Koppelingen 48mm")
        # Uitstroom nabootsen als feitenregel (fase 1: verkoopfactuurregels) — direct in de feitenlaag.
        from app.voorraad.models import VoorraadRegel

        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            session.add(
                VoorraadRegel(
                    administratie_id=administratie_id,
                    document_id=doc1,
                    richting="uit",
                    bron="verkoop_regel",
                    datum=date(2026, 5, 3),
                    regel_volgnummer=1,
                    artikeltekst="Koppeling draaibaar 48 verkoop",
                    aantal=Decimal("3410"),
                    artikelgroep_id=groep.id,
                    normalisatie_status="genormaliseerd",
                    normalisatie_zekerheid=Decimal("0.950"),
                )
            )
        service.voer_telling_in(
            administratie_id=administratie_id,
            artikelgroep_id=groep.id,
            datum=date(2026, 8, 28),
            aantal=Decimal("1428"),
            opmerking="magazijntelling",
            actor_id=gescoopte_gebruiker,
        )
        a = service.aansluiting(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 8, 31))
        rij = next(g for g in a.groepen if g.artikelgroep_id == groep.id)
        assert (rij.begin, rij.inkoop, rij.verkoop, rij.theoretisch) == (
            Decimal("1240.000"),
            Decimal("3600.000"),
            Decimal("3410.000"),
            Decimal("1430.000"),
        )
        assert rij.systeemstand == Decimal("1428.000") and rij.verschil == Decimal("-2.000")
        assert rij.signaal == "binnen_tolerantie" and rij.telling_datum == date(2026, 8, 28)
        assert a.bronnen["inkoop"].startswith("inkoopfacturen")
        # Tolerantie strakker (0,1%) → onderzoeken; telling corrigeren op dezelfde datum = upsert.
        service.zet_tolerantie(
            administratie_id=administratie_id,
            artikelgroep_id=groep.id,
            tolerantie_pct=Decimal("0.1"),
            actor_id=gescoopte_gebruiker,
        )
        a = service.aansluiting(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 8, 31))
        assert next(g for g in a.groepen if g.artikelgroep_id == groep.id).signaal == "onderzoeken"
        service.voer_telling_in(
            administratie_id=administratie_id,
            artikelgroep_id=groep.id,
            datum=date(2026, 8, 28),
            aantal=Decimal("1430"),
            opmerking=None,
            actor_id=gescoopte_gebruiker,
        )
        a = service.aansluiting(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 8, 31))
        assert next(g for g in a.groepen if g.artikelgroep_id == groep.id).verschil == Decimal("0.000")
        # Dagniveau: cumulatieve stand per mutatiedag, beginstand meegenomen.
        dagen = service.dagstanden(
            administratie_id=administratie_id, artikelgroep_id=groep.id, van=date(2026, 1, 1), tot=date(2026, 8, 31)
        )
        assert [(d.datum, d.stand) for d in dagen] == [
            (date(2026, 2, 10), Decimal("4840.000")),
            (date(2026, 5, 3), Decimal("1430.000")),
        ]
        # Geen telling = 'geen_telling' (geen vals signaal).
        with admin_engine.begin() as conn:
            conn.execute(text("DELETE FROM mi.voorraad_telling"))
        a = service.aansluiting(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 8, 31))
        assert next(g for g in a.groepen if g.artikelgroep_id == groep.id).signaal == "geen_telling"

    def test_onzeker_percentage_bij_signaal(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, voorraad_aan, fake_ai
    ) -> None:
        doc = _inkoop_document(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            admin_engine,
            naam="a.pdf",
            factuurdatum="2026-03-01",
            regels=[_regel("Alu plank div.", "40", "1600.00"), _regel("Alu plank div.", "10", "400.00")],
        )
        service.registreer_inkoopregels(administratie_id=administratie_id, document_id=doc)
        a = service.aansluiting(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        rij = next(g for g in a.groepen if g.naam == "Vlonders alu 2,5m")
        assert rij.onzeker_pct == Decimal("100.00") and rij.inkoop == Decimal("50.000")
        assert a.onzeker_totaal == 2


class TestCorrectie:
    def test_correctie_herrekent_historie_en_wint_van_ai(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, voorraad_aan, fake_ai
    ) -> None:
        doc_a = _inkoop_document(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            admin_engine,
            naam="a.pdf",
            factuurdatum="2026-03-01",
            regels=[_regel("Alu plank div.", "40", "1600.00")],
        )
        doc_b = _inkoop_document(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            admin_engine,
            naam="b.pdf",
            factuurdatum="2026-04-01",
            regels=[_regel("Alu plank div.", "10", "400.00")],
        )
        for d in (doc_a, doc_b):
            service.registreer_inkoopregels(administratie_id=administratie_id, document_id=d)
        nieuw = service.maak_groep(
            administratie_id=administratie_id,
            naam="Vlonders hout 2,5m",
            eenheid="st",
            tolerantie_pct=Decimal("1"),
            actor_id=gescoopte_gebruiker,
        )
        eerste = service.regels(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))[0]
        n = service.corrigeer_normalisatie(
            administratie_id=administratie_id,
            regel_id=eerste.id,
            artikelgroep_id=nieuw.id,
            uitgesloten=False,
            actor_id=gescoopte_gebruiker,
        )
        assert n == 2  # beide documenten herrekend
        regels = service.regels(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        assert {r.artikelgroep_naam for r in regels} == {"Vlonders hout 2,5m"}
        assert {r.normalisatie_status for r in regels} == {"genormaliseerd"}
        # Herrekenen ná de correctie: de handmatige regel wint, geen nieuwe AI-call.
        aanroepen_vooraf = len(fake_ai.aanroepen)
        telling = service.herreken_administratie(administratie_id=administratie_id, actor_id=gescoopte_gebruiker)
        assert telling["inkoop_documenten"] == 2 and len(fake_ai.aanroepen) == aanroepen_vooraf
        regels = service.regels(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        assert {r.artikelgroep_naam for r in regels} == {"Vlonders hout 2,5m"}
        # Uitsluiten via correctie.
        service.corrigeer_normalisatie(
            administratie_id=administratie_id,
            regel_id=regels[0].id,
            artikelgroep_id=None,
            uitgesloten=True,
            actor_id=gescoopte_gebruiker,
        )
        assert {
            r.normalisatie_status
            for r in service.regels(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        } == {"uitgesloten"}


class TestEndpoints:
    def test_poorten_en_flows(self, administratie_id, gescoopte_gebruiker, beheerder_id, admin_engine) -> None:
        aid = str(administratie_id)
        resp = client.get(
            f"/administraties/{aid}/voorraad/aansluiting",
            params={"van": "2026-01-01", "tot": "2026-12-31"},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 409  # opt-in uit = leesbare 409, geen lege tabel
        resp = client.put(
            f"/administraties/{aid}/voorraad-instelling",
            json={"ingeschakeld": True},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 403  # Beheerder-only
        resp = client.put(
            f"/administraties/{aid}/voorraad-instelling",
            json={"ingeschakeld": True},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200, resp.text
        resp = client.post(
            f"/administraties/{aid}/voorraad/groepen",
            json={"naam": "Koppelingen 48mm", "eenheid": "st", "tolerantie_pct": "1.00"},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 201, resp.text
        groep_id = resp.json()["id"]
        resp = client.post(
            f"/administraties/{aid}/voorraad/tellingen",
            json={"artikelgroep_id": groep_id, "datum": "2026-08-28", "aantal": "1428", "opmerking": None},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 204, resp.text
        resp = client.get(
            f"/administraties/{aid}/voorraad/aansluiting",
            params={"van": "2026-01-01", "tot": "2026-12-31"},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["groepen"][0]["systeemstand"] == "1428.000" and body["groepen"][0]["signaal"] == "onderzoeken"
        assert body["bronnen"]["systeemstand"].startswith("handmatige telling")
        resp = client.post(
            f"/administraties/{aid}/voorraad/herreken", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
        )
        assert resp.status_code == 200 and resp.json()["inkoop_documenten"] == 0
        # Externe rol komt er niet in (router-brede kantoorpoort).
        accordeur = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) VALUES (:id, 'A', :m, 'klant_accordeur', 'actief')"
                ),
                {"id": accordeur, "m": f"{accordeur}@test.local"},
            )
        resp = client.get(f"/administraties/{aid}/voorraad/groepen", headers=_bearer(accordeur, rol="klant_accordeur"))
        assert resp.status_code == 403
