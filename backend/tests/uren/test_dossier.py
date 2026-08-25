"""ZZP-dossier per veldwerker (steigerbouw-run blok A1–A3, 25-08): documenttypen als instelling
(default-set virtueel), statusmodel ontbreekt → ter controle → goedgekeurd/afgewezen-met-reden,
verlopen/verloopt-binnenkort, handhaving (3 herinneringen → indienen geblokkeerd, óók namens;
deblokkade zodra alle verplichte documenten geüpload zijn; afwijzing heractiveert; teller-reset
bij volledig goedgekeurd; uren raken nooit zoek), audit-keten, KvK-parser + bevestiging, API-
poorten (veld + kantoor + Beheerder)."""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.auth import voorwaarden
from app.berichten import verzending
from app.berichten.models import HerinneringKanaal, HerinneringStatus
from app.db.session import scoped_session
from app.documenten import storage
from app.integraties import kvk
from app.main import app
from app.security.tokens import create_access_token
from app.uren import dossier, service
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)

JAAR, WEEK = 2026, 34
MAANDAG = date.fromisocalendar(JAAR, WEEK, 1)
PDF = b"%PDF-1.4 test"
OVER_EEN_JAAR = date.today() + timedelta(days=365)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture(autouse=True)
def _lokale_opslag(tmp_path: Path, monkeypatch):
    opslag = storage.LokaleBestandsopslag(tmp_path / "dossier")
    monkeypatch.setattr(storage, "standaard_opslag", lambda: opslag)
    return opslag


@pytest.fixture
def push_ok(monkeypatch):
    """Verzendkanaal gemockt: elke herinnering 'komt aan' via push — de handhaving is het
    onderwerp, niet het kanaal (dat is elders getest)."""
    verzonden: list[dict] = []

    def _nep(gebruiker, *, onderwerp, pushtekst, mailtekst, url, extra_payload=None):
        verzonden.append({"gebruiker_id": gebruiker.id, "pushtekst": pushtekst, "url": url})
        return verzending.VerzendUitkomst(HerinneringStatus.VERZONDEN, HerinneringKanaal.PUSH, {"subscripties": 1}, 0)

    monkeypatch.setattr(verzending, "verstuur_push_anders_mail", _nep)
    return verzonden


@pytest.fixture
def zzper_met_scope(zzper, administratie_id, beheerder_id) -> uuid.UUID:
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=zzper, administratie_id=administratie_id)
    voorwaarden.leg_akkoord_vast(gebruiker_id=zzper)
    return zzper


def _upload(administratie_id, gebruiker_id, code, actor, *, geldig_tot=OVER_EEN_JAAR):
    return dossier.upload_document(
        administratie_id=administratie_id,
        gebruiker_id=gebruiker_id,
        type_code=code,
        geldig_tot=geldig_tot,
        bestand=(f"{code}.pdf", "application/pdf", PDF),
        actor_id=actor,
    )


def _doc_id(stand, code):
    return next(d.document_id for d in stand.documenten if d.code == code)


def _keur_alles_goed(administratie_id, gebruiker_id, beheerder_id, *, codes=None):
    stand = dossier.dossier_van(administratie_id=administratie_id, gebruiker_id=gebruiker_id, actor_id=beheerder_id)
    for d in stand.documenten:
        if d.status == "ter_controle" and (codes is None or d.code in codes):
            stand = dossier.beoordeel_document(
                administratie_id=administratie_id, document_id=d.document_id, goedgekeurd=True, reden=None, actor_id=beheerder_id
            )
    return stand


def _herinner(administratie_id, gebruiker_id, beheerder_id, n, monkeypatch):
    """N herinneringen op N verschillende dagen (dagrem)."""
    resultaten = []
    for i in range(n):
        monkeypatch.setattr(dossier, "_vandaag", lambda i=i: date.today() + timedelta(days=i))
        resultaten.append(dossier.stuur_herinnering(administratie_id=administratie_id, gebruiker_id=gebruiker_id, actor_id=beheerder_id))
    monkeypatch.setattr(dossier, "_vandaag", lambda: date.today())
    return resultaten


