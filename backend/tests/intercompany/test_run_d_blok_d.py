# ruff: noqa: F811 — pytest-fixtures als parameters (geïmporteerd uit de zustermodules)
"""Run D 02-10 blok D (Peter 02-10; casus Universal: vier BV's, 12 richtingen, "de verkoop lijkt mij de waarheid"):

1. Relaties: een naam-match tussen twee eigen administraties die BEIDE een bron-KvK-identiteit dragen is automatisch
   `bevestigd` (audit per rij); zonder bron-KvK aan één kant blijft de 16-09-regel (vermoedelijk, niet actief).
2. IC-tegenpartijen (accordering overslaan) volgen de actieve crediteur-relaties — idempotent, mens wint, afwezig-pad.
3. Richtingen: alle geordende paren binnen een handelsgroep (4 BV's = 12), richting zonder records = 0/0 zonder call,
   richting mét één kant = getoetst mét lege andere kant.
4. Sleutel mét/zonder `RLZ-`-prefix (match én onderweg), concept-hulzen geteld, gesplitste bron rond de kanteldatum,
   Odoo-partner op identiteit (KvK/naam), de drie soorten + stand, handeling "Factuur opvragen" (concept + route),
   lees-only CLI `ic-aansluiting-rapport`, querybibliotheek `ic-aansluiting`, nameting-onderdeel `ic-aansluiting`.
Geen enkele echte RLZ-/Odoo-call."""

from __future__ import annotations

import argparse
import re
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import scoped_session
from app.intercompany import factuurmatch as fm
from app.intercompany import identiteit, opvragen, relaties, tegenpartijen
from app.intercompany.models import AdministratieIdentiteit, IntercompanyRelatie
from app.intercompany.relaties import Paar
from app.main import app
from app.reconciliatie import run as run_service
from app.reconciliatie import soort_stand
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.intercompany.test_factuurmatch import (  # noqa: F401
    ENT_A_IN_B,
    ENT_B_IN_A,
    NU,
    FakeOdooClient,
    FakeOdooPort,
    FakeRlzClient,
    _move,
    _purchase_rij,
    _run,
    _sales_rij,
    twee_administraties,
)
from tests.intercompany.test_relaties import KVK_A, KVK_B, _relaties, _vendor, adm_a, adm_b, rlz  # noqa: F401

REPO = Path(__file__).resolve().parents[3]
client = TestClient(app)


def _f(kant: str, nummer: str | None, bedrag: str, datum: str = "2026-08-14", *, status: int = 2, adm=None):
    a = uuid.UUID("aaaaaaaa-0000-4000-8000-00000000000a")
    b = uuid.UUID("bbbbbbbb-0000-4000-8000-00000000000b")
    return fm.maak_factuur(
        id=str(uuid.uuid4()),
        administratie_id=adm or (a if kant == "verkoop" else b),
        kant=kant,
        nummer=nummer,
        bedrag=Decimal(bedrag),
        datum=date.fromisoformat(datum),
        status=status,
    )


def _match(verkoop, inkoop, *, onderweg=frozenset()):
    return fm.match_facturen(
        verkoper_id=uuid.UUID("aaaaaaaa-0000-4000-8000-00000000000a"),
        ontvanger_id=uuid.UUID("bbbbbbbb-0000-4000-8000-00000000000b"),
        verkoop=verkoop,
        inkoop=inkoop,
        module_onderweg=set(onderweg),
        nu=NU,
    )


# ---- 4a. sleutel mét/zonder RLZ-prefix, hulzen ---------------------------------------------------------------------


