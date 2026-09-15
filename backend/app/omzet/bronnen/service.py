"""Documentenlaag van de deterministische omzetbronnen (Peter 15-09): bron-instellingen per administratie, store →
administratie, de kassarapport-hook voor spreadsheets (geen AVG-gate, geen AI), bundeling dagstaat + kascheck van
dezelfde dag, splitsing van een pilates-export in één kinddocument per uitbetaling, en de idempotentie op
Factuurnummer."""

from __future__ import annotations

import copy
import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Document, DocumentGebeurtenis, DocumentSoort, DocumentStatus
from app.omzet.bronnen import (
    BRON_PILATES,
    BRON_ZONNESTUDIO_DAGSTAAT,
    BRON_ZONNESTUDIO_KASCHECK,
    herken_bron_in_grid,
    lees_grid,
)
from app.omzet.bronnen import pilates as pilates_bron
from app.omzet.bronnen import zonnestudio as zonnestudio_bron
from app.omzet.models import OmzetInstelling

logger = logging.getLogger(__name__)

MODULE = "boekhouding"
#: Statussen waarin een kassarapport-document niet meer meetelt (wederhelft, factuurnummer-dedupe).
_TERMINAAL = (
    DocumentStatus.VERWIJDERD,
    DocumentStatus.GESPLITST,
    DocumentStatus.SAMENGEVOEGD,
    DocumentStatus.AFGEWEZEN,
    DocumentStatus.AFGEVOERD_DUPLICAAT,
)

DEFAULT_BRON_INSTELLINGEN: dict[str, Any] = {
    # POS-storenamen ("Store Used") die naar deze administratie routeren — Beheerder vult (2 studio's).
    "stores": [],
    # Pilates: productnaam → categorie (aanvulling op pilates.DEFAULT_PRODUCT_CATEGORIEEN); mens wint, audit.
    "product_categorieen": {},
    # PSP van de betalingsexport: naam + btw op de transactiekosten (Mollie 21 %, Stripe verlegd) — BESLISPUNT Peter.
    "psp": {"naam": None, "kosten_btw": None},
    # Rekeningen per studio (kas, kruispost pin/psp, vooruitontvangen tegoeden, kasverschil) als GB-code — informatief
    # voor de aflettering/kasboek; de Receipt-regels zelf lopen via de categorie-mapping.
    "rekeningen": {},
}


def bron_instellingen_voor(session: Session, administratie_id: uuid.UUID) -> dict[str, Any]:
    rij = session.get(OmzetInstelling, administratie_id)
    uit = copy.deepcopy(DEFAULT_BRON_INSTELLINGEN)
    for sleutel, waarde in ((rij.bron_instellingen if rij else None) or {}).items():
        if sleutel in uit and isinstance(waarde, dict) and isinstance(uit[sleutel], dict):
            uit[sleutel] = {**uit[sleutel], **waarde}
        else:
            uit[sleutel] = waarde
    return uit


def zet_bron_instellingen(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, waarden: dict[str, Any]
) -> dict[str, Any]:
    """PUT door de Beheerder (Instellingen › Administraties › ‹studio› › Omzet): volledig blok vervangen, audit oud→nieuw."""  # noqa: E501
    toegestaan = set(DEFAULT_BRON_INSTELLINGEN)
    onbekend = set(waarden) - toegestaan
    if onbekend:
        raise ValueError(f"Onbekende sleutel(s) in bron-instellingen: {', '.join(sorted(onbekend))}")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(OmzetInstelling, administratie_id)
        if rij is None:
            rij = OmzetInstelling(administratie_id=administratie_id)
            session.add(rij)
        oud = copy.deepcopy(rij.bron_instellingen or {})
        rij.bron_instellingen = {k: v for k, v in waarden.items() if v not in (None, {}, [])} or None
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="omzet_instelling",
            record_id=administratie_id,
            actie="omzet_bron_instellingen_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde=rij.bron_instellingen or {},
            administratie_id=administratie_id,
        )
        session.flush()
        return bron_instellingen_voor(session, administratie_id)


