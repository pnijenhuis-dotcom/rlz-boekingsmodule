# ruff: noqa: F811 — pytest-fixtures als parameters
"""Run D 02-10 blok A — btw-verschil < € 0,10 nooit blokkeren (besluit Peter 29-09, casus Lusso 260987: factuur-btw
913,27 op netto 4.349,18, 21 % geeft 913,33; "de btw vermeld op factuur is altijd leidend … dan moet er geen blokkade
komen" en "onder de € 0,10 lekker boeken … wel dan altijd in ons voordeel").

1. Check "Btw-bedrag past bij tarief": |Σ factuur-btw − Σ tarief-btw| per document < 0,10 = groen zonder melding,
   ≥ 0,10 = oranje mét de twee bestaande acties, rood uitsluitend als netto + btw niet op het factuurtotaal sluit.
2. Autoboek-pad: groen = doorlopen (Lusso boekt automatisch), oranje = `AutoboekGeweigerdDoorSignaal` mét reden.
3. Reconciliatie: bedragverschil dat uitsluitend RLZ's btw-herrekening is (netto gelijk, |Δ btw| < 0,10) → RLZ boekt
   méér voorbelasting = automatisch geaccepteerd mét audit `btw_afronding_rlz`; RLZ boekt minder = soort
   `btw_rlz_lager_dan_factuur` in `meten` mét bedrag; zonder btw-gegevens (afwezig-pad) geldt alleen de 0,05-regel."""

from __future__ import annotations

import argparse
import uuid
from datetime import date
from decimal import Decimal
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine, select, text

from app import cli
from app.backends.port import Backend, ToetsUitkomst
from app.beheer import service as beheer_service
from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import boeken, boekvoorstel, reconciliatie, regelsom, service, volumerem
from app.documenten.checks import (
    ACTIE_BTW_IN_KOSTEN,
    ACTIE_ZET_TARIEF,
    NAAM_BTW_TARIEF,
    CheckRegel,
    TariefInfo,
    check_btw_past_bij_tarief,
)
from app.documenten.reconciliatie import ReconciliatieAfwijking, ReconciliatieRapport, _Geboekt
from app.documenten.storage import LokaleBestandsopslag
from app.reconciliatie import service as acceptatie_service
from app.reconciliatie import soort_stand, teksten
from app.reconciliatie.models import ReconciliatieAcceptatie
from app.reconciliatie.run import Verzamelaar
from app.sync.models import TaxRateCache
from tests.documenten.fake_rlz_client import FakeBoekClient

HOOG = uuid.UUID("55555555-0000-0000-0000-000000000021")
LAAG = uuid.UUID("55555555-0000-0000-0000-000000000009")
NUL = uuid.UUID("55555555-0000-0000-0000-000000000000")
TARIEVEN = {
    HOOG: TariefInfo(D("0.21"), "NL, Hoog Tarief", favoriet=True),
    LAAG: TariefInfo(D("0.09"), "NL, Laag Tarief"),
    NUL: TariefInfo(D("0"), "NL, Nul"),
}
#: Lusso 260987 (Kempen Facilities, 29-09): netto 4.349,18, factuur-btw 913,27; 21 % geeft 913,33 → verschil 0,06.
LUSSO_NETTO = D("4349.18")
LUSSO_BTW = D("913.27")
LUSSO_TOTAAL = D("5262.45")


def _regel(taxrate, netto, btw) -> CheckRegel:
    return CheckRegel(ledger_id=uuid.uuid4(), taxrate_id=taxrate, netto_bedrag=D(netto), btw_bedrag=D(btw))


class TestRegelsomDocumentGrens:
    def test_grens_is_tien_cent_strikt(self) -> None:
        assert D("0.10") == regelsom.BTW_DOCUMENT_TOLERANTIE
        assert regelsom.btw_past_bij_document(D("0.09")) and regelsom.btw_past_bij_document(D("-0.09"))
        assert not regelsom.btw_past_bij_document(D("0.10")) and not regelsom.btw_past_bij_document(D("-0.10"))

    def test_verschil_per_document_is_getekend_en_op_de_cent(self) -> None:
        assert regelsom.btw_verschil_document([LUSSO_BTW], [D("913.33")]) == D("-0.06")
        # +6 ct en −6 ct heffen elkaar op: het document als geheel sluit.
        assert regelsom.btw_verschil_document([D("21.06"), D("20.94")], [D("21.00"), D("21.00")]) == D("0.00")
        with pytest.raises(ValueError):
            regelsom.btw_verschil_document([D("1")], [])


