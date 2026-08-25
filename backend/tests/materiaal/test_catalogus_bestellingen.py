"""Materiaalcatalogus + bestellingen (steigerbouw-run D2/D3): seed uit de bestellijst (idempotent,
m²-formule exact als het blad: 331,09 m² voor Peters voorbeeld), Beheerder-only catalogusbeheer,
bestelling concept → verstuurd (PDF + mail, revisie r1) → revisie r2 met delta (update-mail toont
uitsluitend gewijzigde regels oud → nieuw), mailfout = geen revisie, koppeling aan de levering,
zoeken/paginering (C4), audit-keten."""

from __future__ import annotations

import uuid
from datetime import date, time
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.berichten import mail
from app.main import app
from app.materiaal import service as materiaal
from app.materiaal.models import MateriaalTransport
from app.security.tokens import create_access_token
from app.db.session import scoped_session
from app.uren import service as uren_service
from tests.materiaal.conftest import product_id_op_naam
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _audit(admin_engine: Engine, record_id: uuid.UUID) -> list[str]:
    with admin_engine.begin() as conn:
        return [r[0] for r in conn.execute(text("SELECT actie FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip, id"), {"id": record_id})]


def voorbeeld_regels(administratie_id, leverancier_id, beheerder_id) -> dict[str, int]:
    """Peters bestellijst #262651: D18=50 (2 m), D20=150 (3 m), D21=150 (4 m), D22=45, D23=150, D28=10 → 331,09 m²."""
    pid = lambda naam: str(product_id_op_naam(administratie_id, leverancier_id, beheerder_id, naam))  # noqa: E731
    return {
        pid("Steigerbuis tubelock 0,5 mtr"): 8, pid("Steigerbuis tubelock 2 mtr"): 50, pid("Steigerbuis tubelock 3 mtr"): 150,
        pid("Steigerbuis tubelock 4 mtr"): 150, pid("Uitzetkorteling 6 pl."): 45, pid("Uitschuiver 6+3-planks tube-lock"): 150,
        pid("Stalen ladder 3 mtr"): 3, pid("Stalen ladder 4 mtr"): 1, pid("Steigerogen met plug (lang)"): 10, pid("Ankerbuis layher"): 10,
        pid("Kruiskoppeling"): 1000, pid("Draaikoppeling"): 50, pid("Voetplaat tube-lock"): 90, pid("Steigerdelen gekramd 0,5 mtr"): 90,
        pid("Steigerdelen gekramd 2 mtr"): 30, pid("Steigerdelen gekramd 3 mtr"): 30, pid("Steigerdelen gekramd 5 mtr"): 200, pid("Metselboy"): 25,
    }