def administratie_voor_store(store: str | None) -> uuid.UUID | None:
    """Store-naam uit de dagstaat → de administratie die 'm in `bron_instellingen.stores` heeft (hoofdletterongevoelig);
    geen of meerdere treffers = None (verzamelbak, nooit raden)."""
    if not store:
        return None
    doel = store.strip().lower()
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        administraties = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))))
    treffers: list[uuid.UUID] = []
    for aid in administraties:
        with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
            stores = bron_instellingen_voor(session, aid).get("stores") or []
        if any(str(s).strip().lower() == doel for s in stores):
            treffers.append(aid)
    return treffers[0] if len(treffers) == 1 else None


# ---------------------------------------------------------------------------------------- lezen van documenten


def _laatste_veldvoorstel(session: Session, document_id: uuid.UUID) -> dict | None:
    laatste = None
    for g in session.scalars(
        select(DocumentGebeurtenis)
        .where(DocumentGebeurtenis.document_id == document_id, DocumentGebeurtenis.detail.has_key("veldvoorstel"))
        .order_by(DocumentGebeurtenis.tijdstip)
    ):
        laatste = g.detail["veldvoorstel"]
    return laatste


def _kassarapporten_met_bron(
    session: Session, *, administratie_id: uuid.UUID, bron: str, behalve: uuid.UUID
) -> list[tuple[Document, dict]]:
    uit: list[tuple[Document, dict]] = []
    for doc in session.scalars(
        select(Document).where(
            Document.administratie_id == administratie_id,
            Document.soort == DocumentSoort.KASSARAPPORT.value,
            Document.status.notin_(_TERMINAAL),
            Document.id != behalve,
        )
    ):
        vv = _laatste_veldvoorstel(session, doc.id)
        if vv and vv.get("bron") == bron:
            uit.append((doc, vv))
    return uit


def geboekte_factuurnummers(session: Session, *, administratie_id: uuid.UUID, behalve: uuid.UUID) -> set[str]:
    """Alle transactie-id's (Factuurnummer) die al in een ander pilates-kassarapport van deze administratie staan
    (niet-terminaal) — de idempotentie over overlappende week-/maandexports."""
    uit: set[str] = set()
    for _doc, vv in _kassarapporten_met_bron(
        session, administratie_id=administratie_id, bron=BRON_PILATES, behalve=behalve
    ):
        uit |= set((vv.get("bron_detail") or {}).get("transactie_ids") or [])
    return uit


# ---------------------------------------------------------------------------------------- de hook


def verwerk_spreadsheet(session: Session, *, document: Document, inhoud: bytes) -> dict:
    """Detail voor de extractie-eindovergang van een KASSARAPPORT-spreadsheet: `{"veldvoorstel": …}` (mét `bron`), of
    `{"bron_parse_fout": …}` (zichtbaar, handmatig), of `{"samengevoegd_in_document_id": …}` (kascheck die bij een al
    aanwezige dagstaat is gevoegd), of `{"veldvoorstel": …, "bron_splitsing": [batch-id's]}` (pilates-export mét
    meerdere
    uitbetalingen: de post-commit-stap maakt per batch een kinddocument)."""
    try:
        grid = lees_grid(document.bestandsnaam, inhoud)
    except Exception as exc:  # noqa: BLE001 — onleesbaar bestand = zichtbaar, nooit een 500 op de upload
        return {"bron_parse_fout": f"spreadsheet onleesbaar: {exc}"}
    bron = herken_bron_in_grid(grid)
    if bron is None:
        return {
            "bron_parse_fout": "geen bekende omzetbron (verwacht: Daily Sales-dagstaat, Kascheck of betalingsexport)"
        }
    if document.administratie_id is None:
        return {"bron_parse_fout": "geen administratie — wijs het document eerst toe"}
    try:
        if bron == BRON_ZONNESTUDIO_DAGSTAAT:
            return _verwerk_dagstaat(session, document=document, grid=grid)
        if bron == BRON_ZONNESTUDIO_KASCHECK:
            return _verwerk_kascheck(session, document=document, grid=grid)
        return _verwerk_pilates(session, document=document, grid=grid)
    except Exception as exc:  # noqa: BLE001 — een parserfout is een zichtbare uitkomst
        logger.exception("Omzetbron %s: verwerking mislukt voor document %s", bron, document.id)
        return {"bron_parse_fout": f"{bron}: {exc}"}


