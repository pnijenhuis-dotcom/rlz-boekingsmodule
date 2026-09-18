"""Boeken sneller (Peter 18-09), stap 1: externe checks gesplitst van de lokale, vingerafdruk + cache + parallel.

- de vingerafdruk raakt alleen de externe invoer (omschrijving/grootboek/btw-code veranderen 'm niet; referentie
  genormaliseerd);
- een tweede run met dezelfde vingerafdruk ≤ 15 min raakt RLZ niet meer (cache), een gewijzigde vingerafdruk of
  `extern=vers` wél; `extern=cache` zonder geldige cache = "loopt nog" (blokkerend, nooit stil doorlaten);
- boeken hergebruikt het rapport onder dezelfde voorwaarden; een boeken_mislukt-retry en het autoboek-pad draaien vers;
- een storing wordt nooit gecachet.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.config import settings
from app.documenten import boeken, boekvoorstel, checks_extern, service
from app.documenten.models import DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from tests.documenten.fake_rlz_client import FakeBoekClient


class TellendeFake(FakeBoekClient):
    """FakeBoekClient die de externe aanroepen telt (BankRelations + duplicaatquery's)."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.externe_calls = 0

    def get(self, path: str, *, params=None):  # noqa: ANN001
        if path.endswith("/BankRelations"):
            self.externe_calls += 1
        return super().get(path, params=params)

    def find_purchase_invoices_by_reference(self, **kw):  # noqa: ANN003
        self.externe_calls += 1
        return super().find_purchase_invoices_by_reference(**kw)

    def find_purchase_invoices_kandidaten(self, **kw):  # noqa: ANN003
        self.externe_calls += 1
        return super().find_purchase_invoices_kandidaten(**kw)


def _regel(**overrides) -> boekvoorstel.BoekvoorstelRegelData:
    basis = dict(
        ledger_id=uuid.uuid4(),
        taxrate_id=uuid.uuid4(),
        project_id=None,
        netto_bedrag=Decimal("100.00"),
        btw_bedrag=Decimal("21.00"),
        omschrijving="Testregel",
    )
    basis.update(overrides)
    return boekvoorstel.BoekvoorstelRegelData(**basis)


def _document(administratie_id, actor, opslag, *, referentie="F-1", omschrijving="Testregel") -> uuid.UUID:
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
        referentie=referentie,
        factuurdatum=date(2026, 7, 1),
        totaalbedrag=Decimal("121.00"),
        regels=[_regel(omschrijving=omschrijving)],
    )
    return resultaat.document_id