def _audit_acties(admin_engine: Engine, record_id: uuid.UUID) -> list[str]:
    with admin_engine.begin() as conn:
        return [
            r[0]
            for r in conn.execute(
                text("SELECT actie FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip, id"),
                {"id": record_id},
            )
        ]


class TestDocumenttypen:
    def test_default_set_virtueel_tot_eerste_put(self, administratie_id, beheerder_id):
        typen, is_standaard = dossier.documenttypen(administratie_id=administratie_id, actor_id=beheerder_id)
        assert is_standaard is True
        assert [t.code for t in typen] == ["kopie_id", "steigerpas", "vca_vol", "avb", "kvk_uittreksel"]
        assert all(t.verplicht for t in typen)
        assert next(t for t in typen if t.code == "kopie_id").bsn_gevoelig is True

    def test_put_persisteert_en_deactiveert_ontbrekende(self, administratie_id, beheerder_id, admin_engine):
        typen, _ = dossier.documenttypen(administratie_id=administratie_id, actor_id=beheerder_id)
        nieuw = [t for t in typen if t.code != "avb"] + [
            dossier.TypeDef("g_rekening", "G-rekening-overeenkomst", False, False, False, 9)
        ]
        resultaat = dossier.zet_documenttypen(administratie_id=administratie_id, typen=nieuw, actor_id=beheerder_id)
        per_code = {t.code: t for t in resultaat}
        assert per_code["avb"].actief is False  # nooit verwijderd
        assert per_code["g_rekening"].verplicht is False
        _, is_standaard = dossier.documenttypen(administratie_id=administratie_id, actor_id=beheerder_id)
        assert is_standaard is False
        assert "dossier_documenttypen_gewijzigd" in _audit_acties(admin_engine, administratie_id)

    def test_dubbele_code_weigert(self, administratie_id, beheerder_id):
        t = dossier.STANDAARD_TYPEN[0]
        with pytest.raises(service.OngeldigeInvoer):
            dossier.zet_documenttypen(administratie_id=administratie_id, typen=[t, t], actor_id=beheerder_id)


