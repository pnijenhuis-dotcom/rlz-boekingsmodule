"""Documentenlaag van de deterministische omzetbronnen (Peter 15-09): bron-instellingen per administratie, store →
administratie, de kassarapport-hook voor spreadsheets (geen AVG-gate, geen AI), bundeling dagstaat + kascheck van
dezelfde dag, splitsing van een pilates-export in één kinddocument per uitbetaling, en de idempotentie op
Factuurnummer."""

from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie, Grootboekrekening
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Document, DocumentGebeurtenis, DocumentSoort, DocumentStatus
from app.omzet.bronnen import (
    BRON_PILATES,
    BRON_ZONNESTUDIO_DAGSTAAT,
    BRON_ZONNESTUDIO_KASCHECK,
    herken_bron_in_grid,
    herkenning,
    lees_grid,
)
from app.omzet.bronnen import pilates as pilates_bron
from app.omzet.bronnen import profx as profx_bron
from app.omzet.bronnen import tegenzijde as tegenzijde_bron
from app.omzet.bronnen import zonnestudio as zonnestudio_bron
from app.omzet.models import OmzetInstelling
from app.sync.models import TaxRateCache

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
    # `stores` staat hier NIET meer (0151, Peter 16-09 avond): de store-routering is platformbreed
    # (app/omzet/bronnen/stores.py, Instellingen › Boeken › Stores); `bron_instellingen_voor` levert 'm als AFGELEIDE
    # weergave ("stores die hier landen") — schrijven via deze PUT wordt geweigerd.
    # Pilates: productnaam → categorie (aanvulling op pilates.DEFAULT_PRODUCT_CATEGORIEEN); mens wint, audit.
    "product_categorieen": {},
    # Blok A (16-09): tegenrekening per betaalwijze (ledger_id of None = code-default op naam uit het rekeningschema).
    "tegenrekeningen": {sleutel: None for sleutel in tegenzijde_bron.BETAALWIJZEN},
    # Blok C: mens-override btw per categorie-sleutel (taxrate_id) — geldt vanaf de volgende batch, nooit terugwerkend.
    "categorie_btw": {},
    "combi_regel": pilates_bron.COMBI_REGEL_PRO_RATO,
    # Blok D: PSP van de betalingsexport ('stripe' = EU-dienst verlegd, 'mollie' = NL 21 % voorbelasting, 'anders' =
    # mens kiest). Besluit Peter 16-09: Stripe.
    "psp": tegenzijde_bron.PSP_STRIPE,
    "psp_kosten_ledger_id": None,
    # Beslispunt (default laag): eten/drinken 9 %; alcohol/horeca-uitzonderingen = 'hoog'.
    "eten_drinken_tarief": tegenzijde_bron.BTW_LAAG,
}
#: 15-09-sleutel die niet meer bestaat (informatieve GB-codes) — bij lezen genegeerd, bij schrijven geweigerd.
#: `stores` (0146) is sinds 0151 verhuisd naar `omzet_store_routering`; de JSON-lijst blijft als historisch spoor staan
#: (data-stap `omzet-stores-migreren` leest 'm) maar wordt hier niet meer als instelling gelezen.
_VERVALLEN_SLEUTELS = frozenset({"rekeningen", "stores"})
STORES_PLATFORMBREED_MELDING = (
    "stores worden sinds 16-09 platformbreed beheerd op Instellingen › Boeken › Stores (store → administratie) — "
    "niet meer per administratie"
)