def _datum_van(vv: dict) -> date | None:
    d = (vv.get("bron_detail") or {}).get("datum") or vv.get("periode_start")
    try:
        return date.fromisoformat(d) if d else None
    except ValueError:
        return None


def _verwerk_dagstaat(session: Session, *, document: Document, grid) -> dict:  # noqa: ANN001
    staat = zonnestudio_bron.parse_dagstaat(grid)
    kascheck = None
    wederhelft: Document | None = None
    for doc, vv in _kassarapporten_met_bron(
        session, administratie_id=document.administratie_id, bron=BRON_ZONNESTUDIO_DAGSTAAT, behalve=document.id
    ):
        detail = vv.get("bron_detail") or {}
        if detail.get("wacht_op") == "dagstaat" and _datum_van(vv) == staat.datum and detail.get("kas"):
            kascheck = _kascheck_uit_detail(detail)
            wederhelft = doc
            break
    veldvoorstel = zonnestudio_bron.bouw_veldvoorstel(staat, kascheck, bestandsnaam=document.bestandsnaam)
    if wederhelft is not None:
        _markeer_samengevoegd(session, bron_document=wederhelft, doel_document=document)
        veldvoorstel["bron_detail"]["kascheck_document_id"] = str(wederhelft.id)
    return {"veldvoorstel": veldvoorstel}


def _kascheck_uit_detail(detail: dict) -> zonnestudio_bron.Kascheck:
    from decimal import Decimal

    kas = detail.get("kas") or {}

    def d(k: str) -> Decimal | None:
        w = kas.get(k)
        return Decimal(w) if w not in (None, "None") else None

    k = zonnestudio_bron.Kascheck(
        datum=date.fromisoformat(detail["datum"]) if detail.get("datum") else None,
        beginsaldo=d("beginsaldo"),
        telling=d("telling"),
        eindsaldo=d("eindsaldo"),
        storting=d("storting_automaat"),
        eindsaldo_na_storting=d("eindsaldo_na_storting"),
        contante_omzet=d("contante_omzet"),
    )
    k.controles = zonnestudio_bron._controles_kascheck(k)  # noqa: SLF001 — zelfde module-familie
    return k


def _verwerk_kascheck(session: Session, *, document: Document, grid) -> dict:  # noqa: ANN001
    kascheck = zonnestudio_bron.parse_kascheck(grid)
    for doc, vv in _kassarapporten_met_bron(
        session, administratie_id=document.administratie_id, bron=BRON_ZONNESTUDIO_DAGSTAAT, behalve=document.id
    ):
        detail = vv.get("bron_detail") or {}
        if detail.get("wacht_op") == "kascheck" and _datum_van(vv) == kascheck.datum:
            # De dagstaat wacht op deze kascheck: nieuw, compleet veldvoorstel op het dagstaat-document; dit document
            # wordt de samengevoegde wederhelft (terugvindbaar, nooit verwijderd).
            staat = _dagstaat_uit_veldvoorstel(vv)
            compleet = zonnestudio_bron.bouw_veldvoorstel(staat, kascheck, bestandsnaam=doc.bestandsnaam)
            compleet["bron_detail"]["kascheck_document_id"] = str(document.id)
            session.add(
                DocumentGebeurtenis(
                    id=uuid.uuid4(),
                    document_id=doc.id,
                    van_status=doc.status,
                    naar_status=doc.status,
                    actor_id=SYSTEEM_ACTOR_ID,
                    detail={
                        "veldvoorstel": compleet,
                        "reden": f"kascheck {document.bestandsnaam} toegevoegd — dag compleet",
                    },
                )
            )
            return {
                "samengevoegd_in_document_id": str(doc.id),
                "veldvoorstel": zonnestudio_bron.bouw_veldvoorstel(None, kascheck, bestandsnaam=document.bestandsnaam),
            }
    return {"veldvoorstel": zonnestudio_bron.bouw_veldvoorstel(None, kascheck, bestandsnaam=document.bestandsnaam)}


