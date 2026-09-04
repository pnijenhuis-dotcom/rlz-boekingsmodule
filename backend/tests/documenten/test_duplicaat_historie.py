# ruff: noqa: F811 — pytest-fixtures als parameters
"""Duplicaat over de backend-grens (Odoo-slotstuk 04-09, blok A1-dedup; `app/documenten/duplicaat_historie.py`).

Scenario: een RLZ-administratie is op Odoo overgestapt (kanteldatum, geen poort). Een RLZ-era document is in de app
GEBOEKT (vendor A, btw-nummer NL…, referentie F-…, € 121,00, boekstuk INK-2026-0042). Ná de overstap komt een nakomer
binnen mét een Odoo-partner-UUID (vendor B, zelfde btw-nummer, zelfde referentie + bedrag):
- de harde check `Duplicaatcheck` is rood mét "al geboekt in Reeleezee vóór de overstap (boekstuk INK-2026-0042)";
- `bereken_duplicaatsignaal` → MOGELIJK_DUPLICAAT mét een treffer `bron: app_historie` — óók als de live query faalt;
- `duplicaat_afvoer.verwerk_na_signaal` voert de nakomer af als duplicaat mét origineel bron 'geboekt' + boekstuk;
- ander bedrag → niets; niet-overgestapte administratie → historie niet geraadpleegd (ongewijzigd gedrag)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import boekvoorstel, duplicaat_afvoer, duplicaat_historie, duplicaatsignaal, service
from app.documenten.models import CrediteurKenmerk, DocumentStatus, DuplicaatSignaalUitkomst
from app.documenten.rlz_ids import rlz_herboeking_id
from app.documenten.storage import LokaleBestandsopslag
from app.odoo.ids import odoo_admin_sentinel
from app.odoo.models import OdooKoppeling
from app.security.envelope import wrap_secret
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker, opslag  # noqa: F401
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.documenten.test_vragen import _extra_gebruiker

REF = "F-2026-0042"
TOTAAL = Decimal("121.00")
BTW_NUMMER = "NL123456789B01"
BOEKSTUK = "INK-2026-0042"
VENDOR_RLZ = uuid.UUID("aaaaaaaa-1111-0000-0000-000000000001")  # RLZ-vendor-UUID (vóór de overstap)
VENDOR_ODOO = uuid.UUID("bbbbbbbb-2222-0000-0000-000000000002")  # Odoo-partner-UUID (ná de overstap)


def _upload_met_kop(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    vendor_id: uuid.UUID,
    naam: str,
    referentie: str = REF,
    totaal: Decimal = TOTAAL,
) -> uuid.UUID:
    r = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=naam,
        inhoud=b"%PDF-1.4 " + naam.encode() + uuid.uuid4().bytes,
        actor_id=actor_id,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=r.document_id,
        actor_id=actor_id,
        vendor_id=vendor_id,
        referentie=referentie,
        factuurdatum=date(2026, 8, 20),
        totaalbedrag=totaal,
        regels=[],
    )
    return r.document_id


def _zet_geboekt_in_rlz(admin_engine: Engine, document_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Synthetische RLZ-era GEBOEKT-stand: status + boekstuknummer + tijdlijnrij mét backend rlz."""
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE boekhouding.document SET status = 'geboekt' WHERE id = :id"), {"id": document_id})
        conn.execute(
            text("UPDATE boekhouding.boekvoorstel SET rlz_boekstuknummer = :nr WHERE document_id = :id"),
            {"nr": BOEKSTUK, "id": document_id},
        )
        conn.execute(
            text(
                "INSERT INTO boekhouding.document_gebeurtenis "
                "(id, document_id, van_status, naar_status, actor_id, detail) "
                "VALUES (:id, :d, 'klaar_om_te_boeken', 'geboekt', :a, CAST(:detail AS jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "d": document_id,
                "a": actor_id,
                "detail": '{"backend": "rlz", "rlz_boekstuknummer": "' + BOEKSTUK + '", "reden": "geboekt in RLZ"}',
            },
        )


def _zet_btw(administratie_id: uuid.UUID, vendor_id: uuid.UUID) -> None:
    with scoped_session(administratie_id) as session:
        session.add(
            CrediteurKenmerk(
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                btw_nummer=BTW_NUMMER,
                btw_nummer_geverifieerd=True,
                btw_nummer_bron="factuur",
            )
        )