class TestVingerafdruk:
    def test_omschrijving_en_boekingskeuzes_zitten_niet_in_de_vingerafdruk(self) -> None:
        v = uuid.uuid4()
        a = checks_extern.vingerafdruk(
            vendor_id=v, referentie="2 4594 001722", factuurdatum=date(2026, 7, 1), totaalbedrag=Decimal("121.00"), factuur_iban="NL91 ABNA 0417 1643 00"
        )
        b = checks_extern.vingerafdruk(
            vendor_id=v, referentie="24594001722", factuurdatum=date(2026, 7, 1), totaalbedrag=Decimal("121.0"), factuur_iban="nl91abna0417164300"
        )
        assert a == b  # referentie genormaliseerd, bedrag cent-exact, IBAN zonder spaties/hoofdletters
        c = checks_extern.vingerafdruk(
            vendor_id=v, referentie="24594001722", factuurdatum=date(2026, 7, 1), totaalbedrag=Decimal("121.01"), factuur_iban=None
        )
        assert c != a  # totaal/IBAN raken RLZ wél

    def test_boek_cyclus_en_cluster_veranderen_de_vingerafdruk(self) -> None:
        v, w = uuid.uuid4(), uuid.uuid4()
        basis = dict(vendor_id=v, referentie="F-1", factuurdatum=date(2026, 7, 1), totaalbedrag=Decimal("1"), factuur_iban=None)
        assert checks_extern.vingerafdruk(**basis) != checks_extern.vingerafdruk(**basis, boek_cyclus=1)
        assert checks_extern.vingerafdruk(**basis) != checks_extern.vingerafdruk(**basis, identiteit_vendor_ids=[w])

    def test_geldigheid_verloopt_na_de_ingestelde_minuten(self) -> None:
        nu = datetime.now(UTC)
        rij = type("Rij", (), {"vingerafdruk": "x", "gecontroleerd_op": nu - timedelta(minutes=14)})()
        assert checks_extern.is_geldig(rij, vingerafdruk="x", nu=nu)
        rij.gecontroleerd_op = nu - timedelta(minutes=settings.checks_extern_cache_minuten, seconds=1)
        assert not checks_extern.is_geldig(rij, vingerafdruk="x", nu=nu)
        rij.gecontroleerd_op = nu
        assert not checks_extern.is_geldig(rij, vingerafdruk="anders", nu=nu)
        assert not checks_extern.is_geldig(None, vingerafdruk="x", nu=nu)

    def test_rapport_is_json_rond_en_storing_is_niet_cachebaar(self) -> None:
        nu = datetime.now(UTC)
        ext = checks_extern.ExternRapport(
            gecontroleerd_op=nu,
            vertrouwde_ibans=("NL91ABNA0417164300",),
            duplicaat=checks_extern.CheckResultaat("Duplicaatcheck", True, "ok"),
            duplicaat_over_crediteuren=checks_extern.CheckResultaat("Duplicaat bij andere crediteur", True, "ok", signaal=True),
        )
        terug = checks_extern.ExternRapport.uit_json(ext.naar_json())
        assert terug.vertrouwde_ibans == ext.vertrouwde_ibans and terug.uit_cache is True
        assert terug.duplicaat_over_crediteuren is not None and terug.duplicaat_over_crediteuren.signaal is True
        assert ext.cachebaar
        storing = checks_extern.ExternRapport(gecontroleerd_op=nu, storing="RLZ onbereikbaar")
        assert not storing.cachebaar
        rlz_fout = checks_extern.ExternRapport(
            gecontroleerd_op=nu,
            duplicaat=checks_extern.CheckResultaat("Duplicaatcheck", False, f"{checks_extern.STORING_PREFIX}: 503"),
            duplicaat_over_crediteuren=checks_extern.CheckResultaat("Duplicaat bij andere crediteur", True, "ok"),
        )
        assert not rlz_fout.cachebaar
        assert checks_extern.ExternRapport.nog_niet_gecontroleerd(nu).is_storings_tak


