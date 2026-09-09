# ruff: noqa: F811 — pytest-fixtures als parameters
"""Actiemail + systeemmail (bundel 09-09 blok 1, feedback Peter "hier doe ik niks mee, veel te veel input").

Guard op de TEKSTKWALITEIT van de actiemail (patroon van de WAT_IS_NIEUW-guard, changelog.test.ts): voor een
representatieve fixture-set — élke bevinding-soort uit teksten.py, alle blokken, > 10 bevindingen — mag de mail
geen GUID, vingerafdruk, run-id, blok-sleutel, teller-woord of jargon dragen; élke regel ≤ 140 tekens; er staan
Nederlandse werkwoorden in. Plus de kanaal-logica: geen bevindingen = geen actiemail; systeemmail volgt de
drempel (delta óf exit ≠ 0); twee kanalen onafhankelijk bij een mailfout; een regressie-LET-OP → audit
`automatisering_regressie`, niet in de actiemail, tekst "systeemfout — automatisch gemeld"; bewakingsprobe."""

from __future__ import annotations

import argparse
import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.berichten import mail
from app.bewaking import service as bewaking
from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.reconciliatie import automatiseringen as auto
from app.reconciliatie import run as run_service
from app.reconciliatie import teksten
from app.reconciliatie.models import ReconciliatieRun
from app.reconciliatie.run import (
    Bevinding,
    Delta,
    actie_bevindingen,
    actie_regel,
    bouw_actiemail,
    mail_status_samenstellen,
    mail_statussen,
)
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

ARGS = argparse.Namespace()
AID_A = uuid.UUID("aaaaaaaa-0000-0000-0000-00000000000a")
AID_B = uuid.UUID("bbbbbbbb-0000-0000-0000-00000000000b")
DOC = "cccccccc-1111-2222-3333-444444444444"
NAMEN = {AID_A: "Universal Steigerbouw B.V.", AID_B: "Kempen Facilities B.V."}


def _b(blok: str, soort: str, aid: uuid.UUID | None, vaf: str, tekst: str, **detail) -> Bevinding:
    return Bevinding(blok=blok, soort=soort, administratie_id=aid, vingerafdruk=vaf, tekst=tekst, detail=detail or None)


def _afw(blok: str, afwijking_soort: str, aid: uuid.UUID, vaf: str, detail_tekst: str = "x", **namen) -> Bevinding:
    return _b(
        blok,
        "afwijking",
        aid,
        vaf,
        f"AFWIJKING  document={DOC} rlz_document={DOC} soort={afwijking_soort} [vaf:{vaf}]: {detail_tekst}",
        bron=blok,
        record_id=DOC,
        afwijking_soort=afwijking_soort,
        detail=detail_tekst,
        **namen,
    )


def _auto_let_op(reden: str, aid: uuid.UUID | None, sleutel: str = auto.AUTOBOEK_INKOOP, aantal: int = 3) -> Bevinding:
    return _b(
        auto.BLOK,
        "let_op",
        aid,
        auto.vingerafdruk_automatisering(sleutel=sleutel, categorie=reden, administratie_id=aid),
        f"LET-OP     automatisering {sleutel}: {aantal} overgeslagen wegens ontbrekende harde voorwaarde [{reden}]",
        automatisering=sleutel,
        automatisering_label=auto.LABEL[sleutel],
        reden=reden,
        aantal=aantal,
        voorbeeld=f"reden (administratie {aid})" if aid else None,
        administratie_naam=NAMEN.get(aid) if aid else None,
        doel_pad="/instellingen",
    )