def bron_instellingen_voor(session: Session, administratie_id: uuid.UUID) -> dict[str, Any]:
    """Instellingen van déze administratie + `stores` als AFGELEIDE weergave uit de platformbrede routering (0151)."""
    from app.omzet.bronnen import stores as stores_service

    rij = session.get(OmzetInstelling, administratie_id)
    uit = copy.deepcopy(DEFAULT_BRON_INSTELLINGEN)
    uit["stores"] = stores_service.stores_voor_administratie(session, administratie_id)
    for sleutel, waarde in ((rij.bron_instellingen if rij else None) or {}).items():
        if sleutel in _VERVALLEN_SLEUTELS:
            continue
        if sleutel == "psp":
            # 15-09-vorm {"naam": "Mollie", "kosten_btw": "21"} → 16-09-string; onbekend = 'anders'.
            uit["psp"] = tegenzijde_bron.psp_naam({"psp": waarde}) or DEFAULT_BRON_INSTELLINGEN["psp"]
        elif sleutel in uit and isinstance(waarde, dict) and isinstance(uit[sleutel], dict):
            uit[sleutel] = {**uit[sleutel], **waarde}
        else:
            uit[sleutel] = waarde
    return uit


def rekeningen_voor(session: Session, administratie_id: uuid.UUID) -> list[tegenzijde_bron.Rekening]:
    """Keuzelijst + default-bron: de niet-verdwenen grootboekrekeningen van de administratie (platform-cache)."""
    rijen = session.scalars(
        select(Grootboekrekening)
        .where(
            Grootboekrekening.administratie_id == administratie_id,
            Grootboekrekening.verdwenen_uit_bron_op.is_(None),
        )
        .order_by(Grootboekrekening.code)
    )
    return [
        tegenzijde_bron.Rekening(ledger_id=r.ledger_id, code=r.code, naam=r.naam, is_totaalrekening=r.is_totaalrekening)
        for r in rijen
    ]


def tarieven_voor(session: Session, administratie_id: uuid.UUID) -> list[tegenzijde_bron.Tarief]:
    from app.sync.btw import taxrate_vlaggen

    rijen = session.scalars(
        select(TaxRateCache).where(
            TaxRateCache.administratie_id == administratie_id, TaxRateCache.verdwenen_uit_bron_op.is_(None)
        )
    )
    uit = []
    for t in rijen:
        verlegd, vrijgesteld = taxrate_vlaggen(t.brondata)
        uit.append(
            tegenzijde_bron.Tarief(
                taxrate_id=t.id, naam=t.naam, percentage=t.percentage, is_verlegd=verlegd, is_vrijgesteld=vrijgesteld
            )
        )
    return sorted(uit, key=lambda t: t.naam or "")


