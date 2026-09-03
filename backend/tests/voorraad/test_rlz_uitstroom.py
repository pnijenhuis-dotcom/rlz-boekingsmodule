# ruff: noqa: F811 — pytest-fixtures als parameters (patroon tests/voorraad)
"""Voorraad-uitstroom uit RLZ-verkoopfacturen (blok A 29-08, migratie 0087, STAP-0 groen —
api-verkenning "Voorraad-uitstroom STAP-0"): leesroute strikt GET-only, alleen geboekte facturen
(Status 2/3), creditregels via het teken in Quantity, dedupe met in de app geboekte verkoop, vervangen
per factuur (idempotent), storno ruimt op, incrementeel venster, normalisatie via dezelfde motor,
zichtbaar in aansluiting/drill-down (bron per kolom, RLZ-referentie), herreken zonder RLZ-calls, CLI-
rapportage. Fake RLZ-client — geen netwerk."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.main import app
from app.rlz.credentials import GeenRlzCredentials
from app.security.tokens import create_access_token
from app.voorraad import rlz_uitstroom, service
from app.voorraad.models import VoorraadRegel
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.voorraad.test_voorraad import _FakeAi, fake_ai, voorraad_aan  # noqa: F401

client = TestClient(app)

F_GEBOEKT = "11111111-aaaa-4aaa-8aaa-000000000001"
F_CREDIT = "11111111-aaaa-4aaa-8aaa-000000000002"
F_CONCEPT = "11111111-aaaa-4aaa-8aaa-000000000003"
F_IN_APP = "11111111-aaaa-4aaa-8aaa-000000000004"


def _kop(fid: str, datum: str, status: int, *, referentie: str | None, credit: bool = False) -> dict[str, Any]:
    """Kopvorm zoals de SalesInvoices-collectie 'm levert (STAP-0 29-08)."""
    return {
        "id": fid,
        "Date": f"{datum}T00:00:00",
        "BookDate": f"{datum}T00:00:00",
        "Status": status,
        "IsCreditInvoice": credit,
        "Reference": referentie,
        "InvoiceNumber": int(referentie) if referentie else None,
        "Entity": {"id": "e1", "Name": "Bouwbedr.Gebr. Kanters BV"},
    }


def _regel(seq: int, description: str, quantity: float, price: float, net: float) -> dict[str, Any]:
    return {"Sequence": seq, "Description": description, "Quantity": quantity, "Price": price, "NetAmount": net}


class _FakeRlz:
    """Duck-typed RlzClient: alleen `get` (de motor mag niets anders aanroepen) + `close`."""

    def __init__(self, koppen: list[dict[str, Any]], regels: dict[str, list[dict[str, Any]]]) -> None:
        self.koppen = koppen
        self.regels = regels
        self.aanroepen: list[tuple[str, dict[str, Any] | None]] = []
        self.gesloten = False

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        self.aanroepen.append((path, params))
        if path == "SalesInvoices":
            assert params is not None and params["$filter"].startswith("Date ge ") and params["$filter"].endswith("Z")
            vanaf = date.fromisoformat(params["$filter"].split("Date ge ")[1][:10])
            rijen = [k for k in self.koppen if date.fromisoformat(k["Date"][:10]) >= vanaf]
            rijen.sort(key=lambda k: (k["Date"], k["id"]))
            skip, top = int(params["$skip"]), int(params["$top"])
            return {"value": rijen[skip : skip + top]}
        if path.startswith("SalesInvoices/") and path.endswith("/Lines"):
            return {"value": self.regels[path.split("/")[1]]}
        raise AssertionError(f"onverwachte GET {path}")

    def __getattr__(self, naam: str) -> Any:  # elke niet-GET-methode = fout (read-only-garantie)
        raise AssertionError(f"RLZ-write of onbekende aanroep in de leesroute: {naam}")

    def close(self) -> None:
        self.gesloten = True


