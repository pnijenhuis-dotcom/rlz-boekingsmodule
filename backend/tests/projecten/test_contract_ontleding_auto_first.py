"""Contract-ontleding D6 (07-09, besluit Peter 06-09): kopvelden mét sentinel + AUTO-FIRST.

Bewaakt: (a) het schema is union-vrij en de sentinel "" wordt deterministisch None; de code-afleiding
"doorlopende huur uit de huurstaffel" in meerdere formuleringen (én géén afleiding zonder staffel);
(b) de ontleding schrijft specs/staffels DIRECT mét herkomst 'contract' + één audit_event oud→nieuw;
"niet in contract aangetroffen" is een zichtbare uitkomst; een mens-correctie zet herkomst 'mens' en
wint bij her-ontleding; her-ontleding vervangt alleen de eigen contract-staffels; het
meerwerk-prijsvoorstel uit de staffels blijft een mens-besluit."""

from __future__ import annotations

import inspect
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.extractie.contract import (
    CONTRACT_SCHEMA,
    ContractKop,
    ContractOntleding,
    ContractRegel,
    _normaliseer,
    leid_doorlopende_huur_af,
    map_eenheid,
    parse_getal,
)
from app.extractie.schema_poort import tel_union_parameters
from app.projecten import kantoor, ontleding
from app.uren import service as uren_service
from tests.uren.conftest import maak_project


def _regel(soort: str, oms: str, **kw) -> ContractRegel:
    basis = dict(citaat=None, waarde=None, eenheid=None, van=None, tot=None, zekerheid=0.9)
    basis.update(kw)
    return ContractRegel(soort=soort, omschrijving=oms, **basis)


# --- (a) schema + deterministische afleidingen (geen DB) ------------------------------------------


class TestSchemaEnAfleidingen:
    def test_schema_is_union_vrij_en_vraagt_kopvelden_expliciet(self) -> None:
        assert tel_union_parameters(CONTRACT_SCHEMA) == 0
        kop = CONTRACT_SCHEMA["properties"]["kop"]
        assert set(kop["required"]) >= {"soort_werk", "contract_m2", "doorlopende_huur_na"}
        # Kopvelden zitten NIET dubbel in de regels-enum.
        assert "contract_m2" not in CONTRACT_SCHEMA["properties"]["regels"]["items"]["properties"]["soort"]["enum"]

    def test_sentinel_lege_string_wordt_none(self) -> None:
        resultaat = _normaliseer(
            {
                "kop": {
                    "soort_werk": "  ", "soort_werk_citaat": "",
                    "contract_m2": "4200", "contract_m2_citaat": 'p.1 "4.200 m²"',
                    "doorlopende_huur_na": "", "doorlopende_huur_na_citaat": "",
                },
                "regels": [
                    {"soort": "staffel", "oms": "Trapsteiger", "citaat": "", "waarde": "9.20", "eenheid": "m²",
                     "van": "", "tot": "", "z": 0.9},
                    {"soort": "contract_m2", "oms": "dubbel", "citaat": "", "waarde": "1", "eenheid": "",
                     "van": "", "tot": "", "z": 1},  # onbekende regelsoort → genegeerd
                ],
            }
        )
        assert resultaat.kop.soort_werk is None and resultaat.kop.doorlopende_huur_na is None
        assert resultaat.kop.contract_m2 == "4200"
        [staffel] = resultaat.regels
        assert staffel.citaat is None and staffel.van is None and staffel.eenheid == "m²"

    @pytest.mark.parametrize(
        ("tekst", "verwacht"),
        [
            ("4200", Decimal("4200")),
            ("4.200", Decimal("4200")),
            ("4.200 m²", Decimal("4200")),
            ("4200,50", Decimal("4200.50")),
            ("1.234,56", Decimal("1234.56")),
            ("€ 9,20 per m²", Decimal("9.20")),
            ("150,-", Decimal("150")),
            ("9.2", Decimal("9.2")),
            ("abc", None),
            ("", None),
            (None, None),
        ],
    )
    def test_parse_getal_deterministisch(self, tekst, verwacht) -> None:
        assert parse_getal(tekst) == verwacht

    @pytest.mark.parametrize(
        ("eenheid", "verwacht"),
        [("m²", "m2"), ("m2/week", "m2"), ("m¹/week", "m1"), ("per stuk", "stuks"), ("uur", "manuren"),
         ("manuren", "manuren"), ("week", None), ("", None), (None, None)],
    )
    def test_map_eenheid(self, eenheid, verwacht) -> None:
        assert map_eenheid(eenheid) == verwacht

    @pytest.mark.parametrize(
        ("tekst", "bedrag", "per", "vanaf"),
        [
            ('§5 "€ 150/week uitgaande van 9 weken"', Decimal("150"), "week", 10),
            ("huur € 150,- per week, uitgaande van 9 weken standtijd", Decimal("150"), "week", 10),
            ("huur € 0,42 per m² per week na 16 weken", Decimal("0.42"), "m² per week", 17),
            ("€ 1.250 p/wk vanaf 12 weken", Decimal("1250"), "week", 13),
        ],
    )
    def test_doorlopende_huur_uit_staffel_meerdere_formuleringen(self, tekst, bedrag, per, vanaf) -> None:
        afleiding = leid_doorlopende_huur_af([tekst])
        assert afleiding is not None
        assert (afleiding.bedrag, afleiding.per, afleiding.vanaf_week) == (bedrag, per, vanaf)
        assert f"vanaf week {vanaf}" in afleiding.omschrijving and "afgeleid uit staffel" in afleiding.omschrijving

    def test_doorlopende_huur_geen_staffel_of_onvolledig_is_none(self) -> None:
        assert leid_doorlopende_huur_af([]) is None
        assert leid_doorlopende_huur_af(["Trapsteiger 9.20 m²"]) is None  # geen weektarief
        assert leid_doorlopende_huur_af(["€ 150 per week"]) is None  # geen uitgangsperiode → niet gokken
        assert leid_doorlopende_huur_af(["", None]) is None  # type: ignore[list-item]


