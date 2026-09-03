# ruff: noqa: F811 — pytest-fixtures als parameters (patroon tests/accordering)
"""Voorraad-aansluiting fase 1 (bouwrun 28-08 blok D, mockup voorraad-aansluiting.html, migratie 0086,
mi-schema): volautomatische normalisatie (dienst-regel zonder AI, AI-voorstel direct toegepast,
onzeker telt mee mét vlag, geen AI = niet_genormaliseerd), instroom uit het veldvoorstel, uitstroom uit
verkoopregels, dagniveau-standen, aansluiting mét tolerantie, telling, correctie herrekent historie,
opt-in-poorten en rolpoorten. v2 (30-08, migratie 0088): soort-label artikel/dienst/transport i.p.v.
'uitgesloten' (dienstregels blijven bewaard, tellen niet), dienst-regex op de 29-08-bevindingen,
dienst-inzage + correctie, artikelcode als deterministische sleutel per richting (inkoop ≠ verkoop),
codes-inzage + correctie, legacy-omzetting, AI-batching, CLI-rapport. Code voor cijfers — geen echte AI-calls."""

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
    """Duck-typed client: `vraag_json` geeft per aangeboden regel een gescript voorstel (g, e, z[, soort]);
    onbekende tekst = artikel "Overig" — g None = dienst (zoals de echte prompt bij niet-artikelen)."""

    def __init__(self, antwoorden: dict[str, tuple], *, standaard: tuple | None = ("Overig", "st", 0.9)) -> None:
        self.antwoorden = antwoorden
        self.standaard = standaard
        self.aanroepen: list[str] = []

    def vraag_json(self, *, system: str, opdracht: str, json_schema: dict) -> ClaudeAntwoord:
        self.aanroepen.append(opdracht)
        assert "3 m en 5 m zijn verschillende producten" in system  # besluit Peter: apart tellen
        regels = [
            r for r in opdracht.split("Factuurregels:\n", 1)[1].split("\n\nGeef per regel")[0].splitlines() if r.strip()
        ]
        voorstellen = []
        for regel in regels:
            nr, tekst = regel.split(". ", 1)
            tekst = tekst.split(" (leverancier:")[0]
            antwoord = self.antwoorden.get(tekst, self.standaard or (None, None, 0.9))
            g, e, z = antwoord[:3]
            soort = antwoord[3] if len(antwoord) > 3 else ("artikel" if g else "dienst")
            voorstellen.append({"i": int(nr), "s": soort, "g": g, "e": e, "z": z})
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


def _regel(o: str, h: str | None, n: str, e: str | None = "st", p: str | None = None, a: str | None = None) -> dict:
    return {"omschrijving": o, "hoeveelheid": h, "netto_bedrag": n, "eenheid": e, "stuksprijs": p, "artikelcode": a}