class TestCatalogus:
    def test_seed_idempotent_en_m2_formule_uit_het_blad(self, administratie_id, beheerder_id, admin_engine):
        r1 = materiaal.seed_universal(administratie_id=administratie_id, actor_id=beheerder_id)
        assert r1.categorieen_nieuw == 13 and r1.producten_nieuw == 53 and r1.producten_bestaand == 0
        r2 = materiaal.seed_universal(administratie_id=administratie_id, actor_id=beheerder_id)
        assert r2.producten_nieuw == 0 and r2.producten_bestaand == 53 and r2.leverancier_id == r1.leverancier_id
        cats = materiaal.catalogus(administratie_id=administratie_id, leverancier_id=r1.leverancier_id, actor_id=beheerder_id)
        assert [c.naam for c in cats][:3] == ["Tubelock", "Ladders", "Verankeringen"]
        assert cats[0].producten[0].nummer == "1.1" and cats[-1].bundel == "trappentoren" and cats[-1].producten[0].nummer.startswith("2.")
        producten = {p.id: p for c in cats for p in c.producten}
        assert materiaal.bereken_m2(voorbeeld_regels(administratie_id, r1.leverancier_id, beheerder_id), producten) == Decimal("331.09")
        assert "materiaal_catalogus_geseed" in _audit(admin_engine, r1.leverancier_id)

    def test_beheer_beheerder_only_en_zoeken_paginering(self, administratie_id, leverancier_id, beheerder_id, admin_engine):
        boekhouder = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=boekhouder, administratie_id=administratie_id)
        uren_service.zet_meerwerk_recht(gebruiker_id=boekhouder, ingeschakeld=True, actor_id=beheerder_id)
        with pytest.raises(uren_service.GeenToegang):
            materiaal.zet_leverancier(administratie_id=administratie_id, actor_id=boekhouder, leverancier_id=None, naam="Floor Liften", bestel_email=None, telefoon=None, adres=None, vendor_id=None)
        lid = materiaal.zet_leverancier(administratie_id=administratie_id, actor_id=beheerder_id, leverancier_id=None, naam="Floor Liften", bestel_email="planning@floorliften.nl", telefoon=None, adres=None, vendor_id=uuid.uuid4())
        cid = materiaal.zet_categorie(administratie_id=administratie_id, actor_id=beheerder_id, leverancier_id=lid, categorie_id=None, naam="Liften", bundel="overig", volgorde=1)
        pid = materiaal.zet_product(administratie_id=administratie_id, actor_id=beheerder_id, leverancier_id=lid, product_id=None, categorie_id=cid, naam="Bouwlift 500 kg", verpakking="st.", eenheid="stuks", m2_lengte=None, volgorde=1)
        items, totaal = materiaal.producten_overzicht(administratie_id=administratie_id, actor_id=boekhouder, leverancier_id=None, zoek="tubelock", pagina=1, per_pagina=3)
        assert totaal == 8 and len(items) == 3 and all("tubelock" in p.naam.lower() or "tubelock" in p.categorie_naam.lower() for p in items)
        items2, _ = materiaal.producten_overzicht(administratie_id=administratie_id, actor_id=boekhouder, leverancier_id=None, zoek="tubelock", pagina=3, per_pagina=3)
        assert len(items2) == 2
        levs = materiaal.leveranciers_overzicht(administratie_id=administratie_id, actor_id=boekhouder, zoek="floor")
        assert [lv.naam for lv in levs] == ["Floor Liften"] and levs[0].aantal_producten == 1
        assert "materiaal_product_gezet" in _audit(admin_engine, pid)
        # API-poorten: veldrol 403 (kantoorrol router-breed), catalogus-PUT Beheerder-only.
        zzper = maak_gebruiker(admin_engine, "zzper", "Milan")
        assert client.get(f"/materiaal/{administratie_id}/leveranciers", headers=_bearer(zzper, rol="zzper")).status_code == 403
        assert client.get(f"/materiaal/{administratie_id}/leveranciers", headers=_bearer(boekhouder, rol="boekhouding")).status_code == 200
        resp = client.put(f"/materiaal/{administratie_id}/leveranciers", json={"naam": "X"}, headers=_bearer(boekhouder, rol="boekhouding"))
        assert resp.status_code == 403
        resp = client.get(f"/materiaal/{administratie_id}/producten?zoek=ladder&per_pagina=10", headers=_bearer(boekhouder, rol="boekhouding"))
        assert resp.status_code == 200 and resp.json()["totaal"] == 2