class TestCheckDocumentGrens:
    def test_lusso_zes_cent_is_groen_zonder_actie(self) -> None:
        r = check_btw_past_bij_tarief(regels=[_regel(HOOG, LUSSO_NETTO, LUSSO_BTW)], tarieven=TARIEVEN)
        assert r.ok and not r.signaal and r.acties == ()
        assert "verschil € 0.06 per document" in r.melding and "factuur-btw leidend" in r.melding

    def test_negen_cent_groen_tien_cent_oranje_met_acties_nooit_rood(self) -> None:
        # 21 % op 100,00 = 21,00: 20,91 → Δ 0,09 groen; 20,90 → Δ 0,10 oranje (signaal, ok blijft True).
        groen = check_btw_past_bij_tarief(regels=[_regel(HOOG, "100.00", "20.91")], tarieven=TARIEVEN)
        assert groen.ok and not groen.signaal
        oranje = check_btw_past_bij_tarief(regels=[_regel(HOOG, "100.00", "20.90")], tarieven=TARIEVEN)
        assert oranje.ok and oranje.signaal
        assert "wijkt € 0.10 af van het tarief per document (grens € 0,10" in oranje.melding
        assert "boek met de factuur-btw (leidend)" in oranje.melding
        # De twee bestaande acties staan op de rij: 20,90 past bij geen tarief → alleen "btw in kosten".
        assert [a.code for a in oranje.acties] == [ACTIE_BTW_IN_KOSTEN]
        # Ook de andere kant: 21,10 → Δ 0,10 oranje.
        assert check_btw_past_bij_tarief(regels=[_regel(HOOG, "100.00", "21.10")], tarieven=TARIEVEN).signaal

    def test_rituals_0_procent_met_btw_is_oranje_met_twee_acties_zolang_het_totaal_sluit(self) -> None:
        r = check_btw_past_bij_tarief(regels=[_regel(NUL, "96.36", "20.24")], tarieven=TARIEVEN, totaal_sluit=True)
        assert r.ok and r.signaal
        assert [(a.code, a.taxrate_id) for a in r.acties] == [(ACTIE_BTW_IN_KOSTEN, NUL), (ACTIE_ZET_TARIEF, HOOG)]

    def test_rood_uitsluitend_als_het_factuurtotaal_niet_sluit(self) -> None:
        rood = check_btw_past_bij_tarief(regels=[_regel(NUL, "96.36", "20.24")], tarieven=TARIEVEN, totaal_sluit=False)
        assert rood.ok is False and "sluit niet op het factuurtotaal" in rood.melding
        assert [a.code for a in rood.acties] == [ACTIE_BTW_IN_KOSTEN, ACTIE_ZET_TARIEF]
        # Onder de grens is het totaal-argument irrelevant: nooit rood op zes cent.
        assert check_btw_past_bij_tarief(
            regels=[_regel(HOOG, LUSSO_NETTO, LUSSO_BTW)], tarieven=TARIEVEN, totaal_sluit=False
        ).ok

    def test_opheffende_regels_sluiten_per_document(self) -> None:
        regels = [_regel(HOOG, "100.00", "21.06"), _regel(HOOG, "100.00", "20.94")]
        r = check_btw_past_bij_tarief(regels=regels, tarieven=TARIEVEN)
        assert r.ok and not r.signaal

    def test_verdeeld_over_regels_binnen_de_regelmarge_maar_boven_de_documentgrens(self) -> None:
        # Twaalf regels, elk 1 ct te hoog (binnen de per-regel-marge) → Σ 0,12 ≥ 0,10: oranje zonder regel-acties.
        regels = [_regel(HOOG, "10.00", "2.11") for _ in range(12)]
        r = check_btw_past_bij_tarief(regels=regels, tarieven=TARIEVEN)
        assert r.ok and r.signaal and r.acties == () and "verdeeld over 12 regel(s)" in r.melding


