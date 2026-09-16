# ruff: noqa: F811 — pytest-fixtures als parameters
"""Doorbelasting-aansluiting (Peter 12-09/16-09, blok 2): verkoop bij de bron aan élke whitelist-doelentiteit ↔ inkoop
in het doel op álle crediteurrecords van de bron-identiteit; dezelfde pure matchmotor als het IC-blok; tabellen sluit /
ontbreekt in doel / bedrag afwijkt / status verschilt / doel niet in module / inkoop zonder verkoop; open spiegel-taak =
actie 'Boek inkoop in doel'; webfilter = meting ongeldig; geen credential = zichtbaar overgeslagen; blokfunctie met
Verzamelaar + acceptatie; lees-only CLI. Geen echte RLZ-/Odoo-call."""

from __future__ import annotations

import argparse
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.doorbelasting import aansluiting as da
from app.intercompany.factuurmatch import Bron, BronOvergeslagen, IcFactuur, maak_factuur
from app.reconciliatie import run as run_service
from app.rlz.client import RlzWebfilterError
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

BRON = uuid.UUID("aaaaaaaa-0000-4000-8000-00000000000a")
DOEL = uuid.UUID("bbbbbbbb-0000-4000-8000-00000000000b")
DOEL2 = uuid.UUID("cccccccc-0000-4000-8000-00000000000c")
DEB = uuid.UUID("11111111-0000-4000-8000-000000000001")  # debiteur-record van het doel in de bron
DEB2 = uuid.UUID("11111111-0000-4000-8000-000000000002")
CRED = uuid.UUID("22222222-0000-4000-8000-000000000002")  # crediteurrecord van de bron in het doel
NU = date(2026, 9, 16)
VAN, TOT = date(2026, 1, 1), NU


def _f(kant: str, nummer: str | None, bedrag: str, datum: str = "2026-05-10", *, status: int = 2, adm=None, fid=None) -> IcFactuur:  # noqa: ANN001
    return maak_factuur(
        id=fid or str(uuid.uuid4()), administratie_id=adm or (BRON if kant == "verkoop" else DOEL), kant=kant,
        nummer=nummer, bedrag=Decimal(bedrag), datum=date.fromisoformat(datum), status=status, boekstuk=f"BS-{nummer}",
    )


class FakeBron(Bron):
    def __init__(self, administratie_id: uuid.UUID, *, verkoop=None, inkoop=None, webfilter: bool = False) -> None:  # noqa: ANN001
        super().__init__(administratie_id)
        self._verkoop, self._inkoop, self._webfilter = verkoop or {}, inkoop or [], webfilter
        self.calls: list[tuple[str, frozenset]] = []
        self.gesloten = False

    def verkoop(self, entity_ids, van, tot):  # noqa: ANN001
        if self._webfilter:
            raise RlzWebfilterError(403, "GET", "SalesInvoices", "<html>Access Denied</html>")
        ids = frozenset(entity_ids)
        self.calls.append(("verkoop", ids))
        return [f for e in ids for f in self._verkoop.get(e, [])]

    def inkoop(self, entity_ids, van, tot):  # noqa: ANN001
        self.calls.append(("inkoop", frozenset(entity_ids)))
        return list(self._inkoop)

    def sluit(self) -> None:
        self.gesloten = True


def _rij(naam: str, guid: uuid.UUID, doel: uuid.UUID | None) -> da.WhitelistRij:
    return da.WhitelistRij(mapping_id=uuid.uuid4(), doelentiteit_naam=naam, doel_customer_guid=guid, doel_administratie_id=doel)


def _meet(bronnen: dict, whitelist, *, spiegel=None, crediteurrecords=None):  # noqa: ANN001
    def factory(aid: uuid.UUID) -> Bron:
        b = bronnen.get(aid)
        if b is None:
            raise BronOvergeslagen("overgeslagen — geen RLZ-credential (test)")
        return b

    return da.meet(
        bron_administratie_id=BRON, van=VAN, tot=TOT, nu=NU, bron_factory=factory, whitelist=whitelist,
        crediteurrecords=crediteurrecords or (lambda b, d: (frozenset({CRED}), "ic_relatie")),
        onderweg=lambda d: set(), spiegel_open=spiegel or (lambda b: {}),
        naam_van=lambda aid: {BRON: "Kempen Facilities", DOEL: "Kempen Chalets", DOEL2: "Mantelzorgwoningen"}.get(aid),
    )