class TestSleutelEnHulzen:
    def test_nummer_varianten_met_en_zonder_rlz_prefix(self) -> None:
        assert fm.nummer_varianten("rlz2080142200") == frozenset({"rlz2080142200", "2080142200"})
        assert fm.nummer_varianten("2080142200") == frozenset({"2080142200"})
        assert fm.nummer_varianten("rlz") == frozenset({"rlz"})
        assert fm.nummer_varianten(None) == frozenset()

    def test_inkoop_met_rlz_prefix_matcht_op_nummer(self) -> None:
        """Gat B 28-09: de RLZ-export-UBL zet `RLZ-` voor het verkoopnummer — vóór 02-10 géén nummer-match."""
        u = _match([_f("verkoop", "2080142200", "100.00")], [_f("inkoop", "RLZ-2080142200", "100.00")])
        assert u.bevindingen == () and [m.regel for m in u.matches] == [fm.REGEL_NUMMER]

    def test_onderweg_in_module_met_rlz_prefix_is_geen_bevinding(self) -> None:
        """28-09: 32 open Steigerbouw-documenten droegen `rlz…` als referentie_norm en telden niet als onderweg."""
        u = _match([_f("verkoop", "2080142200", "100.00")], [], onderweg={"rlz2080142200"})
        assert u.bevindingen == () and len(u.onderweg) == 1

    def test_concept_huls_zonder_nummer_en_bedrag_telt_maar_meldt_niet(self) -> None:
        huls = _f("verkoop", None, "0.00", status=1)
        u = _match([huls, _f("verkoop", "50212076", "756.26")], [])
        assert u.hulzen == 1 and u.aantal_verkoop == 1
        assert [b.soort for b in u.bevindingen] == [fm.SOORT_INKOOP_ONTBREEKT]

    def test_drie_soorten_per_richting(self) -> None:
        u = _match(
            [_f("verkoop", "1001", "100.00"), _f("verkoop", "1002", "50.00")],
            [_f("inkoop", "1001", "99.00"), _f("inkoop", "1003", "10.00")],
        )
        assert sorted(b.soort for b in u.bevindingen) == sorted(
            [fm.SOORT_BEDRAG_AFWIJKING, fm.SOORT_INKOOP_ONTBREEKT, fm.SOORT_VERKOOP_ONTBREEKT]
        )
        assert soort_stand.code_default("ic_inkoop_ontbreekt") == "actie"
        assert soort_stand.code_default("ic_verkoop_ontbreekt") == "meten"
        assert soort_stand.code_default("ic_bedrag_afwijking") == "meten"
        # Oude namen blijven geregistreerd (sluiting/acceptaties), de motor produceert ze niet meer.
        assert {"ic_ontbreekt_bij_ontvanger", "ic_ontbreekt_bij_verkoper", "ic_bedrag_verschilt"} <= set(
            soort_stand.REGISTRY
        )
        assert fm.SOORTEN == (
            fm.SOORT_INKOOP_ONTBREEKT,
            fm.SOORT_VERKOOP_ONTBREEKT,
            fm.SOORT_BEDRAG_AFWIJKING,
            fm.SOORT_STATUS_VERSCHILT,
        )


# ---- 3. richtingen -------------------------------------------------------------------------------------------------