def _tarieven_in_cache(administratie_id: uuid.UUID) -> None:
    with scoped_session(administratie_id) as session:
        session.add(
            TaxRateCache(
                id=HOOG, administratie_id=administratie_id, naam="NL, Hoog Tarief", percentage=D("0.2100"), brondata={}
            )
        )


def _document(
    administratie_id: uuid.UUID, actor: uuid.UUID, opslag: LokaleBestandsopslag, *, netto: Decimal, btw: Decimal
) -> uuid.UUID:
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"{uuid.uuid4()}.pdf",
        inhoud=b"%PDF-1.4 " + uuid.uuid4().bytes,
        actor_id=actor,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor,
        vendor_id=uuid.uuid4(),
        referentie=f"F-{uuid.uuid4().hex[:8]}",
        factuurdatum=date(2026, 9, 29),
        totaalbedrag=netto + btw,
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=uuid.uuid4(),
                taxrate_id=HOOG,
                project_id=None,
                netto_bedrag=netto,
                btw_bedrag=btw,
                omschrijving="Lusso",
            )
        ],
    )
    return resultaat.document_id


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status::text FROM boekhouding.document WHERE id = :d"), {"d": document_id}
        ).scalar_one()


class TestAutoboekPad:
    @pytest.fixture
    def boeken_aan(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        _tarieven_in_cache(administratie_id)

    def test_lusso_zes_cent_check_groen_en_autoboek_loopt_door(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda _rlz_admin_id: fake)
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag, netto=LUSSO_NETTO, btw=LUSSO_BTW)
        rapport = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake)
        rij = next(r for r in rapport.resultaten if r.naam == NAAM_BTW_TARIEF)
        assert rij.ok and not rij.signaal, rij
        assert boeken.btw_signaal_rij(rapport) is None
        boeken.boek_document(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=SYSTEEM_ACTOR_ID,
            extra_overgang_detail={volumerem.AUTOMATISCH_MARKERING: True},
        )
        assert _status(admin_engine, document_id) == "geboekt"
        # De factuur-btw gaat naar RLZ (geen netto-verschuiving): de PUT draagt 4.349,18 / 913,27.
        regels = [r for put in fake.puts for r in put.get("body", put).get("DocumentLineList", [])] if fake.puts else []
        if regels:
            assert (D(str(regels[0]["NetAmount"])), D(str(regels[0]["TaxAmount"]))) == (LUSSO_NETTO, LUSSO_BTW)

    def test_oranje_btw_signaal_weigert_het_autoboek_pad_mens_mag_door(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda _rlz_admin_id: fake)
        # 21 % op 100,00 = 21,00; factuur-btw 20,86 → Δ 0,14 ≥ 0,10: oranje, totaal 120,86 sluit.
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag, netto=D("100.00"), btw=D("20.86"))
        rapport = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake)
        rij = boeken.btw_signaal_rij(rapport)
        assert rij is not None and rapport.geblokkeerd is False
        with pytest.raises(boeken.AutoboekGeweigerdDoorSignaal, match="btw-verschil ≥ € 0,10"):
            boeken.boek_document(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=SYSTEEM_ACTOR_ID,
                extra_overgang_detail={volumerem.AUTOMATISCH_MARKERING: True},
            )
        assert fake.puts == [] and _status(admin_engine, document_id) != "geboekt"
        # Een mens mag door (factuur-btw leidend).
        boeken.boek_document(administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker)
        assert _status(admin_engine, document_id) == "geboekt"


def _geboekt(*, totaal: str, btw: str | None, netto: str | None) -> _Geboekt:
    return _Geboekt(
        document_id=uuid.uuid4(),
        totaalbedrag=D(totaal),
        rlz_boekstuknummer="RLZ-04-00000999",
        boek_cyclus=0,
        referentie="260987",
        leverancier_naam="Lusso",
        btw_lokaal=D(btw) if btw is not None else None,
        netto_lokaal=D(netto) if netto is not None else None,
    )