class TestMeting:
    def test_sluit_ontbreekt_bedrag_en_inkoop_zonder_verkoop(self) -> None:
        v1, v2, v3 = _f("verkoop", "2026-001", "100.00"), _f("verkoop", "2026-002", "250.00"), _f("verkoop", "2026-003", "80.00")
        i1, i3, i9 = _f("inkoop", "2026-001", "100.00"), _f("inkoop", "2026-003", "85.00"), _f("inkoop", "2026-999", "12.00")
        bronnen = {BRON: FakeBron(BRON, verkoop={DEB: [v1, v2, v3]}), DOEL: FakeBron(DOEL, inkoop=[i1, i3, i9])}
        a = _meet(bronnen, [_rij("Kempen Chalets B.V.", DEB, DOEL)])
        d = a.doelen[0]
        assert d.doel_in_module and d.inkoop_basis == "ic_relatie" and d.inkoop_entity_ids == frozenset({CRED})
        assert bronnen[DOEL].calls == [("inkoop", frozenset({CRED}))]
        assert bronnen[BRON].calls == [("verkoop", frozenset({DEB}))]
        soorten = sorted(da._IC_NAAR_DA[b.soort] for b in d.uitkomst.bevindingen)
        assert soorten == [da.SOORT_BEDRAG_AFWIJKT, da.SOORT_INKOOP_ZONDER_VERKOOP, da.SOORT_ONTBREEKT_IN_DOEL]
        assert sum(1 for m in d.uitkomst.matches if m.zeker and m.delta == 0) == 1
        assert bronnen[BRON].gesloten and bronnen[DOEL].gesloten
        regels = "\n".join(da.rapport_regels(a))
        assert "#### Sluit — 1" in regels and "#### Ontbreekt in doel (verkoop zónder inkoop) — 1" in regels
        assert "#### Bedrag afwijkt — 1" in regels and "#### Inkoop in doel zónder verkoop bij de bron — 1" in regels
        assert "| Kempen Chalets B.V. | ja — Kempen Chalets | ic_relatie (1) | 3 (€ 430,00) | 3 | 1 | 1 | 1 | 0 | 1 | 0 | AFWIJKING |" in regels

    def test_doel_niet_in_module_leest_verkoop_maar_geen_inkoop(self) -> None:
        v = _f("verkoop", "2026-010", "1.000,00".replace(".", "").replace(",", "."))
        bronnen = {BRON: FakeBron(BRON, verkoop={DEB2: [v]})}
        a = _meet(bronnen, [_rij("Mantelzorgwoning MN B.V.", DEB2, None)])
        d = a.doelen[0]
        assert not d.doel_in_module and d.reden == "doel niet in module" and len(d.verkoop) == 1 and d.uitkomst is None
        regels = "\n".join(da.rapport_regels(a))
        assert "#### Doel niet in module (verkoop aan een doelentiteit zonder administratie) — 1" in regels
        assert "| NEE |" in regels

    def test_doel_zonder_credential_is_overgeslagen_niet_fout(self) -> None:
        bronnen = {BRON: FakeBron(BRON, verkoop={DEB: [_f("verkoop", "2026-001", "10.00")]})}
        a = _meet(bronnen, [_rij("Kempen Chalets B.V.", DEB, DOEL)])
        assert DOEL in a.overgeslagen and a.doelen[0].uitkomst is None and a.doelen[0].reden.startswith("overgeslagen")
        assert not a.meting_ongeldig and a.ongeldig == {}

    def test_webfilter_is_meting_ongeldig(self) -> None:
        bronnen = {BRON: FakeBron(BRON, webfilter=True)}
        a = _meet(bronnen, [_rij("Kempen Chalets B.V.", DEB, DOEL)])
        assert a.meting_ongeldig and da.WEBFILTER_ONGELDIG in a.ongeldig[BRON]
        assert da.WEBFILTER_ONGELDIG in "\n".join(da.rapport_regels(a))

    def test_geen_crediteurrecord_in_doel_geeft_alles_ontbreekt(self) -> None:
        bronnen = {BRON: FakeBron(BRON, verkoop={DEB: [_f("verkoop", "2026-001", "10.00")]}), DOEL: FakeBron(DOEL, inkoop=[_f("inkoop", "2026-001", "10.00")])}
        a = _meet(bronnen, [_rij("Kempen Chalets B.V.", DEB, DOEL)], crediteurrecords=lambda b, d: (frozenset(), ""))
        d = a.doelen[0]
        assert bronnen[DOEL].calls == []  # niets te lezen zonder crediteurrecord
        assert [da._IC_NAAR_DA[b.soort] for b in d.uitkomst.bevindingen] == [da.SOORT_ONTBREEKT_IN_DOEL]