class TestStatusmodel:
    def test_leeg_dossier_alles_ontbreekt(self, administratie_id, zzper, beheerder_id):
        stand = dossier.dossier_van(administratie_id=administratie_id, gebruiker_id=zzper, actor_id=beheerder_id)
        assert stand.aantal_verplicht == 5 and stand.aantal_ontbrekend == 5
        assert stand.compleet is False and stand.geblokkeerd is False
        assert stand.signalen and stand.signalen[0].startswith("ontbrekend:")

    def test_upload_ter_controle_goedkeuren_afwijzen_met_reden(self, administratie_id, zzper, beheerder_id, admin_engine):
        stand = _upload(administratie_id, zzper, "steigerpas", zzper)
        pas = next(d for d in stand.documenten if d.code == "steigerpas")
        assert pas.status == "ter_controle" and pas.bron == "app" and pas.geupload_door_naam == "Milan K."
        assert stand.aantal_ter_controle == 1
        with pytest.raises(service.RedenVerplicht):
            dossier.beoordeel_document(
                administratie_id=administratie_id, document_id=pas.document_id, goedgekeurd=False, reden="  ", actor_id=beheerder_id
            )
        stand = dossier.beoordeel_document(
            administratie_id=administratie_id, document_id=pas.document_id, goedgekeurd=False, reden="Onleesbare scan", actor_id=beheerder_id
        )
        pas = next(d for d in stand.documenten if d.code == "steigerpas")
        assert pas.status == "afgewezen" and pas.afwijs_reden == "Onleesbare scan"
        # Alleen ter_controle is beoordeelbaar; een tweede upload vervangt (nieuwe rij).
        with pytest.raises(service.OngeldigeInvoer):
            dossier.beoordeel_document(
                administratie_id=administratie_id, document_id=pas.document_id, goedgekeurd=True, reden=None, actor_id=beheerder_id
            )
        stand = _upload(administratie_id, zzper, "steigerpas", beheerder_id)
        pas2 = next(d for d in stand.documenten if d.code == "steigerpas")
        assert pas2.status == "ter_controle" and pas2.bron == "kantoor" and pas2.document_id != pas.document_id
        stand = dossier.beoordeel_document(
            administratie_id=administratie_id, document_id=pas2.document_id, goedgekeurd=True, reden=None, actor_id=beheerder_id
        )
        assert next(d for d in stand.documenten if d.code == "steigerpas").status == "goedgekeurd"
        assert stand.aantal_aanwezig == 1
        acties = _audit_acties(admin_engine, pas.document_id)
        assert acties == ["dossier_document_geupload", "dossier_document_afgewezen"]

    def test_geldig_tot_verplicht_en_niet_in_verleden(self, administratie_id, zzper):
        with pytest.raises(service.OngeldigeInvoer):
            _upload(administratie_id, zzper, "vca_vol", zzper, geldig_tot=None)
        with pytest.raises(service.OngeldigeInvoer):
            _upload(administratie_id, zzper, "vca_vol", zzper, geldig_tot=date.today() - timedelta(days=1))

    def test_verlopen_en_vooraankondiging(self, administratie_id, zzper, beheerder_id, monkeypatch):
        _upload(administratie_id, zzper, "vca_vol", zzper, geldig_tot=date.today() + timedelta(days=20))
        _upload(administratie_id, zzper, "avb", zzper, geldig_tot=date.today() + timedelta(days=200))
        stand = _keur_alles_goed(administratie_id, zzper, beheerder_id)
        per = {d.code: d for d in stand.documenten}
        assert per["vca_vol"].status == "verloopt_binnenkort" and per["vca_vol"].verloopt_over_dagen == 20
        assert per["avb"].status == "goedgekeurd"
        assert stand.aantal_verloopt_binnenkort == 1
        # Tijd verstrijkt: 25 dagen later is de VCA verlopen (afgeleide toestand, geen mutatie nodig).
        monkeypatch.setattr(dossier, "_vandaag", lambda: date.today() + timedelta(days=25))
        stand = dossier.dossier_van(administratie_id=administratie_id, gebruiker_id=zzper, actor_id=beheerder_id)
        per = {d.code: d for d in stand.documenten}
        assert per["vca_vol"].status == "verlopen" and stand.aantal_verlopen == 1
        assert any(s.startswith("verlopen:") for s in stand.signalen)

    def test_bestandstype_en_grootte(self, administratie_id, zzper):
        with pytest.raises(service.OngeldigeInvoer):
            dossier.upload_document(
                administratie_id=administratie_id, gebruiker_id=zzper, type_code="avb", geldig_tot=OVER_EEN_JAAR,
                bestand=("x.exe", "application/octet-stream", b"MZ"), actor_id=zzper,
            )
        with pytest.raises(service.OngeldigeInvoer):
            dossier.upload_document(
                administratie_id=administratie_id, gebruiker_id=zzper, type_code="avb", geldig_tot=OVER_EEN_JAAR,
                bestand=("x.pdf", "application/pdf", b""), actor_id=zzper,
            )

    def test_onbekend_type_en_detacheerder_geen_dossier(self, administratie_id, zzper, detacheerder):
        with pytest.raises(service.NietGevonden):
            _upload(administratie_id, zzper, "rijbewijs", zzper)
        with pytest.raises(service.OngeldigeInvoer):
            _upload(administratie_id, detacheerder, "avb", detacheerder)