def _fixture_set() -> Delta:
    """Élke soort uit teksten.py over álle blokken (+ opruim-kandidaat, opruimlijst-fout, administratie-fout,
    kantoor-instelbare automatisering-LET-OP's): ruim boven de tien regels."""
    afwijkingen = [
        _afw("documenten", "ontbreekt_in_rlz", AID_A, "d1", "404", leverancier_naam="Labo Derva", factuurnummer="2026-118",
             bedrag_lokaal="274.89", boekdatum="2026-08-03"),
        _afw("documenten", "ontbreekt_in_odoo", AID_A, "d2", "404", leverancier_naam="BOOT", factuurnummer="202633199", backend="odoo"),
        _afw("documenten", "bedrag_wijkt_af", AID_B, "d3", "eigen=€274.89 rlz=€279.51", leverancier_naam="Kader Consultancy",
             factuurnummer="F212604921", rlz_boekstuk="RLZ-01-00000241", bedrag_lokaal="274.89", bedrag_extern="279.51"),
        _afw("documenten", "status_wijkt_af", AID_B, "d4", "RLZ-status=1", leverancier_naam="Spot Services", factuurnummer="2026-608"),
        _afw("documenten", "status_niet_definitief", AID_B, "d4b", "status 1", leverancier_naam="DCTE", factuurnummer="202611050"),
        _afw("documenten", "boekstuknummer_wijkt_af", AID_A, "d5", "eigen=RLZ-01-1 rlz=RLZ-01-2", leverancier_naam="BDO", factuurnummer="6088744"),
        _afw("documenten", "controle_mislukt", AID_A, "d6", "HTTP 500", leverancier_naam="Floor", factuurnummer="26219"),
        _afw("documenten", "controle_mislukt", AID_A, "d6b", "geen bewaarde RLZ-credential", leverancier_naam="Floor", factuurnummer="26008", rlz_verleden=True),
        _afw("documenten", "niet_geboekt_in_odoo", AID_A, "d7", "draft", leverancier_naam="Universal Nederland", factuurnummer="RLZ-2080143037", backend="odoo", extern_state="draft"),
        _afw("documenten", "teruggedraaid_in_odoo", AID_A, "d8", "reversal", leverancier_naam="Universal Nederland", factuurnummer="RLZ-2080143038", backend="odoo"),
        _afw("documenten", "onbekende_soort_xyz", AID_A, "d9", f"iets met {DOC}"),
        _afw("bank", "document_ontbreekt_in_rlz", AID_A, "b1", "404", tegenpartij_naam="Bouwmaat", mutatie_bedrag="-1234.5", mutatie_datum="2026-09-01", rekening_naam="ING zakelijk"),
        _afw("bank", "boeking_teruggedraaid_in_rlz", AID_A, "b2", "Status=1", tegenpartij_naam="Bouwmaat", mutatie_bedrag="-12.5", mutatie_datum="2026-09-02"),
        _afw("bank", "mutatie_ontbreekt_in_rlz", AID_A, "b3", "404", tegenpartij_naam="Gamma", mutatie_bedrag="-99.99", mutatie_datum="2026-09-03"),
        _afw("bank", "aflettering_teruggedraaid_in_rlz", AID_A, "b4", "OpenAmount=50.00", tegenpartij_naam="Gamma", mutatie_bedrag="-50", mutatie_datum="2026-09-04", referentie="F-1"),
        _afw("bank", "controle_mislukt", AID_A, "b5", "HTTP 503", tegenpartij_naam="Praxis"),
        _afw("omzet", "half_geboekt", AID_B, "o1", "Periode 2026-08-01 t/m 2026-08-31: verkoopfactuur staat geboekt zonder kostprijsmemoriaal", periode_start="2026-08-01", periode_eind="2026-08-31", totaal_omzet="15230.10"),
        _afw("omzet", "ontbreekt_in_rlz", AID_B, "o2", "kostprijsmemoriaal 404", periode_start="2026-07-01", periode_eind="2026-07-31"),
        _afw("omzet", "status_niet_definitief", AID_B, "o3", "verkoopfactuur Status=1", periode_start="2026-06-01", periode_eind="2026-06-30"),
        _afw("omzet", "controle_mislukt", AID_B, "o4", "HTTP 500"),
        _afw("doorbelasting", "half_geboekt", AID_A, "x1", "spiegel ontbreekt sinds 2026-08-20", doelentiteit_naam="Kempen Facilities B.V.", bedrag_lokaal="1000", leverancier_naam="Universal Nederland", factuurnummer="RLZ-2080143039"),
        _afw("doorbelasting", "ontbreekt_in_rlz", AID_A, "x2", "verkoop 404", doelentiteit_naam="Kempen Facilities B.V.", verkoop_referentie="24713188"),
        _afw("doorbelasting", "status_niet_definitief", AID_A, "x3", "spiegel Status=1", doelentiteit_naam="Kempen Facilities B.V."),
        _afw("doorbelasting", "spiegel_open_verouderd", AID_A, "x4", "al 40 dagen open", doelentiteit_naam="A.Y. Holding 2 B.V."),
        _afw("doorbelasting", "controle_mislukt", AID_A, "x5", "geen credentials", doelentiteit_naam="Abbegaa BV"),
        _afw("rlz_dubbel", "dubbel_in_rlz", AID_B, "r1", "paar", leverancier_naam="Kader Consultancy", referentie_a="F1", referentie_b="F1",
             boekstuk_a="RLZ-04-00004037", boekstuk_b="RLZ-04-00004099", datum_a="2026-06-22", bedrag_a="1234.56", status_a="1", van_module_a=True, regel="referentie", concept=True),
    ]
    let_op = [
        _b("doorbelasting", "let_op", AID_A, "l1", f"LET-OP     opruim-kandidaat [gestorneerd] verkoop_bron {DOC} in administratie {AID_A}",
           kant="verkoop_bron", reden="gestorneerd", referentie="24713188", leverancier_naam="Universal Nederland", factuurnummer="RLZ-2080143037"),
        _b("doorbelasting", "let_op", AID_B, "l2", f"LET-OP     opruimlijst: administratie {AID_B}: HTTP 500", reden="opruimlijst_fout"),
        _b("documenten", "let_op", AID_B, "l3", f"LET-OP     iets onbekends bij {DOC}"),
        _auto_let_op(auto.CREDENTIAL, AID_A, auto.BANK_SYNC),
        _auto_let_op(auto.API_KEY, None, auto.EXTRACTIE_WACHTRIJ),
        _auto_let_op(auto.GELDPOORT, AID_B),
        _auto_let_op(auto.NOODREM, None, auto.DUPLICAAT_AFVOER),
        _auto_let_op(auto.VOLUMEREM, AID_A, auto.BANK),
        # beheer- en regressie-signalen: NIET in de actiemail
        _auto_let_op(auto.GEEN_EIGENAAR, AID_A, auto.DUPLICAAT_AFVOER, aantal=155),
        _auto_let_op(auto.VANGNET_SCHEDULER, None, auto.EXTRACTIE_WACHTRIJ),
        _auto_let_op(auto.GEEN_SYNC_RUN, None, auto.BANK_SYNC),
        _b(auto.BLOK, "let_op", None, "stil", "LET-OP     automatisering terugkerend: 7 dagen 0 gedaan", automatisering=auto.TERUGKEREND,
           automatisering_label=auto.LABEL[auto.TERUGKEREND], reden=auto.STIL_7_DAGEN, aantal=9, stand="altijd"),
    ]
    fouten = [
        _b("documenten", "fout", AID_A, "f1", f"FOUT       {AID_A}: 401 Unauthorized", fout="401 Unauthorized"),
        _b("documenten", "fout", AID_B, "f2", f"FOUT       storno-detectie {AID_B}: timeout"),
        _b("bank", "fout", None, "f3", "FOUT       bank-reconciliatie viel om: RLZ onbereikbaar"),
        _b(auto.BLOK, "fout", None, "f4", "FOUT       tellers per automatisering niet bepaald: boem"),
    ]
    return Delta(
        nieuwe_afwijkingen=afwijkingen,
        nieuwe_let_op=let_op,
        nieuwe_fouten=fouten,
        nieuwe_geaccepteerd=[_afw("documenten", "ontbreekt_in_rlz", AID_A, "g1", "404", leverancier_naam="Oud BV")],
        verdwenen_afwijkingen=[_afw("documenten", "bedrag_wijkt_af", AID_A, "h1", "eigen=€1 rlz=€2", leverancier_naam="Hersteld BV")],
        blokken_fout=["bank"],
    )


GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
#: Kale blok-sleutels (de mail zegt "bankmutatie", nooit "bank" als sleutel) en teller-/jargonwoorden.
BLOK_SLEUTELS = ("documenten", "bank", "omzet", "doorbelasting", "automatisering", "rlz_dubbel")
TELLER_WOORDEN = ("verwacht", "gedaan", "overgeslagen", "exit")
JARGON = ("vingerafdruk", "delta", "bevinding-id", "json", "http", "4xx", "5xx", "vaf:", "run-id", "run_id", "let-op", "regressie")
WERKWOORDEN = ("vraagt", "vragen", "bekijken", "afhandelen", "liep", "verdwenen", "afwijkt", "teruggezet", "mislukt", "wacht")


class TestActiemailGuard:
    def _mail(self) -> tuple[str, str, list[Bevinding]]:
        delta = _fixture_set()
        bev = actie_bevindingen(delta)
        uit = bouw_actiemail(bevindingen=bev, namen=NAMEN, alles_gelopen=not delta.blokken_fout)
        assert uit is not None
        return uit[0], uit[1], bev

    def test_fixture_set_is_representatief(self) -> None:
        _, _, bev = self._mail()
        assert len(bev) > run_service.MAX_ACTIE_REGELS
        assert {b.blok for b in bev} >= {"documenten", "bank", "omzet", "doorbelasting", "rlz_dubbel", auto.BLOK}
        assert {b.soort for b in bev} == {"afwijking", "let_op", "fout"}

    def test_geen_guid_vaf_runid_bloksleutel_tellerwoord_of_jargon(self) -> None:
        onderwerp, tekst, _ = self._mail()
        alles = onderwerp + "\n" + tekst
        assert not GUID.search(alles), alles
        # De ene link naar /reconciliatie is de enige toegestane URL; de rest van de mail is jargonvrij.
        linkregels = [r for r in tekst.splitlines() if "/reconciliatie" in r]
        assert len(linkregels) == 1 and linkregels[0].startswith("Bekijken en afhandelen: http")
        laag = "\n".join(r for r in alles.splitlines() if r not in linkregels).lower()
        for woord in (*TELLER_WOORDEN, *JARGON):
            assert not re.search(rf"(?<![a-z]){re.escape(woord)}(?![a-z])", laag), f"jargon/teller-woord '{woord}' in:\n{alles}"
        # Blok-sleutels mogen alleen als gewoon woord in een zin voorkomen ("in de bank" mag niet — de titels zeggen
        # "Bankboeking"/"Bankmutatie"); toets op de kale sleutel als apart token.
        for sleutel in BLOK_SLEUTELS:
            assert not re.search(rf"(?<![a-z]){sleutel}(?![a-z])", laag), f"kale blok-sleutel '{sleutel}' in:\n{alles}"
        # Geen systeemmail-onderdelen.
        for verboden in ("Per blok", "Automatiseringen", "geaccepteerd", "Hersteld", "technisch", "Run-id", "niet gedraaid"):
            assert verboden.lower() not in laag, verboden

    def test_regels_kort_leesbaar_en_met_werkwoorden(self) -> None:
        onderwerp, tekst, bev = self._mail()
        regels = tekst.splitlines()
        assert all(len(r) <= run_service.MAX_ACTIE_REGEL for r in regels), [r for r in regels if len(r) > 140]
        assert len(onderwerp) <= 80
        laag = (onderwerp + " " + tekst).lower()
        assert sum(w in laag for w in WERKWOORDEN) >= 3, laag
        # Kopregel + hooguit tien bevindingsregels + "en N andere" + één link + slotregel.
        n = len(bev)
        assert regels[0] == f"{n} zaken vragen je aandacht."
        assert onderwerp == f"Boekhouding: {n} zaken vragen je aandacht"
        bevindingsregels = [r for r in regels if r.startswith("- ") and not r.startswith("- en ")]
        assert len(bevindingsregels) == run_service.MAX_ACTIE_REGELS
        assert f"- en {n - run_service.MAX_ACTIE_REGELS} andere" in regels
        assert sum("/reconciliatie" in r for r in regels) == 1 and any(r.startswith("Bekijken en afhandelen: ") for r in regels)
        # Een omgevallen blok → eerlijke slotregel i.p.v. "Verder liep alles."
        assert "Verder liep alles." not in tekst and "niet gelopen" in tekst
        # Vorm van een regel: administratie vooraan, de afwijking achteraan, de leverancier ertussen.
        assert "- Kempen Facilities B.V. — Kader Consultancy F212604921 — Bedrag afwijkt in RLZ" in regels

    def test_elke_actie_bevinding_geeft_een_schone_regel(self) -> None:
        """Ook buiten de top-10: élke bevinding-soort uit de set levert een regel zonder technische sleutel."""
        _, _, bev = self._mail()
        for b in bev:
            regel = actie_regel(b, NAMEN.get(b.administratie_id) if b.administratie_id else None)
            assert regel and len(regel) <= run_service.MAX_ACTIE_REGEL and not GUID.search(regel), regel
            assert not teksten.bevat_technische_sleutel(regel), regel
            assert "vaf:" not in regel and "[" not in regel

    def test_slotregel_verder_liep_alles_zonder_omgevallen_blok(self) -> None:
        uit = bouw_actiemail(bevindingen=[_afw("documenten", "bedrag_wijkt_af", AID_A, "z", leverancier_naam="X")], namen=NAMEN)
        assert uit is not None
        assert uit[0] == "Boekhouding: 1 zaak vraagt je aandacht" and "Verder liep alles." in uit[1]
        assert "- en " not in uit[1]

    def test_regressie_en_beheer_signalen_niet_in_de_actiemail(self) -> None:
        delta = _fixture_set()
        bev = actie_bevindingen(delta)
        redenen = {(b.detail or {}).get("reden") for b in bev if b.blok == auto.BLOK}
        assert redenen == {auto.CREDENTIAL, auto.API_KEY, auto.GELDPOORT, auto.NOODREM, auto.VOLUMEREM}
        assert not any(b.soort == "fout" and b.administratie_id is None for b in bev)  # blokcrash/tellers-fout = beheer
        assert not any(b.soort == "geaccepteerd" for b in bev)
        _, tekst, _ = self._mail()
        assert "geen eigenaar" not in tekst.lower() and "Cloud" not in tekst and "stil" not in tekst.lower()

    def test_geen_bevindingen_geen_actiemail(self) -> None:
        assert bouw_actiemail(bevindingen=[], namen=NAMEN) is None
        alleen_beheer = Delta(
            nieuwe_geaccepteerd=[_afw("documenten", "ontbreekt_in_rlz", AID_A, "g", leverancier_naam="X")],
            verdwenen_afwijkingen=[_afw("documenten", "bedrag_wijkt_af", AID_A, "h", leverancier_naam="Y")],
            nieuwe_fouten=[_b("bank", "fout", None, "f", "FOUT       bank-reconciliatie viel om: boem")],
            nieuwe_let_op=[_auto_let_op(auto.GEEN_EIGENAAR, AID_A, auto.DUPLICAAT_AFVOER)],
            blokken_fout=["bank"],
        )
        assert not alleen_beheer.is_leeg and actie_bevindingen(alleen_beheer) == []

    def test_regressie_tekst_in_systeemmail_en_ui_is_systeemfout_automatisch_gemeld(self) -> None:
        lees = teksten.leesbaar(_auto_let_op(auto.GEEN_EIGENAAR, AID_A, auto.DUPLICAAT_AFVOER, aantal=155), administratie_naam=NAMEN[AID_A])
        assert lees.doe == "Systeemfout — automatisch gemeld."
        assert "meld de regressie" not in (lees.titel + lees.wat + lees.doe).lower()
        # De systeemmail draagt dezelfde tekst (één bron met de UI) en géén "meld de regressie".
        _, tekst = run_service.bouw_mail(
            run_id=uuid.uuid4(), bron="scheduler", afgerond_op=datetime(2026, 9, 9, 4, 31, tzinfo=UTC), exit_code=0,
            samenvatting={}, delta=Delta(nieuwe_let_op=[_auto_let_op(auto.GEEN_EIGENAAR, AID_A, auto.DUPLICAAT_AFVOER)]),
            open_afwijkingen=0, namen=NAMEN,
        )
        assert "→ Systeemfout — automatisch gemeld." in tekst and "meld de regressie" not in tekst.lower()