def defaults_voor(
    session: Session, administratie_id: uuid.UUID, *, instellingen: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Wat de code zou kiezen zonder instelling (read-only `defaults` in de DTO): tegenrekeningen op naam, btw per
    categorie-klasse (laag/hoog/verlegd) uit het RLZ-tarief van de administratie, PSP-kostenrekening op naam."""
    from app.documenten.regel_prefill import bepaal_verlegd_taxrate

    inst = instellingen or bron_instellingen_voor(session, administratie_id)
    rekeningen = rekeningen_voor(session, administratie_id)
    tarieven = tarieven_voor(session, administratie_id)
    laag = tegenzijde_bron.default_tarief(tegenzijde_bron.BTW_LAAG, tarieven)
    hoog = tegenzijde_bron.default_tarief(tegenzijde_bron.BTW_HOOG, tarieven)
    verlegd = bepaal_verlegd_taxrate(session, administratie_id=administratie_id)
    vrijgesteld = tegenzijde_bron.default_tarief(tegenzijde_bron.BTW_VRIJGESTELD, tarieven)
    per_klasse = {
        tegenzijde_bron.BTW_LAAG: str(laag.taxrate_id) if laag else None,
        tegenzijde_bron.BTW_HOOG: str(hoog.taxrate_id) if hoog else None,
        tegenzijde_bron.BTW_VERLEGD: str(verlegd.taxrate_id) if verlegd else None,
        tegenzijde_bron.BTW_VRIJGESTELD: str(vrijgesteld.taxrate_id) if vrijgesteld else None,
    }
    categorie_btw: dict[str, dict[str, Any]] = {}
    for sleutel in (
        *tegenzijde_bron.BTW_KLASSE_PER_CATEGORIE,
        tegenzijde_bron.CATEGORIE_ETEN_SLEUTEL,
        tegenzijde_bron.CATEGORIE_PSP_KOSTEN_SLEUTEL,
    ):
        klasse = tegenzijde_bron.btw_klasse_voor(sleutel, inst)
        categorie_btw[sleutel] = {"klasse": klasse, "taxrate_id": per_klasse.get(klasse) if klasse else None}
    return {
        "tegenrekeningen": {
            k: (str(v) if v else None) for k, v in tegenzijde_bron.default_tegenrekeningen(rekeningen).items()
        },
        "categorie_btw": categorie_btw,
        "btw_per_klasse": per_klasse,
        "verlegd_herkomst": verlegd.detail if verlegd else None,
        "psp_kosten_ledger_id": (str(pk) if (pk := tegenzijde_bron.default_psp_kosten_rekening(rekeningen)) else None),
        "psp_btw_herkomst": tegenzijde_bron.psp_btw_herkomst(tegenzijde_bron.psp_naam(inst)),
    }


def _valideer_bron_instellingen(session: Session, administratie_id: uuid.UUID, waarden: dict[str, Any]) -> None:
    """Ledger-/taxrate-id's alleen uit de caches van déze administratie; keuzevelden alleen uit de vaste lijsten."""
    fouten: list[str] = []
    ledgers = {str(r.ledger_id) for r in rekeningen_voor(session, administratie_id)}
    tarieven = {str(t.taxrate_id) for t in tarieven_voor(session, administratie_id)}
    for sleutel, ledger in (waarden.get("tegenrekeningen") or {}).items():
        if sleutel not in tegenzijde_bron.BETAALWIJZEN:
            fouten.append(f"onbekende betaalwijze '{sleutel}'")
        elif ledger and str(ledger) not in ledgers:
            fouten.append(f"tegenrekening {sleutel}: grootboekrekening {ledger} bestaat niet in deze administratie")
    for categorie, taxrate in (waarden.get("categorie_btw") or {}).items():
        if taxrate and str(taxrate) not in tarieven:
            fouten.append(f"btw {categorie}: tarief {taxrate} bestaat niet in deze administratie")
    pk = waarden.get("psp_kosten_ledger_id")
    if pk and str(pk) not in ledgers:
        fouten.append(f"PSP-kostenrekening {pk} bestaat niet in deze administratie")
    psp = waarden.get("psp")
    if psp is not None and str(psp).strip().lower() not in tegenzijde_bron.PSP_KEUZES:
        fouten.append(f"psp '{psp}' — kies stripe, mollie of anders")
    if (cr := waarden.get("combi_regel")) not in (None, pilates_bron.COMBI_REGEL_PRO_RATO):
        fouten.append(f"combi_regel '{cr}' onbekend (alleen '{pilates_bron.COMBI_REGEL_PRO_RATO}')")
    if (et := waarden.get("eten_drinken_tarief")) not in (None, tegenzijde_bron.BTW_LAAG, tegenzijde_bron.BTW_HOOG):
        fouten.append(f"eten_drinken_tarief '{et}' onbekend (laag of hoog)")
    if fouten:
        raise ValueError("; ".join(sorted(set(fouten))))


def zet_bron_instellingen(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, waarden: dict[str, Any]
) -> dict[str, Any]:
    """PUT door de Beheerder (Instellingen › Administraties › ‹studio› › Omzet › Omzetbronnen): volledig blok
    vervangen ná validatie tegen de caches (ledger-/taxrate-id's van déze administratie), audit oud→nieuw."""
    toegestaan = set(DEFAULT_BRON_INSTELLINGEN)
    if "stores" in waarden:
        raise ValueError(STORES_PLATFORMBREED_MELDING)
    onbekend = set(waarden) - toegestaan
    if onbekend:
        raise ValueError(f"Onbekende sleutel(s) in bron-instellingen: {', '.join(sorted(onbekend))}")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _valideer_bron_instellingen(session, administratie_id, waarden)
        rij = session.get(OmzetInstelling, administratie_id)
        if rij is None:
            rij = OmzetInstelling(administratie_id=administratie_id)
            session.add(rij)
        oud = copy.deepcopy(rij.bron_instellingen or {})
        schoon: dict[str, Any] = {}
        for k, v in waarden.items():
            if isinstance(v, dict):
                v = {kk: (str(vv) if isinstance(vv, uuid.UUID) else vv) for kk, vv in v.items() if vv not in (None, "")}
            elif isinstance(v, uuid.UUID):
                v = str(v)
            if v in (None, {}, []):
                continue
            if v == DEFAULT_BRON_INSTELLINGEN.get(k):
                continue  # default niet opslaan — een latere default-wijziging in code werkt dan door
            schoon[k] = v
        rij.bron_instellingen = schoon or None
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
    """Store-naam uit de dagstaat → administratie via de PLATFORMBREDE routering (0151; één bron:
    app/omzet/bronnen/stores.py). Niet gekoppeld = None (verzamelbak mét reden, nooit raden)."""
    from app.omzet.bronnen import stores as stores_service

    return stores_service.administratie_voor_store(store)


def administratie_voor_kascheck(datum: date | None) -> uuid.UUID | None:
    """Een kascheck noemt geen store. Deterministische terugval (0151, "bundeling werkt over de routering heen"): precies
    één actieve administratie heeft een dagstaat van dezelfde dag die nog op zijn kascheck wacht → die administratie.
    Geen of meerdere kandidaten = None (dan de afzender-regel of de verzamelbak)."""
    if datum is None:
        return None
    with scoped_session(None) as session:
        administraties = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))))
    kandidaten: list[uuid.UUID] = []
    for aid in administraties:
        with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
            for _doc, vv in _kassarapporten_met_bron(
                session, administratie_id=aid, bron=BRON_ZONNESTUDIO_DAGSTAAT, behalve=uuid.UUID(int=0)
            ):
                detail = vv.get("bron_detail") or {}
                if detail.get("wacht_op") == "kascheck" and _datum_van(vv) == datum:
                    kandidaten.append(aid)
                    break
    return kandidaten[0] if len(kandidaten) == 1 else None


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