class TestToegang:
    def test_andere_zzper_geen_toegang(self, administratie_id, zzper, admin_engine):
        ander = maak_gebruiker(admin_engine, "zzper", "Stefan B.")
        with pytest.raises(service.GeenToegang):
            dossier.dossier_van(administratie_id=administratie_id, gebruiker_id=zzper, actor_id=ander)

    def test_detacheerder_alleen_gekoppeld(self, administratie_id, zzper, detacheerder, beheerder_id):
        with pytest.raises(service.GeenToegang):
            dossier.dossier_van(administratie_id=administratie_id, gebruiker_id=zzper, actor_id=detacheerder)
        service.koppel_detacheerder(detacheerder_id=detacheerder, zzper_id=zzper, actor_id=beheerder_id)
        stand = _upload(administratie_id, zzper, "avb", detacheerder)
        doc = next(d for d in stand.documenten if d.code == "avb")
        assert doc.geupload_door_naam == "Karin S." and doc.bron == "app"

    def test_kantoor_zonder_module_recht_geen_toegang(self, administratie_id, zzper, admin_engine):
        boekhouder = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
        with pytest.raises(service.GeenToegang):
            dossier.dossier_van(administratie_id=administratie_id, gebruiker_id=zzper, actor_id=boekhouder)

    def test_inzage_bsn_gevoelig_geaudit(self, administratie_id, zzper, beheerder_id, admin_engine):
        stand = _upload(administratie_id, zzper, "kopie_id", zzper)
        stand = _upload(administratie_id, zzper, "avb", zzper)
        id_doc, avb_doc = _doc_id(stand, "kopie_id"), _doc_id(stand, "avb")
        naam, ctype, inhoud, gevoelig = dossier.document_inhoud(administratie_id=administratie_id, document_id=id_doc, actor_id=beheerder_id)
        assert inhoud == PDF and gevoelig is True and ctype == "application/pdf"
        _, _, _, gevoelig2 = dossier.document_inhoud(administratie_id=administratie_id, document_id=avb_doc, actor_id=beheerder_id)
        assert gevoelig2 is False
        assert "dossier_document_ingezien" in _audit_acties(admin_engine, id_doc)
        assert "dossier_document_ingezien" not in _audit_acties(admin_engine, avb_doc)