def _args(**kw) -> argparse.Namespace:  # noqa: ANN003
    return argparse.Namespace(**kw)


class TestBlokfunctie:
    def test_blok_meldt_soorten_met_acceptatie_en_inhaalpad(self, administratie_id) -> None:  # noqa: ANN001
        v1 = _f("verkoop", "2026-001", "100.00", adm=administratie_id, fid=str(uuid.UUID("dddddddd-0000-4000-8000-00000000000d")))
        v2 = _f("verkoop", "2026-002", "50.00", adm=administratie_id)
        bronnen = {administratie_id: FakeBron(administratie_id, verkoop={DEB: [v1, v2], DEB2: [_f("verkoop", "2026-003", "7.00", adm=administratie_id)]}), DOEL: FakeBron(DOEL, inkoop=[])}
        boeking = uuid.uuid4()

        def meet_fn(**kw):  # noqa: ANN003
            return da.meet(
                bron_administratie_id=administratie_id, van=VAN, tot=TOT, nu=NU,
                bron_factory=lambda aid: bronnen[aid],
                whitelist=[_rij("Kempen Chalets B.V.", DEB, DOEL), _rij("Mantelzorgwoning MN B.V.", DEB2, None)],
                crediteurrecords=lambda b, d: (frozenset({CRED}), "kvk"), onderweg=lambda d: set(),
                spiegel_open=lambda b: {"dddddddd-0000-4000-8000-00000000000d": boeking},
                naam_van=lambda aid: "Kempen Facilities" if aid == administratie_id else "Kempen Chalets",
            )

        uit: list[str] = []
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok(da.BLOK)
        code = da.cli_blok(_args(), verzamelaar, bronnen=[administratie_id], nu=NU, meet_fn=meet_fn, stdout=uit.append, stderr=uit.append)
        assert code == 1
        soorten = sorted(b.detail["afwijking_soort"] for b in verzamelaar.bevindingen)
        assert soorten == [da.SOORT_DOEL_NIET_IN_MODULE, da.SOORT_ONTBREEKT_IN_DOEL, da.SOORT_ONTBREEKT_IN_DOEL]
        assert all(b.soort == "afwijking" and b.administratie_id == administratie_id for b in verzamelaar.bevindingen)
        met_inhaal = [b for b in verzamelaar.bevindingen if b.detail.get("spiegel_boeking_id")]
        assert len(met_inhaal) == 1 and met_inhaal[0].detail["spiegel_boeking_id"] == str(boeking)
        assert met_inhaal[0].detail["doel_pad"].endswith("/doorbelasten")
        niet_module = next(b for b in verzamelaar.bevindingen if b.detail["afwijking_soort"] == da.SOORT_DOEL_NIET_IN_MODULE)
        assert niet_module.detail["aantal"] == 1 and niet_module.detail["doel_pad"].endswith("/doorbelasting")
        assert verzamelaar.blokken[da.BLOK].gecontroleerd == 3
        assert any(r.startswith("AFWIJKING ") for r in uit)
        # leesbare teksten: elke soort heeft een titel/wat/doe
        from app.reconciliatie import teksten

        for b in verzamelaar.bevindingen:
            l = teksten.leesbaar(b, administratie_naam="Kempen Facilities", soort=b.soort)
            assert l.titel and l.wat and l.doe and not teksten.bevat_technische_sleutel(l.titel + l.wat + l.doe), l

    def test_blok_zonder_whitelist_is_ok(self) -> None:
        uit: list[str] = []
        assert da.cli_blok(_args(), None, bronnen=[], nu=NU, stdout=uit.append) == 0
        assert any("geen administratie met een actieve doorbelasting-whitelist" in r for r in uit)

    def test_webfilter_in_blok_is_fout_geen_doorrekenen(self, administratie_id) -> None:  # noqa: ANN001
        def meet_fn(**kw):  # noqa: ANN003
            return da.meet(bron_administratie_id=administratie_id, van=VAN, tot=TOT, nu=NU, bron_factory=lambda aid: FakeBron(aid, webfilter=True),
                           whitelist=[_rij("Kempen Chalets B.V.", DEB, DOEL)], crediteurrecords=lambda b, d: (frozenset({CRED}), "kvk"),
                           onderweg=lambda d: set(), spiegel_open=lambda b: {}, naam_van=lambda aid: None)

        uit: list[str] = []
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok(da.BLOK)
        assert da.cli_blok(_args(), verzamelaar, bronnen=[administratie_id], nu=NU, meet_fn=meet_fn, stdout=uit.append, stderr=uit.append) == 1
        fouten = [b for b in verzamelaar.bevindingen if b.soort == "fout"]
        assert len(fouten) == 1 and da.WEBFILTER_ONGELDIG in fouten[0].tekst
        assert not [b for b in verzamelaar.bevindingen if b.soort == "afwijking"]