class TestMailStatusSamengesteld:
    def test_heen_en_terug_en_legacy(self) -> None:
        assert mail_status_samenstellen({"actie": "verzonden", "systeem": "niet_nodig"}) == "actie=verzonden;systeem=niet_nodig"
        assert mail_statussen("actie=verzonden;systeem=mislukt") == {"actie": "verzonden", "systeem": "mislukt"}
        assert mail_statussen("mislukt") == {"actie": "mislukt"}  # run van vóór 09-09
        assert mail_statussen(None) == {} and mail_statussen("") == {}
        assert mail_status_samenstellen({}) == "actie=niet_nodig;systeem=niet_nodig"


# ---- kanaal-logica end-to-end (DB) --------------------------------------------------------------------------


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    verzonden: list[dict] = []

    def nep(*, naar: str, onderwerp: str, tekst: str, bijlagen=None) -> None:  # noqa: ANN001
        verzonden.append({"naar": naar, "onderwerp": onderwerp, "tekst": tekst})

    monkeypatch.setattr(mail, "verzend_mail", nep)
    return verzonden


def _blok(bevindingen: list[dict], *, exit_code: int = 0):
    def functie(args, verzamelaar=None) -> int:  # noqa: ANN001
        if verzamelaar is not None:
            verzamelaar.gecontroleerd(1)
            for kw in bevindingen:
                verzamelaar.bevinding(**kw)
        return exit_code

    return functie