def _maak_overgestapt(admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> None:
    """De DB-stand ná `koppel_overstap` (zonder probe/sync): backend odoo, sentinel in rlz_admin_id, koppeling mét het
    oude RLZ-id bewaard. Gekopieerd i.p.v. de router-helpers (parallelle-run-afspraak)."""
    url = "https://universal-steigers.odoo.com/"
    with admin_engine.begin() as conn:
        oud = conn.execute(
            text("SELECT rlz_admin_id FROM platform.administratie WHERE id = :id"), {"id": administratie_id}
        ).scalar_one()
        conn.execute(
            text("UPDATE platform.administratie SET boekhoud_backend = 'odoo', rlz_admin_id = :s WHERE id = :id"),
            {"s": odoo_admin_sentinel(url, 1), "id": administratie_id},
        )
    ciphertext, wrapped = wrap_secret(b"sleutel")
    with scoped_session(None, actor_id=beheerder_id) as session:
        session.add(
            OdooKoppeling(
                administratie_id=administratie_id,
                odoo_url=url,
                company_id=1,
                company_naam="Universal Steigerbouw",
                api_key_ciphertext=ciphertext,
                wrapped_data_key=wrapped,
                journal_purchase_id=7,
                overgangsdatum=date(2026, 9, 1),
                rlz_admin_id_voor_overstap=oud,
                aangemaakt_door=beheerder_id,
            )
        )


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


@pytest.fixture
def eigenaar_id(admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> uuid.UUID:
    """De afwijs-route wijst het afgevoerde document toe aan de eigenaar van de administratie (afwijzen.py) — zonder
    eigenaar weigert de afvoer leesbaar (`GeenToewijzingMogelijk`, audit `duplicaat_afvoer_geweigerd`)."""
    gid = _extra_gebruiker(admin_engine, met_scope_op=administratie_id, beheerder_id=beheerder_id)
    beheer_service.zet_eigenaar(actor_id=beheerder_id, administratie_id=administratie_id, eigenaar_gebruiker_id=gid)
    return gid


@pytest.fixture
def rlz_era_geboekt(
    administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag: LokaleBestandsopslag, admin_engine: Engine
) -> uuid.UUID:
    """Het origineel: vóór de overstap geüpload + in RLZ geboekt, ZÓNDER duplicaat_signaal-kop (realistisch voor alles
    wat vóór 25-08 geboekt is) — de bestaande app-groepslogica van `duplicaat_afvoer` kent het dus niet; alleen de
    historie (boekvoorstel) weet ervan. De variant MÉT kop staat in `TestBestaandeGroepslogica`."""
    _zet_btw(administratie_id, VENDOR_RLZ)
    document_id = _upload_met_kop(
        administratie_id=administratie_id,
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
        vendor_id=VENDOR_RLZ,
        naam="origineel-rlz.pdf",
    )
    _zet_geboekt_in_rlz(admin_engine, document_id, gescoopte_gebruiker)
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM boekhouding.duplicaat_signaal WHERE document_id = :id"), {"id": document_id})
    return document_id


@pytest.fixture
def nakomer(
    administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag: LokaleBestandsopslag, rlz_era_geboekt
) -> uuid.UUID:
    """De nakomer: zelfde btw-nummer via een ANDERE (Odoo-)vendor-UUID, zelfde referentie + bedrag. Geüpload terwijl
    de administratie nog RLZ is (geen groep, geen historie → blijft te_controleren); de overstap volgt in de test."""
    _zet_btw(administratie_id, VENDOR_ODOO)
    return _upload_met_kop(
        administratie_id=administratie_id,
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
        vendor_id=VENDOR_ODOO,
        naam="nakomer-odoo.pdf",
    )


class TestHistorieTreffers:
    def test_overgestapt_vindt_rlz_era_origineel_in_facade_vorm(
        self, administratie_id, beheerder_id, admin_engine: Engine, rlz_era_geboekt, nakomer
    ) -> None:
        _maak_overgestapt(admin_engine, administratie_id, beheerder_id)
        with scoped_session(administratie_id) as session:
            assert duplicaat_historie.is_overgestapt(session, administratie_id) is True
            treffers = duplicaat_historie.geboekte_treffers_uit_historie(
                session,
                administratie_id=administratie_id,
                vendor_id=VENDOR_ODOO,
                referentie=REF,
                totaalbedrag=TOTAAL,
                eigen_document_id=nakomer,
            )
        [t] = treffers
        assert t["id"] == str(rlz_herboeking_id(rlz_era_geboekt, 0))
        assert t["ReceiptNumber"] == t["invoice_number"] == BOEKSTUK
        assert t["reference"] == t["Reference"] == REF and t["Status"] == {"id": 2}
        assert t["BaseInvoiceAmount"] == 121.0 and t["Entity"]["id"] == str(VENDOR_RLZ)
        assert t["bron"] == "app_historie" and t["backend"] == "rlz" and t["document_id"] == str(rlz_era_geboekt)

    def test_ander_bedrag_of_andere_crediteur_of_eigen_document_niets(
        self, administratie_id, beheerder_id, admin_engine: Engine, rlz_era_geboekt, nakomer
    ) -> None:
        _maak_overgestapt(admin_engine, administratie_id, beheerder_id)
        vreemde_vendor = uuid.uuid4()  # geen btw-kenmerk → vendor-sleutel ≠ btw-sleutel van het origineel
        with scoped_session(administratie_id) as session:
            basis = dict(administratie_id=administratie_id, referentie=REF, eigen_document_id=nakomer)
            assert (
                duplicaat_historie.geboekte_treffers_uit_historie(
                    session, vendor_id=VENDOR_ODOO, totaalbedrag=Decimal("121.01"), **basis
                )
                == []
            )
            assert (
                duplicaat_historie.geboekte_treffers_uit_historie(
                    session, vendor_id=vreemde_vendor, totaalbedrag=TOTAAL, **basis
                )
                == []
            )
            # Het origineel zelf toetsen: het eigen document telt nooit als treffer van zichzelf.
            assert (
                duplicaat_historie.geboekte_treffers_uit_historie(
                    session,
                    administratie_id=administratie_id,
                    vendor_id=VENDOR_RLZ,
                    referentie=REF,
                    totaalbedrag=TOTAAL,
                    eigen_document_id=rlz_era_geboekt,
                )
                == []
            )

    def test_niet_overgestapte_administratie_raadpleegt_de_historie_niet(
        self, administratie_id, admin_engine: Engine, rlz_era_geboekt, nakomer
    ) -> None:
        """RLZ-administratie: de live RLZ-query dekt alles — gedrag ongewijzigd, ook mét een matchend geboekt
        document."""
        with scoped_session(administratie_id) as session:
            assert duplicaat_historie.is_overgestapt(session, administratie_id) is False
            assert (
                duplicaat_historie.geboekte_treffers_uit_historie(
                    session,
                    administratie_id=administratie_id,
                    vendor_id=VENDOR_ODOO,
                    referentie=REF,
                    totaalbedrag=TOTAAL,
                    eigen_document_id=nakomer,
                )
                == []
            )
        data = duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id, document_id=nakomer, client=FakeBoekClient(duplicaten=[])
        )
        assert data is not None and data.uitkomst == DuplicaatSignaalUitkomst.GEEN and data.treffers == []
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=nakomer, client=FakeBoekClient(duplicaten=[])
        )
        dup = next(r for r in rapport.resultaten if r.naam == "Duplicaatcheck")
        assert dup.ok is True

    def test_nieuwe_odoo_administratie_zonder_rlz_verleden_is_niet_overgestapt(
        self, administratie_id, beheerder_id, admin_engine: Engine
    ) -> None:
        _maak_overgestapt(admin_engine, administratie_id, beheerder_id)
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE platform.odoo_koppeling SET rlz_admin_id_voor_overstap = NULL WHERE administratie_id = :id"
                ),
                {"id": administratie_id},
            )
        with scoped_session(administratie_id) as session:
            assert duplicaat_historie.is_overgestapt(session, administratie_id) is False