class TestRichtingen:
    def test_vier_bvs_geven_twaalf_richtingen_ook_zonder_records(self) -> None:
        ned, stb, ver, mat = (uuid.uuid4() for _ in range(4))
        e = lambda: uuid.uuid4()  # noqa: E731
        paren = [
            Paar(ned, e(), stb, "debiteur", "kvk", "afgeleid", e()),  # Nederland → Steigerbouw (beide kanten)
            Paar(ver, e(), stb, "debiteur", "kvk", "afgeleid", None),  # Verkoop → Steigerbouw (alleen verkoopkant)
            Paar(mat, e(), ned, "crediteur", "naam", "bevestigd", None),  # Nederland → Materiaal (alleen inkoopkant)
        ]
        richtingen = fm.bouw_richtingen(paren)
        assert len(richtingen) == 12
        zonder = [r for r in richtingen if r.zonder_records]
        assert len(zonder) == 9
        met = {(r.verkoper_id, r.ontvanger_id): r for r in richtingen if not r.zonder_records}
        assert set(met) == {(ned, stb), (ver, stb), (ned, mat)}
        assert met[(ver, stb)].inkoop_entity_ids == frozenset() and met[(ver, stb)].verkoop_entity_ids
        assert met[(ned, mat)].verkoop_entity_ids == frozenset() and met[(ned, mat)].inkoop_entity_ids

    def test_twee_losse_groepen_blijven_los(self) -> None:
        a, b, c, d = (uuid.uuid4() for _ in range(4))
        paren = [Paar(a, uuid.uuid4(), b, "debiteur", "kvk", "afgeleid", None), Paar(c, uuid.uuid4(), d, "debiteur", "kvk", "afgeleid", None)]
        assert len(fm.bouw_richtingen(paren)) == 4  # 2 × (2 × 1)

    def test_richting_zonder_records_kost_geen_call_en_telt_in_slotregel(self, twee_administraties) -> None:
        a, b = twee_administraties
        rlz_a, rlz_b = FakeRlzClient([_sales_rij(1, 1.0)], []), FakeRlzClient([], [])
        paar = Paar(a, ENT_B_IN_A, b, "debiteur", "kvk", "afgeleid", ENT_A_IN_B)
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok(fm.BLOK)
        code, uit, _ = _run({a: fm.RlzBron(a, rlz_a), b: fm.RlzBron(b, rlz_b)}, [paar], verzamelaar=verzamelaar)
        # A → B getoetst; B → A bestaat als richting zonder records (0/0, geen call op B's verkoopkant).
        assert any(x.startswith("ZONDER RECORDS ") for x in uit), uit
        assert any("2 richting(en) (1 zonder debiteur-/crediteurrecord" in x for x in uit), uit
        assert any(re.search(r"1/2 richting\(en\) getoetst \(1 zonder records\)", x) for x in uit), uit
        assert all(p != "SalesInvoices" for p, _ in rlz_b.calls)
        assert code == 1

    def test_richting_filter_op_naamdelen(self) -> None:
        ned, stb = uuid.uuid4(), uuid.uuid4()
        rel = fm.Handelsrelatie(ned, stb, frozenset({uuid.uuid4()}), frozenset())
        namen = {ned: "Universal Nederland B.V.", stb: "Universal Steigerbouw B.V."}
        assert fm._richting_past(rel, "Nederland>Steigerbouw", namen.get)
        assert fm._richting_past(rel, f"{ned}>{stb}", namen.get)
        assert fm._richting_past(rel, "Steigerbouw", namen.get)
        assert not fm._richting_past(rel, "Steigerbouw>Nederland", namen.get)
        assert not fm._richting_past(rel, "Materiaal", namen.get)


# ---- 4b. gesplitste bron + Odoo-partner op identiteit --------------------------------------------------------------


class _OpnameBron(fm.Bron):
    def __init__(self, aid: uuid.UUID, facturen: list) -> None:
        super().__init__(aid)
        self.facturen = facturen
        self.calls: list[tuple] = []

    def verkoop(self, entity_ids, van, tot, *, tegenpartij_id=None):
        self.calls.append(("verkoop", van, tot, tegenpartij_id))
        return list(self.facturen)

    def inkoop(self, entity_ids, van, tot, *, tegenpartij_id=None):
        self.calls.append(("inkoop", van, tot, tegenpartij_id))
        return list(self.facturen)