class TestHandhaving:
    def test_drie_herinneringen_blokkeren_indienen_ook_namens(
        self, administratie_id, project_id, gekoppelde_zzper, detacheerder, beheerder_id, push_ok, monkeypatch, admin_engine
    ):
        zzper = gekoppelde_zzper
        service.koppel_detacheerder(detacheerder_id=detacheerder, zzper_id=zzper, actor_id=beheerder_id)
        # Uren invoeren blijft altijd mogelijk.
        service.zet_dag(administratie_id=administratie_id, zzper_id=zzper, project_id=project_id, jaar=JAAR, weeknummer=WEEK,
                        datum=MAANDAG, uren=Decimal("8"), m2=None, actor_id=zzper)

        r = _herinner(administratie_id, zzper, beheerder_id, 2, monkeypatch)
        assert [x.volgnummer for x in r] == [1, 2] and not r[-1].geblokkeerd
        assert "1 van 3" in push_ok[0]["pushtekst"] and push_ok[0]["url"] == "/accordeur?dossier=1"
        # Dagrem: tweede herinnering op dezelfde dag weigert.
        with pytest.raises(dossier.AlHerinnerdVandaag):
            monkeypatch.setattr(dossier, "_vandaag", lambda: date.today() + timedelta(days=1))
            dossier.stuur_herinnering(administratie_id=administratie_id, gebruiker_id=zzper, actor_id=beheerder_id)
        monkeypatch.setattr(dossier, "_vandaag", lambda: date.today())
        # Nog niet geblokkeerd → indienen kan.
        staat = service.dien_week_in(administratie_id=administratie_id, zzper_id=zzper, project_id=project_id, jaar=JAAR, weeknummer=WEEK, actor_id=zzper)
        assert staat.status == "ingediend"

        monkeypatch.setattr(dossier, "_vandaag", lambda: date.today() + timedelta(days=2))
        r3 = dossier.stuur_herinnering(administratie_id=administratie_id, gebruiker_id=zzper, actor_id=beheerder_id)
        assert r3.volgnummer == 3 and r3.geblokkeerd is True
        stand = dossier.dossier_van(administratie_id=administratie_id, gebruiker_id=zzper, actor_id=beheerder_id)
        assert stand.geblokkeerd and stand.herinneringen_teller == 3 and stand.kan_herinneren_vandaag is False

        # Volgende week: dagen zetten mag, indienen niet — ook niet namens door de detacheerder.
        volgende = MAANDAG + timedelta(days=7)
        service.zet_dag(administratie_id=administratie_id, zzper_id=zzper, project_id=project_id, jaar=JAAR, weeknummer=WEEK + 1,
                        datum=volgende, uren=Decimal("8"), m2=None, actor_id=detacheerder)
        for actor in (zzper, detacheerder):
            with pytest.raises(dossier.DossierGeblokkeerd):
                service.dien_week_in(administratie_id=administratie_id, zzper_id=zzper, project_id=project_id, jaar=JAAR, weeknummer=WEEK + 1, actor_id=actor)

        # Deblokkade: alle verplichte documenten geüpload (ter controle telt).
        for code in ("kopie_id", "steigerpas", "vca_vol", "avb"):
            _upload(administratie_id, zzper, code, zzper)
        stand = dossier.dossier_van(administratie_id=administratie_id, gebruiker_id=zzper, actor_id=beheerder_id)
        assert stand.geblokkeerd is True  # kvk_uittreksel ontbreekt nog
        stand = _upload(administratie_id, zzper, "kvk_uittreksel", zzper)
        assert stand.geblokkeerd is False and stand.compleet_incl_ter_controle and not stand.compleet
        assert stand.herinneringen_teller == 3  # episode nog niet dicht (niets goedgekeurd)
        # De uren over de geblokkeerde periode kunnen alsnog ingediend worden — niets zoek.
        staat = service.dien_week_in(administratie_id=administratie_id, zzper_id=zzper, project_id=project_id, jaar=JAAR, weeknummer=WEEK + 1, actor_id=detacheerder)
        assert staat.status == "ingediend" and staat.totaal_uren == Decimal("8")

        # Een afwijzing heractiveert de blokkade.
        stand = dossier.beoordeel_document(administratie_id=administratie_id, document_id=_doc_id(stand, "avb"),
                                           goedgekeurd=False, reden="Verkeerde polis", actor_id=beheerder_id)
        assert stand.geblokkeerd is True
        # Volledig goedgekeurd → teller-reset + deblokkade.
        stand = _upload(administratie_id, zzper, "avb", zzper)
        assert stand.geblokkeerd is False
        stand = _keur_alles_goed(administratie_id, zzper, beheerder_id)
        assert stand.compleet and stand.herinneringen_teller == 0 and stand.geblokkeerd is False
        with pytest.raises(dossier.DossierCompleet):
            dossier.stuur_herinnering(administratie_id=administratie_id, gebruiker_id=zzper, actor_id=beheerder_id)

        acties = _audit_acties(admin_engine, zzper)
        assert acties.count("dossier_herinnering_verstuurd") == 3
        assert acties.count("dossier_geblokkeerd") == 2 and acties.count("dossier_gedeblokkeerd") == 2
        assert "dossier_compleet_teller_reset" in acties

    def test_mislukte_verzending_telt_niet(self, administratie_id, zzper, beheerder_id, monkeypatch, admin_engine):
        def _mislukt(gebruiker, **kwargs):
            return verzending.VerzendUitkomst(HerinneringStatus.MISLUKT, None, {"fout": "SMTP dood"}, 0)

        monkeypatch.setattr(verzending, "verstuur_push_anders_mail", _mislukt)
        with pytest.raises(dossier.HerinneringMislukt):
            dossier.stuur_herinnering(administratie_id=administratie_id, gebruiker_id=zzper, actor_id=beheerder_id)
        stand = dossier.dossier_van(administratie_id=administratie_id, gebruiker_id=zzper, actor_id=beheerder_id)
        assert stand.herinneringen_teller == 0 and stand.kan_herinneren_vandaag is True  # opnieuw mag
        assert "dossier_geblokkeerd" not in _audit_acties(admin_engine, zzper)

    def test_verlopen_document_bijt_op_indienmoment(
        self, administratie_id, project_id, gekoppelde_zzper, beheerder_id, push_ok, monkeypatch
    ):
        zzper = gekoppelde_zzper
        for code in ("kopie_id", "steigerpas", "vca_vol", "avb", "kvk_uittreksel"):
            _upload(administratie_id, zzper, code, zzper, geldig_tot=date.today() + timedelta(days=40))
        # Alles ter controle → compleet_incl; kantoor keurt goed → compleet, teller 0.
        _keur_alles_goed(administratie_id, zzper, beheerder_id)
        # Drie herinneringen kunnen niet (compleet) — dus zónder herinneringen nooit een blokkade,
        # ook niet als alles verloopt: de handhaving start altijd met de herinner-knop.
        monkeypatch.setattr(dossier, "_vandaag", lambda: date.today() + timedelta(days=60))
        service.zet_dag(administratie_id=administratie_id, zzper_id=zzper, project_id=project_id, jaar=JAAR, weeknummer=WEEK,
                        datum=MAANDAG, uren=Decimal("8"), m2=None, actor_id=zzper)
        staat = service.dien_week_in(administratie_id=administratie_id, zzper_id=zzper, project_id=project_id, jaar=JAAR, weeknummer=WEEK, actor_id=zzper)
        assert staat.status == "ingediend"
        stand = dossier.dossier_van(administratie_id=administratie_id, gebruiker_id=zzper, actor_id=beheerder_id)
        assert stand.aantal_verlopen == 5 and stand.geblokkeerd is False and stand.kan_herinneren_vandaag


