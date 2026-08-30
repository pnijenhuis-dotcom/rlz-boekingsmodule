# ruff: noqa: F811 — pytest-fixtures als parameters
"""Terugkerende-facturen-signaal (opdracht 30-08 blok B, benchmark gap #3, migratie 0090): pure
intervaldetectie (maand/kwartaal/onregelmatig/eenmalig/tolerantie ±35 %), herberekening uit de
documenthistorie + RLZ-geheugen, signaal 1 (verwachte factuur ontbreekt, verdwijnt bij nieuwe factuur,
snooze/afmelden), signaal 2 (prijsstijging boven de drempel, instelbaar), werkvoorraad-teller,
endpoints/rolpoorten en de sync-alles-rapportage. Puur code — geen AI, nooit blokkerend."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.documenten import service as documenten_service
from app.documenten.models import Boekvoorstel
from app.main import app
from app.security.tokens import create_access_token
from app.terugkerend import service
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401

client = TestClient(app)
VENDOR_A = uuid.UUID("aaaaaaaa-1111-1111-1111-111111111111")
VENDOR_B = uuid.UUID("bbbbbbbb-1111-1111-1111-111111111111")
VANDAAG = date(2026, 8, 30)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _d(*ymd: tuple[int, int, int]) -> list[date]:
    return [date(*x) for x in ymd]


class TestDetectiePuur:
    def test_maandpatroon(self) -> None:
        p = service.detecteer_patroon(_d((2026, 1, 3), (2026, 2, 2), (2026, 3, 4), (2026, 4, 1)))
        assert p is not None and p.soort == "maand" and 28 <= p.interval_dagen <= 32 and p.aantal == 4

    def test_kwartaalpatroon(self) -> None:
        p = service.detecteer_patroon(_d((2025, 10, 1), (2026, 1, 2), (2026, 4, 1)))
        assert p is not None and p.soort == "kwartaal" and p.aantal == 3

    def test_onregelmatig_eenmalig_en_te_weinig(self) -> None:
        assert service.detecteer_patroon(_d((2026, 1, 1), (2026, 1, 20), (2026, 6, 1))) is None  # onregelmatig
        assert service.detecteer_patroon(_d((2026, 1, 1))) is None  # eenmalig
        assert service.detecteer_patroon(_d((2026, 1, 1), (2026, 2, 1))) is None  # twee = nog geen patroon
        dubbel = service.detecteer_patroon(_d((2026, 1, 1), (2026, 1, 1), (2026, 2, 1), (2026, 3, 1)))
        assert dubbel is not None and dubbel.aantal == 3  # dubbele datum telt één keer
        assert (
            service.detecteer_patroon(_d((2026, 1, 1), (2026, 1, 8), (2026, 1, 15))) is None
        )  # wekelijks: niet in scope

    def test_tolerantie_rand_35_procent(self) -> None:
        # 30,44 × 1,35 ≈ 41,1 dagen: 41 dagen valt er nét binnen, 42 er buiten.
        assert service.detecteer_patroon([date(2026, 1, 1), date(2026, 2, 11), date(2026, 3, 24)]) is not None
        assert service.detecteer_patroon([date(2026, 1, 1), date(2026, 2, 12), date(2026, 3, 26)]) is None
        # Eén uitschieter binnen een verder strak maandpatroon = onregelmatig (nooit gokken).
        assert service.detecteer_patroon(_d((2026, 1, 1), (2026, 2, 1), (2026, 3, 1), (2026, 5, 15))) is None

    def test_verwachting_en_prijsstijging(self) -> None:
        p = service.detecteer_patroon(_d((2026, 1, 3), (2026, 2, 2), (2026, 3, 4)))
        assert p is not None
        verwacht, uiterlijk = service.verwachting(p, date(2026, 3, 4))
        assert verwacht == date(2026, 4, 3) and uiterlijk == date(2026, 4, 14)
        assert service.prijsstijging_pct(Decimal("115.00"), Decimal("100.00"), Decimal("10")) == Decimal("15.00")
        assert (
            service.prijsstijging_pct(Decimal("110.00"), Decimal("100.00"), Decimal("10")) is None
        )  # exact drempel telt niet
        assert service.prijsstijging_pct(Decimal("90.00"), Decimal("100.00"), Decimal("10")) is None
        assert service.prijsstijging_pct(Decimal("-50.00"), Decimal("100.00"), Decimal("10")) is None  # creditnota
        assert service.prijsstijging_pct(None, Decimal("100.00"), Decimal("10")) is None


def _factuur(
    administratie_id: uuid.UUID,
    actor: uuid.UUID,
    opslag,
    *,
    vendor: uuid.UUID,
    datum: date,
    bedrag: str,
    naam: str,
) -> uuid.UUID:
    from app.db.session import scoped_session

    document_id = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=naam,
        inhoud=f"%PDF-1.4 {naam}".encode(),
        actor_id=actor,
        opslag=opslag,
    ).document_id
    with scoped_session(administratie_id, actor_id=actor) as session:
        session.add(
            Boekvoorstel(document_id=document_id, vendor_id=vendor, factuurdatum=datum, totaalbedrag=Decimal(bedrag))
        )
    return document_id


@pytest.fixture
def vendors(admin_engine: Engine, administratie_id: uuid.UUID) -> None:
    with admin_engine.begin() as conn:
        for vid, naam in ((VENDOR_A, "Ziggo Zakelijk"), (VENDOR_B, "Incidentele Leverancier")):
            conn.execute(
                text(
                    "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                    "VALUES (:id, :aid, :naam, '{}') ON CONFLICT DO NOTHING"
                ),
                {"id": vid, "aid": administratie_id, "naam": naam},
            )


class TestHerberekening:
    def test_patroon_ontbreekt_prijsstijging_snooze_afmelden_en_teller(
        self, administratie_id, gescoopte_gebruiker, beheerder_id, opslag, admin_engine, vendors
    ) -> None:
        from app.db.session import scoped_session

        # Ziggo: 4 maandfacturen, laatste 2 april → op 30-08 allang te laat; laatste bedrag +20 %.
        for datum, bedrag in ((date(2026, 1, 2), "100.00"), (date(2026, 2, 3), "100.00"), (date(2026, 3, 2), "100.00")):
            _factuur(
                administratie_id,
                gescoopte_gebruiker,
                opslag,
                vendor=VENDOR_A,
                datum=datum,
                bedrag=bedrag,
                naam=f"z{datum}.pdf",
            )
        laatste_doc = _factuur(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            vendor=VENDOR_A,
            datum=date(2026, 4, 2),
            bedrag="120.00",
            naam="z-apr.pdf",
        )
        # Incidentele leverancier: twee facturen = geen patroon.
        for datum in (date(2026, 1, 10), date(2026, 6, 10)):
            _factuur(
                administratie_id,
                gescoopte_gebruiker,
                opslag,
                vendor=VENDOR_B,
                datum=datum,
                bedrag="50.00",
                naam=f"i{datum}.pdf",
            )

        t = service.herbereken_administratie(administratie_id=administratie_id, vandaag=VANDAAG)
        assert t == {"terugkerend": 1, "ontbreekt": 1, "prijsstijging": 1, "vervallen": 0}
        [s] = service.overzicht(administratie_id=administratie_id, vandaag=VANDAAG)
        assert s.leverancier == "Ziggo Zakelijk" and s.patroon == "maand" and s.aantal_facturen == 4
        assert s.laatste_datum == date(2026, 4, 2) and s.laatste_bedrag == Decimal("120.00")
        assert s.verwacht_op == date(2026, 5, 2) and s.uiterlijk_op == date(2026, 5, 13)
        assert s.status == "ontbreekt" and s.ontbreekt_sinds == date(2026, 5, 13) and s.dagen_te_laat == 109
        assert s.prijsstijging_pct == Decimal("20.00") and s.vorige_bedrag == Decimal("100.00")
        assert s.laatste_document_id == laatste_doc
        # Controlescherm-chip: alleen op het document dat de stijging veroorzaakte.
        chip = service.signaal_voor_document(administratie_id=administratie_id, document_id=laatste_doc)
        assert chip is not None and chip.prijsstijging_pct == Decimal("20.00") and chip.leverancier == "Ziggo Zakelijk"
        # Werkvoorraad-teller (duplicaat-patroon).
        with scoped_session(administratie_id) as session:
            assert service.tel_ontbrekend(session, administratie_id, VANDAAG) == 1
        [klant] = documenten_service.werkvoorraad_overzicht(administratie_ids_met_naam=[(administratie_id, "Test")])
        assert klant.terugkerend_signalen == 1

        # Snooze tot morgen: telt niet; opheffen: telt weer. Afmelden: telt niet, status afgemeld.
        service.snooze(
            administratie_id=administratie_id, vendor_id=VENDOR_A, tot=date(2099, 1, 1), actor_id=gescoopte_gebruiker
        )
        assert service.overzicht(administratie_id=administratie_id, vandaag=VANDAAG)[0].status == "gesnoozed"
        with scoped_session(administratie_id) as session:
            assert service.tel_ontbrekend(session, administratie_id, VANDAAG) == 0
        service.snooze(administratie_id=administratie_id, vendor_id=VENDOR_A, tot=None, actor_id=gescoopte_gebruiker)
        with pytest.raises(service.TerugkerendFout):
            service.snooze(
                administratie_id=administratie_id,
                vendor_id=VENDOR_A,
                tot=date(2020, 1, 1),
                actor_id=gescoopte_gebruiker,
            )
        service.zet_afgemeld(
            administratie_id=administratie_id, vendor_id=VENDOR_A, afgemeld=True, actor_id=gescoopte_gebruiker
        )
        assert service.overzicht(administratie_id=administratie_id, vandaag=VANDAAG)[0].status == "afgemeld"
        with scoped_session(administratie_id) as session:
            assert service.tel_ontbrekend(session, administratie_id, VANDAAG) == 0
        service.zet_afgemeld(
            administratie_id=administratie_id, vendor_id=VENDOR_A, afgemeld=False, actor_id=gescoopte_gebruiker
        )
        with pytest.raises(service.TerugkerendFout):
            service.zet_afgemeld(
                administratie_id=administratie_id, vendor_id=VENDOR_B, afgemeld=True, actor_id=gescoopte_gebruiker
            )

        # Nieuwe factuur komt binnen (mei, zelfde bedrag): signaal 1 verdwijnt vanzelf, stijging weg.
        _factuur(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            vendor=VENDOR_A,
            datum=date(2026, 8, 20),
            bedrag="120.00",
            naam="z-aug.pdf",
        )
        # (augustus ligt te ver ná april voor een strak maandpatroon → patroon vervalt: eerlijk, nooit gokken)
        t = service.herbereken_administratie(administratie_id=administratie_id, vandaag=VANDAAG)
        assert t["vervallen"] == 1 and service.overzicht(administratie_id=administratie_id) == []

    def test_drempel_instelbaar_en_rlz_historie_telt_voor_het_patroon(
        self, administratie_id, gescoopte_gebruiker, beheerder_id, opslag, admin_engine, vendors
    ) -> None:
        # RLZ-historie (boekingsgeheugen) levert de eerdere maanden zonder bedrag; twee app-facturen erbij.
        with admin_engine.begin() as conn:
            for i, datum in enumerate((date(2026, 5, 1), date(2026, 6, 1))):
                conn.execute(
                    text(
                        "INSERT INTO boekhouding.boeking_observatie "
                        "(id, administratie_id, vendor_id, gb_id, bron, bron_datum, boekstuk_ref) "
                        "VALUES (:id, :aid, :vid, :gb, 'rlz_seed', :datum, :ref)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "aid": administratie_id,
                        "vid": VENDOR_A,
                        "gb": uuid.uuid4(),
                        "datum": datum,
                        "ref": f"B{i}",
                    },
                )
        _factuur(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            vendor=VENDOR_A,
            datum=date(2026, 7, 1),
            bedrag="100.00",
            naam="j.pdf",
        )
        laatste = _factuur(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            vendor=VENDOR_A,
            datum=date(2026, 8, 1),
            bedrag="108.00",
            naam="a.pdf",
        )
        service.herbereken_administratie(administratie_id=administratie_id, vandaag=VANDAAG)
        [s] = service.overzicht(administratie_id=administratie_id, vandaag=VANDAAG)
        assert s.aantal_facturen == 4 and s.status == "op_schema" and s.prijsstijging_pct is None  # +8 % < 10 %
        # Drempel naar 5 % (Beheerder): herberekend, stijging zichtbaar op de laatste factuur.
        service.zet_drempel(administratie_id=administratie_id, prijsstijging_pct=Decimal("5"), actor_id=beheerder_id)
        [s] = service.overzicht(administratie_id=administratie_id, vandaag=VANDAAG)
        assert s.prijsstijging_pct == Decimal("8.00") and s.laatste_document_id == laatste
        with pytest.raises(service.TerugkerendFout):
            service.zet_drempel(
                administratie_id=administratie_id, prijsstijging_pct=Decimal("0"), actor_id=beheerder_id
            )


class TestEndpointsEnCli:
    def test_poorten_en_flows(
        self, administratie_id, gescoopte_gebruiker, beheerder_id, admin_engine, opslag, vendors, capsys
    ) -> None:
        from app import cli

        aid = str(administratie_id)
        for datum in (date(2026, 1, 2), date(2026, 2, 3), date(2026, 3, 2)):
            _factuur(
                administratie_id,
                gescoopte_gebruiker,
                opslag,
                vendor=VENDOR_A,
                datum=datum,
                bedrag="100.00",
                naam=f"e{datum}.pdf",
            )
        resp = client.post(
            f"/administraties/{aid}/terugkerend/herbereken", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
        )
        assert resp.status_code == 200 and resp.json()["terugkerend"] == 1
        resp = client.get(f"/administraties/{aid}/terugkerend", headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["prijsstijging_drempel_pct"] == "10.00" and body["signalen"][0]["status"] == "ontbreekt"
        resp = client.post(
            f"/administraties/{aid}/terugkerend/{VENDOR_A}/snooze",
            json={"tot": "2099-01-01"},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 204
        resp = client.post(
            f"/administraties/{aid}/terugkerend/{VENDOR_B}/afmelden",
            json={"afgemeld": True},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 404  # geen patroon voor deze leverancier
        # Drempel = Beheerder-only.
        resp = client.put(
            f"/administraties/{aid}/terugkerend-instelling",
            json={"prijsstijging_pct": "5"},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 403
        resp = client.put(
            f"/administraties/{aid}/terugkerend-instelling",
            json={"prijsstijging_pct": "5"},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200 and resp.json()["prijsstijging_pct"] == "5"
        # Documentchip-route: geen stijging = leeg object, nooit een fout.
        doc = client.get(
            f"/administraties/{aid}/documenten", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
        ).json()["documenten"][0]["id"]
        resp = client.get(
            f"/administraties/{aid}/documenten/{doc}/terugkerend-signaal",
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 200 and resp.json()["prijsstijging_pct"] is None
        # Werkvoorraad-overzicht draagt de teller (gesnoozed → 0).
        resp = client.get("/werkvoorraad/overzicht", headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
        assert resp.status_code == 200
        assert next(k for k in resp.json()["klanten"] if k["administratie_id"] == aid)["terugkerend_signalen"] == 0
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
        assert (
            client.get(
                f"/administraties/{aid}/terugkerend", headers=_bearer(accordeur, rol="klant_accordeur")
            ).status_code
            == 403
        )
        # sync-alles-rapportage: OK-regel per administratie, fout = exit 1.
        assert cli._rapporteer_terugkerend(service.herbereken_alle(vandaag=VANDAAG)) == 0
        assert "terugkerende leveranciers" in capsys.readouterr().out
        assert cli._rapporteer_terugkerend({administratie_id: "boem"}) == 1
