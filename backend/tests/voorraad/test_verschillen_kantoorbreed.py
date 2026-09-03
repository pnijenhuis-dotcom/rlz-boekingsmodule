# ruff: noqa: F811 — pytest-fixtures als parameters (patroon tests/accordering)
"""Inzicht › Voorraad kantoorbreed + werkvoorraad-teller (design-ronde 03-09, blok B3 + C2; mockup
inzicht-kantoorbreed.html ⑤ = bouwnorm, geen migratie). Landing = artikelgroepen buiten tolerantie
over álle voorraad-administraties in scope (zwaarste eerst, facet administratie, zoek op groep,
paginering 25), zelfde motorfunctie voor de teller "Voorraadverschil" op de klantenlijst (0 zonder
opt-in), normalisatie-lijsten server-side gepagineerd. Scope-test met een echte niet-Beheerder mét
scope (conventies §RLS). Code voor cijfers — geen AI, geen RLZ-calls."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import service as documenten_service
from app.main import app
from app.security.tokens import create_access_token
from app.voorraad import service
from app.voorraad.models import (
    ONBEKENDE_LEVERANCIER,
    ArtikelcodeKoppeling,
    Artikelgroep,
    VoorraadRegel,
    VoorraadTelling,
)
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401

client = TestClient(app)
TOT = date(2026, 12, 31)
TELDATUM = date(2026, 8, 28)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _administratie(admin_engine: Engine, naam: str) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, :naam, :rlz)"),
            {"id": aid, "naam": naam, "rlz": f"rlz-{aid}"},
        )
    return aid


def _groep(aid: uuid.UUID, actor: uuid.UUID, naam: str, *, tolerantie: str = "1.00") -> uuid.UUID:
    """Rechtstreeks in de feitenlaag (ook mogelijk zónder opt-in — de motor mag daar niets mee doen)."""
    with scoped_session(aid, actor_id=actor) as session:
        g = Artikelgroep(
            administratie_id=aid, naam=naam, eenheid="st", tolerantie_pct=Decimal(tolerantie), aangemaakt_door=actor
        )
        session.add(g)
        session.flush()
        return g.id


def _regel(
    aid: uuid.UUID,
    groep_id: uuid.UUID | None,
    *,
    richting: str = "in",
    aantal: str | None = "1000",
    datum: date = date(2026, 2, 10),
    soort: str = "artikel",
    status: str = "genormaliseerd",
    tekst: str = "Regel",
    code: str | None = None,
) -> None:
    with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
        session.add(
            VoorraadRegel(
                administratie_id=aid,
                rlz_document_id=uuid.uuid4(),
                rlz_referentie="TEST",
                richting=richting,
                bron="rlz_verkoop",
                datum=datum,
                regel_volgnummer=1,
                artikeltekst=tekst,
                artikelcode=code,
                soort=soort,
                aantal=Decimal(aantal) if aantal is not None else None,
                artikelgroep_id=groep_id,
                normalisatie_status=status,
                normalisatie_zekerheid=Decimal("0.900"),
            )
        )


def _telling(aid: uuid.UUID, groep_id: uuid.UUID, aantal: str, actor: uuid.UUID, datum: date = TELDATUM) -> None:
    with scoped_session(aid, actor_id=actor) as session:
        session.add(
            VoorraadTelling(
                administratie_id=aid,
                artikelgroep_id=groep_id,
                datum=datum,
                aantal=Decimal(aantal),
                ingevoerd_door=actor,
            )
        )


@pytest.fixture
def opstelling(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
) -> dict:
    """Drie administraties: A (opt-in, in scope van de boekhouder), B (opt-in, alleen Beheerder), C (géén
    opt-in maar wél data — mag nergens verschijnen). A: rood (−8,8 %), oranje (−1,5 %), binnen tolerantie,
    geen telling; B: rood (+30 %) = de zwaarste van allemaal."""
    a, b, c = (
        administratie_id,
        _administratie(admin_engine, "Beta B.V."),
        _administratie(admin_engine, "Gamma zonder opt-in"),
    )
    for aid in (a, b):
        beheer_service.zet_voorraad_ingeschakeld(actor_id=beheerder_id, administratie_id=aid, ingeschakeld=True)
    koppelingen = _groep(a, beheerder_id, "Koppelingen 48mm")
    buis = _groep(a, beheerder_id, "Steigerbuis 3m")
    vlonders = _groep(a, beheerder_id, "Vlonders alu")
    planken = _groep(a, beheerder_id, "Planken 5m")
    liften = _groep(b, beheerder_id, "Liften")
    gamma = _groep(c, beheerder_id, "Gamma-groep")
    for g in (koppelingen, buis, vlonders):
        _regel(a, g, aantal="1200")
        _regel(a, g, richting="uit", aantal="200", datum=date(2026, 5, 3))
    # Niet-tellende regels op Koppelingen: dienst, niet-genormaliseerd, zonder aantal, ná `tot`.
    _regel(a, koppelingen, aantal="999", soort="dienst")
    _regel(a, koppelingen, aantal="999", status="niet_genormaliseerd")
    _regel(a, koppelingen, aantal=None)
    _regel(a, koppelingen, aantal="999", datum=date(2027, 1, 5))
    _regel(a, planken, aantal="500")
    _regel(b, liften, aantal="200")
    _regel(c, gamma, aantal="100")
    _telling(a, koppelingen, "912", gescoopte_gebruiker)  # −88 = −8,8 % → rood
    _telling(a, buis, "985", gescoopte_gebruiker)  # −15 = −1,5 % → oranje
    _telling(a, vlonders, "995", gescoopte_gebruiker)  # −0,5 % → binnen tolerantie
    _telling(a, koppelingen, "1000", gescoopte_gebruiker, datum=date(2026, 6, 1))  # oudere telling telt niet
    _telling(b, liften, "260", beheerder_id)  # +30 % → rood
    _telling(c, gamma, "50", beheerder_id)
    return {"a": a, "b": b, "c": c, "koppelingen": koppelingen, "buis": buis, "liften": liften}


class TestMotorPuur:
    def test_zwaarte_en_sortering(self) -> None:
        assert service._zwaarte(verschil_pct=Decimal("-8.80"), tolerantie_pct=Decimal("1.00")) == "rood"
        assert service._zwaarte(verschil_pct=Decimal("4.99"), tolerantie_pct=Decimal("1.00")) == "oranje"
        assert service._zwaarte(verschil_pct=Decimal("5.00"), tolerantie_pct=Decimal("1.00")) == "rood"
        # Ruimere tolerantie schuift de rood-grens mee (5×); tolerantie 0 houdt de ondergrens van 5 %.
        assert service._zwaarte(verschil_pct=Decimal("12.00"), tolerantie_pct=Decimal("3.00")) == "oranje"
        assert service._zwaarte(verschil_pct=Decimal("3.00"), tolerantie_pct=Decimal("0")) == "oranje"
        assert service._zwaarte(verschil_pct=None, tolerantie_pct=Decimal("1.00")) == "rood"  # theoretisch 0
        # Signaalregel (één definitie): theoretisch 0 + telling ≠ 0 = onderzoeken zonder %.
        assert service._signaal(theoretisch=Decimal(0), systeemstand=Decimal(3), tolerantie_pct=Decimal(1)) == (
            Decimal(3),
            None,
            "onderzoeken",
        )
        assert (
            service._signaal(theoretisch=Decimal(100), systeemstand=None, tolerantie_pct=Decimal(1))[2]
            == "geen_telling"
        )


class TestKantoorbreed:
    def test_alleen_opt_in_zwaarste_eerst_facet_zoek_en_paginering(self, opstelling, beheerder_id) -> None:
        administraties = [(opstelling["a"], "Scope-test"), (opstelling["b"], "Beta B.V.")]
        lijst = service.verschillen_kantoorbreed(administraties=administraties, actor_id=beheerder_id, tot=TOT)
        assert [(r.naam, r.zwaarte) for r in lijst.rijen] == [
            ("Liften", "rood"),
            ("Koppelingen 48mm", "rood"),
            ("Steigerbuis 3m", "oranje"),
        ]
        kop = lijst.rijen[1]
        assert (kop.theoretisch, kop.systeemstand, kop.verschil, kop.verschil_pct) == (
            Decimal("1000.000"),
            Decimal("912.000"),
            Decimal("-88.000"),
            Decimal("-8.80"),
        )
        assert kop.telling_datum == TELDATUM and kop.tot == TOT and kop.administratie_naam == "Scope-test"
        assert (lijst.tellers.groepen, lijst.tellers.administraties, lijst.tellers.administraties_met_voorraad) == (
            3,
            2,
            2,
        )
        assert [(f.naam, f.aantal) for f in lijst.facetten] == [("Scope-test", 2), ("Beta B.V.", 1)]
        assert lijst.van == date(2026, 1, 1)
        # Facet administratie (filter, nooit poort) + zoekterm op artikelgroep; tellers blijven ongefilterd.
        gefilterd = service.verschillen_kantoorbreed(
            administraties=administraties, actor_id=beheerder_id, administratie_id=opstelling["a"], tot=TOT
        )
        assert [r.naam for r in gefilterd.rijen] == ["Koppelingen 48mm", "Steigerbuis 3m"] and gefilterd.totaal == 2
        assert gefilterd.tellers.groepen == 3
        zoek = service.verschillen_kantoorbreed(administraties=administraties, actor_id=beheerder_id, q="BUIS", tot=TOT)
        assert [r.naam for r in zoek.rijen] == ["Steigerbuis 3m"]
        # Paginering server-side.
        p1 = service.verschillen_kantoorbreed(
            administraties=administraties, actor_id=beheerder_id, per_pagina=2, tot=TOT
        )
        p2 = service.verschillen_kantoorbreed(
            administraties=administraties, actor_id=beheerder_id, per_pagina=2, pagina=2, tot=TOT
        )
        assert [r.naam for r in p1.rijen] == ["Liften", "Koppelingen 48mm"] and p1.totaal == 3
        assert [r.naam for r in p2.rijen] == ["Steigerbuis 3m"] and (p2.pagina, p2.per_pagina) == (2, 2)

    def test_consistent_met_aansluiting(self, opstelling, beheerder_id) -> None:
        """Eén definitie: de compacte kantoorbrede motor geeft per groep exact dezelfde theoretische
        stand, hetzelfde verschil, % en signaal als het aansluitscherm (`aansluiting`)."""
        a = service.aansluiting(administratie_id=opstelling["a"], van=date(2026, 1, 1), tot=TOT)
        with scoped_session(opstelling["a"], actor_id=beheerder_id) as session:
            rijen = service.verschillen_in_sessie(
                session, administratie_id=opstelling["a"], administratie_naam="A", tot=TOT
            )
        per_groep = {r.artikelgroep_id: r for r in rijen}
        assert set(per_groep) == {g.artikelgroep_id for g in a.groepen if g.signaal == "onderzoeken"}
        for g in a.groepen:
            if g.artikelgroep_id in per_groep:
                r = per_groep[g.artikelgroep_id]
                assert (r.theoretisch, r.verschil, r.verschil_pct) == (g.theoretisch, g.verschil, g.verschil_pct)
                assert r.systeemstand == g.systeemstand and r.telling_datum == g.telling_datum

    def test_werkvoorraad_teller_alleen_bij_opt_in(self, opstelling, beheerder_id) -> None:
        klanten = documenten_service.werkvoorraad_overzicht(
            administratie_ids_met_naam=[(opstelling["a"], "A"), (opstelling["b"], "B"), (opstelling["c"], "C")]
        )
        per_naam = {k.naam: k.voorraad_verschillen for k in klanten}
        assert per_naam == {"A": 2, "B": 1, "C": 0}
        # Signaal-teller: telt bewust niet als "openstaand werk" (zelfde patroon als terugkerend/duplicaat).
        assert not next(k for k in klanten if k.naam == "B").heeft_openstaand_werk
        resp = client.get("/werkvoorraad/overzicht", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 200, resp.text
        rij = next(k for k in resp.json()["klanten"] if k["administratie_id"] == str(opstelling["a"]))
        assert rij["voorraad_verschillen"] == 2


class TestEndpoints:
    def test_scope_niet_beheerder_ziet_alleen_eigen_administraties(
        self, opstelling, gescoopte_gebruiker, beheerder_id
    ) -> None:
        # Boekhouder mét scope op A (niet op B): alleen A-rijen én alleen A in de facetten — groen pad,
        # geen lege lijst door een RLS-misser.
        resp = client.get(
            "/voorraad/verschillen",
            params={"tot": TOT.isoformat()},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [r["naam"] for r in body["rijen"]] == ["Koppelingen 48mm", "Steigerbuis 3m"]
        assert body["tellers"] == {"groepen": 2, "administraties": 1, "administraties_met_voorraad": 1}
        assert [f["naam"] for f in body["facetten"]] == ["Scope-test"]
        assert body["rijen"][0]["zwaarte"] == "rood" and body["rijen"][0]["verschil_pct"] == "-8.80"
        # Facet op een administratie buiten de scope = leeg (filter binnen de scope, nooit een doorbraak).
        resp = client.get(
            "/voorraad/verschillen",
            params={"tot": TOT.isoformat(), "administratie_id": str(opstelling["b"])},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 200 and resp.json()["rijen"] == [] and resp.json()["totaal"] == 0
        # Beheerder ziet alles, zwaarste eerst.
        resp = client.get(
            "/voorraad/verschillen", params={"tot": TOT.isoformat()}, headers=_bearer(beheerder_id, rol="beheerder")
        )
        assert [r["administratie_naam"] for r in resp.json()["rijen"]] == ["Beta B.V.", "Scope-test", "Scope-test"]
        assert (resp.json()["pagina"], resp.json()["per_pagina"], resp.json()["totaal"]) == (1, 25, 3)
        resp = client.get(
            "/voorraad/verschillen/stand",
            params={"tot": TOT.isoformat()},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200 and resp.json() == {
            "groepen": 3,
            "administraties": 2,
            "administraties_met_voorraad": 2,
        }
        resp = client.get(
            "/voorraad/verschillen/stand",
            params={"tot": TOT.isoformat()},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.json() == {"groepen": 2, "administraties": 1, "administraties_met_voorraad": 1}
        # per_pagina boven het maximum = 422; externe rol = 403 (router-brede kantoorpoort).
        resp = client.get(
            "/voorraad/verschillen", params={"per_pagina": 500}, headers=_bearer(beheerder_id, rol="beheerder")
        )
        assert resp.status_code == 422

    def test_normalisatie_lijsten_gepagineerd(self, opstelling, gescoopte_gebruiker, beheerder_id) -> None:
        a, buis = opstelling["a"], opstelling["buis"]
        for i in range(30):
            _regel(a, buis, aantal="1", status="onzeker", tekst=f"Onzekere buis {i}")
        for i in range(3):
            _regel(a, None, aantal="1", soort="dienst", tekst=f"Dienst {i}")
        with scoped_session(a, actor_id=beheerder_id) as session:
            for i in range(3):
                session.add(
                    ArtikelcodeKoppeling(
                        administratie_id=a,
                        richting="uit",
                        vendor_id=ONBEKENDE_LEVERANCIER,
                        code=f"55010{i}",
                        soort="artikel",
                        artikelgroep_id=buis,
                        zekerheid=Decimal("0.900"),
                        bron="ai",
                        voorbeeld_tekst=f"Buis ({i})",
                    )
                )
        kop = _bearer(gescoopte_gebruiker, rol="boekhouding")
        basis = {"van": "2026-01-01", "tot": TOT.isoformat()}
        # Regels: meerdere statussen komma-gescheiden (normalisatie-paneel), LIMIT/OFFSET in de DB.
        resp = client.get(
            f"/administraties/{a}/voorraad/regels",
            params={**basis, "normalisatie_status": "niet_genormaliseerd,onzeker"},
            headers=kop,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body["totaal"], len(body["rijen"]), body["pagina"], body["per_pagina"]) == (31, 25, 1, 25)
        resp = client.get(
            f"/administraties/{a}/voorraad/regels",
            params={**basis, "normalisatie_status": "niet_genormaliseerd,onzeker", "pagina": 2},
            headers=kop,
        )
        assert resp.json()["totaal"] == 31 and len(resp.json()["rijen"]) == 6
        resp = client.get(
            f"/administraties/{a}/voorraad/regels",
            params={**basis, "artikelgroep_id": str(buis), "per_pagina": 10},
            headers=kop,
        )
        assert resp.json()["totaal"] == 32 and len(resp.json()["rijen"]) == 10  # 30 onzeker + in + uit
        resp = client.get(f"/administraties/{a}/voorraad/regels", params={**basis, "per_pagina": 201}, headers=kop)
        assert resp.status_code == 422
        # De interne lijst-functie (tests/CLI) blijft volledig.
        assert len(service.regels(administratie_id=a, van=date(2026, 1, 1), tot=TOT, artikelgroep_id=buis)) == 32
        # Diensten + artikelcodes: gepagineerd ná de sortering.
        resp = client.get(f"/administraties/{a}/voorraad/diensten", params={**basis, "per_pagina": 2}, headers=kop)
        assert resp.status_code == 200 and resp.json()["totaal"] == 4 and len(resp.json()["rijen"]) == 2
        resp = client.get(
            f"/administraties/{a}/voorraad/diensten", params={**basis, "per_pagina": 2, "pagina": 2}, headers=kop
        )
        assert len(resp.json()["rijen"]) == 2 and resp.json()["pagina"] == 2
        resp = client.get(f"/administraties/{a}/voorraad/artikelcodes", params={"per_pagina": 2}, headers=kop)
        assert resp.status_code == 200 and resp.json()["totaal"] == 3 and len(resp.json()["rijen"]) == 2
        resp = client.get(
            f"/administraties/{a}/voorraad/artikelcodes", params={"per_pagina": 2, "pagina": 2}, headers=kop
        )
        assert len(resp.json()["rijen"]) == 1