COMBI_HISTORIE_DAGEN = 30


def combi_historie_basis(
    session: Session, *, administratie_id: uuid.UUID, referentiedatum: date | None, behalve: uuid.UUID
) -> dict[str, Decimal]:
    """Netto-omzet Pilateslessen/Yoga van de andere pilates-kassarapporten van deze administratie in de 30 dagen vóór
    de referentiedatum (terugval-basis voor de combi-verdeling, besluit Peter 16-09). Leest de regels van het
    veldvoorstel (kassabedragen), nooit de combi-delen zelf opnieuw."""
    if referentiedatum is None:
        return {}
    basis: dict[str, Decimal] = {pilates_bron.CATEGORIE_PILATES: Decimal(0), pilates_bron.CATEGORIE_YOGA: Decimal(0)}
    ondergrens = referentiedatum - timedelta(days=COMBI_HISTORIE_DAGEN)
    gevonden = False
    for _doc, vv in _kassarapporten_met_bron(
        session, administratie_id=administratie_id, bron=BRON_PILATES, behalve=behalve
    ):
        detail = vv.get("bron_detail") or {}
        try:
            d = date.fromisoformat(detail.get("uitbetaaldatum") or vv.get("periode_eind") or "")
        except ValueError:
            continue
        if not (ondergrens <= d < referentiedatum):
            continue
        combi = (detail.get("combi_verdeling") or {}).get("verdeling") or {}
        for r in vv.get("regels") or []:
            cat = r.get("categorie")
            if cat in basis and r.get("omzet_bedrag") not in (None, "None"):
                basis[cat] += Decimal(str(r["omzet_bedrag"])) - Decimal(str(combi.get(cat, "0")))
                gevonden = True
    return basis if gevonden else {}


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
    combi_regel = instellingen.get("combi_regel") or pilates_bron.COMBI_REGEL_PRO_RATO
    if eigen_batch is not None:
        batch = next((b for b in batches if b.batch_id == eigen_batch), None)
        if batch is None:
            return {"bron_parse_fout": f"uitbetaling {eigen_batch} niet in de export gevonden"}
        vv = pilates_bron.bouw_batch_veldvoorstel(
            batch,
            product_categorieen=product_categorieen,
            al_geboekte_factuurnummers=al_geboekt,
            bestandsnaam=document.bestandsnaam,
            combi_regel=combi_regel,
            combi_historie_basis=combi_historie_basis(
                session,
                administratie_id=document.administratie_id,
                referentiedatum=batch.uitbetaaldatum,
                behalve=document.id,
            ),
        )
        return {"veldvoorstel": vv}
    if len(batches) == 1:
        vv = pilates_bron.bouw_batch_veldvoorstel(
            batches[0],
            product_categorieen=product_categorieen,
            al_geboekte_factuurnummers=al_geboekt,
            bestandsnaam=document.bestandsnaam,
            combi_regel=combi_regel,
            combi_historie_basis=combi_historie_basis(
                session,
                administratie_id=document.administratie_id,
                referentiedatum=batches[0].uitbetaaldatum,
                behalve=document.id,
            ),
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


# ---- ProfX Journaal / Margerapport (PDF-tekstlaag, Peter 16-09) ------------------------------------------------------


def _profx_tekst(inhoud: bytes) -> list[str] | None:
    from app.extractie.template_terugval import lees_tekstlaag

    laag = lees_tekstlaag(inhoud)
    return list(laag.regels) if laag is not None else None


def _profx_journalen(
    session: Session, *, administratie_id: uuid.UUID, behalve: uuid.UUID
) -> list[tuple[Document, dict]]:
    return _kassarapporten_met_bron(
        session, administratie_id=administratie_id, bron=profx_bron.BRON_JOURNAAL, behalve=behalve
    )


def _profx_margerapporten(
    session: Session, *, administratie_id: uuid.UUID, behalve: uuid.UUID
) -> list[tuple[Document, dict]]:
    return _kassarapporten_met_bron(
        session, administratie_id=administratie_id, bron=profx_bron.BRON_MARGE, behalve=behalve
    )


def _marge_uit_veldvoorstel(vv: dict) -> profx_bron.Margerapport:
    from decimal import Decimal

    detail = vv.get("bron_detail") or {}
    m = detail.get("marge") or {}
    groepen = {
        r["categorie"]: Decimal(r["kostprijs_bedrag"]) for r in vv.get("regels") or [] if r.get("kostprijs_bedrag")
    }
    rapport = profx_bron.Margerapport(
        periode_van=date.fromisoformat(m["periode_van"]) if m.get("periode_van") else _datum_van(vv),
        periode_tot=date.fromisoformat(m["periode_tot"]) if m.get("periode_tot") else None,
        groepen=groepen,
        totaal=Decimal(m["totaal"]) if m.get("totaal") else None,
    )
    return rapport


def verwerk_pdf_tekst(session: Session, *, document: Document, inhoud: bytes) -> dict:
    """Detail voor de extractie-eindovergang van een KASSARAPPORT-PDF van een deterministische bron (ProfX): zelfde
    contract als `verwerk_spreadsheet`. Journaal: zoekt een al aanwezig los margerapport dat de kassadag dekt (zelfde
    dag → gebundeld: het margerapport gaat op SAMENGEVOEGD; week → 'gekoppeld', het margerapport blijft eigen document
    mét één memoriaal per periode). Margerapport: zelfde dag als een wachtend journaal → in dat journaal gevoegd;
    anders eigen document (kostprijs per periode)."""
    regels = _profx_tekst(inhoud)
    if regels is None:
        return {"bron_parse_fout": "PDF zonder tekstlaag — ProfX-rapport niet leesbaar zonder AI (scan?)"}
    bron = herkenning.herken_pdf_tekst(regels)
    if bron is None:
        return {"bron_parse_fout": "geen bekende omzetbron in de PDF-tekst (verwacht: ProfX Journaal of Margerapport)"}
    if document.administratie_id is None:
        return {"bron_parse_fout": "geen administratie — wijs het document eerst toe"}
    try:
        if bron == profx_bron.BRON_JOURNAAL:
            return _verwerk_profx_journaal(session, document=document, regels=regels)
        return _verwerk_profx_marge(session, document=document, regels=regels)
    except Exception as exc:  # noqa: BLE001 — een parserfout is een zichtbare uitkomst
        logger.exception("Omzetbron %s: verwerking mislukt voor document %s", bron, document.id)
        return {"bron_parse_fout": f"{bron}: {exc}"}


def _verwerk_profx_journaal(session: Session, *, document: Document, regels: list[str]) -> dict:
    journaal = profx_bron.parse_journaal(regels)
    marge = None
    marge_doc: Document | None = None
    for doc, vv in _profx_margerapporten(session, administratie_id=document.administratie_id, behalve=document.id):
        kandidaat = _marge_uit_veldvoorstel(vv)
        if profx_bron.dekt(kandidaat.periode_van, kandidaat.periode_tot, journaal.kassadag):
            marge, marge_doc = kandidaat, doc
            break
    veldvoorstel = profx_bron.bouw_veldvoorstel(
        journaal, marge, marge_document_id=str(marge_doc.id) if marge_doc else None, bestandsnaam=document.bestandsnaam
    )
    if marge_doc is not None and marge is not None and marge.periode_van == (marge.periode_tot or marge.periode_van):
        # Zelfde dag = één kassarapport, twee boekingen vanuit één scherm (blok F): het margerapport gaat op
        # samengevoegd.
        _markeer_samengevoegd(session, bron_document=marge_doc, doel_document=document)
        veldvoorstel["bron_detail"]["marge"]["stand"] = "gebundeld"
    elif marge_doc is not None:
        # Weekrapport: blijft eigen document (één memoriaal per periode) — het dagjournaal boekt alleen omzet.
        veldvoorstel["bron_detail"]["marge"]["stand"] = "gekoppeld_periode"
        for r in veldvoorstel["regels"]:
            r["kostprijs_bedrag"] = None
        veldvoorstel["totaal_kostprijs"] = None
        veldvoorstel["regelsom_kostprijs"] = {"vergelijkbaar": False, "reden": "kostprijs op het weekrapport"}
    return {"veldvoorstel": veldvoorstel}


def _verwerk_profx_marge(session: Session, *, document: Document, regels: list[str]) -> dict:
    marge = profx_bron.parse_margerapport(regels)
    dag_journaal: Document | None = None
    dag_vv: dict | None = None
    if marge.periode_van is not None and marge.periode_van == (marge.periode_tot or marge.periode_van):
        for doc, vv in _profx_journalen(session, administratie_id=document.administratie_id, behalve=document.id):
            if (
                _datum_van(vv) == marge.periode_van
                and (vv.get("bron_detail") or {}).get("marge", {}).get("stand") == "verwacht"
            ):
                dag_journaal, dag_vv = doc, vv
                break
    if dag_journaal is not None and dag_vv is not None:
        # Zelfde dag als een wachtend journaal: kostprijs bij het journaal voegen (één scherm, twee boekingen).
        journaal_regels = list(dag_vv.get("regels") or [])
        for r in journaal_regels:
            w = marge.groepen.get(r["categorie"]) or next(
                (v for n, v in marge.groepen.items() if n.strip().lower() == r["categorie"].strip().lower()), None
            )
            r["kostprijs_bedrag"] = str(w) if w is not None else None
        nieuw = {**dag_vv, "regels": journaal_regels}
        nieuw["totaal_kostprijs"] = str(marge.totaal) if marge.totaal is not None else None
        nieuw["bron_detail"] = {
            **(dag_vv.get("bron_detail") or {}),
            "marge": {
                "periode_van": marge.periode_van.isoformat() if marge.periode_van else None,
                "periode_tot": marge.periode_tot.isoformat() if marge.periode_tot else None,
                "totaal": str(marge.totaal) if marge.totaal is not None else None,
                "document_id": str(document.id),
                "stand": "gebundeld",
            },
        }
        nieuw["bron_detail"]["controles"] = [
            c
            for c in (nieuw["bron_detail"].get("controles") or [])
            if not c["naam"].startswith("Margerapport (kostprijs)")
        ] + [asdict(c) for c in marge.controles]
        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=dag_journaal.id,
                van_status=dag_journaal.status,
                naar_status=dag_journaal.status,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={
                    "veldvoorstel": nieuw,
                    "reden": "margerapport van dezelfde kassadag gebundeld (kostprijs gevuld)",
                },
            )
        )
        # De eindovergang (`_rond_extractie_af`) zet dít document op SAMENGEVOEGD mét verwijzing; hier alleen het doel.
        return {"samengevoegd_in_document_id": str(dag_journaal.id)}
    # Week- of los dagrapport: eigen document mét kostprijsregels (één memoriaal per periode); dekking als controle.
    veldvoorstel = profx_bron.bouw_veldvoorstel(None, marge, bestandsnaam=document.bestandsnaam)
    gedekt = [
        d
        for d, vv in _profx_journalen(session, administratie_id=document.administratie_id, behalve=document.id)
        if profx_bron.dekt(marge.periode_van, marge.periode_tot, _datum_van(vv))
    ]
    veldvoorstel["bron_detail"]["gedekte_journalen"] = [str(d.id) for d in gedekt]
    if marge.periode_van and marge.periode_tot and marge.periode_tot > marge.periode_van:
        dagen = (marge.periode_tot - marge.periode_van).days + 1
        veldvoorstel["bron_detail"]["controles"].append(
            asdict(
                profx_bron.Controle(
                    "Periode-dekking: dagjournalen in de margeperiode",
                    len(gedekt) >= dagen,
                    f"{len(gedekt)} van {dagen} dagen hebben een journaal",
                    blokkerend=False,
                )
            )
        )
    # Los margerapport zonder journaal: 'wacht op journaal' is al een controle in bouw_veldvoorstel.
    return {"veldvoorstel": veldvoorstel}