def _laatste_run() -> ReconciliatieRun:
    with scoped_session(None) as session:
        rij = session.scalars(select(ReconciliatieRun).order_by(ReconciliatieRun.aangevraagd_op.desc()).limit(1)).one()
        session.expunge(rij)
        return rij


def _afwijking_kw(aid: uuid.UUID, vaf: str) -> dict:
    return {
        "soort": "afwijking",
        "administratie_id": aid,
        "vingerafdruk": vaf,
        "tekst": f"AFWIJKING  document={DOC} soort=bedrag_wijkt_af [vaf:{vaf}]: eigen=€1 rlz=€2",
        "detail": {"bron": "documenten", "afwijking_soort": "bedrag_wijkt_af", "detail": "eigen=€1 rlz=€2",
                   "leverancier_naam": "Kader Consultancy", "factuurnummer": "F212604921"},
    }


def _regressie_kw(aid: uuid.UUID) -> dict:
    b = _auto_let_op(auto.GEEN_EIGENAAR, aid, auto.DUPLICAAT_AFVOER, aantal=6)
    return {"soort": "let_op", "administratie_id": aid, "vingerafdruk": b.vingerafdruk, "tekst": b.tekst,
            "detail": b.detail, "blok": auto.BLOK}


class TestTweeKanalen:
    def test_systeemmail_gaat_bij_exit_1_ook_zonder_delta(self, administratie_id, mails) -> None:
        """Drempel systeemmail = delta óf exit ≠ 0. Twee identieke runs met een blijvende afwijking: run 2 heeft een
        lege delta maar exit 1 → wél een systeemmail, géén actiemail (niets nieuws voor het kantoor)."""
        blokken = [("documenten", _blok([_afwijking_kw(administratie_id, "blijft")], exit_code=1))]
        run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None)
        assert [m["onderwerp"].startswith("[systeem]") for m in mails] == [False, True]
        run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None)
        assert len(mails) == 3 and mails[2]["onderwerp"].startswith("[systeem]")
        assert mails[2]["naar"] == run_service.settings.reconciliatie_beheer_ontvangers
        assert _laatste_run().mail_status == "actie=niet_nodig;systeem=verzonden"

    def test_geen_delta_en_exit_0_geen_enkele_mail(self, administratie_id, mails) -> None:
        blokken = [("documenten", _blok([]))]
        run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None)
        run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None)
        assert mails == []
        assert _laatste_run().mail_status == "actie=niet_nodig;systeem=niet_nodig"

    def test_beheer_ontvangers_leeg_is_niet_geconfigureerd_geen_storing(self, administratie_id, mails, monkeypatch) -> None:
        monkeypatch.setattr(run_service.settings, "reconciliatie_beheer_ontvangers", "")
        blokken = [("documenten", _blok([_afwijking_kw(administratie_id, "n1")], exit_code=1))]
        run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None)
        assert len(mails) == 1 and mails[0]["onderwerp"].startswith("Boekhouding: ")
        rij = _laatste_run()
        assert rij.mail_status == "actie=verzonden;systeem=niet_geconfigureerd"
        assert "systeem: geen RECONCILIATIE_BEHEER_ONTVANGERS" in (rij.mail_detail or "")
        assert bewaking._probe_reconciliatie_mail().status == "ok"

    def test_meerdere_beheer_ontvangers_komma_gescheiden(self, administratie_id, mails, monkeypatch) -> None:
        monkeypatch.setattr(run_service.settings, "reconciliatie_beheer_ontvangers", "a@x.nl, b@x.nl")
        blokken = [("documenten", _blok([_afwijking_kw(administratie_id, "n2")], exit_code=1))]
        run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None)
        assert mails[1]["naar"] == "a@x.nl, b@x.nl"

    def test_mailfout_op_een_kanaal_laat_het_andere_door_en_is_per_kanaal_geauditeerd(
        self, administratie_id, monkeypatch
    ) -> None:
        verzonden: list[str] = []

        def half_kapot(*, naar: str, onderwerp: str, tekst: str, bijlagen=None) -> None:  # noqa: ANN001
            if onderwerp.startswith("[systeem]"):
                raise mail.MailVerzendFout("SMTP 535 (test, systeemkanaal)")
            verzonden.append(onderwerp)

        monkeypatch.setattr(mail, "verzend_mail", half_kapot)
        blokken = [("documenten", _blok([_afwijking_kw(administratie_id, "n3")], exit_code=1))]
        assert run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None) == 1
        rij = _laatste_run()
        assert rij.status == "klaar" and rij.mail_status == "actie=verzonden;systeem=mislukt"
        assert rij.mail_verzonden_op is not None and "systeem: " in rij.mail_detail and "535" in rij.mail_detail
        assert verzonden == ["Boekhouding: 1 zaak vraagt je aandacht"]
        with scoped_session(None) as session:
            audit = session.scalars(
                select(AuditEvent).where(AuditEvent.actie == "reconciliatie_mail_mislukt", AuditEvent.record_id == rij.id)
            ).all()
        assert [a.nieuwe_waarde["kanaal"] for a in audit] == ["systeem"]
        # De bewaking herkent een storing op het systeemkanaal.
        uitkomst = bewaking._probe_reconciliatie_mail()
        assert uitkomst.status == "fout" and "systeem" in uitkomst.detail and str(rij.id) in uitkomst.detail

    def test_actiemail_aan_kantoor_systeemmail_aan_beheer(self, administratie_id, mails) -> None:
        blokken = [("documenten", _blok([_afwijking_kw(administratie_id, "n4")], exit_code=1))]
        run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None)
        actie, systeem = mails
        assert actie["naar"] == run_service.settings.bewaking_alert_ontvanger
        assert systeem["naar"] == run_service.settings.reconciliatie_beheer_ontvangers
        assert "Kader Consultancy F212604921 — Bedrag afwijkt in RLZ" in actie["tekst"]
        assert "Per blok:" in systeem["tekst"] and "Run-id:" in systeem["tekst"] and "Per blok:" not in actie["tekst"]


