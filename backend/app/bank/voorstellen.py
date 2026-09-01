"""Service-laag boven de matchmotor: laadt de matchcontext (open mutaties, open posten, vaste
regels, boekhistorie) uit de eigen caches en bouwt per mutatie het verrijkte voorstel voor het
bankdetail-scherm — inclusief herkomst-chip, concrete boekregels bij een vaste regel
(btw-splitsing in code) en het 3×-regelvoorstel."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select

from app.bank import doelpost, matchmotor
from app.bank.models import (
    AfletterOpdrachtStatus,
    BankAfletterOpdracht,
    BankBoeking,
    BankBoekingRegel,
    BankBoekingStatus,
    BankMutatie,
    BankRegel,
    PaymentItemCache,
)
from app.db.session import scoped_session
from app.sync.models import TaxRateCache


def _specs(post) -> "doelpost.DoelPostSpecs":
    """Kaart-specs uit de cache-rij (blok E5): nooit een RLZ-call, ontbrekend = None."""
    return doelpost.specs_uit_cache(
        entity_naam=post.entity_naam, brondata=post.brondata, referentie2=post.referentie2, boekdatum=post.boekdatum
    )


def intercompany_entity_guids(session, *, administratie_id: uuid.UUID) -> set[uuid.UUID]:
    """De entity-GUID's die in deze administratie als intercompany gelden (gevoed door de
    doorbelasting-mapping, migratie 0045). Lokale import: bank kent doorbelasting verder niet."""
    from app.doorbelasting.models import IntercompanyTegenpartij

    return {
        rij.entity_guid
        for rij in session.scalars(
            select(IntercompanyTegenpartij).where(
                IntercompanyTegenpartij.administratie_id == administratie_id,
                IntercompanyTegenpartij.actief.is_(True),
            )
        )
    }


@dataclass(frozen=True)
class MatchContext:
    open_mutaties: list[matchmotor.MutatieGegevens]
    open_posten: list[matchmotor.OpenPost]
    vaste_regels: list[matchmotor.VasteRegelGegevens]
    regel_per_id: dict[uuid.UUID, BankRegel]
    btw_percentage_per_taxrate: dict[uuid.UUID | None, Decimal | None]
    # (tegenpartij_sleutel, ledger_id, taxrate_id) per eerdere handmatige/regel-boeking —
    # voedt het 3×-regelvoorstel.
    boekhistorie: list[tuple[str, uuid.UUID, uuid.UUID | None]] = field(default_factory=list)
    open_opdracht_per_mutatie: dict[uuid.UUID, BankAfletterOpdracht] = field(default_factory=dict)
    boeking_per_mutatie: dict[uuid.UUID, BankBoeking] = field(default_factory=dict)


def _mutatie_gegevens(rij: BankMutatie) -> matchmotor.MutatieGegevens:
    return matchmotor.MutatieGegevens(
        id=rij.id,
        bedrag=rij.bedrag,
        open_bedrag=rij.open_bedrag,
        tegenpartij_naam=rij.tegenpartij_naam,
        omschrijving=rij.omschrijving,
        tegenrekening_iban=rij.tegenrekening_iban,
        rlz_voorstel_item_id=rij.rlz_voorstel_item_id,
    )


def laad_matchcontext(
    *, administratie_id: uuid.UUID, payment_account_id: uuid.UUID | None = None
) -> MatchContext:
    with scoped_session(administratie_id) as session:
        mutatie_query = select(BankMutatie).where(
            BankMutatie.administratie_id == administratie_id,
            BankMutatie.open_bedrag.isnot(None),
            BankMutatie.open_bedrag != 0,
        )
        if payment_account_id is not None:
            mutatie_query = mutatie_query.where(BankMutatie.payment_account_id == payment_account_id)
        mutaties = list(session.scalars(mutatie_query.order_by(BankMutatie.boekdatum.desc())))

        posten = list(
            session.scalars(
                select(PaymentItemCache).where(
                    PaymentItemCache.administratie_id == administratie_id,
                    PaymentItemCache.verdwenen_uit_bron_op.is_(None),
                )
            )
        )
        # RC-consequentie doorbelasting (blok 2, verkenning/16 §2b): open posten van
        # intercompany-tegenpartijen lopen via de rekening-courant en horen in géén enkel
        # afletter-voorstel — hier filteren betekent: onzichtbaar voor alle vier de
        # voorstelsoorten én voor de auto-afletterlus. De fail-closed-poort voor een
        # handmatige poging zit daarnaast in afletteren.zet_klaar_voor_afletteren.
        ic_guids = intercompany_entity_guids(session, administratie_id=administratie_id)
        if ic_guids:
            posten = [p for p in posten if p.entity_guid not in ic_guids]
        regels = list(
            session.scalars(
                select(BankRegel).where(
                    BankRegel.administratie_id == administratie_id, BankRegel.actief.is_(True)
                )
            )
        )
        taxrates = list(
            session.scalars(select(TaxRateCache).where(TaxRateCache.administratie_id == administratie_id))
        )

        boekingen = list(
            session.scalars(select(BankBoeking).where(BankBoeking.administratie_id == administratie_id))
        )
        regel_rijen = list(
            session.scalars(
                select(BankBoekingRegel).where(
                    BankBoekingRegel.bank_boeking_id.in_([b.id for b in boekingen] or [uuid.UUID(int=0)])
                )
            )
        )
        alle_mutaties_op_id = {
            rij.id: rij
            for rij in session.scalars(
                select(BankMutatie).where(BankMutatie.administratie_id == administratie_id)
            )
        }
        open_opdrachten = list(
            session.scalars(
                select(BankAfletterOpdracht).where(
                    BankAfletterOpdracht.administratie_id == administratie_id,
                    BankAfletterOpdracht.status == AfletterOpdrachtStatus.KLAARGEZET.value,
                )
            )
        )

    eerste_regel_per_boeking: dict[uuid.UUID, BankBoekingRegel] = {}
    for regel_rij in sorted(regel_rijen, key=lambda r: (str(r.bank_boeking_id), r.volgnummer)):
        eerste_regel_per_boeking.setdefault(regel_rij.bank_boeking_id, regel_rij)

    boekhistorie: list[tuple[str, uuid.UUID, uuid.UUID | None]] = []
    for boeking in boekingen:
        if boeking.status != BankBoekingStatus.GEBOEKT.value:
            continue
        mutatie = alle_mutaties_op_id.get(boeking.payment_transaction_id)
        eerste_regel = eerste_regel_per_boeking.get(boeking.id)
        if mutatie is None or eerste_regel is None:
            continue
        sleutel = matchmotor.tegenpartij_sleutel(mutatie.tegenpartij_naam)
        if sleutel is not None:
            boekhistorie.append((sleutel, eerste_regel.ledger_id, eerste_regel.taxrate_id))

    return MatchContext(
        open_mutaties=[_mutatie_gegevens(rij) for rij in mutaties],
        open_posten=[
            matchmotor.OpenPost(
                id=post.id,
                bedrag=post.bedrag,
                referentie=post.referentie,
                referentie2=post.referentie2,
                rlz_document_id=post.rlz_document_id,
                **_specs(post).__dict__,
            )
            for post in posten
        ],
        vaste_regels=[
            matchmotor.VasteRegelGegevens(
                id=regel.id,
                tegenpartij_sleutel=regel.tegenpartij_sleutel,
                tegenrekening_iban=regel.tegenrekening_iban,
                ledger_id=regel.ledger_id,
                taxrate_id=regel.taxrate_id,
                project_id=regel.project_id,
                omschrijving=regel.omschrijving,
            )
            for regel in regels
        ],
        regel_per_id={regel.id: regel for regel in regels},
        btw_percentage_per_taxrate={t.id: t.percentage for t in taxrates},
        boekhistorie=boekhistorie,
        open_opdracht_per_mutatie={o.payment_transaction_id: o for o in open_opdrachten},
        boeking_per_mutatie={
            b.payment_transaction_id: b for b in boekingen if b.status == BankBoekingStatus.GEBOEKT.value
        },
    )


@dataclass(frozen=True)
class MutatieMetVoorstel:
    mutatie: matchmotor.MutatieGegevens
    boekdatum: object
    voorstel: matchmotor.Voorstel
    open_post: matchmotor.OpenPost | None
    regel: BankRegel | None
    regel_boekregels: list  # BankBoekRegelInput bij een vaste-regel-voorstel
    regel_voorstel: matchmotor.RegelVoorstel | None
    afletter_opdracht: BankAfletterOpdracht | None


def open_mutaties_met_voorstellen(
    *, administratie_id: uuid.UUID, payment_account_id: uuid.UUID | None = None
) -> list[MutatieMetVoorstel]:
    from app.bank.boeken import regel_naar_boekregels  # lokale import — boeken importeert deze module ook

    context = laad_matchcontext(administratie_id=administratie_id, payment_account_id=payment_account_id)
    bestaande_sleutels = {regel.tegenpartij_sleutel for regel in context.vaste_regels}
    post_per_id = {post.id: post for post in context.open_posten}

    with scoped_session(administratie_id) as session:
        boekdatum_per_id = {
            rij.id: rij.boekdatum
            for rij in session.scalars(
                select(BankMutatie).where(
                    BankMutatie.administratie_id == administratie_id,
                    BankMutatie.id.in_([m.id for m in context.open_mutaties] or [uuid.UUID(int=0)]),
                )
            )
        }

    resultaat: list[MutatieMetVoorstel] = []
    for mutatie in context.open_mutaties:
        voorstel = matchmotor.bepaal_voorstel(
            mutatie, open_posten=context.open_posten, vaste_regels=context.vaste_regels
        )
        regel = context.regel_per_id.get(voorstel.regel_id) if voorstel.regel_id else None
        regel_boekregels = []
        if regel is not None and mutatie.bedrag is not None:
            regel_boekregels = regel_naar_boekregels(
                regel=regel,
                mutatie_bedrag=mutatie.bedrag,
                btw_percentage=context.btw_percentage_per_taxrate.get(regel.taxrate_id),
            )
        regel_voorstel = None
        if voorstel.soort in (matchmotor.VoorstelSoort.HANDMATIG, matchmotor.VoorstelSoort.RLZ_VOORSTEL):
            regel_voorstel = matchmotor.stel_regel_voor(
                tegenpartij_naam=mutatie.tegenpartij_naam,
                historie=context.boekhistorie,
                bestaande_sleutels=bestaande_sleutels,
            )
        resultaat.append(
            MutatieMetVoorstel(
                mutatie=mutatie,
                boekdatum=boekdatum_per_id.get(mutatie.id),
                voorstel=voorstel,
                open_post=post_per_id.get(voorstel.payment_item_id) if voorstel.payment_item_id else None,
                regel=regel,
                regel_boekregels=regel_boekregels,
                regel_voorstel=regel_voorstel,
                afletter_opdracht=context.open_opdracht_per_mutatie.get(mutatie.id),
            )
        )
    return resultaat