def _uitkomst(*, bedrag: str, btw: str | None, netto: str | None) -> ToetsUitkomst:
    return ToetsUitkomst(
        backend=Backend.RLZ,
        bestaat=True,
        geboekt=True,
        bedrag=D(bedrag),
        btw_bedrag=D(btw) if btw is not None else None,
        netto_bedrag=D(netto) if netto is not None else None,
        boekstuknummer="RLZ-04-00000999",
        extern_state="2",
    )


class TestReconciliatiePuur:
    def test_rlz_boekt_meer_voorbelasting_is_bedrag_wijkt_af_met_btw_context(self) -> None:
        # Lusso: module 4.349,18 + 913,27 = 5.262,45; RLZ herrekent naar 913,33 → 5.262,51 (Δ 0,06, netto gelijk).
        doc = _geboekt(totaal="5262.45", btw="913.27", netto="4349.18")
        (a,) = reconciliatie.beoordeel_uitkomst(
            doc,
            _uitkomst(bedrag="5262.51", btw="913.33", netto="4349.18"),
            backend=Backend.RLZ,
            administratie_naam="KF",
        )
        assert a.soort == "bedrag_wijkt_af"
        assert a.context[reconciliatie.BTW_AFRONDING_SLEUTEL] == reconciliatie.BTW_AFRONDING_RLZ_MEER
        assert (a.context["btw_lokaal"], a.context["btw_extern"]) == ("913.27", "913.33")
        assert reconciliatie.btw_afrondingsverschil(a) == D("0.06")
        assert reconciliatie.is_btw_afrondingsverschil(a)
        # Buiten de 0,05-regel (verbreding alleen voor déze oorzaak): de oude regel zegt None.
        assert reconciliatie.afrondingsverschil(a) is None

    def test_rlz_boekt_minder_voorbelasting_is_eigen_soort_in_meten(self) -> None:
        doc = _geboekt(totaal="5262.45", btw="913.27", netto="4349.18")
        (a,) = reconciliatie.beoordeel_uitkomst(
            doc,
            _uitkomst(bedrag="5262.39", btw="913.21", netto="4349.18"),
            backend=Backend.RLZ,
            administratie_naam="KF",
        )
        assert a.soort == reconciliatie.SOORT_BTW_RLZ_LAGER == "btw_rlz_lager_dan_factuur"
        assert a.context[reconciliatie.BTW_AFRONDING_SLEUTEL] == reconciliatie.BTW_AFRONDING_RLZ_MINDER
        assert "btw eigen=€913.27 rlz=€913.21" in a.detail
        assert reconciliatie.btw_afrondingsverschil(a) is None  # nooit een acceptatie
        assert soort_stand.code_default(a.soort) == soort_stand.METEN
        assert soort_stand.REGISTRY[a.soort].sinds == date(2026, 10, 2)

    def test_afwezig_pad_zonder_btw_gegevens_blijft_de_oude_regel(self) -> None:
        doc = _geboekt(totaal="5262.45", btw=None, netto=None)
        (a,) = reconciliatie.beoordeel_uitkomst(
            doc, _uitkomst(bedrag="5262.48", btw=None, netto=None), backend=Backend.RLZ, administratie_naam="KF"
        )
        assert a.soort == "bedrag_wijkt_af" and reconciliatie.BTW_AFRONDING_SLEUTEL not in a.context
        assert reconciliatie.btw_afrondingsverschil(a) is None
        assert reconciliatie.afrondingsverschil(a) == D("0.03")

    @pytest.mark.parametrize(
        ("bedrag", "btw", "netto"),
        [
            ("5262.55", "913.37", "4349.18"),  # Δ btw 0,10 = niet meer onder de grens
            ("5262.51", "913.27", "4349.24"),  # netto verschoven → geen btw-oorzaak
            ("5263.42", "914.24", "4349.18"),  # Δ 0,97 (Booking Experts) = echte wijziging
        ],
    )
    def test_geen_btw_oorzaak_is_gewoon_bedrag_wijkt_af(self, bedrag: str, btw: str, netto: str) -> None:
        doc = _geboekt(totaal="5262.45", btw="913.27", netto="4349.18")
        (a,) = reconciliatie.beoordeel_uitkomst(
            doc, _uitkomst(bedrag=bedrag, btw=btw, netto=netto), backend=Backend.RLZ, administratie_naam="KF"
        )
        assert a.soort == "bedrag_wijkt_af" and reconciliatie.BTW_AFRONDING_SLEUTEL not in a.context

    def test_richting_puur(self) -> None:
        f = reconciliatie.btw_afronding_richting
        assert f(btw_lokaal=D("1.00"), btw_extern=D("1.09"), netto_lokaal=D("5"), netto_extern=D("5")) == "rlz_meer"
        assert f(btw_lokaal=D("1.00"), btw_extern=D("0.91"), netto_lokaal=D("5"), netto_extern=D("5")) == "rlz_minder"
        assert f(btw_lokaal=D("1.00"), btw_extern=D("1.10"), netto_lokaal=D("5"), netto_extern=D("5")) is None
        assert f(btw_lokaal=D("1.00"), btw_extern=D("1.00"), netto_lokaal=D("5"), netto_extern=D("5")) is None
        assert f(btw_lokaal=None, btw_extern=D("1.05"), netto_lokaal=D("5"), netto_extern=D("5")) is None

    def test_leesbare_tekst_voor_de_nieuwe_soort(self) -> None:
        bevinding = SimpleNamespace(
            blok="documenten",
            soort="afwijking",
            tekst="AFWIJKING document=x soort=btw_rlz_lager_dan_factuur",
            detail={
                "afwijking_soort": "btw_rlz_lager_dan_factuur",
                "bedrag_lokaal": "5262.45",
                "bedrag_extern": "5262.39",
                "btw_lokaal": "913.27",
                "btw_extern": "913.21",
                "backend": "rlz",
                "leverancier_naam": "Lusso",
                "factuurnummer": "260987",
            },
        )
        lb = teksten.leesbaar(bevinding)
        assert "minder btw dan de factuur" in lb.titel
        assert "913,27" in lb.wat and "913,21" in lb.wat and "onder € 0,10" in lb.wat
        assert "factuur-btw leidend" in lb.doe