class TestHardeCheck:
    def test_check_rood_met_boekstuk_ook_al_ziet_de_live_query_niets(
        self, administratie_id, beheerder_id, admin_engine: Engine, rlz_era_geboekt, nakomer
    ) -> None:
        _maak_overgestapt(admin_engine, administratie_id, beheerder_id)
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=nakomer, client=FakeBoekClient(duplicaten=[])
        )
        dup = next(r for r in rapport.resultaten if r.naam == "Duplicaatcheck")
        assert dup.ok is False and rapport.geblokkeerd
        assert dup.melding == (
            f"1 factuur met dezelfde crediteur, referentie en bedrag al geboekt in Reeleezee vóór de overstap "
            f"(boekstuk {BOEKSTUK})"
        )

    def test_storings_tak_draagt_het_boekstuk_ook(
        self, administratie_id, beheerder_id, admin_engine: Engine, rlz_era_geboekt, nakomer, monkeypatch
    ) -> None:
        """Odoo onbereikbaar (verbinding opent niet) → de duplicaatcheck is sowieso rood, maar het bekende RLZ-duplicaat
        verdwijnt niet achter die storing."""
        _maak_overgestapt(admin_engine, administratie_id, beheerder_id)

        def kapot(*a, **kw):
            raise RuntimeError("Odoo onbereikbaar (simulatie)")

        monkeypatch.setattr(boekvoorstel, "inkoop_port_voor", kapot)
        rapport = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=nakomer)
        dup = next(r for r in rapport.resultaten if r.naam == "Duplicaatcheck")
        assert dup.ok is False
        assert "Odoo onbereikbaar" in dup.melding and f"boekstuk {BOEKSTUK}" in dup.melding


