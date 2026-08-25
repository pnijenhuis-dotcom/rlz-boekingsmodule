"""Doorbelasting ín de boekflow (besluit Peter 25-08, feedbackronde punt A — herziet 13-08):
klaargezette run vóór het boeken, "Boeken + doorbelasten" in één gang via de bestaande motoren,
zichtbare fouten ná de inkoopboeking, vervallen-pad en de boekvoorstel-herkoppeling."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, text

from app.db.session import scoped_session
from app.documenten import boeken as documenten_boeken
from app.documenten import boekvoorstel
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentGebeurtenis, DocumentStatus
from app.documenten.service import _schrijf_overgang
from app.documenten.storage import LokaleBestandsopslag
from app.doorbelasting import orkestratie
from app.doorbelasting import service as doorbelasting_service
from app.doorbelasting.models import DoorbelastingRegel, DoorbelastingRun
from app.doorbelasting.service import VerdeelRegelInvoerData, VerdelingBevroren
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.doorbelasting.conftest import (
    DOEL_KOSTEN_LEDGER_ID,
    PROVISIE_KOSTEN_LEDGER_ID,
    FakeDoorbelastingClient,
    geef_scope,
    haal_boekingen,
    haal_run,
    maak_mapping,
)

VENDOR_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _regels(nettos: list[str]) -> list[boekvoorstel.BoekvoorstelRegelData]:
    return [
        boekvoorstel.BoekvoorstelRegelData(
            ledger_id=uuid.uuid4(),
            taxrate_id=uuid.uuid4(),
            project_id=None,
            netto_bedrag=Decimal(n),
            btw_bedrag=(Decimal(n) * Decimal("0.21")).quantize(Decimal("0.01")),
            omschrijving=f"Kostenregel {i + 1}",
        )
        for i, n in enumerate(nettos)
    ]


def maak_boekbaar_document(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    admin_engine: Engine,
    nettos: list[str] = ("100.00",),
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Nog NIET geboekte inkoopfactuur met een compleet boekvoorstel (vendor in cache, regels
    mét GB/btw) — de inkoop-checks staan groen, de doorbelasting kan klaargezet worden."""
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                "VALUES (:id, :aid, 'Bouwmaat B.V.', '{}') ON CONFLICT DO NOTHING"
            ),
            {"id": VENDOR_ID, "aid": administratie_id},
        )
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur-centrale-inkoop.pdf",
        inhoud=b"%PDF-1.4 centrale inkoop",
        actor_id=actor_id,
        opslag=opslag,
    )
    nettos = list(nettos)
    totaal = sum((Decimal(n) * Decimal("1.21") for n in nettos), Decimal(0)).quantize(Decimal("0.01"))
    data = boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor_id,
        vendor_id=VENDOR_ID,
        referentie=f"CI-{resultaat.document_id}",
        factuurdatum=date(2026, 8, 1),
        totaalbedrag=totaal,
        regels=_regels(nettos),
    )
    return resultaat.document_id, [r.id for r in data.regels]


@pytest.fixture
def klaargezet(
    doorbelasting_aan: None,
    instelling_compleet: None,
    doel_administratie_id: uuid.UUID,
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    opslag: LokaleBestandsopslag,
    admin_engine: Engine,
) -> dict:
    document_id, regel_ids = maak_boekbaar_document(
        administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, admin_engine=admin_engine
    )
    mapping = maak_mapping(
        administratie_id=administratie_id,
        actor_id=beheerder_id,
        doel_administratie_id=doel_administratie_id,
        provisie_kosten_ledger_id=PROVISIE_KOSTEN_LEDGER_ID,
    )
    run = doorbelasting_service.start_of_haal_run(
        administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
    )
    assert run.status == "klaargezet"
    doorbelasting_service.sla_verdeling_op(
        administratie_id=administratie_id,
        run_id=run.id,
        actor_id=gescoopte_gebruiker,
        regels=[
            VerdeelRegelInvoerData(
                bron_regel_id=regel_ids[0],
                mapping_id=mapping.id,
                percentage=Decimal("100"),
                doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
            )
        ],
    )
    return {"document_id": document_id, "regel_ids": regel_ids, "mapping": mapping, "run": run}


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


