"""Omzetbatch-posten voor de bank-matchmotor en de reconciliatie (opdracht 4 blok A, 16-09).

Datalaag ZONDER migratie: de posten worden afgeleid uit bestaande rijen — `omzet_boeking` (GEBOEKT, per document) +
het laatste veldvoorstel van het document (`bron`/`bron_detail`) + de actuele bron-instellingen (tegenrekeningen) →
`tegenzijde.bepaal_tegenzijde`. De RLZ-kant per post:
- PIN / Stripe → aflettering tegen de OPEN POST van de Receipt (`payment_item_cache.rlz_document_id ==
  omzet_boeking.verkoop_rlz_id`; deelbedrag = het mutatiebedrag, bewezen actie-15-pad);
- storting kas → bank → direct-op-grootboek op de kas-tegenrekening (bewezen BankMutationDirectBookings-pad).
Gematcht = er bestaat een niet-ingetrokken afletter-opdracht op de Receipt (PIN/Stripe) óf een GEBOEKTE bankboeking
met de deterministische omschrijving `OMSCHRIJVING_PREFIX` (storting), óf de open post van de Receipt is uit RLZ
verdwenen/gesloten. Alleen niet-gematchte posten gaan als kandidaat naar de matchmotor; de reconciliatie meldt een
post ouder dan `TUSSENREKENING_OPEN_DAGEN` dagen zonder match als `tussenrekening_open`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bank.matchmotor import OmzetBatchPost
from app.bank.models import (
    AfletterOpdrachtStatus,
    BankAfletterOpdracht,
    BankBoeking,
    BankBoekingStatus,
    PaymentItemCache,
)
from app.omzet.bronnen import service as bronnen_service
from app.omzet.bronnen import tegenzijde as tz
from app.omzet.models import OmzetBoeking, OmzetBoekingStatus

#: Dagen waarna een niet-gematchte tegenzijde-post een reconciliatie-bevinding wordt (opdracht: 14).
TUSSENREKENING_OPEN_DAGEN = 14
#: Deterministische omschrijving-prefix van een direct-op-grootboek-boeking uit deze stap (storting kas → bank).
OMSCHRIJVING_PREFIX = "omzetbatch"

#: Betaalwijzen die de bank moet laten zien (richting 'ontvangst' in tegenzijde.py).
_BANK_BETAALWIJZEN = frozenset({tz.PIN, tz.STRIPE, tz.STORTING})


@dataclass(frozen=True)
class OmzetBatchStand:
    """Eén tegenzijde-post mét match-stand (voor de reconciliatie en het Bron-blok)."""

    post: OmzetBatchPost
    boeking_id: uuid.UUID
    document_id: uuid.UUID
    gematcht: bool
    match_via: str | None  # 'aflettering' | 'bankboeking' | 'open_post_gesloten' | None

    def dagen_open(self, vandaag: date) -> int | None:
        return (vandaag - self.post.datum).days if self.post.datum else None


def batch_label(bron: str | None, bron_detail: dict, periode_eind: str | None) -> str:
    from app.omzet.bronnen import pilates, zonnestudio

    if bron == pilates.BRON:
        return str(bron_detail.get("batch_id") or periode_eind or "?")
    if bron == zonnestudio.BRON_DAGSTAAT:
        datum = bron_detail.get("datum") or periode_eind
        try:
            d = date.fromisoformat(datum).strftime("%d-%m-%Y") if datum else "?"
        except ValueError:
            d = str(datum)
        store = bron_detail.get("store")
        return f"{d} {store}" if store else d
    return str(periode_eind or "?")


def omzetbatch_standen(session: Session, *, administratie_id: uuid.UUID) -> list[OmzetBatchStand]:
    """Alle tegenzijde-posten (bank-richting) van de GEBOEKTE omzetbron-boekingen van deze administratie mét
    match-stand. Kasposten (Cash) en het kasverschil-signaal horen hier niet: die ziet de bank nooit."""
    boekingen = session.scalars(
        select(OmzetBoeking).where(
            OmzetBoeking.administratie_id == administratie_id,
            OmzetBoeking.status == OmzetBoekingStatus.GEBOEKT.value,
        )
    ).all()
    if not boekingen:
        return []
    instellingen = bronnen_service.bron_instellingen_voor(session, administratie_id)
    rekeningen = bronnen_service.rekeningen_voor(session, administratie_id)
    verkoop_ids = [b.verkoop_rlz_id for b in boekingen]
    open_posten = {
        p.rlz_document_id: p
        for p in session.scalars(
            select(PaymentItemCache).where(
                PaymentItemCache.administratie_id == administratie_id,
                PaymentItemCache.rlz_document_id.in_(verkoop_ids),
            )
        )
    }
    afgeletterd = {
        o.rlz_document_id
        for o in session.scalars(
            select(BankAfletterOpdracht).where(
                BankAfletterOpdracht.administratie_id == administratie_id,
                BankAfletterOpdracht.rlz_document_id.in_(verkoop_ids),
                BankAfletterOpdracht.status != AfletterOpdrachtStatus.INGETROKKEN.value,
            )
        )
    }
    bankboekingen = {
        (b.omschrijving or "")
        for b in session.scalars(
            select(BankBoeking).where(
                BankBoeking.administratie_id == administratie_id,
                BankBoeking.status == BankBoekingStatus.GEBOEKT.value,
                BankBoeking.omschrijving.like(f"{OMSCHRIJVING_PREFIX}%"),
            )
        )
    }
    uit: list[OmzetBatchStand] = []
    for boeking in boekingen:
        vv = bronnen_service._laatste_veldvoorstel(session, boeking.document_id) or {}  # noqa: SLF001
        bron = vv.get("bron")
        detail = vv.get("bron_detail") or {}
        if not bron:
            continue
        tegenzijde = tz.bepaal_tegenzijde(
            bron=bron,
            bron_detail={**detail, "periode_eind": vv.get("periode_eind")},
            instellingen=instellingen,
            rekeningen=rekeningen,
        )
        if tegenzijde is None:
            continue
        label = batch_label(bron, detail, vv.get("periode_eind"))
        open_post = open_posten.get(boeking.verkoop_rlz_id)
        for regel in tegenzijde.regels:
            if regel.betaalwijze not in _BANK_BETAALWIJZEN:
                continue
            if regel.betaalwijze == tz.STORTING:
                post = OmzetBatchPost(
                    id=boeking.document_id,
                    batch_label=label,
                    betaalwijze=regel.betaalwijze,
                    bedrag=regel.bedrag,
                    datum=regel.datum or boeking.periode_eind,
                    venster=tz.VENSTER_DAGEN[regel.betaalwijze],
                    kernen=tz.OMSCHRIJVINGSKERNEN[regel.betaalwijze],
                    label=regel.label,
                    ledger_id=regel.ledger_id,
                )
                omschrijving = bankboeking_omschrijving(post)
                gematcht = omschrijving in bankboekingen
                via = "bankboeking" if gematcht else None
            else:
                item_id = open_post.id if open_post is not None and open_post.verdwenen_uit_bron_op is None else None
                post = OmzetBatchPost(
                    id=boeking.document_id,
                    batch_label=label,
                    betaalwijze=regel.betaalwijze,
                    bedrag=regel.bedrag,
                    datum=regel.datum or boeking.periode_eind,
                    venster=tz.VENSTER_DAGEN[regel.betaalwijze],
                    kernen=tz.OMSCHRIJVINGSKERNEN[regel.betaalwijze],
                    label=regel.label,
                    payment_item_id=item_id,
                    rlz_document_id=boeking.verkoop_rlz_id,
                )
                if boeking.verkoop_rlz_id in afgeletterd:
                    gematcht, via = True, "aflettering"
                elif open_post is not None and (
                    open_post.verdwenen_uit_bron_op is not None
                    or (open_post.bedrag is not None and open_post.bedrag == 0)
                ):
                    gematcht, via = True, "open_post_gesloten"
                else:
                    gematcht, via = False, None
            uit.append(
                OmzetBatchStand(
                    post=post, boeking_id=boeking.id, document_id=boeking.document_id, gematcht=gematcht, match_via=via
                )
            )
    return uit


def bankboeking_omschrijving(post: OmzetBatchPost) -> str:
    """Deterministische omschrijving van de direct-op-grootboek-boeking (storting) — tevens de match-sleutel."""
    return f"{OMSCHRIJVING_PREFIX} {post.batch_label} · {post.label}"


def omzetbatch_posten_voor(session: Session, *, administratie_id: uuid.UUID) -> list[OmzetBatchPost]:
    """De nog niet gematchte posten — de invoer van matchmotor-stap 2b."""
    standen = omzetbatch_standen(session, administratie_id=administratie_id)
    return [stand.post for stand in standen if not stand.gematcht]


def open_tussenrekening_posten(
    session: Session, *, administratie_id: uuid.UUID, vandaag: date, dagen: int = TUSSENREKENING_OPEN_DAGEN
) -> list[OmzetBatchStand]:
    """Niet-gematchte posten ouder dan `dagen` — de reconciliatie-bevinding `tussenrekening_open`."""
    return [
        stand
        for stand in omzetbatch_standen(session, administratie_id=administratie_id)
        if not stand.gematcht and (d := stand.dagen_open(vandaag)) is not None and d > dagen
    ]