class TestSignaalEnAfvoer:
    def test_signaal_mogelijk_duplicaat_met_historie_treffer(
        self, administratie_id, beheerder_id, admin_engine: Engine, rlz_era_geboekt, nakomer
    ) -> None:
        _maak_overgestapt(admin_engine, administratie_id, beheerder_id)
        data = duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id, document_id=nakomer, client=FakeBoekClient(duplicaten=[])
        )
        assert data is not None and data.uitkomst == DuplicaatSignaalUitkomst.MOGELIJK_DUPLICAAT
        [t] = data.treffers
        assert t["bron"] == "app_historie" and t["document_id"] == str(rlz_era_geboekt)
        assert t["invoice_number"] == BOEKSTUK and t["status"] == 2 and t["backend"] == "rlz"
        assert "1 al geboekt in Reeleezee vóór de overstap" in (data.melding or "")

    def test_live_query_faalt_maar_historie_is_hard(
        self, administratie_id, beheerder_id, admin_engine: Engine, rlz_era_geboekt, nakomer
    ) -> None:
        _maak_overgestapt(admin_engine, administratie_id, beheerder_id)

        class _Kapot:
            def find_purchase_invoices_by_reference(self, **kw):
                raise RuntimeError("Odoo onbereikbaar")

        data = duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id, document_id=nakomer, client=_Kapot()
        )
        assert data is not None and data.uitkomst == DuplicaatSignaalUitkomst.MOGELIJK_DUPLICAAT
        assert [t["bron"] for t in data.treffers] == ["app_historie"]

    def test_dedup_op_id_met_de_live_facade(
        self, administratie_id, beheerder_id, admin_engine: Engine, rlz_era_geboekt, nakomer
    ) -> None:
        """Meldt de live query hetzelfde deterministische id (Odoo-era eigen document), dan telt het één keer."""
        _maak_overgestapt(admin_engine, administratie_id, beheerder_id)
        eigen_id = str(rlz_herboeking_id(rlz_era_geboekt, 0))
        data = duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id,
            document_id=nakomer,
            client=FakeBoekClient(duplicaten=[{"id": eigen_id, "Reference": REF, "InvoiceNumber": "BILL/1"}]),
        )
        assert data is not None and len(data.treffers) == 1

    def test_auto_afvoer_als_duplicaat_van_het_rlz_origineel_via_de_historie_treffer(
        self, administratie_id, beheerder_id, eigenaar_id, admin_engine: Engine, rlz_era_geboekt, nakomer
    ) -> None:
        """Het origineel heeft geen signaal-kop (RLZ-era): de groep bestaat uit de nakomer + de historie-treffer →
        origineel = het app-document uit die treffer (bron 'geboekt', boekstuk, bestandsnaam), nakomer afgevoerd."""
        _maak_overgestapt(admin_engine, administratie_id, beheerder_id)
        assert _status(admin_engine, nakomer) == DocumentStatus.TE_CONTROLEREN.value
        duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id, document_id=nakomer, client=FakeBoekClient(duplicaten=[])
        )
        afgevoerd = duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=nakomer)
        assert afgevoerd == [nakomer]
        assert _status(admin_engine, nakomer) == DocumentStatus.AFGEWEZEN.value
        assert _status(admin_engine, rlz_era_geboekt) == DocumentStatus.GEBOEKT.value  # origineel ongemoeid
        stand = duplicaat_afvoer.stand_voor_document(administratie_id=administratie_id, document_id=nakomer)
        o = stand.afgevoerd_als_duplicaat_van
        assert o is not None and o.bron == "geboekt" and o.document_id == rlz_era_geboekt
        assert o.boekstuknummer == BOEKSTUK and o.bestandsnaam == "origineel-rlz.pdf"
        assert o.rlz_document_id == rlz_herboeking_id(rlz_era_geboekt, 0)
        with admin_engine.connect() as conn:
            reden = conn.execute(
                text("SELECT reden FROM boekhouding.afwijzing WHERE document_id = :id"), {"id": nakomer}
            ).scalar_one()
        assert reden.startswith(f"Duplicaat van {REF} (boekstuk {BOEKSTUK} / document origineel-rlz.pdf")
        assert reden.endswith("al geboekt)")
        # Origineel-kant: de kruisverwijzing wijst terug naar de nakomer.
        stand_o = duplicaat_afvoer.stand_voor_document(administratie_id=administratie_id, document_id=rlz_era_geboekt)
        assert [d.document_id for d in stand_o.afgevoerde_duplicaten] == [nakomer]

    def test_zonder_overstap_geen_afvoer_ondanks_dezelfde_kop(
        self, administratie_id, eigenaar_id, admin_engine: Engine, rlz_era_geboekt, nakomer
    ) -> None:
        """RLZ-administratie mét een origineel zonder signaal-kop: de historie wordt niet geraadpleegd, de live query
        (hier leeg) beslist — ongewijzigd gedrag."""
        duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id, document_id=nakomer, client=FakeBoekClient(duplicaten=[])
        )
        assert duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=nakomer) == []
        assert _status(admin_engine, nakomer) == DocumentStatus.TE_CONTROLEREN.value

    def test_ander_bedrag_geen_signaal_geen_afvoer(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, admin_engine: Engine, rlz_era_geboekt
    ) -> None:
        _zet_btw(administratie_id, VENDOR_ODOO)
        andere = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=VENDOR_ODOO,
            naam="ander-bedrag.pdf",
            totaal=Decimal("121.01"),
        )
        _maak_overgestapt(admin_engine, administratie_id, beheerder_id)
        data = duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id, document_id=andere, client=FakeBoekClient(duplicaten=[])
        )
        assert data is not None and data.uitkomst == DuplicaatSignaalUitkomst.GEEN
        assert duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=andere) == []
        assert _status(admin_engine, andere) == DocumentStatus.TE_CONTROLEREN.value


