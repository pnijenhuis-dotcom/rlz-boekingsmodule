# ruff: noqa: F811 — pytest-fixtures als parameters
"""Service activa fase 1: plannen → ná boeken aanmaken in RLZ (FakeBoekClient), overslaan mét reden, automatisch opt-in
(afwezig-pad-marker), ontbrekende afschrijvingsrekening = zichtbaar mislukt, storno → beoordelen, idempotent
client-GUID,
orkestratie-hook ná een geslaagde boeking."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.activa import service
from app.activa.models import ActivaInstelling
from app.db.session import scoped_session
from app.documenten import boeken, tegenboeken
from app.documenten.storage import LokaleBestandsopslag
from app.doorbelasting import orkestratie
from tests.activa.conftest import (
    GB_0107,
    GB_0108,
    GB_0170,
    audit_acties,
    koppelingen,
    maak_factuur,
    regel,
    tijdlijn_teksten,
)
from tests.documenten.fake_rlz_client import FakeBoekClient


def _zet_instelling(administratie_id: uuid.UUID, **velden) -> None:  # noqa: ANN003
    with scoped_session(administratie_id) as session:
        rij = session.get(ActivaInstelling, administratie_id)
        if rij is None:
            rij = ActivaInstelling(administratie_id=administratie_id)
            session.add(rij)
        for k, v in velden.items():
            setattr(rij, k, v)


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


class TestPlannenEnOverslaan:
    def test_plannen_voor_boeken_legt_velden_vast_met_tijdlijn_en_audit(
        self, factuur: uuid.UUID, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        data = service.plan_of_maak_aan(
            administratie_id=administratie_id,
            document_id=factuur,
            regel_volgnummer=1,
            actor_id=gescoopte_gebruiker,
            afschrijving_ledger_id=GB_0108,
        )
        k = data.kandidaten[0]
        assert k.koppeling is not None and k.koppeling.status == "gepland" and k.koppeling.herkomst == "mens"
        assert k.afschrijving_ledger_id == GB_0108
        rijen = koppelingen(admin_engine, factuur)
        assert len(rijen) == 1 and rijen[0]["status"] == "gepland" and rijen[0]["aanschafwaarde"] == Decimal("1250.00")
        assert rijen[0]["categorie"] == "inventaris" and rijen[0]["termijn_maanden"] == 60
        assert tijdlijn_teksten(admin_engine, factuur) == [
            "Activum gepland — wordt aangemaakt ná boeken: Bureau Hoogte-verstelbaar € 1250.00"
        ]
        assert audit_acties(admin_engine) == ["activum_gepland"]

    def test_eigen_termijn_wordt_gevalideerd_en_vastgelegd(
        self, factuur: uuid.UUID, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        with pytest.raises(service.OngeldigeInvoer):
            service.plan_of_maak_aan(
                administratie_id=administratie_id,
                document_id=factuur,
                regel_volgnummer=1,
                actor_id=gescoopte_gebruiker,
                termijn_maanden=13,
            )
        with pytest.raises(service.OngeldigeInvoer):
            service.plan_of_maak_aan(
                administratie_id=administratie_id,
                document_id=factuur,
                regel_volgnummer=1,
                actor_id=gescoopte_gebruiker,
                afschrijving_ledger_id=uuid.uuid4(),
            )
        data = service.plan_of_maak_aan(
            administratie_id=administratie_id,
            document_id=factuur,
            regel_volgnummer=1,
            actor_id=gescoopte_gebruiker,
            termijn_maanden=120,
        )
        assert data.kandidaten[0].termijn_maanden == 120 and data.kandidaten[0].methode_naam == "Lineair 10 jaar"
        assert koppelingen(admin_engine, factuur)[0]["methode_naam"] == "Lineair 10 jaar"

    def test_geen_kandidaat_is_domeinfout(
        self, factuur: uuid.UUID, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        with pytest.raises(service.GeenKandidaat):
            service.plan_of_maak_aan(
                administratie_id=administratie_id, document_id=factuur, regel_volgnummer=2, actor_id=gescoopte_gebruiker
            )
        with pytest.raises(service.GeenKandidaat):
            service.sla_over(
                administratie_id=administratie_id,
                document_id=factuur,
                regel_volgnummer=9,
                actor_id=gescoopte_gebruiker,
                reden="x",
            )

    def test_overslaan_vereist_reden_en_is_omkeerbaar(
        self, factuur: uuid.UUID, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        with pytest.raises(service.OngeldigeInvoer):
            service.sla_over(
                administratie_id=administratie_id,
                document_id=factuur,
                regel_volgnummer=1,
                actor_id=gescoopte_gebruiker,
                reden="  ",
            )
        data = service.sla_over(
            administratie_id=administratie_id,
            document_id=factuur,
            regel_volgnummer=1,
            actor_id=gescoopte_gebruiker,
            reden="huurkoop — activum komt via de leasemaatschappij",
        )
        k = data.kandidaten[0].koppeling
        assert (
            k is not None
            and k.status == "overgeslagen"
            and k.reden == "huurkoop — activum komt via de leasemaatschappij"
        )
        assert "reden: huurkoop" in tijdlijn_teksten(admin_engine, factuur)[-1]
        # "Toch aanmaken": overgeslagen → gepland, reden leeg.
        data = service.plan_of_maak_aan(
            administratie_id=administratie_id, document_id=factuur, regel_volgnummer=1, actor_id=gescoopte_gebruiker
        )
        k = data.kandidaten[0].koppeling
        assert k is not None and k.status == "gepland" and k.reden is None
        assert audit_acties(admin_engine) == ["activum_overgeslagen", "activum_gepland"]


class TestNaBoeken:
    def test_gepland_wordt_na_boeken_aangemaakt_in_rlz_via_de_orkestratie(
        self,
        factuur: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        rlz: FakeBoekClient,
        admin_engine: Engine,
    ) -> None:
        service.plan_of_maak_aan(
            administratie_id=administratie_id,
            document_id=factuur,
            regel_volgnummer=1,
            actor_id=gescoopte_gebruiker,
            afschrijving_ledger_id=GB_0108,
        )
        resultaat = orkestratie.boek_document_met_doorbelasting(
            administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker
        )
        assert _status(admin_engine, factuur) == "geboekt"
        assert resultaat.activa == {"aangemaakt": 1, "mislukt": 0, "gepland_verwerkt": 1, "automatisch": 0}
        assert len(rlz.fixed_asset_puts) == 1
        put = rlz.fixed_asset_puts[0]
        assert put["BalanceAccount"] == {"id": str(GB_0107)} and put["DepreciationAccount"] == {"id": str(GB_0108)}
        assert put["TotalAmountPurchase"] == 1250.0 and put["LiquidationValue"] == 0.0 and put["Type"] == 1
        assert (
            put["PurchaseDate"] == "2026-09-01"
            and put["FirstDepreciationMonth"] == 9
            and put["FirstDepreciationYear"] == 2026
        )
        assert put["NumberOfMonths"] == 60 and put["InvoiceReference"] == "KI-2026-0042"
        assert put["DepreciationMethod"] == {"id": "aaaaaaaa-1111-4111-8111-000000000060"}
        assert put["id"] == str(service.client_guid(document_id=factuur, regel_volgnummer=1, boek_cyclus=0))
        rij = koppelingen(admin_engine, factuur)[0]
        assert (
            rij["status"] == "aangemaakt"
            and rij["rlz_receipt_number"] == "1"
            and rij["methode_naam"] == "Lineair 5 jaar"
        )
        assert str(rij["rlz_fixed_asset_id"]) == put["id"]
        assert tijdlijn_teksten(admin_engine, factuur)[-1] == (
            "Activum aangemaakt in RLZ: Bureau Hoogte-verstelbaar € 1250.00 (Lineair 5 jaar) · nr 1"
        )
        assert audit_acties(admin_engine)[-1] == "activum_aangemaakt"
        # Idempotent: nog eens verwerken maakt niets opnieuw aan.
        uit = service.verwerk_na_boeken(
            administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker, client=rlz
        )
        assert uit.aangemaakt == 0 and len(rlz.fixed_asset_puts) == 1

    def test_zonder_koppeling_en_opt_in_uit_gebeurt_er_niets(
        self,
        factuur: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        rlz: FakeBoekClient,
        admin_engine: Engine,
    ) -> None:
        resultaat = orkestratie.boek_document_met_doorbelasting(
            administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker
        )
        assert resultaat.activa is None and rlz.fixed_asset_puts == [] and koppelingen(admin_engine, factuur) == []

    @pytest.mark.afwezig_pad("activa_instelling.automatisch_aanmaken_ingeschakeld")
    def test_opt_in_aan_maakt_elke_kandidaat_automatisch_aan_zonder_menselijke_instelling_verder(
        self,
        factuur: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        rlz: FakeBoekClient,
        admin_engine: Engine,
    ) -> None:
        """Afwezig-pad (kernprincipe 7.6): opt-in AAN + afschrijvingsrekening per categorie ingesteld, GEEN eigenaar,
        GEEN
        menselijke handeling op de kaart → het activum ontstaat automatisch ná boeken, herkomst `automatisch`."""
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET eigenaar_gebruiker_id = NULL WHERE id = :a"),
                {"a": administratie_id},
            )
        _zet_instelling(
            administratie_id, automatisch_aanmaken_ingeschakeld=True, afschrijving_ledgers={"inventaris": str(GB_0108)}
        )
        resultaat = orkestratie.boek_document_met_doorbelasting(
            administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker
        )
        assert resultaat.activa == {"aangemaakt": 1, "mislukt": 0, "gepland_verwerkt": 0, "automatisch": 1}
        rij = koppelingen(admin_engine, factuur)[0]
        assert rij["status"] == "aangemaakt" and rij["herkomst"] == "automatisch"
        assert tijdlijn_teksten(admin_engine, factuur)[-1].endswith("· nr 1 · automatisch")
        assert "activum_automatisch_gepland" in audit_acties(admin_engine)

    @pytest.mark.afwezig_pad("activa_instelling.automatisch_aanmaken_ingeschakeld")
    def test_opt_in_aan_zonder_afschrijvingsrekening_is_zichtbaar_mislukt_geen_stille_no_op(
        self,
        stamgegevens: None,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        rlz: FakeBoekClient,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
    ) -> None:
        # Blok 6 24-09: 0107 Inventaris krijgt via de conventie 4708 "Afschrijving inventaris" voorgevuld; het afwezig-pad
        # "geen rekening" bestaat alleen nog voor een rekening zonder kostenrekening mét dezelfde omschrijving (0170).
        _zet_instelling(administratie_id, automatisch_aanmaken_ingeschakeld=True)
        laptop = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel(GB_0170, "2400.00", "Laptop")],
            referentie="KI-LAPTOP-AUTO",
        )
        resultaat = orkestratie.boek_document_met_doorbelasting(
            administratie_id=administratie_id, document_id=laptop, actor_id=gescoopte_gebruiker
        )
        assert _status(admin_engine, laptop) == "geboekt"  # de boeking zelf raakt het nooit
        assert resultaat.activa == {"aangemaakt": 0, "mislukt": 1, "gepland_verwerkt": 0, "automatisch": 1}
        rij = koppelingen(admin_engine, laptop)[0]
        assert rij["status"] == "mislukt" and rij["herkomst"] == "automatisch"
        assert rij["reden"] == "geen afschrijvingsrekening — kies op de kaart of stel in onder Instellingen › Activa"
        assert rlz.fixed_asset_puts == []
        assert "Activum aanmaken mislukt" in tijdlijn_teksten(admin_engine, laptop)[-1]
        assert audit_acties(admin_engine)[-1] == "activum_aanmaken_mislukt"
        # Opnieuw aanmaken zónder rekening = 422 (nooit meer "gepland zonder afschrijvingsrekening"); mét rekening →
        # RLZ.
        with pytest.raises(service.AfschrijvingsrekeningVereist, match="Kies een afschrijvingsrekening"):
            service.plan_of_maak_aan(
                administratie_id=administratie_id, document_id=laptop, regel_volgnummer=1, actor_id=gescoopte_gebruiker
            )
        assert koppelingen(admin_engine, laptop)[0]["status"] == "mislukt"
        data = service.plan_of_maak_aan(
            administratie_id=administratie_id,
            document_id=laptop,
            regel_volgnummer=1,
            actor_id=gescoopte_gebruiker,
            afschrijving_ledger_id=GB_0108,
        )
        assert data.kandidaten[0].koppeling.status == "aangemaakt" and len(rlz.fixed_asset_puts) == 1

    def test_geen_rlz_methode_voor_termijn_is_mislukt_met_reden(
        self,
        factuur: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        rlz: FakeBoekClient,
        admin_engine: Engine,
    ) -> None:
        service.plan_of_maak_aan(
            administratie_id=administratie_id,
            document_id=factuur,
            regel_volgnummer=1,
            actor_id=gescoopte_gebruiker,
            afschrijving_ledger_id=GB_0108,
            termijn_maanden=84,
        )
        boeken.boek_document(administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker)
        uit = service.verwerk_na_boeken(
            administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker, client=rlz
        )
        assert uit.mislukt == 1 and rlz.fixed_asset_puts == []
        assert (
            koppelingen(admin_engine, factuur)[0]["reden"]
            == "geen RLZ-afschrijvingsmethode voor 84 maanden (Lineair 7 jaar)"
        )

    def test_rlz_fout_en_ontbrekende_readback_zijn_mislukt_nooit_een_exception(
        self,
        factuur: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        rlz: FakeBoekClient,
        admin_engine: Engine,
    ) -> None:
        service.plan_of_maak_aan(
            administratie_id=administratie_id,
            document_id=factuur,
            regel_volgnummer=1,
            actor_id=gescoopte_gebruiker,
            afschrijving_ledger_id=GB_0108,
        )
        boeken.boek_document(administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker)
        rlz.fixed_assets_403 = True
        uit = service.verwerk_na_boeken(
            administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker, client=rlz
        )
        assert uit.mislukt == 1
        assert koppelingen(admin_engine, factuur)[0]["reden"].startswith("RlzApiError: PUT FixedAssets -> 403")
        rlz.fixed_assets_403 = False
        rlz.faal_op = "fixed_asset_readback"
        service.plan_of_maak_aan(
            administratie_id=administratie_id, document_id=factuur, regel_volgnummer=1, actor_id=gescoopte_gebruiker
        )
        assert (
            koppelingen(admin_engine, factuur)[0]["reden"]
            == "RLZ gaf ná de PUT geen activum terug (404) — niets aangemaakt"
        )

    def test_geboekt_document_maakt_direct_aan_en_al_aangemaakt_is_409(
        self,
        factuur: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        rlz: FakeBoekClient,
    ) -> None:
        boeken.boek_document(administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker)
        data = service.plan_of_maak_aan(
            administratie_id=administratie_id,
            document_id=factuur,
            regel_volgnummer=1,
            actor_id=gescoopte_gebruiker,
            afschrijving_ledger_id=GB_0108,
        )
        assert data.document_geboekt and data.kandidaten[0].koppeling.status == "aangemaakt"
        with pytest.raises(service.AlAangemaakt):
            service.plan_of_maak_aan(
                administratie_id=administratie_id, document_id=factuur, regel_volgnummer=1, actor_id=gescoopte_gebruiker
            )
        with pytest.raises(service.AlAangemaakt):
            service.sla_over(
                administratie_id=administratie_id,
                document_id=factuur,
                regel_volgnummer=1,
                actor_id=gescoopte_gebruiker,
                reden="toch niet",
            )

    def test_client_guid_is_deterministisch_per_document_regel_cyclus(self) -> None:
        d = uuid.uuid4()
        assert service.client_guid(document_id=d, regel_volgnummer=1, boek_cyclus=0) == service.client_guid(
            document_id=d, regel_volgnummer=1, boek_cyclus=0
        )
        assert service.client_guid(document_id=d, regel_volgnummer=1, boek_cyclus=0) != service.client_guid(
            document_id=d, regel_volgnummer=2, boek_cyclus=0
        )
        assert service.client_guid(document_id=d, regel_volgnummer=1, boek_cyclus=0) != service.client_guid(
            document_id=d, regel_volgnummer=1, boek_cyclus=1
        )

    def test_twee_kandidaten_worden_twee_activa(
        self,
        stamgegevens: None,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        boeken_aan: None,
        rlz: FakeBoekClient,
        admin_engine: Engine,
    ) -> None:
        doc = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel(GB_0107, "900.00", "Kast"), regel(GB_0170, "1800.00", "Werkstation")],
            referentie="KI-TWEE",
        )
        _zet_instelling(
            administratie_id,
            automatisch_aanmaken_ingeschakeld=True,
            afschrijving_ledgers={"inventaris": str(GB_0108), "computers_software": str(GB_0108)},
        )
        resultaat = orkestratie.boek_document_met_doorbelasting(
            administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker
        )
        assert resultaat.activa["aangemaakt"] == 2 and len(rlz.fixed_asset_puts) == 2
        assert sorted(p["NumberOfMonths"] for p in rlz.fixed_asset_puts) == [36, 60]
        assert [r["rlz_receipt_number"] for r in koppelingen(admin_engine, doc)] == ["1", "2"]


class TestBug24_09:
    """BUG-opdracht 24-09 (BLOw 23-09): afschrijvingsrekening deterministisch voorgevuld (conventie kostenrekening zelfde omschrijving), nooit
    meer `gepland` zonder rekening, vangnet in de RLZ-write, en de 404-aanmaakroute als nette reden."""

    def test_plannen_zonder_keuze_neemt_de_conventie_rekening_over(
        self, factuur: uuid.UUID, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        data = service.plan_of_maak_aan(
            administratie_id=administratie_id, document_id=factuur, regel_volgnummer=1, actor_id=gescoopte_gebruiker
        )
        k = data.kandidaten[0]
        assert k.koppeling is not None and k.koppeling.status == "gepland"
        assert k.afschrijving_ledger_id == GB_0108 and k.afschrijving_bron == "koppeling"  # vastgelegd bij plannen
        assert koppelingen(admin_engine, factuur)[0]["afschrijving_ledger_id"] == GB_0108

    def test_zonder_conventie_en_zonder_keuze_is_422_en_geen_koppeling(
        self,
        stamgegevens: None,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        laptop = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel(GB_0170, "2400.00", "Laptop")],
            referentie="KI-LAPTOP-422",
        )
        with pytest.raises(service.AfschrijvingsrekeningVereist) as exc:
            service.plan_of_maak_aan(
                administratie_id=administratie_id, document_id=laptop, regel_volgnummer=1, actor_id=gescoopte_gebruiker
            )
        assert str(exc.value) == service.TEKST_AFSCHRIJVING_VEREIST
        assert isinstance(exc.value, service.OngeldigeInvoer)  # router → 422
        assert koppelingen(admin_engine, laptop) == [] and audit_acties(admin_engine) == []

    def test_vangnet_in_de_rlz_write_gebruikt_de_conventie_als_koppeling_en_instelling_leeg_zijn(
        self,
        factuur: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        rlz: FakeBoekClient,
        admin_engine: Engine,
    ) -> None:
        """De BLOw-stand van 23-09: koppeling `gepland` mét `afschrijving_ledger_id` NULL (vóór de fix geplant) → ná
        boeken vult het vangnet de conventie-rekening in en het activum ontstaat wél."""
        service.plan_of_maak_aan(
            administratie_id=administratie_id, document_id=factuur, regel_volgnummer=1, actor_id=gescoopte_gebruiker
        )
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.activum_koppeling SET afschrijving_ledger_id = NULL WHERE document_id = :d"),
                {"d": factuur},
            )
        boeken.boek_document(administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker)
        uit = service.verwerk_na_boeken(
            administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker, client=rlz
        )
        assert uit.aangemaakt == 1 and rlz.fixed_asset_puts[0]["DepreciationAccount"] == {"id": str(GB_0108)}

    def test_put_404_notfound_fixedasset_is_nette_reden_met_ruwe_fout_in_audit(
        self,
        factuur: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        rlz: FakeBoekClient,
        admin_engine: Engine,
    ) -> None:
        """Peter 23-09 (BLOw, MK22507863): `PUT FixedAssets/{client-guid}` → 404 NotFound_FixedAsset. Kaart: nette reden
        i.p.v. de ruwe RlzApiError; audit draagt de ruwe fout; herkomst mens → actie-bevinding."""
        service.plan_of_maak_aan(
            administratie_id=administratie_id, document_id=factuur, regel_volgnummer=1, actor_id=gescoopte_gebruiker
        )
        boeken.boek_document(administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker)
        rlz.faal_op = "fixed_asset_put_404"
        uit = service.verwerk_na_boeken(
            administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker, client=rlz
        )
        assert uit.mislukt == 1 and rlz.fixed_asset_puts == []
        rij = koppelingen(admin_engine, factuur)[0]
        assert rij["status"] == "mislukt" and rij["herkomst"] == "mens"
        assert rij["reden"] == service.REDEN_AANMAAKROUTE_ONBEKEND
        assert "NotFound_FixedAsset" in rij["reden"] and not rij["reden"].startswith("RlzApiError")
        with admin_engine.connect() as conn:
            nieuw = conn.execute(
                text(
                    "SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = 'activum_aanmaken_mislukt' "
                    "ORDER BY tijdstip DESC LIMIT 1"
                )
            ).scalar_one()
        assert "NotFound_FixedAsset" in nieuw["rlz_body"]["rlz_fout"] and nieuw["rlz_body"]["DepreciationAccount"]
        # Herstel ná de STAP-0: opnieuw aanmaken op de kaart → RLZ accepteert → aangemaakt.
        rlz.faal_op = None
        data = service.plan_of_maak_aan(
            administratie_id=administratie_id, document_id=factuur, regel_volgnummer=1, actor_id=gescoopte_gebruiker
        )
        assert data.kandidaten[0].koppeling.status == "aangemaakt" and len(rlz.fixed_asset_puts) == 1


class TestStorno:
    def test_tegenboeken_zet_aangemaakt_op_beoordelen_en_verwijdert_niets(
        self,
        factuur: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        rlz: FakeBoekClient,
        admin_engine: Engine,
    ) -> None:
        service.plan_of_maak_aan(
            administratie_id=administratie_id,
            document_id=factuur,
            regel_volgnummer=1,
            actor_id=gescoopte_gebruiker,
            afschrijving_ledger_id=GB_0108,
        )
        orkestratie.boek_document_met_doorbelasting(
            administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker
        )
        assert koppelingen(admin_engine, factuur)[0]["status"] == "aangemaakt"
        # Tegenboeken (volledig) — het pad waar mini_voorraad.registreer_storno ook hangt.
        rlz.aangiften = [{"Status": 2, "StartDate": "2026-07-01T00:00:00", "Date": "2026-09-30T00:00:00"}]
        tegenboeken.voer_tegenboeking_uit(
            administratie_id=administratie_id,
            document_id=factuur,
            actor_id=gescoopte_gebruiker,
            soort="volledig",
            reden="dubbel geboekt",
        )
        rij = koppelingen(admin_engine, factuur)[0]
        assert rij["status"] == "beoordelen" and rij["rlz_fixed_asset_id"] is not None
        assert rij["reden"].startswith("factuur gestorneerd — activum beoordelen in RLZ (niet verwijderd)")
        assert len(rlz.fixed_assets) == 1  # het activum staat nog in RLZ
        assert (
            "Factuur gestorneerd — activum beoordelen in RLZ (niet verwijderd)"
            in tijdlijn_teksten(admin_engine, factuur)[-1]
        )
        assert audit_acties(admin_engine)[-1] == "activum_beoordelen"

    def test_markeer_beoordelen_is_idempotent_en_zwijgt_zonder_aangemaakt(
        self, factuur: uuid.UUID, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            assert (
                service.markeer_beoordelen_bij_storno(session, document_id=factuur, actor_id=gescoopte_gebruiker) == 0
            )
        service.plan_of_maak_aan(
            administratie_id=administratie_id, document_id=factuur, regel_volgnummer=1, actor_id=gescoopte_gebruiker
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            # gepland (nog niets in RLZ) → niets te beoordelen
            assert (
                service.markeer_beoordelen_bij_storno(session, document_id=factuur, actor_id=gescoopte_gebruiker) == 0
            )


class TestOdoo:
    def test_odoo_administratie_is_zichtbaar_mislukt_geen_rlz_write(
        self,
        factuur: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        rlz: FakeBoekClient,
    ) -> None:
        service.plan_of_maak_aan(
            administratie_id=administratie_id,
            document_id=factuur,
            regel_volgnummer=1,
            actor_id=gescoopte_gebruiker,
            afschrijving_ledger_id=GB_0108,
        )
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET boekhoud_backend = 'odoo' WHERE id = :a"),
                {"a": administratie_id},
            )
            conn.execute(text("UPDATE boekhouding.document SET status = 'geboekt' WHERE id = :d"), {"d": factuur})
        kid = _koppeling_id(admin_engine, factuur)
        status = service.maak_aan_in_rlz(
            administratie_id=administratie_id,
            document_id=factuur,
            koppeling_id=kid,
            actor_id=gescoopte_gebruiker,
            client=rlz,
        )
        assert status == "mislukt" and rlz.fixed_asset_puts == []
        assert "Odoo-activaregister" in koppelingen(admin_engine, factuur)[0]["reden"]


def _koppeling_id(admin_engine: Engine, document_id: uuid.UUID) -> uuid.UUID:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT id FROM boekhouding.activum_koppeling WHERE document_id = :d"), {"d": document_id}
        ).scalar_one()