@pytest.fixture
def fake_rlz(monkeypatch: pytest.MonkeyPatch) -> _FakeRlz:
    koppen = [
        _kop(F_GEBOEKT, "2026-08-28", 2, referentie="50212273"),
        _kop(F_CREDIT, "2026-08-19", 3, referentie="50212199", credit=True),
        _kop(F_CONCEPT, "2026-08-28", 1, referentie=None),
        _kop(F_IN_APP, "2026-08-20", 2, referentie="90006"),
    ]
    regels = {
        F_GEBOEKT: [
            _regel(1, "Steigerbuis 4 mtr incl. tube-connect (550100.210)", 610.0, 20.1, 12261.0),
            _regel(2, "Transportkosten", 1.0, 150.0, 150.0),
            _regel(3, "Koppeling draaibaar 48", 2000.0, 4.5, 9000.0),
        ],
        F_CREDIT: [
            # Teken zit in Quantity (bewezen): −30 × 65,00 = −1.950,00; gratis-regel Q=8 × 0 = 0.
            _regel(1, "Koppeling draaibaar 48", -30.0, 65.0, -1950.0),
            _regel(2, "Gebr. Steigerbuis 1 mtr (Gebr.550100.6 )", 8.0, 0.0, 0.0),
            # Spiegelvorm-vangnet: positief aantal × negatieve prijs → aantal negatief.
            _regel(3, "Koppeling draaibaar 48", 5.0, -4.5, -22.5),
        ],
        F_CONCEPT: [_regel(1, "Koppeling draaibaar 48", 1.0, 1.0, 1.0)],
        F_IN_APP: [_regel(1, "Koppeling draaibaar 48", 999.0, 1.0, 999.0)],
    }
    fake = _FakeRlz(koppen, regels)
    monkeypatch.setattr(rlz_uitstroom, "_open_client", lambda administratie_id, client: (fake, True))
    return fake


def _rlz_regels(administratie_id: uuid.UUID) -> list[VoorraadRegel]:
    from app.db.session import scoped_session

    with scoped_session(administratie_id) as session:
        rijen = list(
            session.scalars(
                select(VoorraadRegel).where(
                    VoorraadRegel.administratie_id == administratie_id, VoorraadRegel.bron == "rlz_verkoop"
                )
            )
        )
        session.expunge_all()
        return sorted(rijen, key=lambda r: (str(r.rlz_document_id), r.regel_volgnummer))


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


class TestPuur:
    def test_aantal_teken_en_vangnet(self) -> None:
        assert rlz_uitstroom._aantal({"Quantity": -30, "Price": 65.0, "NetAmount": -1950.0}) == Decimal("-30")
        assert rlz_uitstroom._aantal({"Quantity": 5, "Price": -4.5, "NetAmount": -22.5}) == Decimal("-5")
        assert rlz_uitstroom._aantal({"Quantity": 8, "Price": 0, "NetAmount": 0}) == Decimal("8")
        assert rlz_uitstroom._aantal({"Quantity": 4.5, "Price": 59.0, "NetAmount": 265.5}) == Decimal("4.5")
        assert rlz_uitstroom._aantal({"Price": 1.0}) is None
        assert rlz_uitstroom._datum({"Date": "2026-08-28T00:00:00"}) == date(2026, 8, 28)
        assert rlz_uitstroom._debiteur({"Entity": {"Name": "X BV"}}) == "X BV"
        assert rlz_uitstroom._debiteur({"Entity": None}) is None