class TestGesplitsteBron:
    def test_splitst_op_kanteldatum_en_telt_niets_dubbel(self) -> None:
        aid, tp = uuid.uuid4(), uuid.uuid4()
        voor = _OpnameBron(aid, [_f("verkoop", "50212076", "756.26", "2026-07-09"), _f("verkoop", "LAAT", "1.00", "2026-09-05")])
        na = _OpnameBron(aid, [_f("verkoop", "F/2026/00066", "692.58", "2026-09-10"), _f("verkoop", "VROEG", "1.00", "2026-08-01")])
        bron = fm.GesplitsteBron(aid, voor=voor, na=na, kanteldatum=date(2026, 9, 1))
        uit = bron.verkoop([uuid.uuid4()], date(2026, 6, 1), date(2026, 9, 16), tegenpartij_id=tp)
        assert sorted(f.nummer for f in uit) == ["50212076", "F/2026/00066"]
        assert voor.calls == [("verkoop", date(2026, 6, 1), date(2026, 8, 31), tp)]
        assert na.calls == [("verkoop", date(2026, 9, 1), date(2026, 9, 16), tp)]

    def test_alleen_voor_de_knip_leest_de_odoo_kant_niet(self) -> None:
        aid = uuid.uuid4()
        voor, na = _OpnameBron(aid, []), _OpnameBron(aid, [])
        fm.GesplitsteBron(aid, voor=voor, na=na, kanteldatum=date(2026, 9, 1)).inkoop([], date(2026, 1, 1), date(2026, 8, 30))
        assert len(voor.calls) == 1 and na.calls == []

    def test_odoo_bron_vindt_partner_op_kvk_van_de_tegenpartij(self, monkeypatch) -> None:
        """Route 4 (run D): de Odoo-kant (leesbron Verkoop) kent de RLZ-entity's niet — partner op KvK van de identiteit."""
        aid, tp = uuid.uuid4(), uuid.uuid4()
        odoo = FakeOdooClient([_move(7, "F/2026/00066", None, 692.58, "2026-09-10", move_type="out_invoice", partner=42)])
        bron = fm.OdooBron(aid, fm._LeesPort(odoo))
        monkeypatch.setattr(fm, "identiteit_van", lambda a: SimpleNamespace(kvk="94539820", naam="Universal Steigerbouw B.V.", naam_norm="universal steigerbouw") if a == tp else None)
        uit = bron.verkoop([uuid.uuid4()], date(2026, 9, 1), date(2026, 9, 16), tegenpartij_id=tp)
        assert [f.nummer for f in uit] == ["F/2026/00066"]
        # Route 3 (uuid5 terugrekenen) leest eerst de partner-id's; route 4 zoekt daarna op KvK van de identiteit.
        assert any(["company_registry", "=", "94539820"] in d for d in odoo.calls), odoo.calls
        # Zonder identiteit = zichtbare LET-OP (EntityNietVertaalbaar), nooit een filterloze read.
        with pytest.raises(fm.EntityNietVertaalbaar):
            bron.verkoop([uuid.uuid4()], date(2026, 9, 1), date(2026, 9, 16), tegenpartij_id=uuid.uuid4())

    def test_verkoop_na_knip_uit_odoo_sluit_inkoop_bij_ontvanger(self, twee_administraties, monkeypatch) -> None:
        """De 28-09-casus F/2026/00066: Odoo-verkoop van Verkoop ↔ RLZ-inkoop bij Steigerbouw — sinds run D gematcht."""
        a, b = twee_administraties
        rlz_a = FakeRlzClient([_sales_rij(50212045, 711.84, "2026-07-06")], [])
        odoo = FakeOdooClient([_move(7, "F/2026/00066", None, 692.58, "2026-09-10", move_type="out_invoice", partner=42)])
        rlz_b = FakeRlzClient([], [_purchase_rij("50212045", 711.84, "2026-07-08"), _purchase_rij("F/2026/00066", 692.58, "2026-09-10")])
        monkeypatch.setattr(fm, "identiteit_van", lambda _a: SimpleNamespace(kvk=KVK_B, naam="Universal Nederland (test)", naam_norm="universal nederland test"))
        bronnen = {
            a: fm.GesplitsteBron(a, voor=fm.RlzBron(a, rlz_a), na=fm.OdooBron(a, fm._LeesPort(odoo)), kanteldatum=date(2026, 9, 1)),
            b: fm.RlzBron(b, rlz_b),
        }
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok(fm.BLOK)
        code, uit, err = _run(bronnen, [Paar(a, ENT_B_IN_A, b, "debiteur", "kvk", "bevestigd", ENT_A_IN_B)], verzamelaar=verzamelaar)
        assert code == 0 and err == [] and verzamelaar.bevindingen == []
        assert any("2 verkoop / 2 inkoop gelezen, 2 gematcht (2 op nummer" in x for x in uit), uit

    def test_open_bron_leesbron_met_knip_is_gesplitst(self, monkeypatch) -> None:
        from app.odoo import credentials as odoo_credentials
        from app.rlz import credentials as rlz_credentials

        aid = uuid.uuid4()
        monkeypatch.setattr("app.backends.registry.backend_voor", lambda _a: SimpleNamespace(name="RLZ"))
        monkeypatch.setattr(rlz_credentials, "rlz_admin_id_voor", lambda _a: "rlz-x")
        monkeypatch.setattr(rlz_credentials, "client_voor_rlz_admin_id", lambda _r: SimpleNamespace(for_administration=lambda r: FakeRlzClient([], [])))
        monkeypatch.setattr(odoo_credentials, "leeskoppeling_voor", lambda _a: SimpleNamespace(voorraad_knip_datum=date(2026, 9, 1), alleen_lezen=True))
        monkeypatch.setattr(odoo_credentials, "odoo_client_voor", lambda _a, read_only=False: FakeOdooClient([]))
        bron = fm.open_bron(aid)
        assert isinstance(bron, fm.GesplitsteBron) and bron.kanteldatum == date(2026, 9, 1)
        assert isinstance(bron.voor, fm.RlzBron) and isinstance(bron.na, fm.OdooBron)
        # Leesbron zonder knipdatum = gewoon RLZ (zichtbaar in het log, geen gok).
        monkeypatch.setattr(odoo_credentials, "leeskoppeling_voor", lambda _a: SimpleNamespace(voorraad_knip_datum=None, alleen_lezen=True))
        assert isinstance(fm.open_bron(aid), fm.RlzBron)