class TestKvk:
    def test_parser_velden(self):
        body = {
            "kvkNummer": "68750110",
            "naam": "Test BV",
            "_embedded": {
                "eigenaar": {"rechtsvorm": "Besloten Vennootschap"},
                "hoofdvestiging": {
                    "adressen": [
                        {"type": "correspondentieadres", "postbusnummer": "12"},
                        {"type": "bezoekadres", "straatnaam": "Ekkersrijt", "huisnummer": 2012, "postcode": "5692BA", "plaats": "Son en Breugel"},
                    ]
                },
            },
        }
        r = kvk.verwerk_basisprofiel(body)
        assert r == {"naam": "Test BV", "rechtsvorm": "Besloten Vennootschap", "adres": "Ekkersrijt 2012", "postcode": "5692BA", "plaats": "Son en Breugel"}

    def test_parser_afgeschermd_en_uitgeschreven(self):
        body = {
            "handelsnamen": [{"naam": "Milan Kowalski Montage"}],
            "_embedded": {"hoofdvestiging": {"adressen": [{"type": "bezoekadres", "straatnaam": "X", "huisnummer": 1, "indAfgeschermd": "Ja", "plaats": "Arnhem"}]}},
            "materieleRegistratie": {"datumEinde": "20260701"},
        }
        r = kvk.verwerk_basisprofiel(body)
        assert r == {"naam": "Milan Kowalski Montage", "uitgeschreven": True, "datum_einde": "01-07-2026"}
        assert kvk.verwerk_basisprofiel({}) is None
        with pytest.raises(kvk.KvkFout):
            kvk.verwerk_basisprofiel([])

    def test_config_consistentie(self, monkeypatch):
        assert kvk.config_probleem() is None  # dev-default: testsleutel + test-URL
        monkeypatch.setattr(kvk.settings, "kvk_api_key", "eigen-sleutel")
        assert "KVK_BASE_URL" in (kvk.config_probleem() or "")
        with pytest.raises(kvk.KvkConfiguratieFout):
            kvk.haal_basisprofiel("68750110")
        with pytest.raises(kvk.KvkFout):
            kvk.haal_basisprofiel("123")

    def test_bevestig_bedrijfsgegevens_valideert_en_audit(self, administratie_id, zzper, beheerder_id, admin_engine):
        with pytest.raises(service.OngeldigeInvoer):
            dossier.bevestig_bedrijfsgegevens(administratie_id=administratie_id, gebruiker_id=zzper, kvk_nummer="123",
                                              btw_nummer=None, naam=None, plaats=None, rechtsvorm=None, actor_id=beheerder_id)
        with pytest.raises(service.OngeldigeInvoer):
            dossier.bevestig_bedrijfsgegevens(administratie_id=administratie_id, gebruiker_id=zzper, kvk_nummer=None,
                                              btw_nummer="BE123", naam=None, plaats=None, rechtsvorm=None, actor_id=beheerder_id)
        stand = dossier.bevestig_bedrijfsgegevens(
            administratie_id=administratie_id, gebruiker_id=zzper, kvk_nummer="68750110", btw_nummer="nl 001234567 b01",
            naam="Milan Kowalski Montage", plaats="Arnhem", rechtsvorm="Eenmanszaak", actor_id=beheerder_id,
        )
        assert stand.kvk_nummer == "68750110" and stand.btw_nummer == "NL001234567B01"
        assert stand.kvk_bevestigd_door_naam == "Test-Beheerder"
        assert "dossier_bedrijfsgegevens_bevestigd" in _audit_acties(admin_engine, zzper)


