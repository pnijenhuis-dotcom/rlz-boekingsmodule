"""Anker-VANGNET (route A): een bestaand systeemanker "Pandprojecten (systeem)" krijgt nooit
een boeking — naam-/GUID-toetsen plus de blokkerende checks in de boekpaden
(verkoop-checkrapport, zorg_voor_debiteur-slot, doorbelasting-whitelist-toets). Sinds de
klant-loze schrijfroute (hertest 2026-08-14) maakt de motor geen ankers meer aan; het vangnet
blijft zolang er nog een anker-debiteur in een administratie bestaat (zie app/projecten/
anker.py)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.doorbelasting import checks as doorbelasting_checks
from app.projecten import anker
from app.verkoop import checks as verkoop_checks
from app.verkoop.debiteur import DebiteurAanmakenMislukt, zorg_voor_debiteur

ADMINISTRATIE_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


class TestAnkerNaamEnGuid:
    def test_naamtoets_normaliseert_hoofdletters_en_whitespace(self) -> None:
        assert anker.is_anker_naam("Pandprojecten (systeem)")
        assert anker.is_anker_naam("  pandprojecten   (SYSTEEM) ")
        assert not anker.is_anker_naam("Pandprojecten")
        assert not anker.is_anker_naam(None)
        assert not anker.is_anker_naam("")

    def test_anker_guid_is_deterministisch_per_administratie(self) -> None:
        assert anker.anker_customer_id(ADMINISTRATIE_ID) == anker.anker_customer_id(ADMINISTRATIE_ID)
        assert anker.anker_customer_id(ADMINISTRATIE_ID) != anker.anker_customer_id(uuid.uuid4())


class TestVerkoopCheck:
    def test_ankernaam_blokkeert(self) -> None:
        resultaat = verkoop_checks.check_geen_ankerdebiteur(debiteur_naam="pandprojecten (systeem)")
        assert resultaat.ok is False
        assert "systeemanker" in resultaat.melding

    def test_echte_huurder_passeert(self) -> None:
        assert verkoop_checks.check_geen_ankerdebiteur(debiteur_naam="J. van den Berg").ok is True

    def test_check_zit_in_het_rapport(self) -> None:
        rapport = verkoop_checks.voer_verkoop_checks_uit(
            debiteur_naam="Pandprojecten (systeem)",
            factuurnummer="VF-1",
            factuurdatum=None,
            totaalbedrag_incl=None,
            regels=[],
            lokale_duplicaat_hits=0,
            rlz_duplicaat_hits=0,
            is_creditnota=False,
            gecrediteerd_factuurnummer=None,
            origineel_geboekt=False,
        )
        resultaat = next(r for r in rapport.resultaten if r.naam == "geen_ankerdebiteur")
        assert resultaat.ok is False
        assert rapport.geblokkeerd


class _FakeClient:
    """Alleen wat zorg_voor_debiteur aanraakt vóór het blok — nooit een PUT."""

    def __init__(self, gevonden: list[dict] | None = None) -> None:
        self.gevonden = gevonden or []
        self.put_customer_aangeroepen = False

    def find_customers_by_name(self, *, name: str) -> list[dict]:
        return self.gevonden

    def put_customer(self, *args, **kwargs):  # pragma: no cover — mag nooit bereikt worden
        self.put_customer_aangeroepen = True
        raise AssertionError("PUT op het anker mag nooit gebeuren")


class TestZorgVoorDebiteurSlot:
    def test_ankernaam_blokkeert_voor_elke_rlz_call(self) -> None:
        client = _FakeClient()
        with pytest.raises(DebiteurAanmakenMislukt, match="projectanker"):
            zorg_voor_debiteur(
                client=client,  # type: ignore[arg-type]
                administratie_id=ADMINISTRATIE_ID,
                actor_id=uuid.uuid4(),
                naam="  Pandprojecten (Systeem) ",
            )

    def test_hernoemd_anker_wordt_op_guid_gevangen(self) -> None:
        # Het anker is in RLZ hernoemd naar een onschuldige naam maar draagt nog het
        # deterministische motor-GUID — de lookup vindt 'm, het GUID-slot blokkeert.
        anker_guid = anker.anker_customer_id(ADMINISTRATIE_ID)
        client = _FakeClient(gevonden=[{"id": str(anker_guid)}])
        with pytest.raises(DebiteurAanmakenMislukt, match="projectanker"):
            zorg_voor_debiteur(
                client=client,  # type: ignore[arg-type]
                administratie_id=ADMINISTRATIE_ID,
                actor_id=uuid.uuid4(),
                naam="Jansen BV",
            )

    def test_gewone_bestaande_debiteur_passeert(self) -> None:
        bestaand = uuid.uuid4()
        client = _FakeClient(gevonden=[{"id": str(bestaand)}])
        resultaat = zorg_voor_debiteur(
            client=client,  # type: ignore[arg-type]
            administratie_id=ADMINISTRATIE_ID,
            actor_id=uuid.uuid4(),
            naam="Jansen BV",
        )
        assert resultaat == bestaand


def _verdeelregel(mapping_id: uuid.UUID) -> doorbelasting_checks.VerdeelRegelInvoer:
    return doorbelasting_checks.VerdeelRegelInvoer(
        bron_regel_id=uuid.uuid4(),
        bron_netto=Decimal("100.00"),
        mapping_id=mapping_id,
        percentage=Decimal("100"),
        netto_deel=Decimal("100.00"),
        doel_kosten_ledger_id=None,
    )


def _mapping(mapping_id: uuid.UUID, customer_guid: uuid.UUID) -> doorbelasting_checks.MappingInvoer:
    return doorbelasting_checks.MappingInvoer(
        mapping_id=mapping_id,
        actief=True,
        doel_administratie_id=None,
        provisie_kosten_ledger_id=None,
        doel_customer_guid=customer_guid,
    )


class TestDoorbelastingCheck:
    def test_anker_guid_in_whitelist_blokkeert(self) -> None:
        mapping_id = uuid.uuid4()
        resultaat = doorbelasting_checks.check_geen_ankerdebiteur(
            [_verdeelregel(mapping_id)],
            {mapping_id: _mapping(mapping_id, anker.anker_customer_id(ADMINISTRATIE_ID))},
            anker_customer_guid=anker.anker_customer_id(ADMINISTRATIE_ID),
        )
        assert resultaat.ok is False
        assert "projectanker" in resultaat.melding

    def test_gewone_doelentiteit_passeert(self) -> None:
        mapping_id = uuid.uuid4()
        resultaat = doorbelasting_checks.check_geen_ankerdebiteur(
            [_verdeelregel(mapping_id)],
            {mapping_id: _mapping(mapping_id, uuid.uuid4())},
            anker_customer_guid=anker.anker_customer_id(ADMINISTRATIE_ID),
        )
        assert resultaat.ok is True

    def test_check_zit_in_het_rapport(self) -> None:
        mapping_id = uuid.uuid4()
        rapport = doorbelasting_checks.voer_doorbelasting_checks_uit(
            regels=[_verdeelregel(mapping_id)],
            mappings={mapping_id: _mapping(mapping_id, anker.anker_customer_id(ADMINISTRATIE_ID))},
            provisie_percentage=Decimal("0"),
            btw_taxrate_id=uuid.uuid4(),
            omzet_ledger_id=uuid.uuid4(),
            anker_customer_guid=anker.anker_customer_id(ADMINISTRATIE_ID),
        )
        resultaat = next(r for r in rapport.resultaten if r.naam == "Geen boeking op het projectanker")
        assert resultaat.ok is False