ARGS = argparse.Namespace()


def _afw(
    lokaal: str, extern: str, *, soort: str = "bedrag_wijkt_af", context_extra: dict | None = None
) -> ReconciliatieAfwijking:
    return ReconciliatieAfwijking(
        document_id=uuid.uuid4(),
        rlz_document_id=uuid.uuid4(),
        soort=soort,
        detail=f"eigen=€{lokaal} rlz=€{extern}",
        context={
            "bedrag_lokaal": lokaal,
            "bedrag_extern": extern,
            "leverancier_naam": "Lusso",
            "factuurnummer": "260987",
            **(context_extra or {}),
        },
    )


def _run(  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID, afwijkingen
) -> tuple[int, Verzamelaar]:
    rapport = ReconciliatieRapport(
        administratie_id=administratie_id, aantal_gecontroleerd=3, afwijkingen=tuple(afwijkingen)
    )
    monkeypatch.setattr(cli.reconciliatie, "reconcilieer_alle_administraties", lambda: {administratie_id: rapport})
    monkeypatch.setattr(cli.storno_detectie, "detecteer_en_meld_gestorneerd_alle", lambda: {})
    verzamelaar = Verzamelaar()
    verzamelaar.start_blok("documenten")
    code = cli._reconciliatie(ARGS, verzamelaar=verzamelaar)
    return code, verzamelaar


def _audits(administratie_id: uuid.UUID, actie: str) -> list[AuditEvent]:
    with scoped_session(administratie_id) as session:
        rijen = session.scalars(select(AuditEvent).where(AuditEvent.actie == actie)).all()
        for r in rijen:
            session.expunge(r)
        return rijen