class TestApi:
    def test_veld_upload_en_dossier_en_bestand(self, administratie_id, zzper_met_scope):
        headers = _bearer(zzper_met_scope, rol="zzper")
        resp = client.post(
            "/uren/dossier/upload",
            data={"administratie_id": str(administratie_id), "type_code": "steigerpas", "geldig_tot": OVER_EEN_JAAR.isoformat()},
            files={"bestand": ("pas.pdf", io.BytesIO(PDF), "application/pdf")},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        pas = next(d for d in body["documenten"] if d["code"] == "steigerpas")
        assert pas["status"] == "ter_controle" and body["herinneringen_max"] == 3
        resp = client.get(f"/uren/dossier?administratie_id={administratie_id}", headers=headers)
        assert resp.status_code == 200 and resp.json()["aantal_ter_controle"] == 1
        resp = client.get(f"/uren/dossier/documenten/{administratie_id}/{pas['document_id']}/bestand", headers=headers)
        assert resp.status_code == 200 and resp.content == PDF and "X-Dossier-Bsn-Gevoelig" not in resp.headers

    def test_indienen_geblokkeerd_geeft_423(self, administratie_id, project_id, gekoppelde_zzper, beheerder_id, push_ok, monkeypatch):
        zzper = gekoppelde_zzper
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=zzper, administratie_id=administratie_id)
        voorwaarden.leg_akkoord_vast(gebruiker_id=zzper)
        _herinner(administratie_id, zzper, beheerder_id, 3, monkeypatch)
        resp = client.post(
            "/uren/zzp/indienen",
            json={"administratie_id": str(administratie_id), "project_id": str(project_id), "jaar": JAAR, "weeknummer": WEEK},
            headers=_bearer(zzper, rol="zzper"),
        )
        assert resp.status_code == 423
        assert "geblokkeerd" in resp.json()["detail"]

    def test_kantoor_flow_en_poorten(self, administratie_id, zzper, beheerder_id, admin_engine, push_ok):
        boekhouder = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=boekhouder, administratie_id=administratie_id)
        pad = f"/uren/kantoor/dossier/{administratie_id}/{zzper}"
        assert client.get(pad, headers=_bearer(boekhouder, rol="boekhouding")).status_code == 403
        service.zet_meerwerk_recht(gebruiker_id=boekhouder, ingeschakeld=True, actor_id=beheerder_id)
        assert client.get(pad, headers=_bearer(boekhouder, rol="boekhouding")).status_code == 200
        assert client.get(pad, headers=_bearer(zzper, rol="zzper")).status_code == 403

        h = _bearer(beheerder_id, rol="beheerder")
        resp = client.post(
            f"{pad}/upload",
            data={"type_code": "kopie_id", "geldig_tot": OVER_EEN_JAAR.isoformat()},
            files={"bestand": ("id.pdf", io.BytesIO(PDF), "application/pdf")},
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        doc_id = next(d["document_id"] for d in resp.json()["documenten"] if d["code"] == "kopie_id")
        resp = client.get(f"/uren/kantoor/dossier/{administratie_id}/documenten/{doc_id}/bestand", headers=h)
        assert resp.status_code == 200 and resp.headers["X-Dossier-Bsn-Gevoelig"] == "1"
        resp = client.post(f"/uren/kantoor/dossier/{administratie_id}/documenten/{doc_id}/beoordelen",
                           json={"goedgekeurd": False}, headers=h)
        assert resp.status_code == 422
        resp = client.post(f"/uren/kantoor/dossier/{administratie_id}/documenten/{doc_id}/beoordelen",
                           json={"goedgekeurd": True}, headers=h)
        assert resp.status_code == 200 and resp.json()["aantal_aanwezig"] == 1
        resp = client.post(f"{pad}/herinneren", headers=h)
        assert resp.status_code == 200 and resp.json()["volgnummer"] == 1
        resp = client.post(f"{pad}/herinneren", headers=h)
        assert resp.status_code == 409  # dagrem
        resp = client.post(f"{pad}/bedrijfsgegevens", json={"kvk_nummer": "68750110", "naam": "Milan Montage"}, headers=h)
        assert resp.status_code == 200 and resp.json()["kvk_nummer"] == "68750110"
        # Documenttypen-instelling: Beheerder-only.
        resp = client.get(f"/uren/beheer/dossier-documenttypen/{administratie_id}", headers=_bearer(boekhouder, rol="boekhouding"))
        assert resp.status_code == 403
        resp = client.get(f"/uren/beheer/dossier-documenttypen/{administratie_id}", headers=h)
        assert resp.status_code == 200 and resp.json()["is_standaard"] is True
        typen = resp.json()["typen"]
        typen[1]["verplicht"] = False
        resp = client.put(f"/uren/beheer/dossier-documenttypen/{administratie_id}", json={"typen": typen}, headers=h)
        assert resp.status_code == 200 and resp.json()["is_standaard"] is False
        # Veldgebruikers-overzicht draagt de dossier-samenvatting.
        resp = client.get("/uren/beheer/veldgebruikers", headers=h)
        kaart = next(k for k in resp.json() if k["gebruiker_id"] == str(zzper))
        assert kaart["dossiers"] == [] or kaart["dossiers"][0]["aantal_aanwezig"] == 1  # zonder scope geen rij

    def test_kvk_lookup_endpoint_valideert(self, beheerder_id, monkeypatch):
        h = _bearer(beheerder_id, rol="beheerder")
        assert client.get("/uren/kantoor/kvk/12", headers=h).status_code == 422
        monkeypatch.setattr(kvk, "haal_basisprofiel", lambda n: {"naam": "Test BV", "plaats": "Son"})
        resp = client.get("/uren/kantoor/kvk/68750110", headers=h)
        assert resp.status_code == 200 and resp.json()["naam"] == "Test BV" and resp.json()["testomgeving"] is True
        monkeypatch.setattr(kvk, "haal_basisprofiel", lambda n: None)
        assert client.get("/uren/kantoor/kvk/68750110", headers=h).json()["gevonden"] is False

    def test_stand_draagt_dossier_signalen(self, administratie_id, zzper_met_scope, beheerder_id):
        resp = client.get(f"/uren/kantoor/stand?administratie_id={administratie_id}", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 200
        assert resp.json()["dossier_veldwerkers_met_signaal"] == 1 and resp.json()["dossier_geblokkeerd"] == 0