def profx_marge_stand(session: Session, *, administratie_id: uuid.UUID, veldvoorstel: dict) -> dict | None:
    """Blok F/notitie 7: de LIVE stand van de kostprijs voor een ProfX-dagjournaal — 'gebundeld' (zelfde dag, in dit
    document), 'gekoppeld_periode' (weekrapport als eigen document: verwacht/geboekt), 'verwacht' (nog geen
    margerapport dat deze kassadag dekt). Niet bevroren in het veldvoorstel: komt het weekrapport later, dan verandert
    de chip zonder herextractie."""
    if veldvoorstel.get("bron") != profx_bron.BRON_JOURNAAL:
        return None
    detail = veldvoorstel.get("bron_detail") or {}
    marge = dict(detail.get("marge") or {})
    if marge.get("stand") == "gebundeld":
        return marge
    dag = _datum_van(veldvoorstel)
    for doc in session.scalars(
        select(Document).where(
            Document.administratie_id == administratie_id,
            Document.soort == DocumentSoort.KASSARAPPORT.value,
            Document.status != DocumentStatus.SAMENGEVOEGD,
        )
    ):
        vv = _laatste_veldvoorstel(session, doc.id)
        if not vv or vv.get("bron") != profx_bron.BRON_MARGE:
            continue
        m = (vv.get("bron_detail") or {}).get("marge") or {}
        van = date.fromisoformat(m["periode_van"]) if m.get("periode_van") else _datum_van(vv)
        tot = date.fromisoformat(m["periode_tot"]) if m.get("periode_tot") else van
        if profx_bron.dekt(van, tot, dag):
            return {
                "periode_van": van.isoformat() if van else None,
                "periode_tot": tot.isoformat() if tot else None,
                "totaal": m.get("totaal") or vv.get("totaal_kostprijs"),
                "document_id": str(doc.id),
                "stand": "geboekt" if doc.status == DocumentStatus.GEBOEKT else "gekoppeld_periode",
                "week": van.isocalendar()[1] if van else None,
            }
    marge["stand"] = "verwacht"
    if dag:
        marge["week"] = dag.isocalendar()[1]
    return marge
