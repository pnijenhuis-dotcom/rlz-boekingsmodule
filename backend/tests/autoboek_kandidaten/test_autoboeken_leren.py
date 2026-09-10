# ruff: noqa: F811 — pytest-fixtures als parameters
"""Autoboeken per administratie — "leren en boeken" (blok A bundel 10-09; besluit Peter 10-09; migratie 0128).

Schakelaar per administratie (Beheerder, default UIT, Kempen-regel → 409), leerregel (het systeem ACTIVEERT i.p.v.
nomineert zodra ≥ drempel IDENTIEKE mens-boekingen op rij staan — telling herzien 10-09 avond, blok 3: de eerste boeking
telt als 1), uitzonderingenlijst (uitzonderen mét reden /
vrijgeven), reset ná storno/correctie van een automatische boeking ("leert 0/N"), post-commit-hook ná een mens-boeking,
rolpoorten en het afwezig-pad (geen eigenaar = doorlopen)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import Engine, text

from app.autoboek_kandidaten import motor, service
from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import autoboeken
from app.documenten.models import LeverancierVoorkeur
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.autoboek_kandidaten.test_kandidaten import (  # noqa: F401
    BTW,
    GB_A,
    GB_B,
    T0,
    VENDOR,
    _audit_acties,
    _bearer,
    _boeking,
    _geboekt,
    client,
    tweede_vendor,
    vendor,
)
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401

KEMPEN_TEKST = beheer_service.AUTOBOEKEN_LEREN_NIET_TOEGESTAAN_TEKST


@pytest.fixture
def drempel_3(beheerder_id: uuid.UUID) -> int:
    """De testdatabase seedt de instelling-rij nog met 5 (migratie 0095); het besluit 10-09 = 3 (CLI post-deploy)."""
    return service.zet_drempel(actor_id=beheerder_id, drempel=3)


@pytest.fixture
def leren_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID, drempel_3: int) -> uuid.UUID:
    stand = beheer_service.zet_autoboeken_leren(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )
    assert stand.ingeschakeld is True and stand.toegestaan is True
    return administratie_id


def _voorkeur(administratie_id: uuid.UUID, vendor_id: uuid.UUID = VENDOR) -> LeverancierVoorkeur | None:
    with scoped_session(administratie_id) as session:
        rij = session.get(LeverancierVoorkeur, (administratie_id, vendor_id))
        if rij is not None:
            session.expunge(rij)
        return rij


def _tijdlijn_sleutels(admin_engine: Engine, document_id: uuid.UUID) -> list[set[str]]:
    with admin_engine.connect() as conn:
        return [
            set(d or {})
            for d in conn.execute(
                text("SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :id ORDER BY tijdstip"),
                {"id": document_id},
            ).scalars()
        ]


class TestSchakelaar:
    def test_default_uit_en_zetten_met_audit(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        stand = beheer_service.haal_autoboeken_leren_op(administratie_id=administratie_id)
        assert (stand.ingeschakeld, stand.toegestaan, stand.reden_niet_toegestaan) == (False, True, None)
        headers = _bearer(beheerder_id, rol="beheerder")
        r = client.put(
            f"/administraties/{administratie_id}/autoboeken-leren-instelling",
            headers=headers,
            json={"ingeschakeld": True},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"ingeschakeld": True, "toegestaan": True, "reden_niet_toegestaan": None}
        assert client.get(f"/administraties/{administratie_id}/autoboeken-leren-instelling", headers=headers).json()[
            "ingeschakeld"
        ]
        assert _audit_acties(admin_engine, "autoboeken_leren_gewijzigd") == 1
        lijst = client.get("/instellingen/administraties", headers=headers).json()["administraties"]
        rij = next(a for a in lijst if a["id"] == str(administratie_id))
        assert rij["autoboeken_leren_ingeschakeld"] is True and rij["autoboeken_leren_toegestaan"] is True

    def test_kempen_regel_doorbelasting_geeft_409_met_uitleg_en_uitzetten_mag(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET doorbelasting_ingeschakeld = true WHERE id = :id"),
                {"id": administratie_id},
            )
        headers = _bearer(beheerder_id, rol="beheerder")
        stand = client.get(f"/administraties/{administratie_id}/autoboeken-leren-instelling", headers=headers).json()
        assert stand == {"ingeschakeld": False, "toegestaan": False, "reden_niet_toegestaan": KEMPEN_TEKST}
        r = client.put(
            f"/administraties/{administratie_id}/autoboeken-leren-instelling",
            headers=headers,
            json={"ingeschakeld": True},
        )
        assert r.status_code == 409 and r.json()["detail"] == KEMPEN_TEKST
        assert _audit_acties(admin_engine, "autoboeken_leren_gewijzigd") == 0
        # Uitzetten mag altijd (idempotent, wél geauditeerd).
        r = client.put(
            f"/administraties/{administratie_id}/autoboeken-leren-instelling",
            headers=headers,
            json={"ingeschakeld": False},
        )
        assert r.status_code == 200 and r.json()["toegestaan"] is False
        lijst = client.get("/instellingen/administraties", headers=headers).json()["administraties"]
        assert next(a for a in lijst if a["id"] == str(administratie_id))["autoboeken_leren_toegestaan"] is False

    def test_onbekende_administratie_404(self, beheerder_id: uuid.UUID) -> None:
        r = client.put(
            f"/administraties/{uuid.uuid4()}/autoboeken-leren-instelling",
            headers=_bearer(beheerder_id, rol="beheerder"),
            json={"ingeschakeld": True},
        )
        assert r.status_code == 404


class TestLeerregel:
    def test_zonder_schakelaar_blijft_het_nomineren(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        vendor: uuid.UUID,
        opslag,
        admin_engine: Engine,
        drempel_3: int,
    ) -> None:
        for n in range(4):
            _geboekt(administratie_id, beheerder_id, opslag, n=n)
        tellers = service.herbereken_administratie(administratie_id=administratie_id)
        assert tellers["kandidaten"] == 1 and tellers["geactiveerd"] == 0
        assert service.activeer_kwalificerend(administratie_id=administratie_id) == []
        assert _voorkeur(administratie_id) is None  # niets aangezet
        assert _audit_acties(admin_engine, "autoboek_leverancier_geactiveerd") == 0

    def test_met_schakelaar_activeert_het_systeem_bij_de_drempel_met_audit_en_tijdlijn(
        self, leren_aan: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID, opslag, admin_engine: Engine
    ) -> None:
        aid = leren_aan
        docs = [_geboekt(aid, beheerder_id, opslag, n=n) for n in range(2)]
        # Telling herzien 10-09 (blok 3): twee identieke boekingen = "leert 2/3", nog niet actief.
        [u] = service.activeer_kwalificerend(administratie_id=aid)
        assert u.status == "overgeslagen" and "2 identieke boekingen (drempel 3)" in (u.reden or "")
        assert _voorkeur(aid) is None
        rij = next(r for r in autoboeken.lijst_leverancier_autoboeken(administratie_id=aid) if r.vendor_id == vendor)
        assert (rij.stand, rij.reeks, rij.drempel) == ("leert", 2, 3)
        # Precies drie identieke mens-boekingen → actief.
        docs.append(_geboekt(aid, beheerder_id, opslag, n=2))
        [uitkomst] = service.activeer_kwalificerend(administratie_id=aid, vendor_id=vendor)
        assert (uitkomst.status, uitkomst.reeks_ongewijzigd, uitkomst.drempel) == ("geactiveerd", 3, 3)
        voorkeur = _voorkeur(aid)
        assert (
            voorkeur is not None and voorkeur.autoboeken_ingeschakeld is True and voorkeur.autoboeken_bron == "systeem"
        )
        assert _audit_acties(admin_engine, "autoboek_leverancier_geactiveerd") == 1
        assert _audit_acties(admin_engine, "leverancier_autoboeken_gewijzigd") == 1
        # Tijdlijnregel op het document dat de drempel haalde; systeem-actor.
        assert any("autoboek_geactiveerd" in s for s in _tijdlijn_sleutels(admin_engine, docs[-1]))
        with admin_engine.connect() as conn:
            actor = conn.execute(
                text("SELECT actor_id FROM platform.audit_event WHERE actie = 'autoboek_leverancier_geactiveerd'")
            ).scalar_one()
        assert actor == SYSTEEM_ACTOR_ID
        # Idempotent: nog eens = overgeslagen "staat al aan".
        [nogmaals] = service.activeer_kwalificerend(administratie_id=aid, vendor_id=vendor)
        assert nogmaals.status == "overgeslagen" and "al aan" in (nogmaals.reden or "")
        # Uitzonderingenlijst toont de chip.
        rij = next(r for r in autoboeken.lijst_leverancier_autoboeken(administratie_id=aid) if r.vendor_id == vendor)
        assert (rij.stand, rij.reeks, rij.drempel, rij.bron) == ("boekt_automatisch", 3, 3, "systeem")
        # Kandidaten-scherm: rij op tab Actief mét de chip "administratie leert zelf".
        lijst = service.lijst(tab="actief")
        assert (
            lijst.totaal == 1
            and lijst.rijen[0].administratie_leren_aan is True
            and lijst.rijen[0].stand == "boekt_automatisch"
        )

    def test_herberekening_activeert_en_telt(
        self, leren_aan: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID, opslag, admin_engine: Engine
    ) -> None:
        for n in range(4):
            _geboekt(leren_aan, beheerder_id, opslag, n=n)
        tellers = service.herbereken_administratie(administratie_id=leren_aan)
        assert tellers["geactiveerd"] == 1 and tellers["actief"] == 1 and tellers["kandidaten"] == 0
        assert _voorkeur(leren_aan).autoboeken_ingeschakeld is True
        # Tweede run: niets meer te activeren, stand blijft actief.
        tellers = service.herbereken_administratie(administratie_id=leren_aan)
        assert tellers["geactiveerd"] == 0 and tellers["actief"] == 1

    def test_correctie_in_de_reeks_activeert_pas_na_drie_identieke_recente(
        self, leren_aan: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID, opslag
    ) -> None:
        # Telling herzien 10-09: A, B, A — de middelste wijkt af, de laatste start een nieuwe reeks (1/3).
        _geboekt(leren_aan, beheerder_id, opslag, n=0)
        _geboekt(leren_aan, beheerder_id, opslag, n=1, gb=GB_B)
        _geboekt(leren_aan, beheerder_id, opslag, n=2)
        [u] = service.activeer_kwalificerend(administratie_id=leren_aan, vendor_id=vendor)
        assert u.status == "overgeslagen" and "1 identieke boeking (drempel 3)" in (u.reden or "")
        assert u.reeks_ongewijzigd == 1
        assert _voorkeur(leren_aan) is None
        # A, B, A, A → reeks 2/3 en de geheugen-stem is nog gesplitst (laatste drie mens-boekingen B, A, A niet
        # identiek) → géén activatie, leesbaar in de reden.
        _geboekt(leren_aan, beheerder_id, opslag, n=3)
        [u] = service.activeer_kwalificerend(administratie_id=leren_aan, vendor_id=vendor)
        assert u.status == "overgeslagen" and u.reeks_ongewijzigd == 2
        assert "gesplitste stem" in (u.reden or "")
        assert _voorkeur(leren_aan) is None
        # A, B, A, A, A → reeks 3/3 én de recency-regel (blok 3 vervolgrun 10-09 avond, besluit Peter "recency wint")
        # maakt de leverancier-stem groen: de laatste drie mens-boekingen zijn identiek, de ene oude B telt niet meer
        # mee in de tie-break (wél zichtbaar als "eerder ook"). Vóór 10-09 avond bleef dit blijvend "gesplitst" —
        # de activatie-motor zelf is ongewijzigd, de engine levert het.
        _geboekt(leren_aan, beheerder_id, opslag, n=4)
        [u] = service.activeer_kwalificerend(administratie_id=leren_aan, vendor_id=vendor)
        assert u.status == "geactiveerd" and u.reeks_ongewijzigd == 3, u.reden
        assert _voorkeur(leren_aan).autoboeken_ingeschakeld is True
        stand = next(s for s in service.bereken_standen(administratie_id=leren_aan) if s.vendor_id == vendor)
        assert stand.eerder_afwijkend is True

    def test_aanzetten_van_de_schakelaar_activeert_direct(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID, opslag, drempel_3: int
    ) -> None:
        for n in range(4):
            _geboekt(administratie_id, beheerder_id, opslag, n=n)
        assert _voorkeur(administratie_id) is None
        beheer_service.zet_autoboeken_leren(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        assert _voorkeur(administratie_id).autoboeken_ingeschakeld is True

    def test_veldwerker_koppeling_wordt_nooit_geactiveerd(
        self, leren_aan: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID, opslag, admin_engine: Engine
    ) -> None:
        from tests.uren.conftest import maak_gebruiker

        for n in range(4):
            _geboekt(leren_aan, beheerder_id, opslag, n=n)
        zzper = maak_gebruiker(admin_engine, "zzper", "Z. Zper")
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.veldwerker_crediteur (administratie_id, gebruiker_id, vendor_id, gekoppeld_door, autoboeken_ingeschakeld) "
                    "VALUES (:a, :g, :v, :b, false)"
                ),
                {"a": leren_aan, "g": zzper, "v": vendor, "b": beheerder_id},
            )
        [u] = service.activeer_kwalificerend(administratie_id=leren_aan, vendor_id=vendor)
        assert u.status == "overgeslagen" and "veldwerker" in (u.reden or "")
        assert _voorkeur(leren_aan) is None


class TestUitzonderenEnVrijgeven:
    def test_uitzonderen_vereist_reden_zet_uit_en_blokkeert_activatie(
        self, leren_aan: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID, opslag, admin_engine: Engine
    ) -> None:
        for n in range(4):
            _geboekt(leren_aan, beheerder_id, opslag, n=n)
        service.activeer_kwalificerend(administratie_id=leren_aan, vendor_id=vendor)
        assert _voorkeur(leren_aan).autoboeken_ingeschakeld is True
        headers = _bearer(beheerder_id, rol="beheerder")
        pad = f"/administraties/{leren_aan}/leveranciers/{vendor}/autoboeken-uitzonderen"
        assert client.post(pad, headers=headers, json={"reden": "   "}).status_code == 422
        r = client.post(pad, headers=headers, json={"reden": "wisselende projecten, wil ik zelf zien"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["stand"], body["autoboeken_ingeschakeld"], body["bron"]) == ("uitgezonderd", False, None)
        assert body["uitzondering_reden"] == "wisselende projecten, wil ik zelf zien"
        assert _audit_acties(admin_engine, "autoboek_leverancier_uitgezonderd") == 1
        # Het systeem activeert een uitgezonderde leverancier nooit — ook niet in de herberekening.
        [u] = service.activeer_kwalificerend(administratie_id=leren_aan, vendor_id=vendor)
        assert u.status == "overgeslagen" and "uitgezonderd" in (u.reden or "")
        assert service.herbereken_administratie(administratie_id=leren_aan)["geactiveerd"] == 0
        # Vrijgeven → direct weer actief (de reeks haalt de drempel nog).
        r = client.post(f"/administraties/{leren_aan}/leveranciers/{vendor}/autoboeken-vrijgeven", headers=headers)
        assert r.status_code == 200 and r.json()["stand"] == "boekt_automatisch" and r.json()["bron"] == "systeem"
        assert _audit_acties(admin_engine, "autoboek_leverancier_vrijgegeven") == 1

    def test_mens_zet_aan_zonder_schakelaar_is_handmatig_aan_en_bron_mens(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID
    ) -> None:
        headers = _bearer(beheerder_id, rol="beheerder")
        r = client.put(
            f"/administraties/{administratie_id}/leveranciers/{vendor}/autoboeken-instelling",
            headers=headers,
            json={"ingeschakeld": True},
        )
        assert r.status_code == 200 and (r.json()["stand"], r.json()["bron"]) == ("handmatig_aan", "mens")
        lijst = client.get(f"/administraties/{administratie_id}/leveranciers-autoboeken", headers=headers).json()
        rij = next(x for x in lijst["leveranciers"] if x["vendor_id"] == str(vendor))
        assert rij["stand"] == "handmatig_aan" and rij["drempel"] >= 1 and rij["reeks"] == 0

    def test_heroverwegen_uitzetten_wordt_uitzonderen_als_de_schakelaar_aan_staat(
        self, leren_aan: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID, opslag
    ) -> None:
        for n in range(4):
            _geboekt(leren_aan, beheerder_id, opslag, n=n)
        service.activeer_kwalificerend(administratie_id=leren_aan, vendor_id=vendor)
        service.uitzetten(administratie_id=leren_aan, vendor_id=vendor, actor_id=beheerder_id)
        voorkeur = _voorkeur(leren_aan)
        assert voorkeur.autoboeken_ingeschakeld is False and voorkeur.autoboeken_uitgezonderd is True
        assert "Heroverwegen" in (voorkeur.autoboeken_uitzondering_reden or "")
        assert service.herbereken_administratie(administratie_id=leren_aan)["geactiveerd"] == 0


class TestResetNaStornoOfCorrectie:
    def test_reset_zet_uit_start_de_reeks_opnieuw_met_audit_en_tijdlijn(
        self, leren_aan: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID, opslag, admin_engine: Engine
    ) -> None:
        for n in range(4):
            _geboekt(leren_aan, beheerder_id, opslag, n=n)
        service.activeer_kwalificerend(administratie_id=leren_aan, vendor_id=vendor)
        automatisch_doc = _geboekt(leren_aan, beheerder_id, opslag, n=4, automatisch=True)
        mens_doc = _geboekt(leren_aan, beheerder_id, opslag, n=5)
        with scoped_session(leren_aan, actor_id=beheerder_id) as session:
            # Een correctie op een MENS-boeking raakt de leerregel niet.
            assert (
                autoboeken.reset_na_correctie_in_sessie(
                    session, administratie_id=leren_aan, document_id=mens_doc, reden="storno", actor_id=beheerder_id
                )
                is False
            )
            assert (
                autoboeken.reset_na_correctie_in_sessie(
                    session,
                    administratie_id=leren_aan,
                    document_id=automatisch_doc,
                    reden="storno",
                    actor_id=beheerder_id,
                )
                is True
            )
        voorkeur = _voorkeur(leren_aan)
        assert voorkeur.autoboeken_ingeschakeld is False and voorkeur.autoboeken_bron is None
        assert voorkeur.autoboeken_gereset_op is not None
        assert _audit_acties(admin_engine, "autoboek_leverancier_gereset") == 1
        regels = _tijdlijn_sleutels(admin_engine, automatisch_doc)
        assert any("autoboek_reset" in s for s in regels)
        with admin_engine.connect() as conn:
            tekst = conn.execute(
                text(
                    "SELECT detail->>'reden' FROM boekhouding.document_gebeurtenis WHERE document_id = :id "
                    "AND detail ? 'autoboek_reset'"
                ),
                {"id": automatisch_doc},
            ).scalar_one()
        assert tekst == "Autoboeken voor Ebbers Salarisadvies B.V. teruggezet naar leren (0/3) — storno"
        # De reeks telt alleen boekingen ná de reset: 0/3 — óók de herberekening activeert niet opnieuw.
        stand = service.hertoets_vendor(administratie_id=leren_aan, vendor_id=vendor)
        assert stand.reeks_ongewijzigd == 0 and stand.actief is False and stand.gereset_op is not None
        assert service.herbereken_administratie(administratie_id=leren_aan)["geactiveerd"] == 0
        rij = next(
            r for r in autoboeken.lijst_leverancier_autoboeken(administratie_id=leren_aan) if r.vendor_id == vendor
        )
        assert (rij.stand, rij.reeks, rij.gereset_op is not None) == ("leert", 0, True)
        # Drie nieuwe mens-boekingen ná de reset (geheugen kent GB_A al → élke gelijke boeking bevestigt) → weer actief.
        for n in (20, 21, 22):
            _geboekt(leren_aan, beheerder_id, opslag, n=n)
        [u] = service.activeer_kwalificerend(administratie_id=leren_aan, vendor_id=vendor)
        assert u.status == "geactiveerd" and u.reeks_ongewijzigd == 3

    def test_onbekende_reden_is_een_programmeerfout(self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> None:
        with scoped_session(administratie_id) as session, pytest.raises(ValueError):
            autoboeken.reset_na_correctie_in_sessie(
                session, administratie_id=administratie_id, document_id=uuid.uuid4(), reden="x", actor_id=beheerder_id
            )


class TestMotorReeksVanaf:
    def test_boekingen_op_of_voor_de_reset_voeden_alleen_het_geheugen(self) -> None:
        boekingen = [_boeking(i) for i in range(6)]
        reset = T0 + timedelta(days=30 * 3)  # ná boeking 3
        reeks = motor.analyseer_reeks(boekingen, seed_observaties=[], project_verplicht=False, reeks_vanaf=reset)
        # Boekingen 4 en 5 tellen; het geheugen kende GB_A al uit 0–3, dus beide bevestigen.
        assert reeks.reeks_ongewijzigd == 2 and reeks.mens_boekingen == 2
        zonder = motor.analyseer_reeks(boekingen, seed_observaties=[], project_verplicht=False)
        assert zonder.reeks_ongewijzigd == 6  # telling herzien 10-09 (was 5)


class TestGeheugenPoortGelijkAanReeks:
    """Blok 3 10-09: nu de reeks identieke boekingen telt (niet meer "ongewijzigd t.o.v. het voorstel"), bewaakt de
    service-poort dat het geheugen dezelfde waarden voorstelt als de reeks — anders zou het autoboek-pad iets anders
    boeken dan de mens de laatste N keer deed. Nooit gokken."""

    def _obs(self, gb, n: int, dag_offset: int) -> list:
        from datetime import date

        from app.geheugen.engine import Observatie
        from app.geheugen.models import ObservatieBron

        return [
            Observatie(None, gb, BTW, None, ObservatieBron.APP.value, date(2026, 1, 1) + timedelta(days=dag_offset + i))
            for i in range(n)
        ]

    def test_geheugen_dat_nog_de_oude_waarde_voorstelt_blokkeert_leesbaar(self) -> None:
        from datetime import date

        # A recent en talrijk → voorstel A (gesplitst/oranje, maar dat toetst de eerste poort al — hier gaat het om
        # de gelijkheidstoets; daarom alleen A-observaties voor het groene pad hieronder).
        observaties = self._obs(GB_A, 10, 200)
        ok, reden = service._geheugen_bevestigd(
            observaties,
            project_verplicht=False,
            vandaag=date(2026, 9, 10),
            reeks_waarden=frozenset({(None, GB_B, BTW, None)}),
        )
        assert ok is False
        assert reden == "geheugen stelt voor grootboek nog een andere waarde voor dan de laatste identieke boekingen"
        ok, reden = service._geheugen_bevestigd(
            observaties,
            project_verplicht=False,
            vandaag=date(2026, 9, 10),
            reeks_waarden=frozenset({(None, GB_A, BTW, None)}),
        )
        assert (ok, reden) == (True, None)
        # Zonder reeks-handtekening (geen mens-boeking in de reeks) blijft alleen de app-bevestigd-poort over.
        vandaag = date(2026, 9, 10)
        assert service._geheugen_bevestigd(observaties, project_verplicht=False, vandaag=vandaag) == (True, None)

    def test_projectplicht_toetst_ook_het_project_van_de_reeks(self) -> None:
        from datetime import date

        from app.geheugen.engine import Observatie
        from app.geheugen.models import ObservatieBron

        p1, p2 = uuid.uuid4(), uuid.uuid4()
        observaties = [
            Observatie(None, GB_A, BTW, p1, ObservatieBron.APP.value, date(2026, 8, 1) + timedelta(days=i))
            for i in range(4)
        ]
        ok, reden = service._geheugen_bevestigd(
            observaties,
            project_verplicht=True,
            vandaag=date(2026, 9, 10),
            reeks_waarden=frozenset({(None, GB_A, BTW, p2)}),
        )
        assert ok is False and "project" in (reden or "")
        ok, _ = service._geheugen_bevestigd(
            observaties,
            project_verplicht=False,
            vandaag=date(2026, 9, 10),
            reeks_waarden=frozenset({(None, GB_A, BTW, None)}),
        )
        assert ok is True


class TestAfwezigPad:
    @pytest.mark.afwezig_pad("administratie.autoboeken_leren_ingeschakeld")
    def test_schakelaar_aan_zonder_eigenaar_en_zonder_kandidaten_loopt_door(
        self, leren_aan: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID, opslag, admin_engine: Engine
    ) -> None:
        with admin_engine.connect() as conn:
            eigenaar = conn.execute(
                text("SELECT eigenaar_gebruiker_id FROM platform.administratie WHERE id = :id"), {"id": leren_aan}
            ).scalar_one()
        assert eigenaar is None  # geen eigenaar, geen toewijzing: optionele voorwaarden ontbreken
        # Geen kandidaten: geen fout, lege uitkomst, tellers op 0 — geen stille no-op, gewoon niets te doen.
        assert service.activeer_kwalificerend(administratie_id=leren_aan) == []
        assert service.herbereken_administratie(administratie_id=leren_aan)["geactiveerd"] == 0
        # Mét kandidaten (nog steeds zonder eigenaar) activeert het systeem gewoon.
        for n in range(4):
            _geboekt(leren_aan, beheerder_id, opslag, n=n)
        assert service.herbereken_administratie(administratie_id=leren_aan)["geactiveerd"] == 1


class TestRolpoorten:
    @pytest.mark.parametrize("rol", ["boekhouding", "boekhouding_projecten"])
    def test_alleen_beheerder(self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, rol: str) -> None:
        headers = _bearer(gescoopte_gebruiker, rol=rol)
        basis = f"/administraties/{administratie_id}"
        assert client.get(f"{basis}/autoboeken-leren-instelling", headers=headers).status_code == 403
        assert (
            client.put(f"{basis}/autoboeken-leren-instelling", headers=headers, json={"ingeschakeld": True}).status_code
            == 403
        )
        assert (
            client.post(
                f"{basis}/leveranciers/{VENDOR}/autoboeken-uitzonderen", headers=headers, json={"reden": "x"}
            ).status_code
            == 403
        )
        assert client.post(f"{basis}/leveranciers/{VENDOR}/autoboeken-vrijgeven", headers=headers).status_code == 403


class TestCli:
    def test_drempel_zetten_en_leren_rapport(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        vendor: uuid.UUID,
        opslag,
        capsys,
        admin_engine: Engine,
    ) -> None:
        from app.cli import main

        assert main(["autoboek-drempel-zetten", "--drempel", "3"]) == 0
        assert service.haal_instelling_op()[0] == 3
        assert _audit_acties(admin_engine, "autoboek_drempel_gewijzigd") == 1
        assert main(["autoboek-drempel-zetten", "--drempel", "0"]) == 1
        # Telling herzien 10-09 (blok 3): het rapport volgt dezelfde telling als de motor — twee identieke = 2/3.
        for n in range(2):
            _geboekt(administratie_id, beheerder_id, opslag, n=n)
        capsys.readouterr()
        assert main(["autoboek-leren-rapport", "--administratie", str(administratie_id)]) == 0
        uit = capsys.readouterr().out
        assert "schakelaar: uit" in uit and "drempel 3" in uit and "identiek" in uit
        assert "Ebbers Salarisadvies B.V." in uit and "2/3" in uit and "leert" in uit
        assert "2 identieke boekingen (drempel 3)" in uit and "NB schakelaar uit" not in uit
        # Derde identieke boeking → 3/3, kwalificeert.
        _geboekt(administratie_id, beheerder_id, opslag, n=2)
        capsys.readouterr()
        assert main(["autoboek-leren-rapport", "--administratie", str(administratie_id)]) == 0
        uit = capsys.readouterr().out
        assert "3/3" in uit and "kwalificeert" in uit
        assert "NB schakelaar uit: 1 leverancier(s)" in uit
        # Lees-only: niets aangezet.
        assert _voorkeur(administratie_id) is None
        assert main(["autoboek-leren-rapport", "--administratie", str(uuid.uuid4())]) == 1
        assert main(["autoboek-leren-rapport", "--administratie", "geen-uuid"]) == 1