# ---- 1. relaties: auto-bevestiging + afwezig-pad -------------------------------------------------------------------


def test_naam_match_zonder_bron_kvk_blijft_vermoedelijk(adm_a, adm_b, rlz) -> None:
    """Afwezig-pad van de auto-bevestiging: B heeft géén KvK in haar bron-identiteit → de 16-09-regel blijft gelden."""
    identiteit.sync_identiteiten()
    with scoped_session(None) as session:
        session.get(AdministratieIdentiteit, adm_b).kvk = None
    v_naam = _vendor(adm_a, "Kempen Facilities BV")
    uitkomst = relaties.leid_relaties_af()
    rij = {r.entity_in_a: r for r in _relaties(adm_a)}[v_naam]
    assert rij.basis == "naam" and rij.status == "afgeleid" and rij.reden is None
    assert uitkomst.auto_bevestigd == 0 and uitkomst.zonder_kvk_identiteit == 1
    assert v_naam not in {p.entity_in_a for p in relaties.actieve_paren()}


def test_mens_identiteit_telt_niet_als_bron_kvk(adm_a, adm_b, rlz) -> None:
    identiteit.sync_identiteiten()
    with scoped_session(None) as session:
        session.get(AdministratieIdentiteit, adm_b).bron = "mens"
    _vendor(adm_a, "Kempen Facilities BV")
    uitkomst = relaties.leid_relaties_af()
    assert uitkomst.auto_bevestigd == 0 and uitkomst.per_basis == {"naam": 1}
    assert all(r.status == "afgeleid" for r in _relaties(adm_a))


def test_bestaande_afgeleide_naam_rij_wordt_alsnog_auto_bevestigd_met_audit(adm_a, adm_b, rlz, admin_engine) -> None:
    identiteit.sync_identiteiten()
    v_naam = _vendor(adm_a, "Kempen Facilities BV")
    with scoped_session(None) as session:
        session.add(
            IntercompanyRelatie(
                administratie_a_id=adm_a, entity_in_a=v_naam, entity_naam="Kempen Facilities BV", administratie_b_id=adm_b,
                richting="crediteur", basis="naam", status="afgeleid", bron="afgeleid",
            )
        )
    uitkomst = relaties.leid_relaties_af()
    rij = {r.entity_in_a: r for r in _relaties(adm_a)}[v_naam]
    assert rij.status == "bevestigd" and rij.bron == "afgeleid" and rij.reden == relaties.AUTO_BEVESTIGD_REDEN
    assert (uitkomst.relaties_bijgewerkt, uitkomst.auto_bevestigd) == (1, 1)
    with admin_engine.connect() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM platform.audit_event WHERE actie = 'intercompany_relatie_gewijzigd' "
                "AND nieuwe_waarde ->> 'auto_bevestigd' = 'true' AND record_id = :rid"
            ),
            {"rid": rij.id},
        ).scalar_one()
    assert n == 1
    # Een door een Beheerder UITGESLOTEN rij (bron mens) wordt nooit alsnog bevestigd.
    with scoped_session(None) as session:
        r = session.get(IntercompanyRelatie, rij.id)
        r.status, r.bron, r.reden = "uitgesloten", "mens", "geen groepsmaatschappij"
    opnieuw = relaties.leid_relaties_af()
    assert opnieuw.mens_rijen_overgeslagen == 1 and opnieuw.auto_bevestigd == 0