def _dagstaat_uit_veldvoorstel(vv: dict) -> zonnestudio_bron.Dagstaat:
    """Herbouw de Dagstaat uit een eerder veldvoorstel (de bron-bytes opnieuw parsen zou ook kunnen; dit blijft binnen
    de sessie en is deterministisch dezelfde informatie)."""
    from decimal import Decimal

    detail = vv.get("bron_detail") or {}
    cats = [
        zonnestudio_bron.Categorie(
            naam=r["categorie"],
            aantal=Decimal(r["aantal"]) if r.get("aantal") not in (None, "None") else None,
            netto=Decimal(r.get("netto_pos") or "0"),
            btw_service=Decimal(r.get("btw_pos") or "0"),
            btw_product=Decimal("0"),
            bruto=Decimal(r["omzet_bedrag"]),
        )
        for r in vv.get("regels") or []
    ]
    gt = detail.get("grand_total") or {}
    s = zonnestudio_bron.Dagstaat(
        datum=_datum_van(vv),
        store=detail.get("store"),
        categorieen=cats,
        grand_netto=Decimal(gt["netto"]) if gt.get("netto") not in (None, "None") else None,
        grand_btw=Decimal(gt["btw"]) if gt.get("btw") not in (None, "None") else None,
        grand_bruto=Decimal(gt["bruto"]) if gt.get("bruto") not in (None, "None") else None,
        betaalwijzen={k: Decimal(v) for k, v in (detail.get("betaalwijzen") or {}).items()},
        deposit_totaal=None,
        points_redeemed=Decimal(detail["points_redeemed"])
        if detail.get("points_redeemed") not in (None, "None")
        else None,
    )
    s.controles = zonnestudio_bron._controles_dagstaat(s)  # noqa: SLF001
    return s


def _markeer_samengevoegd(session: Session, *, bron_document: Document, doel_document: Document) -> None:
    """De wederhelft (kascheck- of dagstaat-document) gaat op SAMENGEVOEGD mét verwijzing — nooit verwijderd."""
    oud = bron_document.status
    bron_document.status = DocumentStatus.SAMENGEVOEGD
    bron_document.samengevoegd_in_id = doel_document.id
    session.add(
        DocumentGebeurtenis(
            id=uuid.uuid4(),
            document_id=bron_document.id,
            van_status=oud,
            naar_status=DocumentStatus.SAMENGEVOEGD,
            actor_id=SYSTEEM_ACTOR_ID,
            detail={
                "samengevoegd_in": str(doel_document.id),
                "reden": "dagstaat + kascheck van dezelfde dag gebundeld",
            },
        )
    )
    record_audit_event(
        session,
        actor_id=SYSTEEM_ACTOR_ID,
        module=MODULE,
        tabel="document",
        record_id=bron_document.id,
        actie="omzetbron_gebundeld",
        correlatie_id=doel_document.id,
        oude_waarde={"status": oud.value},
        nieuwe_waarde={"status": DocumentStatus.SAMENGEVOEGD.value, "samengevoegd_in": str(doel_document.id)},
        administratie_id=bron_document.administratie_id,
    )