class TestReconciliatieRun:
    def test_rlz_meer_wordt_geaccepteerd_met_audit_btw_afronding_rlz(
        self, administratie_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        lusso = _afw(
            "5262.45",
            "5262.51",
            context_extra={
                reconciliatie.BTW_AFRONDING_SLEUTEL: reconciliatie.BTW_AFRONDING_RLZ_MEER,
                "btw_lokaal": "913.27",
                "btw_extern": "913.33",
            },
        )
        code, v = _run(monkeypatch, administratie_id, [lusso])
        assert code == 0
        stand = v.blokken["documenten"]
        assert (stand.afwijkingen, stand.geaccepteerd, stand.auto_geaccepteerd) == (0, 1, 1)
        uit = capsys.readouterr().out
        assert f"automatisch geaccepteerd ({reconciliatie.BTW_AFRONDING_REDEN}, verschil € 0.06)" in uit
        with scoped_session(administratie_id) as session:
            (acc,) = session.scalars(
                select(ReconciliatieAcceptatie).where(ReconciliatieAcceptatie.administratie_id == administratie_id)
            ).all()
            assert acc.geaccepteerd_door == SYSTEEM_ACTOR_ID and acc.record_id == lusso.document_id
            assert acc.reden == f"automatisch ({reconciliatie.BTW_AFRONDING_REDEN})"
        (audit,) = _audits(administratie_id, "btw_afronding_rlz")
        assert audit.actor_id == SYSTEEM_ACTOR_ID and audit.nieuwe_waarde["verschil"] == "0.06"
        assert audit.nieuwe_waarde["regel"] == "run D 02-10 blok A"
        assert _audits(administratie_id, "reconciliatie_auto_geaccepteerd") == []

    def test_rlz_minder_blijft_bevinding_in_meten_zonder_acceptatie(
        self, administratie_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lager = _afw(
            "5262.45",
            "5262.39",
            soort="btw_rlz_lager_dan_factuur",
            context_extra={
                reconciliatie.BTW_AFRONDING_SLEUTEL: reconciliatie.BTW_AFRONDING_RLZ_MINDER,
                "btw_lokaal": "913.27",
                "btw_extern": "913.21",
            },
        )
        _, v = _run(monkeypatch, administratie_id, [lager])
        stand = v.blokken["documenten"]
        assert (stand.afwijkingen, stand.geaccepteerd, stand.auto_geaccepteerd) == (1, 0, 0)
        (b,) = [b for b in v.bevindingen if b.detail.get("record_id") == str(lager.document_id)]
        assert b.soort == "afwijking" and b.detail["afwijking_soort"] == "btw_rlz_lager_dan_factuur"
        assert b.detail["btw_lokaal"] == "913.27" and b.detail["btw_extern"] == "913.21"
        assert _audits(administratie_id, "btw_afronding_rlz") == []
        # In meting: telt, nooit actiemail (soort_stand.code_default).
        assert soort_stand.code_default("btw_rlz_lager_dan_factuur") == soort_stand.METEN

    def test_afwezig_pad_zonder_btw_context_volgt_de_regel_van_15_09(
        self, administratie_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        klein = _afw("5255.61", "5255.64")
        _, v = _run(monkeypatch, administratie_id, [klein])
        assert v.blokken["documenten"].auto_geaccepteerd == 1
        (audit,) = _audits(administratie_id, "reconciliatie_auto_geaccepteerd")
        assert audit.nieuwe_waarde["reden"] == reconciliatie.AFRONDING_REDEN
        assert _audits(administratie_id, "btw_afronding_rlz") == []

    def test_lees_only_markeert_de_btw_regel_zonder_te_schrijven(
        self, administratie_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        lusso = _afw(
            "5262.45",
            "5262.51",
            context_extra={
                reconciliatie.BTW_AFRONDING_SLEUTEL: reconciliatie.BTW_AFRONDING_RLZ_MEER,
                "btw_lokaal": "913.27",
                "btw_extern": "913.33",
            },
        )
        rapport = ReconciliatieRapport(administratie_id=administratie_id, aantal_gecontroleerd=1, afwijkingen=(lusso,))
        monkeypatch.setattr(cli.reconciliatie, "reconcilieer_alle_administraties", lambda: {administratie_id: rapport})
        monkeypatch.setattr(cli.storno_detectie, "detecteer_en_meld_gestorneerd_alle", lambda: {})
        code = cli._reconciliatie(ARGS, verzamelaar=None)
        assert code == 1
        assert f"{reconciliatie.BTW_AFRONDING_REDEN}: wordt in de dagelijkse run automatisch geaccepteerd" in (
            capsys.readouterr().out
        )
        with scoped_session(administratie_id) as session:
            assert session.scalars(select(ReconciliatieAcceptatie)).all() == []
        assert acceptatie_service is not None