class TestBestellingen:
    def test_concept_versturen_revisie_delta_en_levering(self, administratie_id, project_id, leverancier_id, beheerder_id, mail_log, admin_engine, _lokale_opslag):
        bid = materiaal.maak_bestelling(administratie_id=administratie_id, actor_id=beheerder_id, project_id=project_id, leverancier_id=leverancier_id)
        detail = materiaal.bestelling_detail(administratie_id=administratie_id, bestelling_id=bid, actor_id=beheerder_id)
        assert detail.nummer.startswith("B-2026-0001") and detail.status == "concept" and detail.revisie == 0
        assert len(detail.regels) == 53 and all(r.was is None for r in detail.regels)  # volledige catalogus in vaste volgorde
        regels = voorbeeld_regels(administratie_id, leverancier_id, beheerder_id)
        with pytest.raises(uren_service.OngeldigeInvoer):
            materiaal.verstuur_bestelling(administratie_id=administratie_id, actor_id=beheerder_id, bestelling_id=bid)  # zonder regels: leeg
        detail = materiaal.werk_concept_bij(
            administratie_id=administratie_id, actor_id=beheerder_id, bestelling_id=bid, regels=regels, gewenste_leverdatum=date(2026, 8, 24),
            gewenste_levertijd=time(7, 0), leveradres="Tweede Bloksweg 42C, Waddinxveen", contactpersoon=None, opmerking=None,
        )
        assert detail.m2_totaal == Decimal("331.09") and detail.aantal_regels == 18
        # r1
        detail = materiaal.verstuur_bestelling(administratie_id=administratie_id, actor_id=beheerder_id, bestelling_id=bid)
        assert detail.status == "verstuurd" and detail.revisie == 1 and not detail.heeft_concept_wijzigingen
        assert len(mail_log) == 1 and mail_log[0]["naar"] == "reijer@universalbv.nl" and "Bestelling B-2026-0001 r1" in mail_log[0]["onderwerp"]
        assert mail_log[0]["bijlagen"][0][0].endswith("-r1.pdf") and mail_log[0]["bijlagen"][0][1].startswith(b"%PDF")
        assert "Kruiskoppeling: 1000" in mail_log[0]["tekst"] and "331.09 m²" in mail_log[0]["tekst"]
        # gekoppelde levering (D3 ↔ D1) op de gewenste leverdatum, status gepland
        assert len(detail.transport_ids) == 1
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            lev = session.get(MateriaalTransport, detail.transport_ids[0])
            assert lev.datum == date(2026, 8, 24) and lev.status == "gepland" and lev.regels == regels
        # opnieuw versturen zonder wijziging = fout (niets te versturen)
        with pytest.raises(uren_service.OngeldigeOvergang):
            materiaal.verstuur_bestelling(administratie_id=administratie_id, actor_id=beheerder_id, bestelling_id=bid)
        # r2: 4 m-buizen 150 → 90, Metselboy 25 → 50 (mockup-popup)
        regels2 = dict(regels)
        regels2[str(product_id_op_naam(administratie_id, leverancier_id, beheerder_id, "Steigerbuis tubelock 4 mtr"))] = 90
        regels2[str(product_id_op_naam(administratie_id, leverancier_id, beheerder_id, "Metselboy"))] = 50
        detail = materiaal.werk_concept_bij(
            administratie_id=administratie_id, actor_id=beheerder_id, bestelling_id=bid, regels=regels2, gewenste_leverdatum=date(2026, 8, 24),
            gewenste_levertijd=time(7, 0), leveradres=detail.leveradres, contactpersoon=None, opmerking=None,
        )
        assert detail.heeft_concept_wijzigingen is True
        was = {r.product.naam: r.was for r in detail.regels if r.was}
        assert was["Steigerbuis tubelock 4 mtr"] == 150 and was["Metselboy"] == 25
        detail = materiaal.verstuur_bestelling(administratie_id=administratie_id, actor_id=beheerder_id, bestelling_id=bid)
        assert detail.revisie == 2 and detail.revisies[1].delta == [
            {"product_id": str(product_id_op_naam(administratie_id, leverancier_id, beheerder_id, "Steigerbuis tubelock 4 mtr")), "naam": "Steigerbuis tubelock 4 mtr", "oud": 150, "nieuw": 90},
            {"product_id": str(product_id_op_naam(administratie_id, leverancier_id, beheerder_id, "Metselboy")), "naam": "Metselboy", "oud": 25, "nieuw": 50},
        ]
        tekst = mail_log[1]["tekst"]
        assert "Steigerbuis tubelock 4 mtr: 150 → 90" in tekst and "Metselboy: 25 → 50" in tekst and "Kruiskoppeling" not in tekst  # alleen gewijzigde regels
        assert "Gewijzigde bestelling" in mail_log[1]["onderwerp"]
        assert detail.revisies[1].m2_totaal == Decimal("278.91")  # 4 m-buizen 60 minder: 331,09 − 60×4/4,6
        # De gekoppelde levering volgt de revisie (nog gepland).
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            lev = session.get(MateriaalTransport, detail.transport_ids[0])
            assert lev.regels == regels2
        # PDF's opgeslagen + leesbaar; audit-keten compleet
        naam, pdf = materiaal.revisie_pdf(administratie_id=administratie_id, actor_id=beheerder_id, bestelling_id=bid, revisie=2)
        assert naam.endswith("-r2.pdf") and b"was 150" in pdf.replace(b"\\(", b"(") or b"150" in pdf
        acties = _audit(admin_engine, bid)
        assert acties.count("bestelling_verstuurd") == 2 and "bestelling_concept_gewijzigd" in acties and acties[0] == "bestelling_aangemaakt"

    def test_mailfout_legt_geen_revisie_vast(self, administratie_id, project_id, leverancier_id, beheerder_id, monkeypatch, admin_engine):
        def _kapot(**kw):
            raise mail.MailFout("SMTP dood")

        monkeypatch.setattr(mail, "verzend_mail", _kapot)
        bid = materiaal.maak_bestelling(administratie_id=administratie_id, actor_id=beheerder_id, project_id=project_id, leverancier_id=leverancier_id)
        regels = voorbeeld_regels(administratie_id, leverancier_id, beheerder_id)
        materiaal.werk_concept_bij(administratie_id=administratie_id, actor_id=beheerder_id, bestelling_id=bid, regels=regels, gewenste_leverdatum=date(2026, 8, 24), gewenste_levertijd=None, leveradres=None, contactpersoon=None, opmerking=None)
        with pytest.raises(materiaal.VerzendenMislukt):
            materiaal.verstuur_bestelling(administratie_id=administratie_id, actor_id=beheerder_id, bestelling_id=bid)
        detail = materiaal.bestelling_detail(administratie_id=administratie_id, bestelling_id=bid, actor_id=beheerder_id)
        assert detail.status == "concept" and detail.revisie == 0 and detail.revisies == [] and detail.transport_ids == []
        assert "bestelling_verzending_mislukt" in _audit(admin_engine, bid)

    def test_overzicht_zoeken_paginering_en_api(self, administratie_id, project_id, tweede_project_id, leverancier_id, beheerder_id, admin_engine):
        for pid in (project_id, tweede_project_id, project_id):
            materiaal.maak_bestelling(administratie_id=administratie_id, actor_id=beheerder_id, project_id=pid, leverancier_id=leverancier_id)
        items, totaal = materiaal.bestellingen_overzicht(administratie_id=administratie_id, actor_id=beheerder_id, zoek="Tilburg")
        assert totaal == 1 and items[0].project_naam == "26021 Tilburg (Heijmans)"
        items, totaal = materiaal.bestellingen_overzicht(administratie_id=administratie_id, actor_id=beheerder_id, pagina=2, per_pagina=2)
        assert totaal == 3 and len(items) == 1
        h = _bearer(beheerder_id, rol="beheerder")
        resp = client.get(f"/materiaal/{administratie_id}/bestellingen?project_id={project_id}", headers=h)
        assert resp.status_code == 200 and resp.json()["totaal"] == 2
        resp = client.post(f"/materiaal/{administratie_id}/bestellingen", json={"project_id": str(project_id), "leverancier_id": str(leverancier_id)}, headers=h)
        assert resp.status_code == 201
        bid = resp.json()["id"]
        resp = client.post(f"/materiaal/{administratie_id}/bestellingen/{bid}/annuleren", json={"reden": "dubbel aangemaakt"}, headers=h)
        assert resp.status_code == 200 and resp.json()["status"] == "geannuleerd"
        resp = client.put(f"/materiaal/{administratie_id}/bestellingen/{bid}/concept", json={"regels": {}}, headers=h)
        assert resp.status_code == 409