# --- (b) auto-first wegschrijven (DB) ---------------------------------------------------------------


def _audit(admin_engine: Engine, *, actie: str, record_id: uuid.UUID) -> list[tuple]:
    with admin_engine.begin() as conn:
        return conn.execute(
            text(
                "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event "
                "WHERE actie = :actie AND record_id = :rid ORDER BY tijdstip"
            ),
            {"actie": actie, "rid": record_id},
        ).all()


class TestAutoFirst:
    def _document(self, admin_engine, administratie_id, beheerder_id, project_id, tmp_path, monkeypatch) -> uuid.UUID:
        from app.documenten.storage import LokaleBestandsopslag

        opslag = LokaleBestandsopslag(tmp_path)
        monkeypatch.setattr("app.projecten.kantoor.standaard_opslag", lambda: opslag)
        monkeypatch.setattr("app.projecten.ontleding.standaard_opslag", lambda: opslag)
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET ai_extractie_ingeschakeld = true WHERE id = :id"),
                {"id": administratie_id},
            )
        monkeypatch.setattr("app.projecten.ontleding.settings.anthropic_api_key", "test-key", raising=False)
        return kantoor.upload_project_document(
            administratie_id=administratie_id, project_id=project_id, actor_id=beheerder_id,
            soort="contract", titel="OB", bestandsnaam="ob.pdf", inhoud=b"%PDF-1.4 contract",
        )

    @staticmethod
    def _ontleding_1() -> ContractOntleding:
        return ContractOntleding(
            kop=ContractKop(
                soort_werk="gevelsteiger t.b.v. renovatie", soort_werk_citaat='p.1 "gevelsteiger t.b.v. renovatie"',
                contract_m2="4.200", contract_m2_citaat='p.1 "4.200 m² steigerwerk"',
                doorlopende_huur_na=None, doorlopende_huur_na_citaat=None,
            ),
            regels=[
                _regel("opdrachtgever", "Opdrachtgever", waarde="BAM Wonen", citaat='p.1 "opdrachtgever: BAM Wonen"'),
                _regel("looptijd", "Looptijd", van="2026-06-02", tot="2026-11-30"),
                _regel("staffel", "Trapsteiger", waarde="9.20", eenheid="m²", citaat='§4.2 "€ 9,20 per m²"'),
                _regel("staffel", "Huur doorlopend", waarde="150", eenheid="week",
                       citaat='§5 "€ 150/week uitgaande van 9 weken"'),
                _regel("staffel", "Hoogwerker", waarde="45", eenheid="uur", citaat='§4.3 "€ 45 per uur"'),
                _regel("boete", "Boeteclausule", waarde="500", citaat='§7 "€ 500 per kalenderdag"'),
            ],
        )

    def test_ontleding_schrijft_direct_met_herkomst_en_audit(
        self, admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, tmp_path, monkeypatch
    ) -> None:
        project_id = maak_project(admin_engine, administratie_id, "26040 AutoFirst (X)")
        document_id = self._document(admin_engine, administratie_id, beheerder_id, project_id, tmp_path, monkeypatch)

        resultaat = ontleding.ontleed_document(
            administratie_id=administratie_id, project_id=project_id, project_document_id=document_id,
            actor_id=beheerder_id, extraheer=lambda *_a, **_k: self._ontleding_1(),
        )
        # 3 kopvelden + 6 regels = 9 leesspoor-rijen; huurstaffel 'week' is geen meerwerk-eenheid → ongeldig,
        # maar voedt wél de code-afleiding van de doorlopende huur.
        assert resultaat.aantal_regels == 9
        tellers = (resultaat.overgenomen, resultaat.ongeldig, resultaat.niet_aangetroffen, resultaat.mens_behouden)
        assert tellers == (8, 1, 0, 0)
        assert resultaat.doorlopende_huur_afgeleid is True

        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        spec = detail.specificatie
        assert spec is not None
        assert spec.soort_werk == "gevelsteiger t.b.v. renovatie"
        assert spec.contract_m2 == Decimal("4200")
        assert spec.opdrachtgever == "BAM Wonen"
        assert (str(spec.looptijd_van), str(spec.looptijd_tot)) == ("2026-06-02", "2026-11-30")
        assert spec.doorlopende_huur_omschrijving is not None
        assert spec.doorlopende_huur_omschrijving.startswith("€ 150 per week vanaf week 10")
        assert spec.veld_herkomst == {
            "soort_werk": "contract", "contract_m2": "contract", "opdrachtgever": "contract",
            "looptijd_van": "contract", "looptijd_tot": "contract", "doorlopende_huur_omschrijving": "contract",
        }
        staffels = {s.omschrijving: s for s in detail.staffels}
        assert set(staffels) == {"Trapsteiger", "Hoogwerker"}
        assert (staffels["Trapsteiger"].eenheid, staffels["Trapsteiger"].prijs_per_eenheid) == ("m2", Decimal("9.20"))
        assert staffels["Hoogwerker"].eenheid == "manuren"
        assert all(s.herkomst == "contract" and s.herkomst_document_id == document_id for s in detail.staffels)
        assert staffels["Trapsteiger"].bron == '§4.2 "€ 9,20 per m²"'

        spoor = {(r.soort, r.omschrijving): r for r in detail.ontleding}
        assert spoor[("staffel", "Huur doorlopend")].status == "ongeldig"
        assert "eenheid 'week' niet herkend" in spoor[("staffel", "Huur doorlopend")].waarde["reden"]
        assert spoor[("doorlopende_huur", "Doorlopende huur daarna (afgeleid uit huurstaffel)")].status == "overgenomen"
        assert spoor[("boete", "Boeteclausule")].status == "overgenomen"
        assert all(r.status != "voorstel" for r in detail.ontleding)  # geen bevestig-poort meer

        [(oud, nieuw)] = _audit(admin_engine, actie="contract_ontleed", record_id=document_id)
        # Vóór de ontleding: lege spec (alle velden None, geen herkomst) en geen contract-staffels.
        assert all(v is None for k, v in oud["specificatie"].items() if k != "veld_herkomst")
        assert oud["specificatie"]["veld_herkomst"] == {} and oud["staffels_contract"] == []
        assert nieuw["specificatie"]["contract_m2"] == "4200"
        assert [s["omschrijving"] for s in nieuw["staffels_contract"]] == ["Trapsteiger", "Hoogwerker"]
        assert (nieuw["aantal_regels"], nieuw["overgenomen"], nieuw["ongeldig"]) == (9, 8, 1)

    def test_niet_aangetroffen_is_expliciete_uitkomst(
        self, admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, tmp_path, monkeypatch
    ) -> None:
        project_id = maak_project(admin_engine, administratie_id, "26041 Leeg (X)")
        document_id = self._document(admin_engine, administratie_id, beheerder_id, project_id, tmp_path, monkeypatch)
        resultaat = ontleding.ontleed_document(
            administratie_id=administratie_id, project_id=project_id, project_document_id=document_id,
            actor_id=beheerder_id, extraheer=lambda *_a, **_k: ContractOntleding(kop=ContractKop(), regels=[]),
        )
        assert (resultaat.aantal_regels, resultaat.niet_aangetroffen, resultaat.overgenomen) == (3, 3, 0)
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        assert {r.soort for r in detail.ontleding} == {"soort_werk", "contract_m2", "doorlopende_huur"}
        assert all(r.status == "niet_aangetroffen" and r.waarde is None for r in detail.ontleding)
        assert detail.specificatie is not None and detail.specificatie.contract_m2 is None
        assert detail.staffels == []

    def test_ongeldig_contract_m2_wordt_niet_ingevuld(
        self, admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, tmp_path, monkeypatch
    ) -> None:
        project_id = maak_project(admin_engine, administratie_id, "26042 Ongeldig (X)")
        document_id = self._document(admin_engine, administratie_id, beheerder_id, project_id, tmp_path, monkeypatch)
        resultaat = ontleding.ontleed_document(
            administratie_id=administratie_id, project_id=project_id, project_document_id=document_id,
            actor_id=beheerder_id,
            extraheer=lambda *_a, **_k: ContractOntleding(
                kop=ContractKop(contract_m2="ca. vierduizend", contract_m2_citaat='p.2 "ca. vierduizend m²"'), regels=[]
            ),
        )
        assert resultaat.ongeldig == 1
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        assert detail.specificatie is not None and detail.specificatie.contract_m2 is None
        [m2] = [r for r in detail.ontleding if r.soort == "contract_m2"]
        assert m2.status == "ongeldig" and "geen leesbaar getal" in m2.waarde["reden"]

    def test_mens_correctie_zet_herkomst_mens_en_wint_bij_herontleding(
        self, admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, tmp_path, monkeypatch
    ) -> None:
        project_id = maak_project(admin_engine, administratie_id, "26043 Correctie (X)")
        document_id = self._document(admin_engine, administratie_id, beheerder_id, project_id, tmp_path, monkeypatch)
        ontleding.ontleed_document(
            administratie_id=administratie_id, project_id=project_id, project_document_id=document_id,
            actor_id=beheerder_id, extraheer=lambda *_a, **_k: self._ontleding_1(),
        )
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        spec = detail.specificatie
        assert spec is not None

        # Mens corrigeert contract-m² (rest ongewijzigd doorgegeven, zoals het specs-formulier doet).
        kantoor.zet_specificatie(
            administratie_id=administratie_id, project_id=project_id, actor_id=beheerder_id,
            opdrachtgever=spec.opdrachtgever, werknummer_opdrachtgever=spec.werknummer_opdrachtgever,
            soort_werk=spec.soort_werk, contract_m2=Decimal("4350"),
            looptijd_van=spec.looptijd_van, looptijd_tot=spec.looptijd_tot,
            huurtijd_omschrijving=spec.huurtijd_omschrijving,
            doorlopende_huur_omschrijving=spec.doorlopende_huur_omschrijving,
        )
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        assert detail.specificatie is not None
        herkomst = detail.specificatie.veld_herkomst or {}
        assert herkomst["contract_m2"] == "mens"
        assert herkomst["soort_werk"] == "contract"  # ongewijzigd veld houdt zijn chip
        [(oud, nieuw)] = _audit(admin_engine, actie="project_specificatie_bijgewerkt", record_id=project_id)
        assert (oud["contract_m2"], nieuw["contract_m2"]) == ("4200", "4350")

        # Mens corrigeert een contract-staffel → herkomst 'mens'; voegt zelf een staffel toe → 'mens'.
        trap = next(s for s in detail.staffels if s.omschrijving == "Trapsteiger")
        kantoor.wijzig_staffel(
            administratie_id=administratie_id, staffel_id=trap.id, actor_id=beheerder_id,
            omschrijving="Trapsteiger", eenheid="m2", prijs_per_eenheid=Decimal("9.50"), verrekenbaar=True,
        )
        kantoor.voeg_staffel_toe(
            administratie_id=administratie_id, project_id=project_id, actor_id=beheerder_id,
            omschrijving="Netten", eenheid="m2", prijs_per_eenheid=Decimal("1.10"),
        )
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        per_naam = {s.omschrijving: s for s in detail.staffels}
        assert per_naam["Trapsteiger"].herkomst == "mens"
        assert per_naam["Trapsteiger"].prijs_per_eenheid == Decimal("9.50")
        assert per_naam["Netten"].herkomst == "mens"
        assert per_naam["Hoogwerker"].herkomst == "contract"
        [(oud_s, nieuw_s)] = _audit(admin_engine, actie="project_staffel_gewijzigd", record_id=trap.id)
        assert (oud_s["herkomst"], nieuw_s["herkomst"]) == ("contract", "mens")

        # Her-ontleding (nu leest de AI 4.100 m² en een duurdere trapsteiger): mens-waarden winnen zichtbaar,
        # eigen contract-staffels worden vervangen, mens-staffels blijven.
        herlezing = ContractOntleding(
            kop=ContractKop(contract_m2="4100", contract_m2_citaat='p.1 "4.100 m²"',
                            soort_werk="gevelsteiger t.b.v. renovatie", soort_werk_citaat="p.1"),
            regels=[
                _regel("staffel", "Trapsteiger", waarde="9.90", eenheid="m²", citaat="§4.2"),
                _regel("staffel", "Rolsteiger", waarde="12", eenheid="stuks", citaat="§4.4"),
            ],
        )
        resultaat = ontleding.ontleed_document(
            administratie_id=administratie_id, project_id=project_id, project_document_id=document_id,
            actor_id=beheerder_id, extraheer=lambda *_a, **_k: herlezing,
        )
        assert resultaat.mens_behouden == 1
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        assert detail.specificatie is not None and detail.specificatie.contract_m2 == Decimal("4350")
        assert (detail.specificatie.veld_herkomst or {})["contract_m2"] == "mens"
        per_naam = {s.omschrijving: s for s in detail.staffels}
        # Mens-Trapsteiger (9.50) blijft; contract-Hoogwerker weg (niet meer gelezen); Rolsteiger nieuw;
        # de her-gelezen contract-Trapsteiger (9.90) komt ernaast (de mens-regel wordt nooit overschreven).
        assert per_naam["Netten"].herkomst == "mens"
        assert "Hoogwerker" not in per_naam
        assert per_naam["Rolsteiger"].herkomst == "contract"
        trapsteigers = sorted(s.prijs_per_eenheid for s in detail.staffels if s.omschrijving == "Trapsteiger")
        assert trapsteigers == [Decimal("9.50"), Decimal("9.90")]
        m2_spoor = next(r for r in detail.ontleding if r.soort == "contract_m2")
        assert m2_spoor.status == "mens_behouden"
        # Het audit-spoor toont de vervangen contract-staffels oud→nieuw.
        audits = _audit(admin_engine, actie="contract_ontleed", record_id=document_id)
        assert len(audits) == 2
        oud2, nieuw2 = audits[1]
        assert [s["omschrijving"] for s in oud2["staffels_contract"]] == ["Hoogwerker"]
        assert sorted(s["omschrijving"] for s in nieuw2["staffels_contract"]) == ["Rolsteiger", "Trapsteiger"]

    def test_prijsvoorstel_meerwerk_blijft_mens_besluit(
        self, admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, tmp_path, monkeypatch
    ) -> None:
        """Een contract-staffel mag als VOORSTEL dienen (contract_toets toont 'm mét herkomst), maar het
        prijsbesluit zelf (keur_meerwerk_goed) vereist prijs én bedrag van een mens — geen default, en
        de motor leest de staffel daar niet stilzwijgend uit."""
        project_id = maak_project(admin_engine, administratie_id, "26044 Meerwerk (X)")
        document_id = self._document(admin_engine, administratie_id, beheerder_id, project_id, tmp_path, monkeypatch)
        ontleding.ontleed_document(
            administratie_id=administratie_id, project_id=project_id, project_document_id=document_id,
            actor_id=beheerder_id, extraheer=lambda *_a, **_k: self._ontleding_1(),
        )
        voorstel = uren_service.contract_toets(administratie_id=administratie_id, project_id=project_id, eenheid="m2")
        assert [(v.omschrijving, v.prijs_per_eenheid, v.herkomst) for v in voorstel] == [
            ("Trapsteiger", Decimal("9.20"), "contract")
        ]
        params = inspect.signature(uren_service.keur_meerwerk_goed).parameters
        assert params["prijs_per_eenheid"].default is inspect.Parameter.empty
        assert params["bedrag"].default is inspect.Parameter.empty
        bron = inspect.getsource(uren_service.keur_meerwerk_goed)
        assert "ProjectStaffel" not in bron and "contract_toets" not in bron

    def test_legacy_voorstel_rij_blijft_afwikkelbaar_met_herkomst_contract(
        self, admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, tmp_path, monkeypatch
    ) -> None:
        """Rijen van vóór 0118 in status 'voorstel' kunnen nog bevestigd worden (legacy-pad); het resultaat
        draagt dezelfde herkomst 'contract' als de auto-first-route."""
        project_id = maak_project(admin_engine, administratie_id, "26045 Legacy (X)")
        document_id = self._document(admin_engine, administratie_id, beheerder_id, project_id, tmp_path, monkeypatch)
        regel_id = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.project_ontleding_regel "
                    "(id, administratie_id, project_id, project_document_id, soort, omschrijving, citaat, waarde, "
                    " zekerheid, status) VALUES (:id, :aid, :pid, :doc, 'staffel', 'Trapsteiger', '§4.2', "
                    " CAST(:w AS jsonb), 0.9, 'voorstel')"
                ),
                {"id": regel_id, "aid": administratie_id, "pid": project_id, "doc": document_id,
                 "w": '{"waarde": "9.20", "eenheid": "m²"}'},
            )
        ontleding.beslis_regel(
            administratie_id=administratie_id, regel_id=regel_id, actor_id=beheerder_id, bevestigen=True, eenheid="m2"
        )
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        [staffel] = detail.staffels
        assert (staffel.herkomst, staffel.herkomst_document_id, staffel.prijs_per_eenheid) == (
            "contract", document_id, Decimal("9.20"),
        )
        # Een her-ontleding laat de legacy-beslissing als vastlegging staan.
        ontleding.ontleed_document(
            administratie_id=administratie_id, project_id=project_id, project_document_id=document_id,
            actor_id=beheerder_id, extraheer=lambda *_a, **_k: ContractOntleding(kop=ContractKop(), regels=[]),
        )
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        assert any(r.id == regel_id and r.status == "bevestigd" for r in detail.ontleding)