# ---- 2. tegenpartijen ---------------------------------------------------------------------------------------------


def test_tegenpartijen_afwezig_pad_zonder_relaties() -> None:
    uit = tegenpartijen.leid_tegenpartijen_af()
    assert uit.kandidaten == 0 and uit.nieuw == 0 and uit.fouten == []
    assert uit.regels == ["0 kandidaten — geen (actieve) crediteur-relaties tussen eigen administraties"]


def test_tegenpartijen_volgen_actieve_crediteur_relaties(adm_a, adm_b, beheerder_id, rlz, admin_engine) -> None:
    from app.doorbelasting.models import IntercompanyTegenpartij

    identiteit.sync_identiteiten()
    v_kvk = _vendor(adm_a, "Kempen Facilities B.V.", kvk=KVK_B)  # B levert aan A (kvk → actief)
    relaties.leid_relaties_af()
    uit = tegenpartijen.leid_tegenpartijen_af()
    assert (uit.kandidaten, uit.nieuw, uit.fouten) == (1, 1, [])
    assert _is_ic(adm_a, v_kvk) is True
    with scoped_session(adm_a) as session:
        rij = session.query(IntercompanyTegenpartij).filter_by(administratie_id=adm_a, entity_guid=v_kvk).one()
        assert rij.actief and rij.bron == tegenpartijen.BRON_INTERCOMPANY_RELATIE and rij.naam == "Kempen Facilities B.V."
    with admin_engine.connect() as conn:
        audits = conn.execute(
            text(
                "SELECT count(*) FROM platform.audit_event WHERE actie = 'intercompany_leverancier_gewijzigd' "
                "AND administratie_id = :a AND record_id = :v"
            ),
            {"a": adm_a, "v": v_kvk},
        ).scalar_one()
    assert audits == 1
    # Idempotent.
    opnieuw = tegenpartijen.leid_tegenpartijen_af()
    assert (opnieuw.nieuw, opnieuw.ongewijzigd, opnieuw.geheractiveerd) == (0, 1, 0)
    # Beheerder sluit de relatie uit → de rij die wij zetten gaat uit (nooit delete), zichtbaar.
    rel = next(r for r in _relaties(adm_a) if r.entity_in_a == v_kvk)
    relaties.zet_status(rel.id, status="uitgesloten", reden="geen groepsmaatschappij meer", actor_id=beheerder_id)
    na_uitsluiting = tegenpartijen.leid_tegenpartijen_af()
    assert na_uitsluiting.gedeactiveerd == 1
    assert _is_ic(adm_a, v_kvk) is False
    # Mens zet 'm zelf uit (bron handmatig, inactief) → de afleiding heractiveert NOOIT over de mens heen.
    relaties.zet_status(rel.id, status="afgeleid", reden=None, actor_id=beheerder_id)
    with scoped_session(adm_a) as session:
        rij = session.query(IntercompanyTegenpartij).filter_by(administratie_id=adm_a, entity_guid=v_kvk).one()
        rij.bron = "handmatig"
        rij.actief = False
    mens = tegenpartijen.leid_tegenpartijen_af()
    assert mens.mens_uit_overgeslagen == 1 and mens.geheractiveerd == 0
    assert any("mens/mapping wint" in r for r in mens.regels)


def _is_ic(administratie_id: uuid.UUID, vendor_id: uuid.UUID) -> bool:
    """De ENE leesbron van de IC-vlag (accordering overslaan), gelezen in de scope van de administratie."""
    with scoped_session(administratie_id) as session:
        return relaties.is_intercompany_leverancier(session, administratie_id=administratie_id, vendor_id=vendor_id)