def _verwerk_pilates(session: Session, *, document: Document, grid) -> dict:  # noqa: ANN001
    transacties = pilates_bron.parse_transacties(grid)
    batches = pilates_bron.groepeer_batches(transacties)
    instellingen = bron_instellingen_voor(session, document.administratie_id)
    product_categorieen = instellingen.get("product_categorieen") or {}
    al_geboekt = geboekte_factuurnummers(session, administratie_id=document.administratie_id, behalve=document.id)
    niet_geslaagd = [t.factuurnummer for t in transacties if not t.geslaagd]
    eigen_batch = pilates_bron.batch_uit_bestandsnaam(document.bestandsnaam)
    if eigen_batch is not None:
        batch = next((b for b in batches if b.batch_id == eigen_batch), None)
        if batch is None:
            return {"bron_parse_fout": f"uitbetaling {eigen_batch} niet in de export gevonden"}
        vv = pilates_bron.bouw_batch_veldvoorstel(
            batch,
            product_categorieen=product_categorieen,
            al_geboekte_factuurnummers=al_geboekt,
            bestandsnaam=document.bestandsnaam,
        )
        return {"veldvoorstel": vv}
    if len(batches) == 1:
        vv = pilates_bron.bouw_batch_veldvoorstel(
            batches[0],
            product_categorieen=product_categorieen,
            al_geboekte_factuurnummers=al_geboekt,
            bestandsnaam=document.bestandsnaam,
        )
        vv["bron_detail"]["niet_geslaagd"] = niet_geslaagd
        return {"veldvoorstel": vv}
    # Meerdere uitbetalingen: het export-document wordt GESPLITST in één kinddocument per batch (post-commit,
    # `splits_pilates_export_na_extractie`); hier alleen het overzicht als veldvoorstel van de ouder.
    return {
        "veldvoorstel": {
            "soort": "kassarapport",
            "bron": BRON_PILATES,
            "rapport_titel": f"Betalingsexport · {len(batches)} uitbetalingen",
            "periode_start": min((b.periode[0] for b in batches if b.periode[0]), default=None).isoformat()
            if any(b.periode[0] for b in batches)
            else None,
            "periode_eind": max((b.periode[1] for b in batches if b.periode[1]), default=None).isoformat()
            if any(b.periode[1] for b in batches)
            else None,
            "totaal_omzet": None,
            "regels": [],
            "bron_detail": {
                "batches": [
                    {
                        "batch_id": b.batch_id,
                        "uitbetaaldatum": b.uitbetaaldatum.isoformat() if b.uitbetaaldatum else None,
                        "netto": str(b.netto),
                        "transacties": len(b.transacties),
                    }
                    for b in batches
                ],
                "niet_geslaagd": niet_geslaagd,
                "aantal_transacties": len(transacties),
            },
        },
        "bron_splitsing": [b.batch_id for b in batches],
    }


def splits_pilates_export_na_extractie(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, opslag, actor_id: uuid.UUID | None = None
) -> int:  # noqa: ANN001
    """Post-commit: maakt per uitbetaling een kinddocument (zelfde bytes, bestandsnaam mét '— uitbetaling <batch>')
    en zet
    de ouder op GESPLITST — idempotent (bestaande kinderen worden niet opnieuw gemaakt). → aantal nieuwe kinderen."""
    from app.documenten import service as documenten_service

    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        ouder = session.get(Document, document_id)
        if ouder is None or ouder.status in _TERMINAAL:
            return 0
        vv = _laatste_veldvoorstel(session, document_id) or {}
        batches = [b["batch_id"] for b in ((vv.get("bron_detail") or {}).get("batches") or [])]
        if not batches:
            return 0
        bestaand = {
            pilates_bron.batch_uit_bestandsnaam(d.bestandsnaam)
            for d in session.scalars(select(Document).where(Document.gesplitst_uit_id == document_id))
        }
        bestandsnaam, pad = ouder.bestandsnaam, ouder.opslag_pad
        # De ouder gaat EERST op GESPLITST (eigen commit) — de kinderen tellen hem anders bij hun extractie als
        # 'al aanwezig' mee in de factuurnummer-dedupe.
        if ouder.status != DocumentStatus.GESPLITST:
            oud = ouder.status
            ouder.status = DocumentStatus.GESPLITST
            session.add(
                DocumentGebeurtenis(
                    id=uuid.uuid4(),
                    document_id=document_id,
                    van_status=oud,
                    naar_status=DocumentStatus.GESPLITST,
                    actor_id=SYSTEEM_ACTOR_ID,
                    detail={
                        "reden": f"betalingsexport gesplitst in {len(batches)} uitbetalingen (één kassarapport per uitbetaling)"  # noqa: E501
                    },
                )
            )
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module=MODULE,
                tabel="document",
                record_id=document_id,
                actie="omzetbron_gesplitst",
                correlatie_id=document_id,
                oude_waarde={"status": oud.value},
                nieuwe_waarde={"status": DocumentStatus.GESPLITST.value, "batches": batches},
                administratie_id=administratie_id,
            )
    inhoud = opslag.lezen(pad=pad)
    nieuw = 0
    for batch_id in batches:
        if batch_id in bestaand:
            continue
        documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam=pilates_bron.kind_bestandsnaam(bestandsnaam, batch_id),
            inhoud=inhoud,
            actor_id=actor_id or SYSTEEM_ACTOR_ID,
            opslag=opslag,
            soort=DocumentSoort.KASSARAPPORT,
            gesplitst_uit_id=document_id,
        )
        nieuw += 1
    return nieuw