class TestRegressie:
    def test_regressie_let_op_geeft_audit_niet_in_actiemail_en_bewaking_alarmeert(self, administratie_id, mails) -> None:
        blokken = [("documenten", _blok([_regressie_kw(administratie_id)]))]
        assert run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None) == 0
        rij = _laatste_run()
        # Alleen de systeemmail (regressie = beheer-signaal), mét de tekst "systeemfout — automatisch gemeld".
        assert len(mails) == 1 and mails[0]["onderwerp"].startswith("[systeem]")
        assert "Systeemfout — automatisch gemeld." in mails[0]["tekst"] and "meld de regressie" not in mails[0]["tekst"].lower()
        assert rij.mail_status == "actie=niet_nodig;systeem=verzonden"
        with scoped_session(None) as session:
            audit = session.scalars(
                select(AuditEvent).where(AuditEvent.actie == "automatisering_regressie", AuditEvent.record_id == rij.id)
            ).all()
        assert len(audit) == 1
        nw = audit[0].nieuwe_waarde
        assert nw["automatisering"] == auto.DUPLICAAT_AFVOER and nw["categorie"] == auto.GEEN_EIGENAAR
        assert nw["aantal"] == 6 and nw["run_id"] == str(rij.id) and nw["vingerafdruk"]
        assert audit[0].administratie_id is None
        # Idempotent per run + vingerafdruk.
        bev = run_service.lees_bevindingen(rij.id, administratie_ids=[administratie_id])
        with scoped_session(None, actor_id=run_service.SYSTEEM_ACTOR_ID) as session:
            assert run_service._registreer_regressies(session, rij.id, bev) == 0
        # Bewakingsprobe: storing binnen 24 u, daarna weer ok.
        nu = datetime.now(UTC)
        uitkomst = bewaking._probe_automatisering_regressie(nu)
        assert uitkomst.status == "fout" and auto.DUPLICAAT_AFVOER in uitkomst.detail and auto.GEEN_EIGENAAR in uitkomst.detail
        assert bewaking._probe_automatisering_regressie(nu + timedelta(hours=25)).status == "ok"

    def test_zonder_regressie_geen_audit(self, administratie_id, mails) -> None:
        blokken = [("documenten", _blok([_afwijking_kw(administratie_id, "n5")], exit_code=1))]
        run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None)
        rij = _laatste_run()
        with scoped_session(None) as session:
            n = session.scalars(
                select(AuditEvent).where(AuditEvent.actie == "automatisering_regressie", AuditEvent.record_id == rij.id)
            ).all()
        assert n == []