# ---- handeling "Factuur opvragen bij ‹BV›" ------------------------------------------------------------------------


class TestOpvragen:
    def test_concept_puur_zonder_adres_met_intake_adres(self) -> None:
        c = opvragen.bouw_concept(
            bevinding_id=uuid.uuid4(),
            administratie_id=uuid.uuid4(),
            detail={"verkoper_naam": "Universal Nederland B.V.", "ontvanger_naam": "Universal Steigerbouw B.V.", "nummer": "2080143084", "datum": "2026-08-19", "bedrag_verkoop": "21420.63"},
            intake_adres="facturen@ak-nijenhuis.nl",
        )
        assert c.aan is None and "Universal Nederland B.V." in c.aan_tekst
        assert c.onderwerp.startswith("Factuur 2080143084 aan Universal Steigerbouw B.V.")
        assert "€ 21.420,63" in c.tekst and "19-08-2026" in c.tekst and "facturen@ak-nijenhuis.nl" in c.tekst
        assert c.mailto.startswith("mailto:?subject=") and "body=" in c.mailto
        # Zonder intake-adres: geen gok, een omschrijving.
        c2 = opvragen.bouw_concept(bevinding_id=uuid.uuid4(), administratie_id=uuid.uuid4(), detail={}, intake_adres=None)
        assert "onze boekhoudmail" in c2.tekst and c2.nummer is None

    def test_route_200_concept_met_audit_en_409_op_andere_soort(self, administratie_id, beheerder_id, admin_engine) -> None:
        from app.reconciliatie.models import ReconciliatieBevinding, ReconciliatieRun

        with scoped_session(None) as session:
            run = ReconciliatieRun(status="klaar", bron="cli")
            session.add(run)
            session.flush()
            run_id = run.id
        detail_ok = {
            "bron": "intercompany", "afwijking_soort": "ic_inkoop_ontbreekt", "verkoper_naam": "Universal Nederland B.V.",
            "ontvanger_naam": "Universal Steigerbouw B.V.", "nummer": "2080143084", "datum": "2026-08-19", "bedrag_verkoop": "21420.63",
        }
        with scoped_session(administratie_id) as session:
            ok = ReconciliatieBevinding(run_id=run_id, blok="intercompany", soort="afwijking", administratie_id=administratie_id, vingerafdruk="a" * 16, tekst="x", detail=detail_ok)
            ander = ReconciliatieBevinding(run_id=run_id, blok="intercompany", soort="afwijking", administratie_id=administratie_id, vingerafdruk="b" * 16, tekst="y", detail={**detail_ok, "afwijking_soort": "ic_verkoop_ontbreekt"})
            session.add_all([ok, ander])
            session.flush()
            ok_id, ander_id = ok.id, ander.id
        headers = {"Authorization": f"Bearer {create_access_token(beheerder_id, rol='beheerder')}"}
        r = client.post(f"/reconciliatie/intercompany/{ok_id}/factuur-opvragen", json={"administratie_id": str(administratie_id)}, headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["verkoper_naam"] == "Universal Nederland B.V." and body["nummer"] == "2080143084" and body["aan"] is None
        assert body["onderwerp"].startswith("Factuur 2080143084 aan Universal Steigerbouw B.V.") and body["mailto"].startswith("mailto:?")
        assert "€ 21.420,63" in body["tekst"]
        with admin_engine.connect() as conn:
            n = conn.execute(
                text("SELECT count(*) FROM platform.audit_event WHERE actie = 'ic_factuur_opgevraagd_concept' AND record_id = :id"),
                {"id": ok_id},
            ).scalar_one()
        assert n == 1
        r = client.post(f"/reconciliatie/intercompany/{ander_id}/factuur-opvragen", json={"administratie_id": str(administratie_id)}, headers=headers)
        assert r.status_code == 409 and "ic_inkoop_ontbreekt" in r.json()["detail"]

    def test_route_404_buiten_scope_en_401_zonder_token(self, administratie_id, beheerder_id) -> None:
        onbekend = uuid.uuid4()
        r = client.post(f"/reconciliatie/intercompany/{onbekend}/factuur-opvragen", json={"administratie_id": str(administratie_id)})
        assert r.status_code == 401
        r = client.post(
            f"/reconciliatie/intercompany/{onbekend}/factuur-opvragen",
            json={"administratie_id": str(administratie_id)},
            headers={"Authorization": f"Bearer {create_access_token(beheerder_id, rol='beheerder')}"},
        )
        assert r.status_code == 404


# ---- lees-only CLI, querybibliotheek, nameting ------------------------------------------------------------------------


class TestMeetlat:
    def test_cli_ic_aansluiting_rapport_geeft_richting_en_administratie_door(self, monkeypatch, capsys) -> None:
        from app import cli as app_cli
        from app.intercompany import aansluiting_cli

        gezien: dict = {}

        def nep_blok(args, verzamelaar, **kw):  # noqa: ANN001
            gezien["args"], gezien["verzamelaar"] = args, verzamelaar
            kw["stdout"]("3/12 richting(en) getoetst (9 zonder records), 0 afwijking(en) totaal (0 geaccepteerd)")
            return 0

        monkeypatch.setattr(fm, "cli_blok", nep_blok)
        aid = uuid.uuid4()
        monkeypatch.setattr(app_cli, "_zoek_administraties", lambda t: [(aid, "Universal Steigerbouw B.V.")] if "Steiger" in t else [])
        assert app_cli.main(["ic-aansluiting-rapport", "--administratie", "Steigerbouw", "--richting", "Nederland>Steigerbouw"]) == 0
        assert gezien["verzamelaar"] is None and gezien["args"].ic_richting == "Nederland>Steigerbouw"
        assert gezien["args"].administratie_ids == [aid]
        assert "LEES-ONLY" in capsys.readouterr().out
        assert app_cli.main(["ic-aansluiting-rapport", "--administratie", "Onbekend"]) == 2
        assert aansluiting_cli.COMMANDO == "ic-aansluiting-rapport"

    def test_querybibliotheek_ic_aansluiting_parseert_en_draait(self, administratie_id, capsys) -> None:
        from app import cli as app_cli
        from app.lezen import bibliotheek

        q = bibliotheek.zoek("ic-aansluiting")
        assert q.scope == "administratie" and q.optioneel == ("richting", "afwijking_soort")
        assert app_cli.main(["db-lezen", "ic-aansluiting", "--administratie", str(administratie_id), "--param", "richting=Nederland>Steigerbouw"]) == 0
        assert "ic-aansluiting" in capsys.readouterr().out

    def test_nameting_onderdeel_ic_aansluiting_alleen_op_verzoek_en_lees_only(self) -> None:
        yml = (REPO / ".github" / "workflows" / "nameting.yml").read_text(encoding="utf-8")
        blok = yml.split('if [[ "$ONDERDEEL" == "ic-aansluiting" ]]; then', 1)[1].split("\n          fi\n", 1)[0]
        assert "reconciliatie-alles --alleen intercompany --lees-only" in blok
        assert 'ic-aansluiting-rapport --administratie "Universal Steigerbouw"' in blok
        assert "/reconciliatie/intercompany/" in blok
        assert 'UIT="verkenning/nameting-ic-aansluiting-$DATUM.txt"' in blok
        assert 'elif [[ "$ONDERDEEL" == "ic-aansluiting" ]]; then\n            OORDEEL_BRON="verkenning/nameting-ic-aansluiting-$DATUM.txt"' in yml
        assert '"$ONDERDEEL" != "ic-aansluiting"' in yml and ", ic-aansluiting]" in yml
        sh = (REPO / "scripts" / "gcp" / "nameting.sh").read_text(encoding="utf-8")
        allow = re.search(r'^ALLOWLIST="([^"]+)"', sh, flags=re.M)
        assert allow and "ic-aansluiting-rapport" in allow.group(1).split()
        assert re.search(r"^\s*ic-aansluiting-rapport\) echo ic-aansluiting ;;", sh, re.M)