class TestNormalisatiePuur:
    def test_tekstsleutel_en_dienstregel(self) -> None:
        assert normalisatie.normaliseer_tekst("  KOP.DR.48/48  SW22, gegalv. ") == "kop.dr.48/48 sw22. gegalv."
        assert normalisatie.is_dienst("Transportkosten zone 2") is True
        assert normalisatie.is_dienst("Koppeling 48mm") is False
        assert normalisatie.bepaal_status(Decimal("0.61"), artikelgroep_id=uuid.uuid4()) == "onzeker"
        assert normalisatie.bepaal_status(Decimal("0.92"), artikelgroep_id=uuid.uuid4()) == "genormaliseerd"
        # v2: soort dienst/transport = altijd 'genormaliseerd' (deterministisch geclassificeerd), geen groep.
        assert normalisatie.bepaal_status(None, soort="dienst", artikelgroep_id=None) == "genormaliseerd"
        assert normalisatie.bepaal_status(None, artikelgroep_id=None) == "niet_genormaliseerd"

    def test_soort_regex_op_de_bevindingen_van_29_08(self) -> None:
        """De top-teksten uit de eerste cloud-vulling (Universal Verkoop/Nederland/Bradwolff) die de oude
        regex NIET ving — plus echte artikelen die er níét in mogen vallen (Verankeringen ≠ keuring)."""
        c = normalisatie.classificeer_soort
        assert c("Verreden kilometers") == "transport"
        assert c("Werk- en reistijd") == "dienst"
        assert c("Inspectie lift volgens Arbobesluit") == "dienst"
        assert c("Voor u gekeurd/gekalibreerd") == "dienst"
        assert c("Huurperiode augustus 2026, conform huuroverzicht") == "dienst"
        assert c("Betalingskorting:") == "dienst"  # samenstellings-staart …korting
        assert c("Kraanhuur 2 uur") == "dienst"
        assert c("Milieutoeslag") == "dienst"
        assert c("Transportkosten") == "transport"
        assert c("Pallets retour") == "dienst"
        # Artikelen blijven artikel-kandidaat (None): geen valse dienst op deelwoorden.
        assert c("Gebr. Verankeringsbuis 1.00 mtr met varkensstaart (Gebr. 550173.38)") is None
        assert c("Steigerbuis 4 mtr incl. tube-connect (550100.210)") is None
        assert c("Kruiskoppeling met vaste spie (550116.1)") is None
        assert c("Bouwkast Powerbox 63A 3x5P 32A(NM) (st) (580385024)") is None
        assert c("Nalevering steigerdelen 3m") is None  # woordbegin: 'levering' ≠ 'Nalevering'
        assert c("Steigerdeel 3m staal") is None and c("Steigerdeel 5m staal") is None

    def test_artikelcode_uit_tekst_en_codesleutel(self) -> None:
        f = normalisatie.artikelcode_uit_tekst
        assert f("Steigerbuis 1 mtr (550100.6)") == "550100.6"
        assert f("Gebr. Steigerbuis 1 mtr (Gebr.550100.6 )") == "550100.6"  # gebruikt = zelfde artikel
        assert f("Gebr. Verankeringsbuis 1.00 mtr met varkensstaart (Gebr. 550173.38)") == "550173.38"
        assert f("Bouwkast Powerbox 63A 3x5P 32A(NM) (st) (580385024)") == "580385024"  # laatste code telt
        assert f("Kruiskoppeling met vaste spie (550116.1)") == "550116.1"
        assert f("Werk- en reistijd") is None
        assert f("Koppeling 48mm (per 100)") is None and f("Steigerdeel (3m)") is None and f("Buis (100)") is None
        assert f("Buis 48,3 (1002-3)") == "1002-3"  # leverancierscode mét streepje
        assert normalisatie.normaliseer_code(" kop 48-a ") == "KOP48-A"
        assert normalisatie.normaliseer_code("Koppeling") is None  # geen cijfer = geen code
        assert normalisatie.normaliseer_code(12) is None


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
        # v2: dienst-/transportregel BLIJFT als feit mét soort-label (geen 'uitgesloten'-status meer).
        assert per["Transportkosten zone 2"].soort == "transport"
        assert per["Transportkosten zone 2"].normalisatie_status == "genormaliseerd"
        assert per["Transportkosten zone 2"].artikelgroep_id is None
        a = service.aansluiting(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        assert a.transport_regels == 1 and a.dienst_regels == 0 and a.regels_totaal == 4
        assert "diensten" in a.bronnen
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
            soort="artikel",
            artikelgroep_id=nieuw.id,
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
        # Naar dienst via correctie (v2: soort-label; de regels blijven bewaard, tellen niet meer).
        service.corrigeer_normalisatie(
            administratie_id=administratie_id,
            regel_id=regels[0].id,
            soort="dienst",
            artikelgroep_id=None,
            actor_id=gescoopte_gebruiker,
        )
        regels = service.regels(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        assert {(r.soort, r.normalisatie_status, r.artikelgroep_id) for r in regels} == {
            ("dienst", "genormaliseerd", None)
        }
        a = service.aansluiting(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        assert a.dienst_regels == 2 and all(g.inkoop == 0 for g in a.groepen)
        with pytest.raises(service.OngeldigeInvoer):
            service.corrigeer_normalisatie(
                administratie_id=administratie_id,
                regel_id=regels[0].id,
                soort="artikel",
                artikelgroep_id=None,
                actor_id=gescoopte_gebruiker,
            )


class TestSoortEnDienstInzage:
    def test_dienst_inzage_per_tekst_met_aantallen_en_correctie_dienst_naar_artikel(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, voorraad_aan, fake_ai
    ) -> None:
        """Controlemechanisme (eis Peter): de regex wordt nooit blind vertrouwd — per unieke tekst
        zichtbaar mét aantallen/bron, en een correctie dienst → artikel herrekent de historie."""
        doc = _inkoop_document(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            admin_engine,
            naam="a.pdf",
            factuurdatum="2026-03-01",
            regels=[
                _regel("Verreden kilometers", "120", "48.00"),
                _regel("Verreden kilometers", "80", "32.00"),
                _regel("Werk- en reistijd", "4.5", "265.50", e="uur"),
                _regel("Huur lift week 12", "1", "400.00"),  # regex zegt dienst, Peter wil 'm als artikel tellen
                _regel("Koppeling draaibaar 48", "10", "45.00"),
            ],
        )
        service.registreer_inkoopregels(administratie_id=administratie_id, document_id=doc)
        assert all("kilometers" not in a and "reistijd" not in a for a in fake_ai.aanroepen)  # regex, geen AI
        inzage = service.dienst_teksten(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        per = {d.artikeltekst: d for d in inzage}
        assert set(per) == {"Verreden kilometers", "Werk- en reistijd", "Huur lift week 12"}
        km = per["Verreden kilometers"]
        assert (km.soort, km.bron, km.regels, km.som_aantal, km.som_netto, km.richtingen) == (
            "transport",
            "regel",
            2,
            Decimal("200.000"),
            Decimal("80.00"),
            "in",
        )
        assert inzage[0].artikeltekst == "Verreden kilometers"  # meest voorkomend eerst
        assert per["Huur lift week 12"].soort == "dienst"
        # Dienstregels blijven queryable als omzet-/dienstregel (MI) — soort-filter.
        diensten = service.regels(
            administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31), soort="transport"
        )
        assert [r.artikeltekst for r in diensten] == ["Verreden kilometers", "Verreden kilometers"]
        # Correctie dienst → artikel op de voorbeeldregel: groep telt vanaf dan, inzage-rij verdwijnt.
        groep = service.maak_groep(
            administratie_id=administratie_id,
            naam="Liften (huurvloot)",
            eenheid="st",
            tolerantie_pct=Decimal("1"),
            actor_id=gescoopte_gebruiker,
        )
        n = service.corrigeer_normalisatie(
            administratie_id=administratie_id,
            regel_id=per["Huur lift week 12"].voorbeeld_regel_id,
            soort="artikel",
            artikelgroep_id=groep.id,
            actor_id=gescoopte_gebruiker,
        )
        assert n == 1
        a = service.aansluiting(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        assert next(g for g in a.groepen if g.artikelgroep_id == groep.id).inkoop == Decimal("1.000")
        assert a.dienst_regels == 1 and a.transport_regels == 2
        assert "Huur lift week 12" not in {
            d.artikeltekst
            for d in service.dienst_teksten(
                administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31)
            )
        }
        # En de handmatige tekstregel wint bij hernormalisatie van de regex (geen AI-call nodig).
        aanroepen = len(fake_ai.aanroepen)
        service.herreken_administratie(administratie_id=administratie_id, actor_id=gescoopte_gebruiker)
        assert len(fake_ai.aanroepen) == aanroepen
        a = service.aansluiting(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        assert next(g for g in a.groepen if g.artikelgroep_id == groep.id).inkoop == Decimal("1.000")

    def test_legacy_uitgesloten_status_geldt_als_dienst_en_wordt_omgezet(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, voorraad_aan, fake_ai
    ) -> None:
        """Pre-0088-rijen (status 'uitgesloten') tellen als dienst; de hernormalisatie zet ze om."""
        from app.voorraad.models import NormalisatieRegel, VoorraadRegel

        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            session.add(
                VoorraadRegel(
                    administratie_id=administratie_id,
                    rlz_document_id=uuid.uuid4(),
                    rlz_referentie="1",
                    richting="uit",
                    bron="rlz_verkoop",
                    datum=date(2026, 5, 1),
                    regel_volgnummer=1,
                    artikeltekst="Transportkosten",
                    aantal=Decimal("1"),
                    normalisatie_status="uitgesloten",
                    soort="artikel",
                )
            )
            session.add(
                NormalisatieRegel(
                    administratie_id=administratie_id,
                    vendor_id=uuid.UUID(int=0),
                    artikeltekst_norm="transportkosten",
                    uitgesloten=True,
                    soort="artikel",
                    zekerheid=Decimal("1"),
                    bron="regel",
                )
            )
        a = service.aansluiting(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        assert a.dienst_regels == 1 and a.niet_genormaliseerd_uit == 0
        stand = service.normalisatie_stand(administratie_id=administratie_id)
        assert stand["legacy_uitgesloten"] == 1 and stand["regels"] == 1
        service.herreken_administratie(administratie_id=administratie_id, actor_id=gescoopte_gebruiker, met_ai=False)
        stand = service.normalisatie_stand(administratie_id=administratie_id)
        assert stand["legacy_uitgesloten"] == 0 and stand["transport"] == 1
        with scoped_session(administratie_id) as session:
            regel = session.scalars(select_norm := __import__("sqlalchemy").select(NormalisatieRegel)).one()
            assert regel.soort == "transport" and regel.uitgesloten is True  # legacy-kolom in sync
        del select_norm


class TestArtikelcode:
    def test_inkoopcode_deterministisch_en_los_van_verkoopcode(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, voorraad_aan, fake_ai
    ) -> None:
        """Eerste keer per code = AI-voorstel (bron 'ai', zekerheid zichtbaar), daarna deterministisch
        óók bij een ándere omschrijving; inkoopcode (leverancier) en verkoopcode zijn aparte sleutels."""
        fake_ai.antwoorden["Buis 48,3 x 3,2 mm 3000 gegalv. (art. 1002-3)"] = ("Steigerbuis 3m", "st", 0.9)
        doc1 = _inkoop_document(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            admin_engine,
            naam="a.pdf",
            factuurdatum="2026-03-01",
            regels=[_regel("Buis 48,3 x 3,2 mm 3000 gegalv. (art. 1002-3)", "100", "2000.00", a="1002-3")],
        )
        service.registreer_inkoopregels(administratie_id=administratie_id, document_id=doc1)
        codes = service.artikelcodes(administratie_id=administratie_id)
        assert len(codes) == 1
        k = codes[0]
        assert (k.richting, k.code, k.artikelgroep_naam, k.bron, k.regels, k.relatie_naam) == (
            "in",
            "1002-3",
            "Steigerbuis 3m",
            "ai",
            1,
            "Scafom B.V.",
        )
        # Zelfde leverancierscode, ándere omschrijving: deterministisch via de code — GEEN AI-call.
        aanroepen = len(fake_ai.aanroepen)
        doc2 = _inkoop_document(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            admin_engine,
            naam="b.pdf",
            factuurdatum="2026-04-01",
            regels=[_regel("Steigerbuis 3 mtr verzinkt", "50", "1000.00", a="1002-3")],
        )
        service.registreer_inkoopregels(administratie_id=administratie_id, document_id=doc2)
        assert len(fake_ai.aanroepen) == aanroepen
        regels = service.regels(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        assert {(r.artikelcode, r.artikelgroep_naam) for r in regels} == {("1002-3", "Steigerbuis 3m")}
        # De code-kennis groeit: de nieuwe tekst kreeg zélf een tekstregel (bron ai, zonder AI-call).
        assert service.artikelcodes(administratie_id=administratie_id)[0].teksten == 2
        # Verkoopkant met toevallig dezelfde code "(1002-3)"… is een andere sleutelruimte: niet aannemen.
        from app.voorraad.models import VoorraadRegel

        fake_ai.antwoorden["Steigerdeel 5m (1002-3)"] = ("Steigerdelen 5m", "st", 0.8)
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            uitkomst = normalisatie.normaliseer_regels(
                session,
                administratie_id=administratie_id,
                document_id=None,
                regels=[normalisatie.RegelInvoer("Steigerdeel 5m (1002-3)", None, None, "uit")],
            )[0]
        assert uitkomst.artikelcode == "1002-3" and len(fake_ai.aanroepen) == aanroepen + 1
        groepen = {g.naam for g in service.groepen(administratie_id=administratie_id)}
        assert {"Steigerbuis 3m", "Steigerdelen 5m"} <= groepen
        codes = {
            (c.richting, c.code): c.artikelgroep_naam for c in service.artikelcodes(administratie_id=administratie_id)
        }
        assert codes == {("in", "1002-3"): "Steigerbuis 3m", ("uit", "1002-3"): "Steigerdelen 5m"}
        del VoorraadRegel

    def test_codecorrectie_wint_van_ai_en_herleidt_alle_regels_met_die_code(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, voorraad_aan, fake_ai
    ) -> None:
        fake_ai.antwoorden["Steigerdeel 3m (77001.3)"] = ("Steigerdelen", "st", 0.6)
        fake_ai.antwoorden["Gebr. Steigerdeel 3 meter (Gebr.77001.3 )"] = ("Steigerdelen 3m", "st", 0.7)
        docs = [
            _inkoop_document(
                administratie_id,
                gescoopte_gebruiker,
                opslag,
                admin_engine,
                naam=f"{i}.pdf",
                factuurdatum=f"2026-0{i}-01",
                regels=[_regel(tekst, "10", "100.00")],
            )
            for i, tekst in ((3, "Steigerdeel 3m (77001.3)"), (4, "Gebr. Steigerdeel 3 meter (Gebr.77001.3 )"))
        ]
        for d in docs:
            service.registreer_inkoopregels(administratie_id=administratie_id, document_id=d)
        # Eerste tekst maakte de code-koppeling (AI, onzeker); de tweede tekst volgde de code — geen 2e groep.
        regels = service.regels(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        assert {r.artikelgroep_naam for r in regels} == {"Steigerdelen"}
        assert {r.normalisatie_status for r in regels} == {"onzeker"}
        k = service.artikelcodes(administratie_id=administratie_id)[0]
        assert (k.code, k.bron, k.zekerheid, k.regels, k.teksten) == ("77001.3", "ai", Decimal("0.600"), 2, 2)
        # Correctie op de code: besluit Peter — 3m en 5m apart; hier expliciet 'Steigerdelen 3m' (de tweede
        # tekst volgde de code, dus de AI heeft die groep nooit voorgesteld — de mens maakt 'm aan).
        groep = service.maak_groep(
            administratie_id=administratie_id,
            naam="Steigerdelen 3m",
            eenheid="st",
            tolerantie_pct=Decimal("1"),
            actor_id=gescoopte_gebruiker,
        )
        n = service.corrigeer_artikelcode(
            administratie_id=administratie_id,
            koppeling_id=k.id,
            soort="artikel",
            artikelgroep_id=groep.id,
            actor_id=gescoopte_gebruiker,
        )
        assert n == 2
        regels = service.regels(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        assert {(r.artikelgroep_naam, r.normalisatie_status) for r in regels} == {("Steigerdelen 3m", "genormaliseerd")}
        k = service.artikelcodes(administratie_id=administratie_id)[0]
        assert k.bron == "handmatig" and k.artikelgroep_naam == "Steigerdelen 3m"
        # Hernormaliseren: de handmatige koppeling blijft winnen, geen AI.
        aanroepen = len(fake_ai.aanroepen)
        service.herreken_administratie(administratie_id=administratie_id, actor_id=gescoopte_gebruiker)
        assert len(fake_ai.aanroepen) == aanroepen
        regels = service.regels(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        assert {r.artikelgroep_naam for r in regels} == {"Steigerdelen 3m"}
        # Code naar dienst = groep los, regels blijven bewaard als dienst.
        service.corrigeer_artikelcode(
            administratie_id=administratie_id,
            koppeling_id=k.id,
            soort="transport",
            artikelgroep_id=None,
            actor_id=gescoopte_gebruiker,
        )
        regels = service.regels(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        assert {(r.soort, r.artikelgroep_id) for r in regels} == {("transport", None)}

    def test_ai_in_batches_en_zonder_ai_pad(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, voorraad_aan, fake_ai, monkeypatch
    ) -> None:
        monkeypatch.setattr(normalisatie, "AI_BATCH", 10)
        regels = [_regel(f"Artikel nummer {i} uniek", "1", "1.00") for i in range(25)]
        doc = _inkoop_document(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            admin_engine,
            naam="a.pdf",
            factuurdatum="2026-03-01",
            regels=regels,
        )
        service.registreer_inkoopregels(administratie_id=administratie_id, document_id=doc)
        assert len(fake_ai.aanroepen) == 3  # 10 + 10 + 5
        # Zonder-AI-pad (herleiden ná correctie / CLI --zonder-ai): onbekende tekst = niet_genormaliseerd, geen call.
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            uit = normalisatie.normaliseer_regels(
                session,
                administratie_id=administratie_id,
                document_id=None,
                regels=[
                    normalisatie.RegelInvoer("Volstrekt nieuw ding", VENDOR_ID, "Scafom", "in"),
                    normalisatie.RegelInvoer("Artikel nummer 3 uniek", VENDOR_ID, "Scafom", "in"),
                ],
                met_ai=False,
            )
        assert uit[0].status == "niet_genormaliseerd" and uit[1].status == "genormaliseerd"
        assert len(fake_ai.aanroepen) == 3


class TestCliRapport:
    def test_hernormaliseer_rapport_per_administratie_met_ai_meter(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, voorraad_aan, fake_ai, capsys
    ) -> None:
        from app import cli

        doc = _inkoop_document(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            admin_engine,
            naam="a.pdf",
            factuurdatum="2026-03-01",
            regels=[
                _regel("Koppeling draaibaar 48", "10", "45.00"),
                _regel("Verreden kilometers", "12", "4.80"),
                _regel("Alu plank div.", "4", "160.00"),
            ],
        )
        service.registreer_inkoopregels(administratie_id=administratie_id, document_id=doc)
        assert cli.main(["voorraad-hernormaliseer", "--administratie-id", str(administratie_id)]) == 0
        out = capsys.readouterr().out
        assert "genormaliseerd 1 / onzeker 1 / dienst 0 / transport 1 / NIET genormaliseerd 0" in out
        assert "AI-maandmeter: €" in out
        assert cli.main(["voorraad-hernormaliseer", "--administratie-id", "geen-uuid"]) == 1
        # Rapportfunctie: één kapotte administratie = exit 1, rest blijft leesbaar.
        stand = service.normalisatie_stand(administratie_id=administratie_id)
        assert (
            cli._rapporteer_voorraad_normalisatie(
                {
                    administratie_id: "boem",
                    uuid.uuid4(): {
                        "stand": stand,
                        "naam": "X",
                        "inkoop_regels": 0,
                        "verkoop_regels": 0,
                        "rlz_regels": 0,
                    },
                }
            )
            == 1
        )
        assert cli._rapporteer_voorraad_normalisatie({}) == 0


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
        assert body["dienst_regels"] == 0 and body["transport_regels"] == 0 and "diensten" in body["bronnen"]
        resp = client.get(
            f"/administraties/{aid}/voorraad/diensten",
            params={"van": "2026-01-01", "tot": "2026-12-31"},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 200 and resp.json() == {"rijen": [], "totaal": 0, "pagina": 1, "per_pagina": 25}
        resp = client.get(
            f"/administraties/{aid}/voorraad/artikelcodes", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
        )
        assert resp.status_code == 200 and resp.json() == {"rijen": [], "totaal": 0, "pagina": 1, "per_pagina": 25}
        resp = client.post(
            f"/administraties/{aid}/voorraad/artikelcodes/{uuid.uuid4()}/corrigeer",
            json={"soort": "dienst"},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 422  # onbekende koppeling = leesbare fout
        resp = client.post(
            f"/administraties/{aid}/voorraad/normalisatie/corrigeer",
            json={"regel_id": str(uuid.uuid4()), "soort": "bestaat_niet"},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 422  # soort is een gesloten lijst
        # Externe rol komt er niet in (router-brede kantoorpoort).
        accordeur = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                    "VALUES (:id, 'A', :m, 'klant_accordeur', 'actief')"
                ),
                {"id": accordeur, "m": f"{accordeur}@test.local"},
            )
        resp = client.get(f"/administraties/{aid}/voorraad/groepen", headers=_bearer(accordeur, rol="klant_accordeur"))
        assert resp.status_code == 403