class TestBestaandeGroepslogica:
    def test_origineel_met_signaalkop_wordt_al_bij_upload_afgevoerd_historie_dedupt(
        self,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        eigenaar_id,
        opslag,
        admin_engine: Engine,
    ) -> None:
        """Origineel MÉT signaal-kop (geboekt ná 25-08): de bestaande app-groepslogica (zelfde btw-nummer, referentie,
        bedrag; geboekt lid = origineel) voert de nakomer al af in de upload-hook — óók vóór/zonder overstap. Ná de
        overstap komt de historie-treffer er dubbel bij in het signaal (zelfde id → één treffer) en verandert het
        origineel niet."""
        _zet_btw(administratie_id, VENDOR_RLZ)
        _zet_btw(administratie_id, VENDOR_ODOO)
        origineel = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=VENDOR_RLZ,
            naam="origineel-met-kop.pdf",
        )
        _zet_geboekt_in_rlz(admin_engine, origineel, gescoopte_gebruiker)
        nakomer = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=VENDOR_ODOO,
            naam="nakomer.pdf",
        )
        assert _status(admin_engine, nakomer) == DocumentStatus.AFGEWEZEN.value
        _maak_overgestapt(admin_engine, administratie_id, beheerder_id)
        with scoped_session(administratie_id) as session:
            treffers = duplicaat_historie.geboekte_treffers_uit_historie(
                session,
                administratie_id=administratie_id,
                vendor_id=VENDOR_ODOO,
                referentie=REF,
                totaalbedrag=TOTAAL,
                eigen_document_id=nakomer,
            )
        assert [t["document_id"] for t in treffers] == [str(origineel)]
        o = duplicaat_afvoer.stand_voor_document(
            administratie_id=administratie_id, document_id=nakomer
        ).afgevoerd_als_duplicaat_van
        assert o is not None and o.bron == "geboekt" and o.document_id == origineel and o.boekstuknummer == BOEKSTUK