class TestCli:
    def test_run_cli_jaar_en_exitcodes(self, monkeypatch) -> None:  # noqa: ANN001
        gezien: dict = {}

        def meet_fn(**kw):  # noqa: ANN003
            gezien.update(kw)
            return da.Aansluiting(bron_administratie_id=BRON, bron_naam="Kempen Facilities", van=kw["van"], tot=kw["tot"])

        uit: list[str] = []
        code = da.run_cli(_args(bron="Kempen Fac", jaar=2026, van=None, tot=None), zoek=lambda t: [(BRON, "Kempen Facilities")], meet_fn=meet_fn, stdout=uit.append)
        assert code == 0 and gezien["van"] == date(2026, 1, 1) and gezien["tot"] <= date(2026, 12, 31)
        assert uit[0].startswith("Bron: Kempen Facilities") and "LEES-ONLY" in uit[0]
        assert da.run_cli(_args(bron="x", jaar=None, van=None, tot=None), zoek=lambda t: [], meet_fn=meet_fn) == 2
        assert da.run_cli(_args(bron="K", jaar=None, van=None, tot=None), zoek=lambda t: [(BRON, "A"), (DOEL, "B")], meet_fn=meet_fn) == 2

    def test_cli_main_dispatch_en_allowlist(self, monkeypatch) -> None:  # noqa: ANN001
        from pathlib import Path

        from app import cli

        monkeypatch.setattr(cli, "_zoek_administraties", lambda t: [(BRON, "Kempen Facilities")])
        monkeypatch.setattr(da, "meet", lambda **kw: da.Aansluiting(bron_administratie_id=BRON, bron_naam="Kempen Facilities", van=kw["van"], tot=kw["tot"]))
        assert cli.main(["doorbelasting-aansluiting", "--bron", "Kempen Facilities", "--jaar", "2026"]) == 0
        allow = (Path(__file__).resolve().parents[3] / "scripts" / "gcp" / "nameting.sh").read_text(encoding="utf-8")
        assert "doorbelasting-aansluiting" in allow, "lees-only CLI hoort in de nameting-allowlist"

    def test_reconciliatie_alles_kent_het_blok(self) -> None:
        from app.reconciliatie.run import BLOKKEN

        assert "doorbelasting_aansluiting" in BLOKKEN
        assert BLOKKEN.index("doorbelasting_aansluiting") == BLOKKEN.index("doorbelasting") + 1
