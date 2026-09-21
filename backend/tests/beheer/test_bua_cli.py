"""BUA-kandidaten (lees-only) + bua-kenmerk-zetten (schrijvend, dry-run) — contract B 21-09 (`app/beheer/bua_cli.py`,
`btw_aftrek.voeg_toe`). Twee administraties in eigen RLS-scope (de tweede lekt niet in de eerste), module-bedragen
tellen alleen GEBOEKT + jaar + inkoopfactuur, bank alleen GEBOEKT in het jaar, advies_voor puur (alle vijf takken +
terugval), dry-run schrijft niets, echt zetten = audit mét bron, idempotent, `voeg_toe` laat bestaande aan staan. Élke
CLI-vorm uit het meetrecept wordt letterlijk via `cli.main` aangeroepen (les 19-09 poging 2)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app import cli
from app.bank.models import BankBoeking, BankBoekingBron, BankBoekingRegel, BankBoekingStatus
from app.beheer import btw_aftrek, bua_cli
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentBron, DocumentSoort, DocumentStatus
from app.sync.models import TaxRateCache

pytestmark = pytest.mark.usefixtures("_clean_tables")


@pytest.fixture
def tweede_administratie(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Tweede BV', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


class Stam:
    """Per administratie eigen tarief- en rekening-id's (ledger_id is per administratie uniek in de PK, maar aparte id's
    maken een lek tussen scopes zichtbaar in de asserts)."""

    def __init__(self, administratie_id: uuid.UUID) -> None:
        self.aid = administratie_id
        self.nul = uuid.uuid4()
        self.hoog = uuid.uuid4()
        self.gb = {c: uuid.uuid4() for c in ("4510", "4508", "4014", "4503", "4404", "0100", "4599")}


def _stam(administratie_id: uuid.UUID, *, kenmerk_4510: bool = False) -> Stam:
    s = Stam(administratie_id)
    with scoped_session(administratie_id) as session:
        session.add(
            TaxRateCache(
                id=s.nul, administratie_id=administratie_id, naam="NL, Nul", percentage=Decimal("0"), brondata={}
            )
        )
        session.add(
            TaxRateCache(
                id=s.hoog,
                administratie_id=administratie_id,
                naam="NL, Hoog Tarief",
                percentage=Decimal("0.21"),
                brondata={},
            )
        )
        rijen = (
            ("4510", "Representatiekosten (beperkt aftrekbaar)", 2, s.nul, None),
            ("4508", "Relatiegeschenken (beperkt aftrekbaar)", 2, None, None),
            ("4014", "Kantinekosten", 2, None, None),
            ("4503", "Kosten promotie/sponsoring", 2, s.hoog, None),
            ("4404", "Kosten mobiele telefonie", 2, s.hoog, None),  # geen BUA-woord
            ("0100", "Kantine-inventaris", 3, None, None),  # geen 4xxx-kostenrekening
            ("4599", "Lunchkosten (oud)", 2, None, datetime(2026, 1, 5, tzinfo=UTC)),  # verdwenen uit de bron
        )
        for code, naam, soort, default, verdwenen in rijen:
            session.add(
                Grootboekrekening(
                    ledger_id=s.gb[code],
                    administratie_id=administratie_id,
                    code=code,
                    naam=naam,
                    soort=soort,
                    is_totaalrekening=False,
                    standaard_taxrate_id=default,
                    verdwenen_uit_bron_op=verdwenen,
                    btw_aftrek_uitgesloten=(kenmerk_4510 and code == "4510"),
                    btw_aftrek_uitgesloten_op=(
                        datetime(2026, 9, 1, tzinfo=UTC) if kenmerk_4510 and code == "4510" else None
                    ),
                )
            )
    return s


def _document(
    s: Stam,
    actor: uuid.UUID,
    *,
    factuurdatum: date,
    regels: list[tuple[str, str, str]],
    status: DocumentStatus = DocumentStatus.GEBOEKT,
    soort: str = DocumentSoort.INKOOPFACTUUR.value,
) -> uuid.UUID:
    doc_id = uuid.uuid4()
    with scoped_session(s.aid, actor_id=actor) as session:
        session.add(
            Document(
                id=doc_id,
                administratie_id=s.aid,
                bron=DocumentBron.UPLOAD,
                soort=soort,
                bestandsnaam=f"{doc_id.hex[:8]}.pdf",
                sha256_hash=doc_id.hex * 2,
                opslag_pad=f"test/{doc_id}.pdf",
                status=status,
            )
        )
        session.flush()
        session.add(Boekvoorstel(document_id=doc_id, factuurdatum=factuurdatum, referentie=f"F-{doc_id.hex[:6]}"))
        session.flush()
        for n, (code, netto, btw) in enumerate(regels, start=1):
            session.add(
                BoekvoorstelRegel(
                    document_id=doc_id,
                    volgnummer=n,
                    ledger_id=s.gb[code],
                    taxrate_id=s.nul,
                    netto_bedrag=Decimal(netto),
                    btw_bedrag=Decimal(btw),
                )
            )
    return doc_id


def _bankboeking(
    s: Stam, actor: uuid.UUID, *, code: str, netto: str, btw: str, geboekt_op: datetime, gestorneerd: bool = False
) -> None:
    with scoped_session(s.aid, actor_id=actor) as session:
        rij = BankBoeking(
            administratie_id=s.aid,
            payment_transaction_id=uuid.uuid4(),
            rlz_document_id=uuid.uuid4(),
            bron=BankBoekingBron.HANDMATIG.value,
            status=(BankBoekingStatus.GESTORNEERD if gestorneerd else BankBoekingStatus.GEBOEKT).value,
            geboekt_door=actor,
            geboekt_op=geboekt_op,
            **(
                {"gestorneerd_door": actor, "gestorneerd_op": geboekt_op, "storno_reden": "test"} if gestorneerd else {}
            ),
        )
        session.add(rij)
        session.flush()
        session.add(
            BankBoekingRegel(
                bank_boeking_id=rij.id,
                volgnummer=1,
                ledger_id=s.gb[code],
                taxrate_id=s.hoog,
                netto_bedrag=Decimal(netto),
                btw_bedrag=Decimal(btw),
            )
        )


def _audit(admin_engine: Engine, administratie_id: uuid.UUID) -> list[tuple[dict, dict, uuid.UUID]]:
    with admin_engine.connect() as conn:
        return [
            (r.oude_waarde, r.nieuwe_waarde, r.actor_id)
            for r in conn.execute(
                text(
                    "SELECT oude_waarde, nieuwe_waarde, actor_id FROM platform.audit_event WHERE record_id = :id "
                    "AND actie = 'btw_aftrek_uitgesloten_gewijzigd' ORDER BY tijdstip"
                ),
                {"id": administratie_id},
            )
        ]


def _kenmerk(administratie_id: uuid.UUID) -> dict[str, bool]:
    with scoped_session(administratie_id) as session:
        return {
            r.code: bool(r.btw_aftrek_uitgesloten)
            for r in session.query(Grootboekrekening).filter(Grootboekrekening.administratie_id == administratie_id)
        }


# ---- advies_voor (puur) ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("naam", "advies"),
    [
        ("Representatiekosten (beperkt aftrekbaar)", "zetten"),
        ("Relatiegeschenken (beperkt aftrekbaar)", "zetten"),
        ("Geschenken personeel", "zetten"),
        ("Horecakosten", "zetten"),
        ("Lunch en diner", "zetten"),
        ("Eten en drinken onderweg", "zetten"),
        ("Consumpties", "zetten"),
        ("Kantinekosten", "beoordelen"),
        ("Personeelsfeest", "beoordelen"),
        ("Bedrijfsuitje", "beoordelen"),
        ("Giften", "beoordelen"),
        ("Kosten promotie/sponsoring", "niet_zetten"),
        ("Sponsoring voetbalclub", "niet_zetten"),
        ("Kosten mobiele telefonie", "beoordelen"),  # terugval: geen categorie → mens
    ],
)
def test_advies_voor_is_puur_en_deterministisch(naam: str, advies: str) -> None:
    uitkomst, reden = bua_cli.advies_voor("4xxx", naam)
    assert uitkomst == advies
    assert reden and (uitkomst != "beoordelen" or "beoordeel" in reden.lower() or "conservatief" in reden.lower())
    assert bua_cli.advies_voor("4xxx", naam) == (uitkomst, reden)


def test_is_kandidaat_en_naamdelen() -> None:
    assert bua_cli.is_kandidaat(code="4510", naam="Representatiekosten", soort=2)
    assert bua_cli.is_kandidaat(code="4014", naam="KANTINEKOSTEN", soort=2)
    assert not bua_cli.is_kandidaat(code="4404", naam="Kosten mobiele telefonie", soort=2)
    assert not bua_cli.is_kandidaat(code="0100", naam="Kantine-inventaris", soort=3)
    assert not bua_cli.is_kandidaat(code="1510", naam="Representatie", soort=2)
    assert set(bua_cli.BUA_NAAMDELEN) >= set(btw_aftrek.VOORSTEL_NAAMDELEN) - {"personeelsvoorzien"}
    assert bua_cli.DEFAULT_CODES == ("4508", "4510")


# ---- bua-kandidaten (lees-only, twee administraties) -----------------------------------------------------------------


@pytest.fixture
def scenario(
    administratie_id: uuid.UUID, tweede_administratie: uuid.UUID, beheerder_id: uuid.UUID
) -> tuple[Stam, Stam]:
    a = _stam(administratie_id)
    b = _stam(tweede_administratie, kenmerk_4510=True)
    # A: 2026 geboekt op 4510 (twee regels, btw 0 = "btw in de kosten"), telt.
    _document(
        a, beheerder_id, factuurdatum=date(2026, 3, 2), regels=[("4510", "20.00", "0.00"), ("4510", "14.45", "0.00")]
    )
    # A: tellen NIET — 2025, te controleren, kassarapport, andere rekening.
    _document(a, beheerder_id, factuurdatum=date(2025, 12, 30), regels=[("4510", "999.00", "0.00")])
    _document(
        a,
        beheerder_id,
        factuurdatum=date(2026, 5, 1),
        regels=[("4510", "555.00", "0.00")],
        status=DocumentStatus.TE_CONTROLEREN,
    )
    _document(
        a,
        beheerder_id,
        factuurdatum=date(2026, 5, 1),
        regels=[("4508", "777.00", "0.00")],
        soort=DocumentSoort.KASSARAPPORT.value,
    )
    _document(a, beheerder_id, factuurdatum=date(2026, 5, 1), regels=[("4404", "10.00", "2.10")])
    # A: bank-direct 2026 op 4508 telt; gestorneerd en 2025 niet.
    _bankboeking(
        a, beheerder_id, code="4508", netto="50.00", btw="10.50", geboekt_op=datetime(2026, 4, 1, 10, tzinfo=UTC)
    )
    _bankboeking(
        a,
        beheerder_id,
        code="4508",
        netto="80.00",
        btw="16.80",
        geboekt_op=datetime(2026, 4, 2, 10, tzinfo=UTC),
        gestorneerd=True,
    )
    _bankboeking(
        a, beheerder_id, code="4508", netto="90.00", btw="18.90", geboekt_op=datetime(2025, 12, 31, 23, tzinfo=UTC)
    )
    # B: eigen module-boeking op 4508 — mag niet in A's rij terechtkomen.
    _document(b, beheerder_id, factuurdatum=date(2026, 6, 1), regels=[("4508", "100.00", "21.00")])
    return a, b


def _rijen(meting: bua_cli.Meting, aid: uuid.UUID) -> dict[str, bua_cli.KandidaatRij]:
    return {r.code: r for r in meting.rijen if r.administratie_id == str(aid)}


def test_kandidaten_per_administratie_in_eigen_scope_zonder_lek(scenario: tuple[Stam, Stam]) -> None:
    a, b = scenario
    meting = bua_cli.meet(administratie=None, jaar=2026)
    assert meting is not None and meting.fouten == []
    ra, rb = _rijen(meting, a.aid), _rijen(meting, b.aid)
    # Selectie: 4xxx, soort 2, naam met BUA-woord, niet verdwenen — 4404/0100/4599 vallen af.
    assert set(ra) == {"4510", "4508", "4014", "4503"} and set(rb) == set(ra)
    # Module 2026 op A-4510: precies de twee GEBOEKTE inkoopregels (34,45 / 0,00); 2025, te_controleren en
    # kassarapport niet.
    assert (ra["4510"].mod_n, ra["4510"].mod_netto, ra["4510"].mod_btw) == (2, "34.45", "0.00")
    assert (ra["4508"].mod_n, ra["4508"].mod_netto) == (0, "0.00"), "kassarapport-regel mag niet meetellen"
    # Bank 2026 op A-4508: alleen de GEBOEKTE boeking in het jaar.
    assert (ra["4508"].bank_n, ra["4508"].bank_netto, ra["4508"].bank_btw) == (1, "50.00", "10.50")
    # Geen lek: B's 100/21 staat alleen bij B.
    assert (rb["4508"].mod_n, rb["4508"].mod_netto, rb["4508"].mod_btw) == (1, "100.00", "21.00")
    assert ra["4508"].mod_n == 0 and rb["4510"].mod_n == 0
    # Stand + defaults + advies.
    assert ra["4510"].kenmerk is False and rb["4510"].kenmerk is True
    assert (ra["4510"].rlz_default, ra["4510"].rlz_default_pct) == ("NL, Nul", "0")
    assert ra["4508"].rlz_default is None and ra["4503"].rlz_default_pct == "0.21"
    assert ra["4510"].advies == "zetten" and ra["4014"].advies == "beoordelen" and ra["4503"].advies == "niet_zetten"
    # Samenvatting over beide administraties.
    samen = {s.code: s for s in bua_cli.samenvat(meting.rijen)}
    assert (samen["4510"].administraties, samen["4510"].kenmerk_aan, samen["4510"].rlz_default_nul_of_geen) == (2, 1, 2)
    assert (samen["4508"].mod_n, samen["4508"].mod_netto, samen["4508"].bank_n) == (1, Decimal("100.00"), 1)
    assert (samen["4503"].rlz_default_nul_of_geen, samen["4503"].advies) == (0, "niet_zetten")


def test_cli_bua_kandidaten_alle_vormen_uit_het_meetrecept(
    scenario: tuple[Stam, Stam], capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = scenario
    # Vorm 1 — de nameting-workflow: kantoorbreed mét --detail.
    assert cli.main(["bua-kandidaten", "--jaar", "2026", "--detail"]) == 0
    uit = capsys.readouterr().out
    assert "BUA-kandidaten — 2 administratie(s), boekjaar 2026" in uit
    assert "TOTAAL 8 kandidaat-rekening(en) in 2 van 2 administratie(s) · 1 mét kenmerk aan · advies zetten: 4" in uit
    assert "0 fout(en)" in uit and "RLZ-kant niet gemeten" in uit
    assert "DETAIL per administratie" in uit and "Tweede BV" in uit and "Scope-test" in uit
    assert "zetten — BUA: btw op representatie" in uit and "niet_zetten — zakelijke reclamekosten" in uit
    # Vorm 2 — één administratie op naamdeel, zonder detail.
    assert cli.main(["bua-kandidaten", "--administratie", "Tweede"]) == 0
    uit = capsys.readouterr().out
    assert "1 administratie(s)" in uit and "DETAIL" not in uit and "TOTAAL 4 kandidaat-rekening(en) in 1 van 1" in uit
    # Vorm 3 — JSON, op uuid.
    assert cli.main(["bua-kandidaten", "--administratie", str(a.aid), "--json-uit", "--detail"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["administraties"] == 1 and data["rlz_kant"] == "niet gemeten" and data["fouten"] == []
    per = {r["code"]: r for r in data["rijen"]}
    assert per["4510"]["mod_netto"] == "34.45" and per["4508"]["bank_netto"] == "50.00"
    assert {s["code"] for s in data["samenvatting"]} == {"4510", "4508", "4014", "4503"}
    # Onbekende administratie = exit 2, zichtbaar.
    assert cli.main(["bua-kandidaten", "--administratie", "bestaat-niet-xyz"]) == 2
    assert "onbekend" in capsys.readouterr().err


def test_kapotte_administratie_stopt_de_rest_niet(scenario: tuple[Stam, Stam], monkeypatch: pytest.MonkeyPatch) -> None:
    a, b = scenario
    echte = bua_cli.kandidaten_voor

    def kapot_voor_b(aid, naam, *, jaar):  # noqa: ANN001
        if aid == b.aid:
            raise RuntimeError("kapot")
        return echte(aid, naam, jaar=jaar)

    monkeypatch.setattr(bua_cli, "kandidaten_voor", kapot_voor_b)
    meting = bua_cli.meet(administratie=None, jaar=2026)
    assert meting is not None
    assert len(_rijen(meting, a.aid)) == 4 and _rijen(meting, b.aid) == {}
    assert meting.fouten == [f"Tweede BV ({b.aid}): RuntimeError: kapot"]


# ---- bua-kenmerk-zetten (schrijvend) --------------------------------------------------------------------------------


def test_kenmerk_zetten_dry_run_schrijft_niets(
    scenario: tuple[Stam, Stam], admin_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = scenario
    assert cli.main(["bua-kenmerk-zetten", "--alles", "--dry-run"]) == 0
    uit = capsys.readouterr().out
    assert "DRY-RUN — niets geschreven" in uit
    assert "zou zetten: 4508,4510" in uit  # A: beide uit
    assert "zou zetten: 4508 · al aan: 4510" in uit  # B: 4510 stond al aan
    assert "TOTAAL 3 rekening(en) in 2 administratie(s) zou zetten · 1 al aan (ongewijzigd)" in uit
    assert _kenmerk(a.aid)["4510"] is False and _kenmerk(a.aid)["4508"] is False and _kenmerk(b.aid)["4508"] is False
    assert _audit(admin_engine, a.aid) == [] and _audit(admin_engine, b.aid) == []


def test_kenmerk_zetten_echt_met_audit_en_idempotent(
    scenario: tuple[Stam, Stam], admin_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    a, b = scenario
    # Eén administratie op uuid (vorm uit het meetrecept naast --alles).
    assert cli.main(["bua-kenmerk-zetten", "--administratie", str(a.aid)]) == 0
    uit = capsys.readouterr().out
    assert "GESCHREVEN" in uit and "gezet: 4508,4510" in uit
    stand = _kenmerk(a.aid)
    assert stand["4508"] and stand["4510"] and not stand["4014"] and not stand["4503"] and not stand["4404"]
    assert _audit(admin_engine, a.aid) == [
        ({"codes": []}, {"codes": ["4508", "4510"], "bron": bua_cli.BRON_ZETTEN}, SYSTEEM_ACTOR_ID)
    ]
    assert _audit(admin_engine, b.aid) == [], "de andere administratie is niet geraakt"
    # Tweede run: 0 wijzigingen, geen nieuw audit-event.
    assert cli.main(["bua-kenmerk-zetten", "--administratie", str(a.aid)]) == 0
    uit = capsys.readouterr().out
    assert "gezet: — · al aan: 4508,4510" in uit and "TOTAAL 0 rekening(en) in 0 administratie(s) gezet" in uit
    assert len(_audit(admin_engine, a.aid)) == 1
    # Kantoorbreed: A ongewijzigd, B krijgt alleen 4508 erbij (4510 stond al aan) — oud→nieuw in de audit.
    assert cli.main(["bua-kenmerk-zetten", "--alles"]) == 0
    uit = capsys.readouterr().out
    assert "TOTAAL 1 rekening(en) in 1 administratie(s) gezet · 3 al aan (ongewijzigd)" in uit
    assert _audit(admin_engine, b.aid) == [
        ({"codes": ["4510"]}, {"codes": ["4508", "4510"], "bron": bua_cli.BRON_ZETTEN}, SYSTEEM_ACTOR_ID)
    ]
    assert len(_audit(admin_engine, a.aid)) == 1
    # De meting laat de nieuwe stand zien (meetrecept ná de zetting).
    meting = bua_cli.meet(administratie=None, jaar=2026)
    assert meting is not None and sum(1 for r in meting.rijen if r.kenmerk) == 4


def test_kenmerk_zetten_eigen_codes_en_niet_gevonden(
    scenario: tuple[Stam, Stam], capsys: pytest.CaptureFixture[str]
) -> None:
    a, _ = scenario
    assert cli.main(["bua-kenmerk-zetten", "--administratie", str(a.aid), "--codes", "4014,4999"]) == 0
    uit = capsys.readouterr().out
    assert "gezet: 4014 · al aan: — · niet gevonden: 4999" in uit
    assert _kenmerk(a.aid)["4014"] is True and _kenmerk(a.aid)["4510"] is False
    # 4599 is verdwenen uit de bron: niet gevonden, nooit gezet.
    assert cli.main(["bua-kenmerk-zetten", "--administratie", str(a.aid), "--codes", "4599"]) == 0
    assert "niet gevonden: 4599" in capsys.readouterr().out and _kenmerk(a.aid)["4599"] is False


def test_kenmerk_zetten_ongeldige_argumenten_exit_2(
    scenario: tuple[Stam, Stam], capsys: pytest.CaptureFixture[str]
) -> None:
    a, _ = scenario
    assert cli.main(["bua-kenmerk-zetten", "--administratie", str(a.aid), "--codes", "abc"]) == 2
    assert "--codes" in capsys.readouterr().err
    assert cli.main(["bua-kenmerk-zetten", "--administratie", "bestaat-niet-xyz", "--dry-run"]) == 2
    assert "onbekend" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:  # --administratie óf --alles is verplicht (argparse)
        cli.main(["bua-kenmerk-zetten", "--dry-run"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:  # niet beide
        cli.main(["bua-kenmerk-zetten", "--alles", "--administratie", str(a.aid)])
    assert exc.value.code == 2


def test_kapotte_administratie_bij_zetten_stopt_de_rest_niet(
    scenario: tuple[Stam, Stam], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = scenario
    echte = bua_cli.zet_voor

    def kapot_voor_a(aid, naam, *, codes, dry_run):  # noqa: ANN001
        if aid == a.aid:
            raise RuntimeError("kapot")
        return echte(aid, naam, codes=codes, dry_run=dry_run)

    monkeypatch.setattr(bua_cli, "zet_voor", kapot_voor_a)
    assert cli.main(["bua-kenmerk-zetten", "--alles"]) == 0
    uit = capsys.readouterr().out
    assert "FOUT  Scope-test" in uit and "RuntimeError: kapot" in uit and "1 fout(en)" in uit
    assert _kenmerk(b.aid)["4508"] is True and _kenmerk(a.aid)["4508"] is False


# ---- btw_aftrek.voeg_toe --------------------------------------------------------------------------------------------


def test_voeg_toe_laat_bestaande_aan_staan_en_zet_is_de_exacte_set(
    scenario: tuple[Stam, Stam], beheerder_id: uuid.UUID, admin_engine: Engine
) -> None:
    a, _ = scenario
    btw_aftrek.zet(actor_id=beheerder_id, administratie_id=a.aid, ledger_ids=[a.gb["4404"]])
    uit = btw_aftrek.voeg_toe(actor_id=beheerder_id, administratie_id=a.aid, ledger_ids=[a.gb["4510"], a.gb["4404"]])
    assert (uit.toegevoegd, uit.al_aan) == (["4510"], ["4404"])
    assert {r.code for r in uit.stand.rekeningen if r.uitgesloten} == {"4404", "4510"}
    # Nog eens: niets nieuw, geen audit; zonder `bron` geen bron-sleutel.
    uit2 = btw_aftrek.voeg_toe(actor_id=beheerder_id, administratie_id=a.aid, ledger_ids=[a.gb["4510"]])
    assert (uit2.toegevoegd, uit2.al_aan) == ([], ["4510"])
    assert [(o, n) for o, n, _ in _audit(admin_engine, a.aid)] == [
        ({"codes": []}, {"codes": ["4404"]}),
        ({"codes": ["4404"]}, {"codes": ["4404", "4510"]}),
    ]
    with pytest.raises(btw_aftrek.BtwAftrekOnbekendeRekening):
        btw_aftrek.voeg_toe(actor_id=beheerder_id, administratie_id=a.aid, ledger_ids=[uuid.uuid4()])
    with pytest.raises(btw_aftrek.BtwAftrekOnbekendeRekening):  # verdwenen rekening telt als onbekend
        btw_aftrek.voeg_toe(actor_id=beheerder_id, administratie_id=a.aid, ledger_ids=[a.gb["4599"]])
