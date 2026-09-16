"""Matchmotor-stap 2b "omzetbatch-post" (opdracht 4 blok A, besluiten Peter 16-09): de tegenzijde van een geboekte
omzetbatch (Stripe-payout, PIN, storting kas → bank) is een matchbare post — bedrag cent-exact, datumvenster (Stripe
+1…+7 d ná de uitbetalingsdatum, NOOIT ervoor; storting ± 3 d), omschrijvingskern. Puur (unit) + de datalaag zonder
migratie (posten uit omzet_boeking + veldvoorstel + open post van de Receipt) + de reconciliatie
`tussenrekening_open`."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.bank import matchmotor, voorstellen
from app.bank.matchmotor import MutatieGegevens, OmzetBatchPost, VoorstelSoort, bepaal_voorstel
from app.bank.models import AfletterOpdrachtStatus, BankAfletterOpdracht, BankMutatie, PaymentItemCache
from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten.models import DocumentSoort
from app.omzet import reconciliatie as omzet_reconciliatie
from app.omzet import tegenzijde_posten
from app.omzet.bronnen import pilates, tegenzijde, zonnestudio
from app.omzet.models import OmzetBoeking, OmzetBoekingStatus
from tests.documenten.conftest import _opslag_naar_tmp, opslag  # noqa: F401 — pytest-fixtures
from tests.omzet.conftest import voeg_veldvoorstel_toe
from tests.omzet.test_bronnen import DAGSTAAT, EXPORT, KASCHECK, seed_rekeningschema

UITBETAALDATUM = date(2026, 7, 9)


def _payout(
    *,
    bedrag: str = "637.08",
    dagen_na: int = 1,
    omschrijving: str = "STRIPE PAYOUT 2026-7-9",
    naam: str = "Stripe Payments Europe Ltd",
) -> MutatieGegevens:
    return MutatieGegevens(
        id=uuid.uuid4(),
        bedrag=Decimal(bedrag),
        open_bedrag=Decimal(bedrag),
        tegenpartij_naam=naam,
        omschrijving=omschrijving,
        tegenrekening_iban="IE29AIBK93115212345678",
        rlz_voorstel_item_id=None,
        boekdatum=UITBETAALDATUM + timedelta(days=dagen_na),
    )


def _stripe_post(**over) -> OmzetBatchPost:  # noqa: ANN003
    basis = dict(
        id=uuid.uuid4(),
        batch_label="2026-7-9-ca834c16",
        betaalwijze=tegenzijde.STRIPE,
        bedrag=Decimal("637.08"),
        datum=UITBETAALDATUM,
        venster=tegenzijde.VENSTER_DAGEN[tegenzijde.STRIPE],
        kernen=tegenzijde.OMSCHRIJVINGSKERNEN[tegenzijde.STRIPE],
        label=tegenzijde.LABELS[tegenzijde.STRIPE],
        payment_item_id=uuid.uuid4(),
        rlz_document_id=uuid.uuid4(),
    )
    basis.update(over)
    return OmzetBatchPost(**basis)


class TestStripePayout:
    @pytest.mark.parametrize("dagen_na", [1, 4, 7])
    def test_payout_binnen_1_tot_7_dagen_is_groen_afletterkandidaat(self, dagen_na: int) -> None:
        post = _stripe_post()
        v = bepaal_voorstel(_payout(dagen_na=dagen_na), open_posten=[], vaste_regels=[], omzetbatch_posten=[post])
        assert (v.soort, v.kleur) == (VoorstelSoort.OMZETBATCH_POST, "groen")
        assert v.bron == "omzetbatch 2026-7-9-ca834c16 · Stripe/PSP-uitbetaling"
        assert v.payment_item_id == post.payment_item_id and v.rlz_document_id == post.rlz_document_id
        assert v.ledger_id is None and v.omzetbatch_post == post

    @pytest.mark.parametrize("dagen_na", [0, -1, -3])
    def test_payout_op_of_voor_de_omzetdatum_matcht_nooit(self, dagen_na: int) -> None:
        """Peter 16-09 (2): Stripe loopt altijd achter — een bijschrijving op/vóór de uitbetalingsdatum is een
        andere."""
        v = bepaal_voorstel(
            _payout(dagen_na=dagen_na), open_posten=[], vaste_regels=[], omzetbatch_posten=[_stripe_post()]
        )
        assert v.soort == VoorstelSoort.HANDMATIG

    def test_payout_na_7_dagen_of_ander_bedrag_matcht_niet(self) -> None:
        assert (
            bepaal_voorstel(
                _payout(dagen_na=8), open_posten=[], vaste_regels=[], omzetbatch_posten=[_stripe_post()]
            ).soort
            == VoorstelSoort.HANDMATIG
        )
        assert (
            bepaal_voorstel(
                _payout(bedrag="637.09"), open_posten=[], vaste_regels=[], omzetbatch_posten=[_stripe_post()]
            ).soort
            == VoorstelSoort.HANDMATIG
        )
        # afschrijving met hetzelfde bedrag = geen ontvangst
        assert (
            bepaal_voorstel(
                _payout(bedrag="-637.08"), open_posten=[], vaste_regels=[], omzetbatch_posten=[_stripe_post()]
            ).soort
            == VoorstelSoort.HANDMATIG
        )

    def test_zonder_omschrijvingskern_is_oranje_bevestigen(self) -> None:
        v = bepaal_voorstel(
            _payout(omschrijving="uitbetaling 2026-7-9", naam="Onbekende tegenpartij"),
            open_posten=[],
            vaste_regels=[],
            omzetbatch_posten=[_stripe_post()],
        )
        assert (v.soort, v.kleur) == (VoorstelSoort.OMZETBATCH_POST, "oranje") and "bevestigen" in v.bron
        assert "omschrijving zonder stripe" in v.reden

    def test_open_post_nog_niet_gesynchroniseerd_is_hooguit_oranje(self) -> None:
        post = _stripe_post(payment_item_id=None)
        v = bepaal_voorstel(_payout(), open_posten=[], vaste_regels=[], omzetbatch_posten=[post])
        assert v.kleur == "oranje" and "nog niet gesynchroniseerd" in v.reden

    def test_meerdere_gelijkwaardige_posten_nooit_blind_kiezen(self) -> None:
        v = bepaal_voorstel(
            _payout(),
            open_posten=[],
            vaste_regels=[],
            omzetbatch_posten=[_stripe_post(), _stripe_post(batch_label="2026-7-9-b")],
        )
        assert v.soort == VoorstelSoort.HANDMATIG and "meerdere omzetbatches" in v.bron

    def test_open_post_match_gaat_voor(self) -> None:
        """Stap 1/2 (open posten) blijft vóór stap 2b: een échte open-post-match wint."""
        mutatie = _payout(omschrijving="factuur 2026-0642 STRIPE")
        open_post = matchmotor.OpenPost(
            id=uuid.uuid4(),
            bedrag=Decimal("637.08"),
            referentie="2026-0642",
            referentie2=None,
            rlz_document_id=uuid.uuid4(),
            tegenpartij_naam="Stripe Payments Europe Ltd",
            documentsoort="Verkoopfactuur",
        )
        v = bepaal_voorstel(mutatie, open_posten=[open_post], vaste_regels=[], omzetbatch_posten=[_stripe_post()])
        assert v.soort == VoorstelSoort.EXACTE_MATCH


class TestStortingKasNaarBank:
    def _storting(self, *, dagen: int, omschrijving: str = "Sealbag storting geldautomaat") -> MutatieGegevens:
        return MutatieGegevens(
            id=uuid.uuid4(),
            bedrag=Decimal("80.00"),
            open_bedrag=Decimal("80.00"),
            tegenpartij_naam="ABN AMRO",
            omschrijving=omschrijving,
            tegenrekening_iban=None,
            rlz_voorstel_item_id=None,
            boekdatum=date(2026, 9, 8) + timedelta(days=dagen),
        )

    def _post(self, kas: uuid.UUID | None) -> OmzetBatchPost:
        return OmzetBatchPost(
            id=uuid.uuid4(),
            batch_label="08-09-2026 Elderveld",
            betaalwijze=tegenzijde.STORTING,
            bedrag=Decimal("80.00"),
            datum=date(2026, 9, 8),
            venster=tegenzijde.VENSTER_DAGEN[tegenzijde.STORTING],
            kernen=tegenzijde.OMSCHRIJVINGSKERNEN[tegenzijde.STORTING],
            label=tegenzijde.LABELS[tegenzijde.STORTING],
            ledger_id=kas,
        )

    @pytest.mark.parametrize("dagen", [-3, 0, 3])
    def test_storting_binnen_3_dagen_groen_direct_op_kas(self, dagen: int) -> None:
        kas = uuid.uuid4()
        v = bepaal_voorstel(
            self._storting(dagen=dagen), open_posten=[], vaste_regels=[], omzetbatch_posten=[self._post(kas)]
        )
        assert (v.soort, v.kleur, v.ledger_id, v.payment_item_id) == (VoorstelSoort.OMZETBATCH_POST, "groen", kas, None)
        assert v.bron == "omzetbatch 08-09-2026 Elderveld · Storting automaat (kas → bank)"
        from app.bank.boeken import omzetbatch_naar_boekregels

        regels = omzetbatch_naar_boekregels(voorstel=v, mutatie=self._storting(dagen=dagen))
        assert [(r.ledger_id, r.netto_bedrag, r.btw_bedrag) for r in regels] == [(kas, Decimal("80.00"), None)]
        assert regels[0].omschrijving == "omzetbatch 08-09-2026 Elderveld · Storting automaat (kas → bank)"

    def test_storting_buiten_venster_of_zonder_kasrekening(self) -> None:
        kas = uuid.uuid4()
        assert (
            bepaal_voorstel(
                self._storting(dagen=4), open_posten=[], vaste_regels=[], omzetbatch_posten=[self._post(kas)]
            ).soort
            == VoorstelSoort.HANDMATIG
        )
        v = bepaal_voorstel(
            self._storting(dagen=1), open_posten=[], vaste_regels=[], omzetbatch_posten=[self._post(None)]
        )
        assert v.kleur == "oranje"  # geen tegenrekening = niet uitvoerbaar → nooit groen


# ---------------------------------------------------------------------------------------- datalaag + reconciliatie


def _boek_pilates_batch(
    administratie_id: uuid.UUID, actor: uuid.UUID, opslag, *, verkoop_rlz_id: uuid.UUID
) -> uuid.UUID:  # noqa: ANN001
    """Een GEBOEKTE pilates-batch (2026-7-9-ca834c16, netto 637,08) zonder RLZ-call: veldvoorstel + omzet_boeking-rij."""  # noqa: E501
    bs = {b.batch_id: b for b in pilates.groepeer_batches(pilates.parse_transacties(EXPORT))}
    vv = pilates.bouw_batch_veldvoorstel(bs["2026-7-9-ca834c16"])
    doc = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="uitbetaling-2026-7-9-ca834c16.pdf",
        inhoud=b"%PDF-1.4 batch",
        actor_id=actor,
        opslag=opslag,
        soort=DocumentSoort.KASSARAPPORT,
    ).document_id
    voeg_veldvoorstel_toe(administratie_id=administratie_id, document_id=doc, actor_id=actor, veldvoorstel=vv)
    with scoped_session(administratie_id, actor_id=actor) as session:
        session.add(
            OmzetBoeking(
                administratie_id=administratie_id,
                document_id=doc,
                periode_start=date(2026, 7, 1),
                periode_eind=date(2026, 7, 9),
                totaal_omzet=Decimal("637.08"),
                totaal_kostprijs=Decimal(0),
                verkoop_rlz_id=verkoop_rlz_id,
                status=OmzetBoekingStatus.GEBOEKT.value,
                geboekt_door=actor,
            )
        )
    return doc


def _open_post(administratie_id: uuid.UUID, *, rlz_document_id: uuid.UUID, bedrag: str = "637.08") -> uuid.UUID:
    item_id = uuid.uuid4()
    with scoped_session(administratie_id) as session:
        session.add(
            PaymentItemCache(
                id=item_id,
                administratie_id=administratie_id,
                bedrag=Decimal(bedrag),
                referentie="801",
                rlz_document_id=rlz_document_id,
                brondata={"Document": {"DocumentType": 10}},
            )
        )
    return item_id


def _bankmutatie(administratie_id: uuid.UUID, *, bedrag: str, boekdatum: date, omschrijving: str) -> uuid.UUID:
    mid = uuid.uuid4()
    with scoped_session(administratie_id) as session:
        session.add(
            BankMutatie(
                id=mid,
                administratie_id=administratie_id,
                boekdatum=boekdatum,
                bedrag=Decimal(bedrag),
                open_bedrag=Decimal(bedrag),
                tegenpartij_naam="Stripe Payments Europe Ltd",
                omschrijving=omschrijving,
                brondata={},
            )
        )
    return mid


class TestDatalaagEnReconciliatie:
    def test_geboekte_batch_wordt_post_en_payout_matcht_groen_in_context(
        self, administratie_id, gescoopte_gebruiker, opslag
    ) -> None:  # noqa: ANN001
        seed_rekeningschema(administratie_id)
        verkoop = uuid.uuid4()
        doc = _boek_pilates_batch(administratie_id, gescoopte_gebruiker, opslag, verkoop_rlz_id=verkoop)
        item = _open_post(administratie_id, rlz_document_id=verkoop)
        mutatie = _bankmutatie(
            administratie_id, bedrag="637.08", boekdatum=date(2026, 7, 10), omschrijving="STRIPE PAYOUT"
        )
        context = voorstellen.laad_matchcontext(administratie_id=administratie_id)
        assert [(p.betaalwijze, p.bedrag, p.datum, p.payment_item_id, p.id) for p in context.omzetbatch_posten] == [
            ("stripe", Decimal("637.08"), UITBETAALDATUM, item, doc)
        ]
        items = {m.mutatie.id: m for m in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)}
        v = items[mutatie].voorstel
        assert (v.soort, v.kleur, v.payment_item_id) == (VoorstelSoort.OMZETBATCH_POST, "groen", item)
        assert items[mutatie].open_post is not None and items[mutatie].open_post.id == item
        # Na een (niet-ingetrokken) afletter-opdracht op de Receipt is de post gematcht → geen kandidaat meer.
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            session.add(
                BankAfletterOpdracht(
                    administratie_id=administratie_id,
                    payment_transaction_id=mutatie,
                    payment_item_id=item,
                    rlz_document_id=verkoop,
                    status=AfletterOpdrachtStatus.KLAARGEZET.value,
                    klaargezet_door=gescoopte_gebruiker,
                )
            )
        with scoped_session(administratie_id) as session:
            standen = tegenzijde_posten.omzetbatch_standen(session, administratie_id=administratie_id)
        assert [(s.gematcht, s.match_via) for s in standen] == [(True, "aflettering")]
        assert voorstellen.laad_matchcontext(administratie_id=administratie_id).omzetbatch_posten == []

    def test_tussenrekening_open_na_14_dagen_zonder_bankmatch(
        self, administratie_id, gescoopte_gebruiker, opslag
    ) -> None:  # noqa: ANN001
        seed_rekeningschema(administratie_id)
        verkoop = uuid.uuid4()
        _boek_pilates_batch(administratie_id, gescoopte_gebruiker, opslag, verkoop_rlz_id=verkoop)
        _open_post(administratie_id, rlz_document_id=verkoop)
        # dag 14: nog geen bevinding; dag 15: wél
        assert (
            omzet_reconciliatie.tussenrekening_open_afwijkingen(
                administratie_id, vandaag=UITBETAALDATUM + timedelta(days=14)
            )
            == []
        )
        afw = omzet_reconciliatie.tussenrekening_open_afwijkingen(
            administratie_id, vandaag=UITBETAALDATUM + timedelta(days=21)
        )
        assert len(afw) == 1 and afw[0].soort == "tussenrekening_open"
        assert "Omzetbatch 2026-7-9-ca834c16: Stripe/PSP-uitbetaling € 637.08 staat al 21 dagen" in afw[0].detail
        assert "koppel de bankontvangst of accepteer met reden" in afw[0].detail
        # Open post uit RLZ verdwenen (betaald) = gematcht → geen bevinding.
        with scoped_session(administratie_id) as session:
            from datetime import UTC, datetime

            for item in session.query(PaymentItemCache).filter_by(rlz_document_id=verkoop):
                item.verdwenen_uit_bron_op = datetime.now(UTC)
        assert (
            omzet_reconciliatie.tussenrekening_open_afwijkingen(
                administratie_id, vandaag=UITBETAALDATUM + timedelta(days=21)
            )
            == []
        )

    def test_zonnestudio_dag_levert_pin_en_storting_posten(self, administratie_id, gescoopte_gebruiker, opslag) -> None:  # noqa: ANN001
        ids = seed_rekeningschema(administratie_id)
        vv = zonnestudio.bouw_veldvoorstel(
            zonnestudio.parse_dagstaat(DAGSTAAT), zonnestudio.parse_kascheck(KASCHECK), bestandsnaam="8-9-26.xls"
        )
        doc = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="8-9-26.pdf",
            inhoud=b"%PDF-1.4 dagstaat",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.KASSARAPPORT,
        ).document_id
        voeg_veldvoorstel_toe(
            administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker, veldvoorstel=vv
        )
        verkoop = uuid.uuid4()
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            session.add(
                OmzetBoeking(
                    administratie_id=administratie_id,
                    document_id=doc,
                    periode_start=date(2026, 9, 8),
                    periode_eind=date(2026, 9, 8),
                    totaal_omzet=Decimal("1019.03"),
                    totaal_kostprijs=Decimal(0),
                    verkoop_rlz_id=verkoop,
                    status=OmzetBoekingStatus.GEBOEKT.value,
                    geboekt_door=gescoopte_gebruiker,
                )
            )
        with scoped_session(administratie_id) as session:
            posten = tegenzijde_posten.omzetbatch_posten_voor(session, administratie_id=administratie_id)
        per = {p.betaalwijze: p for p in posten}
        assert set(per) == {"pin", "storting"}  # cash blijft in de kas, kasverschil is een signaal
        assert (per["pin"].bedrag, per["pin"].payment_item_id, per["pin"].rlz_document_id) == (
            Decimal("932.22"),
            None,
            verkoop,
        )
        assert (per["storting"].bedrag, per["storting"].ledger_id) == (Decimal("80.00"), ids["Kas"])
        assert per["storting"].batch_label == "08-09-2026 Elderveld"
