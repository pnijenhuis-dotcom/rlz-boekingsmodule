"""Blok 3 herstelrun "Basis eerst" 08-09 — UBL is deterministisch: nooit leeg, nooit via AI (casus BDO 6088744,
Universal Steigerbouw: crediteur-kaart leeg, "Duplicaatcheck: kan niet controleren zonder crediteur en referentie").

Bewezen gedrag:
1. Bij INTAKE (upload / los bestand / mail) staan crediteur (match op KvK/btw/IBAN/naam), referentie, factuur- én
   vervaldatum, totaal en regel in het GEPERSISTEERDE boekvoorstel — vóór iemand het document opent en zonder dat er
   ooit een extractie-wachtrij/AI-stap aan te pas komt (`.xml` gaat nooit naar de wachtrij).
2. Het veldvoorstel in de tijdlijn draagt `bron: "ubl"` + KvK/btw/IBAN/adres (voedt "Nieuwe crediteur in RLZ").
3. De duplicaatcheck-tekst zegt bij een UBL zonder crediteur nooit meer "zonder crediteur en referentie".
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from app.config import settings
from app.db.session import scoped_session
from app.documenten import boekvoorstel, checks, service
from app.documenten.models import Boekvoorstel, CrediteurKenmerk, DocumentStatus, LeverancierIban, LeverancierIbanBron
from app.documenten.storage import LokaleBestandsopslag
from app.documenten.ubl import is_ubl_veldvoorstel, parseer_ubl_factuur
from app.intake import verwerking
from app.sync.models import VendorCache
from tests.documenten.fake_rlz_client import FakeBoekClient

FIXTURES = Path(__file__).parent / "fixtures"
NLCIUS = (FIXTURES / "nlcius_accountant_ubl.xml").read_bytes()
RLZ_EXPORT = (FIXTURES / "rlz_export_ubl.xml").read_bytes()


@pytest.fixture(autouse=True)
def _ai_zou_kunnen(monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> None:
    """AI-gate AAN + key aanwezig: precies de productiestand waarin een PDF naar de wachtrij gaat — een UBL mag
    daar NOOIT heen. Zou er tóch een AI-call komen, dan faalt de test hard."""
    from app.beheer import service as beheer_service

    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    def _nooit(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("UBL mag nooit naar de AI-extractie")

    monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _nooit)


def _vendor(
    administratie_id: uuid.UUID, *, naam: str, kvk: str | None = None, btw: str | None = None, iban: str | None = None
) -> uuid.UUID:
    vendor_id = uuid.uuid4()
    with scoped_session(administratie_id) as session:
        session.add(VendorCache(id=vendor_id, administratie_id=administratie_id, naam=naam, brondata={}))
        if kvk or btw:
            session.add(
                CrediteurKenmerk(
                    administratie_id=administratie_id,
                    vendor_id=vendor_id,
                    kvk_nummer=kvk,
                    kvk_nummer_bron="handmatig" if kvk else None,
                    btw_nummer=btw,
                    btw_nummer_geverifieerd=True if btw else None,
                    btw_nummer_bron="handmatig" if btw else None,
                )
            )
        if iban:
            session.add(
                LeverancierIban(
                    administratie_id=administratie_id,
                    vendor_id=vendor_id,
                    iban=iban,
                    bron=LeverancierIbanBron.RLZ_SEED.value,
                )
            )
    return vendor_id


def _tijdlijn(admin_engine: Engine, document_id: uuid.UUID) -> list[tuple[str | None, str, dict]]:
    with admin_engine.connect() as conn:
        return [
            (r[0], r[1], r[2] or {})
            for r in conn.execute(
                text(
                    "SELECT van_status, naar_status, detail FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :d ORDER BY tijdstip, id"
                ),
                {"d": document_id},
            )
        ]


def _boekvoorstel_rij(administratie_id: uuid.UUID, document_id: uuid.UUID) -> Boekvoorstel | None:
    with scoped_session(administratie_id) as session:
        rij = session.get(Boekvoorstel, document_id)
        if rij is not None:
            session.expunge(rij)
        return rij


class TestParser:
    def test_nlcius_kernvelden_crediteur_identiteit_en_betaalgegevens(self) -> None:
        v = parseer_ubl_factuur(NLCIUS).als_dict()
        assert v["bron"] == "ubl"
        assert v["leverancier_naam"] == "Voorbeeld Accountancy, Tax & Legal B.V."  # RegistrationName wint van PartyName
        assert v["kvk_nummer"] == "87654321"
        assert v["btw_nummer"] == "NL123456782B01"
        assert v["iban"] == "NL91ABNA0417164300"
        assert v["vervaldatum"] == "2026-07-16"
        assert v["betalingskenmerk"] == "6099001"
        assert v["leverancier_adres"] == "Kantoorlaan 12, 5611 AB Eindhoven, NL"
        assert v["factuurnummer"] == "6099001" and v["totaal_incl"] == "6655.00"
        assert is_ubl_veldvoorstel(v)

    def test_legacy_ubl_voorstel_zonder_bron_wordt_herkend_ai_niet(self) -> None:
        assert is_ubl_veldvoorstel({"factuurnummer": "1", "ubl_regels": []})
        assert not is_ubl_veldvoorstel({"bron": "ai", "factuurnummer": "1"})
        assert not is_ubl_veldvoorstel({"bron": "template", "ubl_regels": []})
        assert not is_ubl_veldvoorstel(None)

    def test_ongeldig_iban_en_afwijkende_scheme_worden_niet_overgenomen(self) -> None:
        xml = NLCIUS.replace(b"NL91ABNA0417164300", b"NL00FOUT0000000000").replace(
            b'<cbc:CompanyID schemeID="0106">87654321</cbc:CompanyID>',
            b'<cbc:CompanyID schemeID="NL:OIN">87654321</cbc:CompanyID>',
        )
        v = parseer_ubl_factuur(xml)
        assert v.iban is None  # mod-97 faalt → nooit een gok
        assert v.kvk_nummer is None  # ander identificatieschema is geen KvK


class TestIntakePersisteertBoekvoorstel:
    def test_upload_ubl_vult_boekvoorstel_direct_met_crediteur_op_kvk_zonder_wachtrij(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        # Crediteur heet in RLZ ánders dan op de factuur — alleen het KvK-nummer verbindt ze (casus BDO).
        vendor_id = _vendor(administratie_id, naam="Voorbeeld Acc. & Adviseurs", kvk="87654321")
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="Voorbeeld Accountancy - 6099001.xml",
            inhoud=NLCIUS,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        assert resultaat.status == DocumentStatus.TE_CONTROLEREN
        statussen = [naar for _, naar, _ in _tijdlijn(admin_engine, resultaat.document_id)]
        assert DocumentStatus.EXTRACTIE_WACHTRIJ.value not in statussen  # UBL gaat nooit naar de wachtrij

        rij = _boekvoorstel_rij(administratie_id, resultaat.document_id)
        assert rij is not None, "boekvoorstel moet bij intake gepersisteerd zijn (vóór het openen)"
        assert rij.vendor_id == vendor_id
        assert rij.referentie == "6099001"
        assert rij.factuurdatum == date(2026, 7, 2)
        assert rij.vervaldatum == date(2026, 7, 16)
        assert rij.totaalbedrag == Decimal("6655.00")

        # Het veldvoorstel in de tijdlijn draagt de crediteur-identiteit + de match-herkomst; snapshot-bron = intake.
        details = [d for _, _, d in _tijdlijn(admin_engine, resultaat.document_id)]
        veldvoorstel = next(d["veldvoorstel"] for d in details if "veldvoorstel" in d)
        assert veldvoorstel["bron"] == "ubl"
        assert veldvoorstel["kvk_nummer"] == "87654321" and veldvoorstel["iban"] == "NL91ABNA0417164300"
        assert veldvoorstel["vendor_suggestie"] == {"vendor_id": str(vendor_id), "match": "kvk_nummer"}
        snapshot = next(d["boekvoorstel_prefill"] for d in details if "boekvoorstel_prefill" in d)
        assert snapshot["bron"] == "intake" and "kop: ubl" in snapshot["triggers"]

        # Het gelezen voorstel (controlescherm) = dezelfde stand, mét één regel uit de totalen.
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        assert data.opgeslagen and data.vendor_id == vendor_id and data.referentie == "6099001"
        assert len(data.regels) == 1 and data.regels[0].netto_bedrag == Decimal("5500.00")

    def test_crediteur_op_btw_nummer_en_op_iban_zonder_naam_match(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        op_btw = _vendor(administratie_id, naam="Totaal andere naam B.V.", btw="NL123456782B01")
        r1 = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="a.xml",
            inhoud=NLCIUS,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        assert _boekvoorstel_rij(administratie_id, r1.document_id).vendor_id == op_btw

        # IBAN als vierde sleutel: een andere UBL (RLZ-export-fixture, IBAN NL91ABNA0417164300 = zelfde rekening)
        # zonder KvK-/btw-treffer en zonder naam-match → de vertrouwde rekening van precies één crediteur wint.
        op_iban = _vendor(administratie_id, naam="Rekeninghouder Onbekend B.V.", iban="NL91ABNA0417164300")
        xml = RLZ_EXPORT.replace(b"NL001234567B01", b"NL000000000B00").replace(b"12345678", b"00000000")
        r2 = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="b.xml",
            inhoud=xml,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        rij = _boekvoorstel_rij(administratie_id, r2.document_id)
        assert rij is not None and rij.vendor_id == op_iban
        details = [d for _, _, d in _tijdlijn(admin_engine, r2.document_id) if "veldvoorstel" in d]
        assert details[0]["veldvoorstel"]["vendor_suggestie"]["match"] == "iban"

    def test_zonder_crediteur_in_cache_blijft_de_kop_toch_gevuld_en_de_dialoogbron_compleet(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        """De BDO-stand: geen crediteur in de cache. Referentie/datum/totaal staan er tóch; de crediteur-dialoog krijgt
        naam + KvK + btw + IBAN + adres uit de UBL (geen lege velden meer)."""
        r = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="bdo.xml",
            inhoud=NLCIUS,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        rij = _boekvoorstel_rij(administratie_id, r.document_id)
        assert (
            rij is not None
            and rij.vendor_id is None
            and rij.referentie == "6099001"
            and rij.totaalbedrag == Decimal("6655.00")
        )
        veldvoorstel = next(
            d["veldvoorstel"] for _, _, d in _tijdlijn(admin_engine, r.document_id) if "veldvoorstel" in d
        )
        assert veldvoorstel["vendor_suggestie"] is None
        assert {
            veldvoorstel[k] is not None
            for k in ("leverancier_naam", "kvk_nummer", "btw_nummer", "iban", "leverancier_adres")
        } == {True}

    def test_los_bestand_intake_route_vult_boekvoorstel_bij_toewijzing(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_heet_blow: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        vendor_id = _vendor(administratie_heet_blow, naam="X", kvk="87654321")
        resultaat = verwerking.verwerk_los_bestand(
            bestandsnaam="6099001.xml",
            inhoud=NLCIUS,
            content_type="application/xml",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        assert resultaat.uitkomst == "toegewezen" and resultaat.document_id is not None
        rij = _boekvoorstel_rij(administratie_heet_blow, resultaat.document_id)
        assert rij is not None and rij.vendor_id == vendor_id and rij.referentie == "6099001"

    def test_ubl_van_voor_08_09_zonder_bron_krijgt_live_crediteur_match_bij_openen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        """Bestaande UBL-rijen in productie dragen een voorstel zónder `bron`/KvK; ná het aanmaken van de crediteur
        vindt de prefill 'm alsnog (exacte of fuzzy naam)."""
        r = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="oud.xml",
            inhoud=NLCIUS,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with admin_engine.begin() as conn:  # simuleer het pre-08-09-voorstel: geen bron, geen nummers, geen suggestie
            conn.execute(
                text(
                    "UPDATE boekhouding.document_gebeurtenis SET detail = detail || jsonb_build_object('veldvoorstel', "
                    "(detail->'veldvoorstel') - 'bron' - 'kvk_nummer' - 'btw_nummer' - 'iban' - 'vendor_suggestie') "
                    "WHERE document_id = :d AND detail ? 'veldvoorstel'"
                ),
                {"d": r.document_id},
            )
            conn.execute(
                text("DELETE FROM boekhouding.boekvoorstel_regel WHERE document_id = :d"), {"d": r.document_id}
            )
            conn.execute(text("DELETE FROM boekhouding.boekvoorstel WHERE document_id = :d"), {"d": r.document_id})
        vendor_id = _vendor(administratie_id, naam="Voorbeeld Accountancy Tax Legal BV")  # fuzzy op de naam
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=r.document_id)
        assert data.vendor_id == vendor_id


class TestDuplicaatcheckTekst:
    def test_ubl_zonder_crediteur_zegt_niet_meer_zonder_crediteur_en_referentie(self) -> None:
        r = checks.check_duplicaat(
            client=FakeBoekClient(),
            vendor_id=None,
            referentie="6099001",
            totaalbedrag=Decimal("6655.00"),
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert r.ok is False
        assert "en referentie" not in r.melding
        assert (
            r.melding
            == "Kan niet controleren zonder crediteur — kies of maak de crediteur; referentie 6099001 is bekend"
        )
        # Beide leeg (PDF zonder extractie) blijft de oude, complete melding.
        leeg = checks.check_duplicaat(
            client=FakeBoekClient(),
            vendor_id=None,
            referentie=None,
            totaalbedrag=None,
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert leeg.melding == "Kan niet controleren zonder crediteur en referentie"
