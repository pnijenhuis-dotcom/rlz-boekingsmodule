# ruff: noqa: F811 — pytest-fixtures als parameters
"""Detectie bij boeken (ontwerp §2): kandidaat = regel op een is_activa-rekening ≥ grens; onder de grens = oranje
signaal;
bestaande koppeling reist mee; RLZ-grens wint van de instelling; geen boekvoorstel/geen inkoopfactuur = lege kaart."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.activa import instelling as instelling_service
from app.activa import service
from app.activa.models import ActivaInstelling
from app.db.session import scoped_session
from app.documenten.service import DocumentNietGevonden
from app.documenten.storage import LokaleBestandsopslag
from tests.activa.conftest import GB_0107, GB_0108, GB_0170, GB_4400, maak_factuur, regel


class TestKandidaten:
    def test_regel_op_mva_rekening_boven_grens_is_kandidaat_met_voorvulling(
        self, factuur: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        data = service.haal_voorstel_op(administratie_id=administratie_id, document_id=factuur)
        assert data.document_geboekt is False and data.stand.effectieve_grens == Decimal("450.00")
        assert data.stand.grens_bron == "instelling" and data.stand.automatisch_aanmaken_ingeschakeld is False
        assert len(data.kandidaten) == 1 and data.onder_grens == []
        k = data.kandidaten[0]
        assert k.regel_volgnummer == 1 and k.ledger_code == "0107"
        assert k.omschrijving == "Bureau Hoogte-verstelbaar"
        assert k.aanschafwaarde == Decimal("1250.00") and k.aanschafdatum == date(2026, 9, 1)
        assert k.categorie == "inventaris" and k.categorie_label == "Inventaris"
        assert k.termijn_maanden == 60 and k.methode_naam == "Lineair 5 jaar" and k.restwaarde == Decimal("0.00")
        # BUG 24-09 punt 1: geen instelling → conventie code + 1 mét naam "Afschrijving…" (0107 → 0108), herkomst-chip.
        assert k.afschrijving_ledger_id == GB_0108 and k.afschrijving_ledger_code == "0108"
        assert k.afschrijving_bron == "conventie"
        assert [s.code for s in k.signalen] == ["kia_mia_mogelijk"]
        assert k.koppeling is None
        # Opties: alle 0xxx-rekeningen soort 3, 'afschrijving' eerst, dan op code.
        assert [r.code for r in data.afschrijving_ledger_opties] == ["0108", "0107", "0170"]

    def test_onder_de_grens_is_oranje_signaal_geen_kandidaat(
        self,
        stamgegevens: None,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        doc = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel(GB_0107, "120.00", "Bureaustoel"), regel(GB_0170, "449.99", "Muis + toetsenbord")],
            referentie="KI-KLEIN",
        )
        data = service.haal_voorstel_op(administratie_id=administratie_id, document_id=doc)
        assert data.kandidaten == []
        assert [(o.regel_volgnummer, o.ledger_code, o.netto) for o in data.onder_grens] == [
            (1, "0107", Decimal("120.00")),
            (2, "0170", Decimal("449.99")),
        ]
        assert "onder de grens € 450.00" in data.onder_grens[0].tekst
        assert data.leeg is False

    def test_kostenregel_en_negatieve_regel_tellen_niet(
        self,
        stamgegevens: None,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        doc = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel(GB_4400, "5000.00", "Inhuur"), regel(GB_0107, "-800.00", "Creditregel inventaris")],
            referentie="KI-KOSTEN",
        )
        data = service.haal_voorstel_op(administratie_id=administratie_id, document_id=doc)
        assert data.leeg is True

    def test_instelling_stuurt_termijn_afschrijvingsrekening_en_grens(
        self, factuur: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        with scoped_session(administratie_id) as session:
            session.add(
                ActivaInstelling(
                    administratie_id=administratie_id,
                    activeringsgrens=Decimal("1000.00"),
                    termijnen={"inventaris": 120},
                    afschrijving_ledgers={"inventaris": str(GB_0108)},
                )
            )
        data = service.haal_voorstel_op(administratie_id=administratie_id, document_id=factuur)
        k = data.kandidaten[0]
        assert data.stand.effectieve_grens == Decimal("1000.00") and data.stand.grens_bron == "instelling"
        assert k.termijn_maanden == 120 and k.methode_naam == "Lineair 10 jaar"
        assert k.afschrijving_ledger_id == GB_0108 and k.afschrijving_ledger_code == "0108"
        assert k.afschrijving_bron == "instelling"  # instelling wint van de conventie

    def test_rlz_grens_wint_van_de_instelling(self, factuur: uuid.UUID, administratie_id: uuid.UUID) -> None:
        with scoped_session(administratie_id) as session:
            session.add(
                ActivaInstelling(
                    administratie_id=administratie_id, activeringsgrens=Decimal("100.00"), grens_rlz=Decimal("2000.00")
                )
            )
        data = service.haal_voorstel_op(administratie_id=administratie_id, document_id=factuur)
        assert data.stand.effectieve_grens == Decimal("2000.00") and data.stand.grens_bron == "rlz"
        assert data.kandidaten == [] and len(data.onder_grens) == 1  # € 1.250 valt nu onder de RLZ-grens

    def test_computerrekening_krijgt_drie_jaar_en_20pct_signaal(
        self,
        stamgegevens: None,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        doc = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel(GB_0170, "2400.00", "Laptop")],
            referentie="KI-LAPTOP",
        )
        k = service.haal_voorstel_op(administratie_id=administratie_id, document_id=doc).kandidaten[0]
        assert k.categorie == "computers_software" and k.termijn_maanden == 36
        assert [s.code for s in k.signalen] == ["afschrijving_boven_20pct", "kia_mia_mogelijk"]
        # 0170 heeft geen 0171 "Afschrijving…" → geen conventie, leeg (de kaart maakt de combobox dan verplicht).
        assert k.afschrijving_ledger_id is None and k.afschrijving_bron is None

    def test_onbekend_document_is_404_domeinfout(self, stamgegevens: None, administratie_id: uuid.UUID) -> None:
        with pytest.raises(DocumentNietGevonden):
            service.haal_voorstel_op(administratie_id=administratie_id, document_id=uuid.uuid4())

    def test_stand_zonder_rij_heeft_de_ontwerp_defaults(self, administratie_id: uuid.UUID) -> None:
        with scoped_session(administratie_id) as session:
            stand = instelling_service.lees_stand(session, administratie_id)
        assert stand.automatisch_aanmaken_ingeschakeld is False
        assert stand.effectieve_grens == Decimal("450.00") and stand.grens_bron == "instelling"
        assert stand.termijn_voor("steigermateriaal") == 60 and stand.afschrijving_ledger_voor("inventaris") is None
        assert stand.register_leesbaar is None