class TestCacheInVoerChecksUit:
    def test_tweede_run_zelfde_vingerafdruk_raakt_rlz_niet_gewijzigde_omschrijving_ook_niet(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        fake = TellendeFake()
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        r1 = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake)
        assert r1.extern_uit_cache is False and r1.extern_gecontroleerd_op is not None
        n = fake.externe_calls
        assert n >= 2  # BankRelations + duplicaatquery's
        r2 = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake)
        assert r2.extern_uit_cache is True and fake.externe_calls == n
        assert [r.ok for r in r1.resultaten] == [r.ok for r in r2.resultaten]
        # Omschrijving wijzigen = geen externe run.
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id).vendor_id,
            referentie="F-1",
            factuurdatum=date(2026, 7, 1),
            totaalbedrag=Decimal("121.00"),
            regels=[_regel(omschrijving="Andere omschrijving")],
        )
        r3 = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake)
        assert r3.extern_uit_cache is True and fake.externe_calls == n

    def test_gewijzigde_referentie_of_vers_of_verlopen_cache_draait_extern_opnieuw(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = TellendeFake()
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake)
        n = fake.externe_calls
        boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=fake, extern=checks_extern.VERS
        )
        assert fake.externe_calls > n
        n = fake.externe_calls
        vendor = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id).vendor_id
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=vendor,
            referentie="F-2",
            factuurdatum=date(2026, 7, 1),
            totaalbedrag=Decimal("121.00"),
            regels=[_regel()],
        )
        r = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake)
        assert r.extern_uit_cache is False and fake.externe_calls > n
        n = fake.externe_calls
        monkeypatch.setattr(settings, "checks_extern_cache_minuten", 0)
        r = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake)
        assert r.extern_uit_cache is False and fake.externe_calls > n

    def test_cache_modus_zonder_geldige_cache_is_loopt_nog_en_blokkeert(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        fake = TellendeFake()
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        r = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=fake, extern=checks_extern.CACHE
        )
        assert fake.externe_calls == 0
        assert r.extern_nog_niet is True and r.geblokkeerd is True
        per_naam = {x.naam: x for x in r.resultaten}
        assert per_naam["Duplicaatcheck"].ok is False and "loopt nog" in per_naam["Duplicaatcheck"].melding
        # Ná een echte run levert CACHE de gecachete uitkomst zonder RLZ te raken.
        boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake)
        n = fake.externe_calls
        r2 = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=fake, extern=checks_extern.CACHE
        )
        assert r2.extern_uit_cache is True and r2.extern_nog_niet is False and fake.externe_calls == n

    def test_storing_wordt_niet_gecachet(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        fake = TellendeFake(faal_op="bank_relations")
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        r1 = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake)
        # seed_mislukt → IBAN-wissel fail-closed, maar het is geen storings-tak: duplicaatcheck draaide en de uitkomst
        # is cachebaar (de seed-poging zelf herhaalt zich niet — bestaand gedrag).
        assert r1.extern_uit_cache is False
        goed = TellendeFake()
        fout_client = TellendeFake()

        def _kapot(**kw):  # noqa: ANN003
            raise RuntimeError("RLZ onbereikbaar")

        fout_client.find_purchase_invoices_by_reference = _kapot  # type: ignore[method-assign]
        fout_client.find_purchase_invoices_kandidaten = _kapot  # type: ignore[method-assign]
        document_2 = _document(administratie_id, gescoopte_gebruiker, opslag, referentie="F-STORING")
        r = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_2, client=fout_client)
        assert r.geblokkeerd and r.extern_uit_cache is False
        r2 = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_2, client=goed)
        assert r2.extern_uit_cache is False and goed.externe_calls >= 2  # geen cache-hit ná de storing


class TestExternModusBijBoeken:
    def test_modus_vers_bij_retry_en_autoboek_auto_voor_de_mens(self) -> None:
        assert (
            boeken.extern_checks_modus(status_bij_start=DocumentStatus.BOEKEN_MISLUKT, extra_overgang_detail=None)
            == checks_extern.VERS
        )
        assert (
            boeken.extern_checks_modus(
                status_bij_start=DocumentStatus.KLAAR_OM_TE_BOEKEN, extra_overgang_detail={"automatisch_geboekt": True}
            )
            == checks_extern.VERS
        )
        assert (
            boeken.extern_checks_modus(status_bij_start=DocumentStatus.KLAAR_OM_TE_BOEKEN, extra_overgang_detail=None)
            == checks_extern.AUTO
        )
        assert (
            boeken.extern_checks_modus(
                status_bij_start=DocumentStatus.BOEKEN_MISLUKT, extra_overgang_detail=None, gevraagd=checks_extern.CACHE
            )
            == checks_extern.CACHE
        )

    def test_boek_document_hergebruikt_geldig_rapport_en_draait_vers_bij_retry(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.beheer import service as beheer_service

        beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        fake = TellendeFake()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        # Controlescherm draaide de checks al (cache gevuld) …
        boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake)
        n = fake.externe_calls
        # … boeken hergebruikt het rapport: geen nieuwe externe calls, wél de PUT.
        boeken.boek_document(administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker)
        assert fake.externe_calls == n and len(fake.puts) == 1

    def test_retry_vanuit_boeken_mislukt_draait_de_externe_checks_vers(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.beheer import service as beheer_service

        beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        kapot = TellendeFake(faal_op="put")
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: kapot)
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        with pytest.raises(boeken.RlzBoekingMislukt):
            boeken.boek_document(administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker)
        goed = TellendeFake()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: goed)
        boeken.boek_document(administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker)
        assert goed.externe_calls >= 2 and len(goed.puts) == 1  # vers, ondanks een geldige cache van de eerste poging