class TestLeesroute:
    def test_toggle_uit_leest_niets(self, administratie_id, fake_rlz) -> None:
        telling = rlz_uitstroom.sync_rlz_verkoopregels(administratie_id=administratie_id)
        assert telling.vanaf is None and telling.facturen_gelezen == 0
        assert fake_rlz.aanroepen == []

    def test_verkoopmodule_afwezig_slaat_zichtbaar_over_zonder_rlz_calls(
        self, administratie_id, admin_engine, voorraad_aan, fake_rlz
    ) -> None:
        """Facturatiemodule niet afgenomen (01-09): SalesInvoices geeft daar altijd 403 — de
        leesroute slaat de administratie over mét zichtbare reden, nooit stil stuklopen."""
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET verkoopmodule_afwezig = true WHERE id = :id"),
                {"id": administratie_id},
            )
        telling = rlz_uitstroom.sync_rlz_verkoopregels(administratie_id=administratie_id)
        assert telling.overgeslagen_reden == "facturatiemodule niet afgenomen (RLZ)"
        assert telling.als_dict()["overgeslagen_reden"] == "facturatiemodule niet afgenomen (RLZ)"
        assert fake_rlz.aanroepen == []

    def test_geboekt_credit_concept_in_app_en_idempotent(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, admin_engine, voorraad_aan, fake_ai, fake_rlz
    ) -> None:
        # In-app geboekte verkoop (verkoop_boeking.verkoop_rlz_id) = al onder bron verkoop_regel → skip.
        from app.documenten import service as documenten_service

        doc_id = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="v.pdf",
            inhoud=b"%PDF-1.4 verkoop",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        ).document_id
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.document SET soort = 'verkoopfactuur', status = 'geboekt' WHERE id = :id"),
                {"id": doc_id},
            )
            conn.execute(
                text(
                    "INSERT INTO boekhouding.verkoop_boeking (id, administratie_id, document_id, factuurnummer, "
                    "is_creditnota, totaalbedrag_incl, debiteur_customer_id, debiteur_naam, verkoop_rlz_id, status, "
                    "geboekt_door) VALUES (:id, :aid, :doc, 'V-1', false, 1, :cust, 'Huurder', :rlz, 'geboekt', :actor)"
                ),
                {
                    "id": uuid.uuid4(),
                    "aid": administratie_id,
                    "doc": doc_id,
                    "cust": uuid.uuid4(),
                    "rlz": uuid.UUID(F_IN_APP),
                    "actor": gescoopte_gebruiker,
                },
            )

        telling = rlz_uitstroom.sync_rlz_verkoopregels(administratie_id=administratie_id)
        assert telling.vanaf == date(date.today().year, 1, 1)
        assert telling.facturen_gelezen == 4
        assert telling.facturen_verwerkt == 2 and telling.overgeslagen_concept == 1 and telling.overgeslagen_in_app == 1
        assert telling.regels == 6
        # Read-only: uitsluitend GET's op de collectie + Lines van de twee geboekte facturen.
        paden = [p for p, _ in fake_rlz.aanroepen]
        assert paden.count("SalesInvoices") == 1
        assert sorted(p for p in paden if p.endswith("/Lines")) == sorted(
            [f"SalesInvoices/{F_GEBOEKT}/Lines", f"SalesInvoices/{F_CREDIT}/Lines"]
        )
        assert fake_rlz.gesloten is True

        rijen = _rlz_regels(administratie_id)
        assert len(rijen) == 6 and all(r.document_id is None and r.richting == "uit" for r in rijen)
        per_factuur = {
            str(r.rlz_document_id): [x for x in rijen if x.rlz_document_id == r.rlz_document_id] for r in rijen
        }
        geboekt = sorted(per_factuur[F_GEBOEKT], key=lambda r: r.regel_volgnummer)
        assert [r.aantal for r in geboekt] == [Decimal("610.000"), Decimal("1.000"), Decimal("2000.000")]
        assert geboekt[0].rlz_referentie == "50212273" and geboekt[0].relatie_naam == "Bouwbedr.Gebr. Kanters BV"
        assert geboekt[0].datum == date(2026, 8, 28) and geboekt[0].prijs == Decimal("20.1000")
        assert geboekt[0].eenheid is None  # RLZ kent geen eenheidsveld op de regel (STAP-0)
        # v2: artikelcode uit de Description als sleutel (richting 'uit'); transport = soort-label, geen AI.
        assert geboekt[0].artikelcode == "550100.210" and geboekt[0].soort == "artikel"
        assert geboekt[1].soort == "transport" and geboekt[1].normalisatie_status == "genormaliseerd"
        assert geboekt[1].artikelcode is None
        assert geboekt[2].normalisatie_status == "genormaliseerd" and geboekt[2].artikelgroep_id is not None
        credit = sorted(per_factuur[F_CREDIT], key=lambda r: r.regel_volgnummer)
        assert [r.aantal for r in credit] == [Decimal("-30.000"), Decimal("8.000"), Decimal("-5.000")]
        assert credit[1].artikelcode == "550100.6"  # "(Gebr.550100.6 )" — gebruikt = zelfde code
        codes = {(k.richting, k.code) for k in service.artikelcodes(administratie_id=administratie_id)}
        assert codes == {("uit", "550100.210"), ("uit", "550100.6")}
        assert credit[0].netto_bedrag == Decimal("-1950.00")
        assert credit[0].artikelgroep_id == geboekt[2].artikelgroep_id  # zelfde regel, geen 2e AI-call
        # Eén AI-call per factuur voor uitsluitend de nog onbekende teksten: "Koppeling draaibaar 48"
        # komt in de tweede call niet meer voor (regel bestaat), Transportkosten nooit (dienst-regel).
        assert len(fake_ai.aanroepen) == 2
        assert sum("Koppeling draaibaar 48" in a for a in fake_ai.aanroepen) == 1
        assert not any("Transportkosten" in a for a in fake_ai.aanroepen)

        # Aansluiting: verkoop = 2000 − 30 − 5 (credit telt als retour); bron per kolom benoemt RLZ.
        groep = next(g for g in service.groepen(administratie_id=administratie_id) if g.naam == "Koppelingen 48mm")
        a = service.aansluiting(administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        g = next(x for x in a.groepen if x.artikelgroep_id == groep.id)
        assert g.verkoop == Decimal("1965.000") and g.regels_uit == 3
        assert "RLZ-verkoopfacturen" in a.bronnen["verkoop"] and "verkoop_rlz" in a.bronnen
        assert a.transport_regels == 1  # "Transportkosten" blijft als feit bewaard, telt niet
        drill = service.regels(
            administratie_id=administratie_id, van=date(2026, 1, 1), tot=date(2026, 12, 31), artikelgroep_id=groep.id
        )
        assert all(r.document_id is None and r.rlz_document_id is not None for r in drill)
        assert {r.rlz_referentie for r in drill} == {"50212273", "50212199"}

        # Idempotent: nogmaals draaien vervangt per factuur — geen dubbele regels, zelfde aantallen.
        telling2 = rlz_uitstroom.sync_rlz_verkoopregels(administratie_id=administratie_id)
        assert telling2.regels == 6 and len(_rlz_regels(administratie_id)) == 6
        # Incrementeel: vanaf = jongste geregistreerde datum − 14 dagen.
        assert telling2.vanaf == date(2026, 8, 28) - timedelta(days=14)
        laatste_collectie = [pr for pad, pr in fake_rlz.aanroepen if pad == "SalesInvoices"][-1]
        assert laatste_collectie["$filter"] == f"Date ge {telling2.vanaf.isoformat()}T00:00:00Z"

        # Storno in RLZ: de geboekte factuur wordt concept → haar regels verdwijnen bij de volgende run.
        fake_rlz.koppen[0]["Status"] = 1
        telling3 = rlz_uitstroom.sync_rlz_verkoopregels(administratie_id=administratie_id)
        assert telling3.verwijderd_na_storno == 3 and telling3.overgeslagen_concept == 2
        assert {str(r.rlz_document_id) for r in _rlz_regels(administratie_id)} == {F_CREDIT}

    def test_volledig_en_herreken_zonder_rlz_calls(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, voorraad_aan, fake_ai, fake_rlz
    ) -> None:
        rlz_uitstroom.sync_rlz_verkoopregels(administratie_id=administratie_id)
        aanroepen_na_sync = len(fake_rlz.aanroepen)
        telling = service.herreken_administratie(administratie_id=administratie_id, actor_id=gescoopte_gebruiker)
        assert telling["rlz_regels"] == 7  # incl. de F_IN_APP-factuur (hier geen in-app-boeking)
        assert len(fake_rlz.aanroepen) == aanroepen_na_sync  # herreken = lokaal, nooit een RLZ-lees-lus
        volledig = rlz_uitstroom.sync_rlz_verkoopregels(administratie_id=administratie_id, volledig=True)
        assert volledig.vanaf == date(date.today().year, 1, 1)

    def test_endpoint_regels_met_rlz_herkomst(
        self, administratie_id, gescoopte_gebruiker, voorraad_aan, fake_ai, fake_rlz
    ) -> None:
        rlz_uitstroom.sync_rlz_verkoopregels(administratie_id=administratie_id)
        resp = client.get(
            f"/administraties/{administratie_id}/voorraad/regels",
            params={"van": "2026-01-01", "tot": "2026-12-31"},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 200, resp.text
        rij = next(r for r in resp.json()["rijen"] if r["bron"] == "rlz_verkoop" and r["rlz_referentie"] == "50212273")
        assert rij["document_id"] is None and rij["rlz_document_id"] == F_GEBOEKT
        resp = client.post(
            f"/administraties/{administratie_id}/voorraad/herreken",
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 200 and resp.json()["rlz_regels"] == 7

    def test_sync_alle_en_cli_rapportage(
        self, administratie_id, beheerder_id, voorraad_aan, fake_ai, fake_rlz, monkeypatch, capsys
    ) -> None:
        from app import cli

        resultaten = rlz_uitstroom.sync_alle_voorraad_administraties()
        assert isinstance(resultaten[administratie_id], rlz_uitstroom.RlzUitstroomTelling)
        assert cli._rapporteer_voorraad_rlz(resultaten) == 0
        assert "facturen gelezen" in capsys.readouterr().out
        # Geen credential = overgeslagen (exit 0); échte fout = exit 1.
        assert cli._rapporteer_voorraad_rlz({administratie_id: GeenRlzCredentials("geen prefix")}) == 0
        assert cli._rapporteer_voorraad_rlz({administratie_id: "boem"}) == 1
        # Eén kapotte administratie stopt de rest niet.
        monkeypatch.setattr(
            rlz_uitstroom, "sync_rlz_verkoopregels", lambda **kw: (_ for _ in ()).throw(RuntimeError("RLZ 500"))
        )
        assert rlz_uitstroom.sync_alle_voorraad_administraties()[administratie_id] == "RLZ 500"