def _patch_inkoop_rlz(monkeypatch: pytest.MonkeyPatch) -> FakeBoekClient:
    fake = FakeBoekClient()
    monkeypatch.setattr(documenten_boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    return fake


class TestBoekenPlusDoorbelasten:
    def test_boekt_inkoop_en_doorbelast_in_een_gang(
        self,
        klaargezet: dict,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inkoop = _patch_inkoop_rlz(monkeypatch)
        bron, doel = FakeDoorbelastingClient(), FakeDoorbelastingClient()
        resultaat = orkestratie.boek_document_met_doorbelasting(
            administratie_id=administratie_id,
            document_id=klaargezet["document_id"],
            actor_id=beheerder_id,  # scope op bron én doel (Beheerder = alles)
            bron_client=bron,
            doel_client_factory=lambda _aid: doel,
        )
        assert resultaat.boek.status == DocumentStatus.GEBOEKT
        assert len(inkoop.puts) == 1  # de échte inkoopmotor deed de RLZ-write
        assert resultaat.doorbelasting == {str(klaargezet["mapping"].id): "geboekt"}
        assert resultaat.doorbelasting_fout is None
        assert _status(admin_engine, klaargezet["document_id"]) == "geboekt"
        run = haal_run(administratie_id, klaargezet["run"].id)
        assert run.status == "geboekt"
        assert len(bron.sales_invoices) == 1 and len(doel.purchase_invoices) == 1
        # Tijdlijn: de GEBOEKT-overgang draagt de koppeling naar de run (Boeken + doorbelasten)
        with scoped_session(administratie_id) as session:
            gebeurtenissen = session.scalars(
                select(DocumentGebeurtenis).where(
                    DocumentGebeurtenis.document_id == klaargezet["document_id"],
                    DocumentGebeurtenis.naar_status == DocumentStatus.GEBOEKT,
                )
            ).all()
            # De inkoop-GEBOEKT-overgang draagt de koppeling; de motor schrijft daarnaast zijn
            # eigen "doorbelast"-tijdlijnregel (zonder statusovergang).
            [geboekt] = [g for g in gebeurtenissen if g.detail and "doorbelasting_na_boeken" in g.detail]
            assert geboekt.detail["doorbelasting_na_boeken"] == str(klaargezet["run"].id)
        # Audit: klaargezet → geactiveerd
        with admin_engine.connect() as conn:
            acties = (
                conn.execute(
                    text(
                        "SELECT actie FROM platform.audit_event "
                        "WHERE tabel='doorbelasting_run' AND record_id=:id ORDER BY tijdstip"
                    ),
                    {"id": klaargezet["run"].id},
                )
                .scalars()
                .all()
            )
        # De verdeling-opslag-audit (25-08, deel 2) zit ertussen — hier gaat het om de run-overgangen.
        overgangen = [a for a in acties if a != "doorbelasting_verdeling_opgeslagen"]
        assert overgangen[:2] == ["doorbelasting_run_klaargezet", "doorbelasting_run_geactiveerd_na_boeken"]

    def test_rode_doorbelasting_checks_blokkeren_voor_de_inkoopboeking(
        self,
        klaargezet: dict,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A2: boek-checks én doorbelasting-checks samen groen — anders wordt er níéts geschreven."""
        inkoop = _patch_inkoop_rlz(monkeypatch)
        # Verdeling naar 50% (werkstaat) → check_verdeling_100 blokkeert
        doorbelasting_service.sla_verdeling_op(
            administratie_id=administratie_id,
            run_id=klaargezet["run"].id,
            actor_id=gescoopte_gebruiker,
            regels=[
                VerdeelRegelInvoerData(
                    bron_regel_id=klaargezet["regel_ids"][0],
                    mapping_id=klaargezet["mapping"].id,
                    percentage=Decimal("50"),
                    doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
                )
            ],
        )
        with pytest.raises(orkestratie.DoorbelastingChecksNietGroen) as exc:
            orkestratie.boek_document_met_doorbelasting(
                administratie_id=administratie_id, document_id=klaargezet["document_id"], actor_id=gescoopte_gebruiker
            )
        assert exc.value.rapport.geblokkeerd
        assert inkoop.puts == []
        assert _status(admin_engine, klaargezet["document_id"]) != "geboekt"
        assert haal_run(administratie_id, klaargezet["run"].id).status == "klaargezet"

    def test_vinkje_zonder_verdeling_blokkeert_expliciet(
        self,
        klaargezet: dict,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_inkoop_rlz(monkeypatch)
        doorbelasting_service.sla_verdeling_op(
            administratie_id=administratie_id, run_id=klaargezet["run"].id, actor_id=gescoopte_gebruiker, regels=[]
        )
        with pytest.raises(orkestratie.DoorbelastingChecksNietGroen) as exc:
            orkestratie.boek_document_met_doorbelasting(
                administratie_id=administratie_id, document_id=klaargezet["document_id"], actor_id=gescoopte_gebruiker
            )
        assert any(r.naam == "doorbelasting_verdeling" and not r.ok for r in exc.value.rapport.resultaten)

    def test_geen_scope_op_doel_blokkeert_voor_de_inkoopboeking(
        self,
        klaargezet: dict,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """De medewerker heeft alleen scope op de bron: de motor zou pas ná de inkoopboeking op
        doel-scope stranden — de orkestratie toetst dat vooraf, er wordt niets geschreven."""
        inkoop = _patch_inkoop_rlz(monkeypatch)
        with pytest.raises(orkestratie.DoorbelastingChecksNietGroen) as exc:
            orkestratie.boek_document_met_doorbelasting(
                administratie_id=administratie_id, document_id=klaargezet["document_id"], actor_id=gescoopte_gebruiker
            )
        [scope_check] = [r for r in exc.value.rapport.resultaten if r.naam == "doorbelasting_scope"]
        assert not scope_check.ok
        assert klaargezet["mapping"].doelentiteit_naam in scope_check.melding  # de juiste naam
        assert inkoop.puts == []
        assert _status(admin_engine, klaargezet["document_id"]) != "geboekt"

    def test_medewerker_met_scope_op_bron_en_doel_boekt_in_een_gang(
        self,
        klaargezet: dict,
        administratie_id: uuid.UUID,
        doel_administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regressie kliktest Peter 25-08 (Barbara, Boekhouding+Projecten, scope op bron én
        Molenhof Beheer): de scope-check sloeg onterecht aan omdat de koppeltabel in een
        scope-loze sessie zonder actor werd gelezen (RLS verborg élke rij). Echte niet-Beheerder
        MÉT scope op alle doelen → check groen, alles boekt."""
        geef_scope(beheerder_id=beheerder_id, gebruiker_id=gescoopte_gebruiker, administratie_id=doel_administratie_id)
        inkoop = _patch_inkoop_rlz(monkeypatch)
        bron, doel = FakeDoorbelastingClient(), FakeDoorbelastingClient()
        rapport = orkestratie.toets_klaargezette_doorbelasting(
            administratie_id=administratie_id, document_id=klaargezet["document_id"], actor_id=gescoopte_gebruiker
        )
        assert rapport is not None and not rapport.geblokkeerd
        assert not any(r.naam == "doorbelasting_scope" for r in rapport.resultaten)
        resultaat = orkestratie.boek_document_met_doorbelasting(
            administratie_id=administratie_id,
            document_id=klaargezet["document_id"],
            actor_id=gescoopte_gebruiker,
            bron_client=bron,
            doel_client_factory=lambda _aid: doel,
        )
        assert resultaat.boek.status == DocumentStatus.GEBOEKT
        assert resultaat.doorbelasting == {str(klaargezet["mapping"].id): "geboekt"}
        assert resultaat.doorbelasting_fout is None
        assert len(inkoop.puts) == 1
        assert len(bron.sales_invoices) == 1 and len(doel.purchase_invoices) == 1
        assert _status(admin_engine, klaargezet["document_id"]) == "geboekt"

    def test_scope_op_een_van_twee_doelen_blokkeert_met_alleen_die_naam(
        self,
        klaargezet: dict,
        administratie_id: uuid.UUID,
        doel_administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Twee doelen, scope op één: de melding noemt uitsluitend het doel zónder scope."""
        from tests.doorbelasting.conftest import maak_administratie

        geef_scope(beheerder_id=beheerder_id, gebruiker_id=gescoopte_gebruiker, administratie_id=doel_administratie_id)
        tweede_doel = maak_administratie(admin_engine, "Molenhof Beheer B.V.")
        tweede_mapping = maak_mapping(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            naam="Molenhof Beheer B.V.",
            doel_administratie_id=tweede_doel,
            provisie_kosten_ledger_id=PROVISIE_KOSTEN_LEDGER_ID,
        )
        doorbelasting_service.sla_verdeling_op(
            administratie_id=administratie_id,
            run_id=klaargezet["run"].id,
            actor_id=gescoopte_gebruiker,
            regels=[
                VerdeelRegelInvoerData(
                    bron_regel_id=klaargezet["regel_ids"][0],
                    mapping_id=klaargezet["mapping"].id,
                    percentage=Decimal("50"),
                    doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
                ),
                VerdeelRegelInvoerData(
                    bron_regel_id=klaargezet["regel_ids"][0],
                    mapping_id=tweede_mapping.id,
                    percentage=Decimal("50"),
                    doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
                ),
            ],
        )
        inkoop = _patch_inkoop_rlz(monkeypatch)
        with pytest.raises(orkestratie.DoorbelastingChecksNietGroen) as exc:
            orkestratie.boek_document_met_doorbelasting(
                administratie_id=administratie_id, document_id=klaargezet["document_id"], actor_id=gescoopte_gebruiker
            )
        [scope_check] = [r for r in exc.value.rapport.resultaten if r.naam == "doorbelasting_scope"]
        assert "Molenhof Beheer B.V." in scope_check.melding
        assert klaargezet["mapping"].doelentiteit_naam not in scope_check.melding
        assert inkoop.puts == []

    def test_doorbelasting_faalt_na_inkoopboeking_is_zichtbaar_nooit_stil(
        self,
        klaargezet: dict,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A4: half-geboekt-patroon — inkoop staat, de doorbelasting-fout staat op de run en in
        het resultaat; de bestaande herstelroutes gelden."""
        _patch_inkoop_rlz(monkeypatch)
        bron = FakeDoorbelastingClient(faal_op="rechten_probe")
        resultaat = orkestratie.boek_document_met_doorbelasting(
            administratie_id=administratie_id,
            document_id=klaargezet["document_id"],
            actor_id=beheerder_id,
            bron_client=bron,
            doel_client_factory=lambda _aid: FakeDoorbelastingClient(),
        )
        assert resultaat.boek.status == DocumentStatus.GEBOEKT
        assert _status(admin_engine, klaargezet["document_id"]) == "geboekt"
        assert resultaat.doorbelasting_fout is not None
        run = haal_run(administratie_id, klaargezet["run"].id)
        assert run.status == "concept"  # herstel via de bestaande "Doorbelasten…"-route
        assert run.laatste_fout  # zichtbare fout op de run
        assert haal_boekingen(administratie_id, run.id) == []

    def test_zonder_klaargezette_run_is_het_een_gewone_boeking(
        self,
        doorbelasting_aan: None,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_inkoop_rlz(monkeypatch)
        document_id, _ = maak_boekbaar_document(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, admin_engine=admin_engine
        )
        resultaat = orkestratie.boek_document_met_doorbelasting(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        assert resultaat.doorbelasting_run_id is None and resultaat.doorbelasting is None
        assert _status(admin_engine, document_id) == "geboekt"


class TestKlaargezetteRunLevenscyclus:
    def test_vervallen_laat_spoor_en_maakt_nieuwe_run_mogelijk(
        self, klaargezet: dict, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        vervallen = doorbelasting_service.laat_run_vervallen(
            administratie_id=administratie_id, run_id=klaargezet["run"].id, actor_id=gescoopte_gebruiker
        )
        assert vervallen.status == "vervallen"
        with scoped_session(administratie_id) as session:
            assert session.get(DoorbelastingRun, klaargezet["run"].id) is not None  # nooit een delete
        assert (
            doorbelasting_service.vind_run(administratie_id=administratie_id, document_id=klaargezet["document_id"])
            is None
        )
        nieuw = doorbelasting_service.start_of_haal_run(
            administratie_id=administratie_id, document_id=klaargezet["document_id"], actor_id=gescoopte_gebruiker
        )
        assert nieuw.id != klaargezet["run"].id and nieuw.status == "klaargezet"
        with pytest.raises(VerdelingBevroren):
            doorbelasting_service.laat_run_vervallen(
                administratie_id=administratie_id, run_id=klaargezet["run"].id, actor_id=gescoopte_gebruiker
            )
        with admin_engine.connect() as conn:
            acties = (
                conn.execute(
                    text("SELECT actie FROM platform.audit_event WHERE tabel='doorbelasting_run' AND record_id=:id"),
                    {"id": klaargezet["run"].id},
                )
                .scalars()
                .all()
            )
        assert "doorbelasting_run_vervallen" in acties

    def test_verdeling_bevroren_zolang_document_ter_accordering_ligt(
        self, klaargezet: dict, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        """A3: de accordeur beoordeelt precies wat hij ziet — tot het besluit geen wijziging."""
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            document = session.get(Document, klaargezet["document_id"])
            if document.status != DocumentStatus.KLAAR_OM_TE_BOEKEN:
                _schrijf_overgang(
                    session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=gescoopte_gebruiker
                )
            _schrijf_overgang(
                session, document=document, naar=DocumentStatus.TER_ACCORDERING, actor_id=gescoopte_gebruiker
            )
        with pytest.raises(VerdelingBevroren, match="ter accordering"):
            doorbelasting_service.sla_verdeling_op(
                administratie_id=administratie_id, run_id=klaargezet["run"].id, actor_id=gescoopte_gebruiker, regels=[]
            )
        with pytest.raises(VerdelingBevroren, match="ter accordering"):
            doorbelasting_service.laat_run_vervallen(
                administratie_id=administratie_id, run_id=klaargezet["run"].id, actor_id=gescoopte_gebruiker
            )

    def test_motor_weigert_klaargezette_run_zolang_document_niet_geboekt_is(
        self, klaargezet: dict, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        from app.doorbelasting.boeken import boek_doorbelasting_run
        from app.doorbelasting.service import DoorbelastingFout

        with pytest.raises(DoorbelastingFout, match="nog niet geboekt"):
            boek_doorbelasting_run(
                administratie_id=administratie_id,
                run_id=klaargezet["run"].id,
                actor_id=gescoopte_gebruiker,
                bron_client=FakeDoorbelastingClient(),
                doel_client_factory=lambda _aid: FakeDoorbelastingClient(),
            )


class TestBoekvoorstelHerkoppeling:
    def test_heropslaan_boekvoorstel_neemt_verdeling_per_volgnummer_mee(
        self, klaargezet: dict, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        """Het boekvoorstel vervangt zijn regels (delete+insert → nieuwe id's); de klaargezette
        verdeling volgt per volgnummer en de netto-delen worden herberekend op het nieuwe bedrag."""
        data = boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=klaargezet["document_id"],
            actor_id=gescoopte_gebruiker,
            vendor_id=VENDOR_ID,
            referentie="CI-herzien",
            factuurdatum=date(2026, 8, 1),
            totaalbedrag=Decimal("302.50"),
            regels=_regels(["150.00", "100.00"]),
        )
        nieuwe_ids = [r.id for r in data.regels]
        assert nieuwe_ids[0] != klaargezet["regel_ids"][0]
        with scoped_session(administratie_id) as session:
            regels = list(
                session.scalars(select(DoorbelastingRegel).where(DoorbelastingRegel.run_id == klaargezet["run"].id))
            )
        assert len(regels) == 1
        assert regels[0].bron_regel_id == nieuwe_ids[0]  # volgnummer 1 → nieuwe regel 1
        assert regels[0].percentage == Decimal("100")
        assert regels[0].netto_deel == Decimal("150.00")  # herberekend op het nieuwe bedrag
        assert regels[0].doel_kosten_ledger_id == DOEL_KOSTEN_LEDGER_ID

    def test_verdwenen_regel_verliest_verdeling_zichtbaar(
        self, klaargezet: dict, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        # Verdeel regel 2 van een tweeregelig voorstel, sla daarna een éénregelig voorstel op.
        data = boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=klaargezet["document_id"],
            actor_id=gescoopte_gebruiker,
            vendor_id=VENDOR_ID,
            referentie="CI-twee",
            factuurdatum=date(2026, 8, 1),
            totaalbedrag=Decimal("242.00"),
            regels=_regels(["100.00", "100.00"]),
        )
        doorbelasting_service.sla_verdeling_op(
            administratie_id=administratie_id,
            run_id=klaargezet["run"].id,
            actor_id=gescoopte_gebruiker,
            regels=[
                VerdeelRegelInvoerData(
                    bron_regel_id=data.regels[1].id,
                    mapping_id=klaargezet["mapping"].id,
                    percentage=Decimal("100"),
                    doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
                )
            ],
        )
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=klaargezet["document_id"],
            actor_id=gescoopte_gebruiker,
            vendor_id=VENDOR_ID,
            referentie="CI-een",
            factuurdatum=date(2026, 8, 1),
            totaalbedrag=Decimal("121.00"),
            regels=_regels(["100.00"]),
        )
        review = doorbelasting_service.review_data(administratie_id=administratie_id, run_id=klaargezet["run"].id)
        assert review.regels == []  # verdeling weg — en dus zichtbaar rood bij Boeken + doorbelasten
        with pytest.raises(orkestratie.DoorbelastingChecksNietGroen):
            orkestratie.toets_klaargezette_doorbelasting(
                administratie_id=administratie_id, document_id=klaargezet["document_id"]
            )
