# ruff: noqa: F811
"""Blok F 06-09 — instroom ín de boek-transactie (②), matchvolgorde (①), nieuw product mét vlag (④), storno-spiegel
bij tegenboeken, idempotentie per (document, cyclus), gearchiveerd product herleeft. Code voor cijfers — geen AI."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.documenten import boeken, tegenboeken
from app.documenten.models import DocumentStatus
from app.mini_voorraad import instroom, service
from app.mini_voorraad.instroom import beoordeel_regels
from tests.mini_voorraad.conftest import (
    ANDERE_VENDOR_ID,
    FACTUURDATUM,
    VENDOR_NAAM,
    audit_acties,
    maak_document,
    mutaties,
    regel,
    standen,
    tijdlijn_details,
)

pytestmark = pytest.mark.usefixtures("_opslag_naar_tmp")


class TestPureMatchlogica:
    def test_beoordeel_regels_selecteert_deterministisch(self) -> None:
        uit = beoordeel_regels(
            [
                regel("Stapelbok 1,25×0,85", "24", "560140.4"),
                regel("Transportkosten", "1"),
                regel("Montage uren", "8"),
                regel("Kanaalplaatvork speciaal", None),
                regel("AR-40 gaffel", "0"),
                {"omschrijving": ""},  # lege regel telt niet mee (ook niet in de nummering)
                regel("Wielset 200 mm", "1.234,5", e="set"),
            ]
        )
        assert [u.volgnummer for u in uit] == [1, 2, 3, 4, 5, 6]
        assert uit[0].overslaan_reden is None and uit[0].aantal == Decimal("24") and uit[0].artikelcode == "560140.4"
        assert uit[1].overslaan_reden == "transportregel"
        assert uit[2].overslaan_reden == "dienstregel"
        assert uit[3].overslaan_reden == "geen aantal op de regel"
        assert uit[4].overslaan_reden == "aantal 0"
        assert uit[5].aantal == Decimal("1234.5") and uit[5].eenheid == "set"

    def test_aantal_parser_en_weergave(self) -> None:
        assert service.parse_aantal("4") == Decimal("4.000")
        assert service.parse_aantal("2,5") == Decimal("2.500")
        for fout in ("0", "-3", "abc", "1.2345", ""):
            with pytest.raises(service.OngeldigeInvoer):
                service.parse_aantal(fout)
        assert service.als_aantal_str(Decimal("96.000")) == "96"
        assert service.als_aantal_str(Decimal("12.500")) == "12.5"
        assert service.als_aantal_str(Decimal("-4")) == "-4"
        assert service.als_aantal_str(Decimal("0")) == "0"
        assert service.als_aantal_str(Decimal("1000")) == "1000"

    def test_resultaat_tekst(self) -> None:
        r = instroom.InstroomResultaat(regels=3, nieuwe_producten=["Kanaalplaatvork speciaal"], bestaande=2)
        assert r.tekst == "Mini-voorraad bijgewerkt — 3 regels · nieuw: Kanaalplaatvork speciaal"
        assert instroom.InstroomResultaat(regels=1).tekst == "Mini-voorraad bijgewerkt — 1 regel"


class TestInstroomInBoekTransactie:
    def test_boeken_telt_productregels_bij_en_meldt_in_tijdlijn(
        self, mini_voorraad_aan, fake_client, administratie_id, gescoopte_gebruiker, opslag, admin_engine: Engine
    ) -> None:
        doc = maak_document(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[
                regel("Stapelbok 1,25×0,85", "24", "560140.4"),
                regel("AR-40 gaffel", "12"),
                regel("Kanaalplaatvork speciaal", "6"),
                regel("Transportkosten", "1"),
                regel("Kanaalplaatvork groot", None),  # géén dienstwoord, wél zonder aantal
            ],
        )
        resultaat = boeken.boek_document(
            administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker
        )
        assert resultaat.status == DocumentStatus.GEBOEKT
        assert resultaat.mini_voorraad is not None
        assert resultaat.mini_voorraad.regels == 3
        assert resultaat.mini_voorraad.nieuwe_producten == [
            "Stapelbok 1,25×0,85",
            "AR-40 gaffel",
            "Kanaalplaatvork speciaal",
        ]
        assert resultaat.mini_voorraad.bestaande == 0
        # Transportkosten (transportregel) + statiegeld zonder aantal — beide mét leesbare reden.
        assert [o.split(" — ")[1] for o in resultaat.mini_voorraad.overgeslagen] == [
            "transportregel",
            "geen aantal op de regel",
        ]

        assert standen(admin_engine, administratie_id) == {
            "Stapelbok 1,25×0,85": Decimal("24.000"),
            "AR-40 gaffel": Decimal("12.000"),
            "Kanaalplaatvork speciaal": Decimal("6.000"),
        }
        rijen = mutaties(admin_engine, administratie_id, "instroom")
        assert [(r["regel_volgnummer"], r["boek_cyclus"], r["datum"]) for r in rijen] == [
            (1, 0, FACTUURDATUM),
            (2, 0, FACTUURDATUM),
            (3, 0, FACTUURDATUM),
        ]
        assert all(r["document_id"] == doc for r in rijen)
        with admin_engine.connect() as conn:
            producten = conn.execute(
                text(
                    "SELECT omschrijving, artikelcode, leverancier_naam, eenheid, nieuw_controleren, bron_document_id "
                    "FROM mi.mini_product WHERE administratie_id = :aid ORDER BY omschrijving"
                ),
                {"aid": administratie_id},
            ).all()
        assert [tuple(p) for p in producten] == [
            ("AR-40 gaffel", None, VENDOR_NAAM, "st", True, doc),
            ("Kanaalplaatvork speciaal", None, VENDOR_NAAM, "st", True, doc),
            ("Stapelbok 1,25×0,85", "560140.4", VENDOR_NAAM, "st", True, doc),
        ]
        [detail] = tijdlijn_details(admin_engine, doc, instroom.TIJDLIJN_SLEUTEL)
        assert detail["regels"] == 3 and detail["nieuwe_producten"][0] == "Stapelbok 1,25×0,85"
        assert detail["tekst"].startswith("Mini-voorraad bijgewerkt — 3 regels · nieuw: ")
        assert audit_acties(admin_engine, "mini_voorraad_instroom") == 1
        assert audit_acties(admin_engine, "mini_product_aangemaakt") == 3

    def test_transportregel_wordt_overgeslagen_met_reden(
        self, mini_voorraad_aan, fake_client, administratie_id, gescoopte_gebruiker, opslag, admin_engine: Engine
    ) -> None:
        doc = maak_document(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel("Transportkosten", "1"), regel("Montage uren", "8")],
        )
        resultaat = boeken.boek_document(
            administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker
        )
        assert resultaat.mini_voorraad is not None and resultaat.mini_voorraad.regels == 0
        assert [o.split(" — ")[1] for o in resultaat.mini_voorraad.overgeslagen] == ["transportregel", "dienstregel"]
        assert standen(admin_engine, administratie_id) == {}
        [detail] = tijdlijn_details(admin_engine, doc, instroom.TIJDLIJN_SLEUTEL)
        assert detail["regels"] == 0 and len(detail["overgeslagen"]) == 2

    def test_opt_in_uit_schrijft_niets(
        self, boeken_aan_zonder_mini, fake_client, administratie_id, gescoopte_gebruiker, opslag, admin_engine: Engine
    ) -> None:
        doc = maak_document(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel("Stapelbok 1,25×0,85", "24", "560140.4")],
        )
        resultaat = boeken.boek_document(
            administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker
        )
        assert resultaat.status == DocumentStatus.GEBOEKT
        assert resultaat.mini_voorraad is None
        assert standen(admin_engine, administratie_id) == {}
        assert tijdlijn_details(admin_engine, doc, instroom.TIJDLIJN_SLEUTEL) == []

    def test_matchvolgorde_code_dan_omschrijving_dan_nieuw_per_leverancier(
        self, mini_voorraad_aan, fake_client, administratie_id, gescoopte_gebruiker, opslag, admin_engine: Engine
    ) -> None:
        doc1 = maak_document(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel("Stapelbok 1,25×0,85", "24", "560140.4"), regel("AR-40 gaffel", "12")],
        )
        boeken.boek_document(administratie_id=administratie_id, document_id=doc1, actor_id=gescoopte_gebruiker)
        # Tweede factuur: andere tekst mét dezelfde code (code wint) · zelfde tekst in andere casing/interpunctie
        # (omschrijving_norm) · onbekende tekst zonder code (nieuw) · zelfde tekst bij een ANDERE leverancier (nieuw).
        doc2 = maak_document(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[
                regel("STAPELBOK 1.25 x 0.85 (gebr.)", "10", "560140.4"),
                regel("AR-40  GAFFEL", "3"),  # casing + dubbele spatie = dezelfde sleutel (⑧: interpunctie niet)
                regel("Wielset 200 mm", "2"),
            ],
        )
        r2 = boeken.boek_document(administratie_id=administratie_id, document_id=doc2, actor_id=gescoopte_gebruiker)
        assert r2.mini_voorraad is not None
        assert r2.mini_voorraad.nieuwe_producten == ["Wielset 200 mm"] and r2.mini_voorraad.bestaande == 2
        doc3 = maak_document(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel("AR-40 gaffel", "5")],
            vendor_id=ANDERE_VENDOR_ID,
        )
        r3 = boeken.boek_document(administratie_id=administratie_id, document_id=doc3, actor_id=gescoopte_gebruiker)
        assert r3.mini_voorraad is not None and r3.mini_voorraad.nieuwe_producten == ["AR-40 gaffel"]
        with admin_engine.connect() as conn:
            rijen = conn.execute(
                text(
                    "SELECT p.omschrijving, p.vendor_id, COALESCE(SUM(m.aantal), 0) FROM mi.mini_product p "
                    "LEFT JOIN mi.mini_voorraad_mutatie m ON m.product_id = p.id WHERE p.administratie_id = :aid "
                    "GROUP BY p.id ORDER BY p.omschrijving, p.vendor_id"
                ),
                {"aid": administratie_id},
            ).all()
        assert [(o, Decimal(s)) for o, _, s in rijen] == [
            ("AR-40 gaffel", Decimal("15.000")),  # Huvanco: 12 + 3
            ("AR-40 gaffel", Decimal("5.000")),  # Wola: eigen product (sleutel per leverancier)
            ("Stapelbok 1,25×0,85", Decimal("34.000")),  # 24 + 10 via de artikelcode
            ("Wielset 200 mm", Decimal("2.000")),
        ]

    def test_idempotent_per_document_en_cyclus(
        self, mini_voorraad_aan, fake_client, administratie_id, gescoopte_gebruiker, opslag, admin_engine: Engine
    ) -> None:
        from app.db.session import scoped_session

        doc = maak_document(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel("Stapelbok 1,25×0,85", "24", "560140.4")],
        )
        boeken.boek_document(administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker)
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            opnieuw = instroom.registreer_bij_boeking(
                session, administratie_id=administratie_id, document_id=doc, boek_cyclus=0, actor_id=gescoopte_gebruiker
            )
        assert opnieuw is None
        assert standen(admin_engine, administratie_id) == {"Stapelbok 1,25×0,85": Decimal("24.000")}
        assert len(mutaties(admin_engine, administratie_id)) == 1

    def test_gearchiveerd_product_herleeft_zonder_tweede_rij(
        self,
        mini_voorraad_aan,
        fake_client,
        administratie_id,
        gescoopte_gebruiker,
        beheerder_id,
        opslag,
        admin_engine: Engine,
    ) -> None:
        doc1 = maak_document(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel("Kanaalplaatvork speciaal", "6")],
        )
        boeken.boek_document(administratie_id=administratie_id, document_id=doc1, actor_id=gescoopte_gebruiker)
        lijst = service.producten(administratie_id=administratie_id, actor_id=gescoopte_gebruiker)
        [product] = lijst.items
        gearchiveerd = service.archiveer(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            product_id=product.id,
            reden="niet meer in gebruik",
        )
        assert gearchiveerd.gearchiveerd is True and gearchiveerd.stand == "6"
        assert service.producten(administratie_id=administratie_id, actor_id=gescoopte_gebruiker).items == []
        doc2 = maak_document(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel("Kanaalplaatvork speciaal", "4")],
        )
        r2 = boeken.boek_document(administratie_id=administratie_id, document_id=doc2, actor_id=gescoopte_gebruiker)
        assert (
            r2.mini_voorraad is not None and r2.mini_voorraad.bestaande == 1 and r2.mini_voorraad.nieuwe_producten == []
        )
        actief = service.producten(administratie_id=administratie_id, actor_id=gescoopte_gebruiker)
        assert [(p.id, p.gearchiveerd, p.stand) for p in actief.items] == [(product.id, False, "10")]
        with admin_engine.connect() as conn:
            n = conn.execute(
                text("SELECT count(*) FROM mi.mini_product WHERE administratie_id = :aid"), {"aid": administratie_id}
            ).scalar_one()
        assert n == 1
        assert audit_acties(admin_engine, "mini_product_gedearchiveerd") == 1


class TestStornoSpiegel:
    def test_tegenboeken_volledig_spiegelt_instroom_naar_nul(
        self, mini_voorraad_aan, fake_client, administratie_id, gescoopte_gebruiker, opslag, admin_engine: Engine
    ) -> None:
        doc = maak_document(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel("Stapelbok 1,25×0,85", "24", "560140.4"), regel("AR-40 gaffel", "12")],
        )
        boeken.boek_document(administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker)
        tegenboeken.voer_tegenboeking_uit(
            administratie_id=administratie_id,
            document_id=doc,
            actor_id=gescoopte_gebruiker,
            soort="volledig",
            reden="verkeerde leverancier gekozen",
        )
        assert standen(admin_engine, administratie_id) == {
            "Stapelbok 1,25×0,85": Decimal("0.000"),
            "AR-40 gaffel": Decimal("0.000"),
        }
        storno = mutaties(admin_engine, administratie_id, "storno")
        assert sorted((r["omschrijving"], r["aantal"], r["boek_cyclus"]) for r in storno) == [
            ("AR-40 gaffel", Decimal("-12.000"), 0),
            ("Stapelbok 1,25×0,85", Decimal("-24.000"), 0),
        ]
        [detail] = tijdlijn_details(admin_engine, doc, instroom.TIJDLIJN_SLEUTEL_STORNO)
        assert detail["regels"] == 2 and "tegengeboekt (volledig)" in detail["reden"]
        assert audit_acties(admin_engine, "mini_voorraad_storno") == 1
        # Het product blijft bestaan (⑥) — alleen de stand is 0; de vlag "nieuw — controleer" blijft staan.
        lijst = service.producten(administratie_id=administratie_id, actor_id=gescoopte_gebruiker)
        assert sorted(p.stand for p in lijst.items) == ["0", "0"]

    def test_registreer_storno_is_idempotent_en_zwijgt_zonder_instroom(
        self, mini_voorraad_aan, fake_client, administratie_id, gescoopte_gebruiker, opslag, admin_engine: Engine
    ) -> None:
        from app.db.session import scoped_session

        doc = maak_document(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel("Stapelbok 1,25×0,85", "24", "560140.4")],
        )
        boeken.boek_document(administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker)
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            assert (
                instroom.registreer_storno(
                    session,
                    administratie_id=administratie_id,
                    document_id=doc,
                    boek_cyclus=0,
                    actor_id=gescoopte_gebruiker,
                )
                == 1
            )
            assert (
                instroom.registreer_storno(
                    session,
                    administratie_id=administratie_id,
                    document_id=doc,
                    boek_cyclus=0,
                    actor_id=gescoopte_gebruiker,
                )
                == 0
            )
            assert (
                instroom.registreer_storno(
                    session,
                    administratie_id=administratie_id,
                    document_id=uuid.uuid4(),
                    boek_cyclus=0,
                    actor_id=gescoopte_gebruiker,
                )
                == 0
            )
        assert standen(admin_engine, administratie_id) == {"Stapelbok 1,25×0,85": Decimal("0.000")}

    def test_tegenboeken_en_opnieuw_boeken_telt_nieuwe_cyclus_opnieuw(
        self, mini_voorraad_aan, fake_client, administratie_id, gescoopte_gebruiker, opslag, admin_engine: Engine
    ) -> None:
        doc = maak_document(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel("Stapelbok 1,25×0,85", "24", "560140.4")],
        )
        boeken.boek_document(administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker)
        resultaat = tegenboeken.voer_tegenboeking_uit(
            administratie_id=administratie_id,
            document_id=doc,
            actor_id=gescoopte_gebruiker,
            soort="vervang",
            reden="regelverdeling gecorrigeerd",
        )
        assert resultaat.status == DocumentStatus.TE_CONTROLEREN
        assert standen(admin_engine, administratie_id) == {"Stapelbok 1,25×0,85": Decimal("0.000")}
        r2 = boeken.boek_document(administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker)
        assert r2.mini_voorraad is not None and r2.mini_voorraad.regels == 1 and r2.mini_voorraad.bestaande == 1
        assert standen(admin_engine, administratie_id) == {"Stapelbok 1,25×0,85": Decimal("24.000")}
        assert sorted((r["soort"], r["boek_cyclus"]) for r in mutaties(admin_engine, administratie_id)) == [
            ("instroom", 0),
            ("instroom", 1),
            ("storno", 0),
        ]
