"""`doorbelasting-bedragen-gelijktrekken` — data-stap ná de RLZ-vorm-fix (opdracht 24-09, akkoord Peter "3. ja").

Aanleiding: tot 24-09 boekte en registreerde de doorbelastingsmotor de btw PER REGEL afgerond (995,73 + 49,79 = 1.045,52);
RLZ negeert die regel-`TaxAmount` en legt de document-btw per tarief over het subtotaal vast (1.045,51) — STAP-0 24-09,
166/166 productiedocumenten (`verkenning/stap0-doorbelasting-btw-rekenregel-24-09.tsv`). Gevolg: `doorbelasting_boeking.
btw_bedrag` wijkt bij ~55 van de 188 geboekte doorbelastingen één cent af van RLZ (module = tweede waarheid — fout,
kernprincipe 1), de factuur-PDF-toets faalt (chip "factuur ontbreekt") en de Vastly-webhook droeg 1 cent te veel.

Wat dit commando doet — UITSLUITEND in onze database, nooit een write in RLZ (geen actie 19, geen her-PUT, geen herboeking):
  1. per geboekte doorbelasting (`geboekt` én `spiegel_open`) de RLZ-totalen lezen (GET): verkoop `SalesInvoices/{id}` in de
     bron én — bij `geboekt` — spiegel `PurchaseInvoices/{id}` in het doel;
  2. vergelijken met onze registratie (netto + provisie + btw), met dezelfde toets als het dagelijkse reconciliatieblok
     (`app/doorbelasting/reconciliatie.toets_bedragen`, tolerantie € 0,05);
  3. verschil ≤ € 0,05 én verkoop = spiegel → `btw_bedrag` := RLZ-btw mét audit `doorbelasting_bedrag_gelijkgetrokken`
     (oud → nieuw, bron = beide RLZ-document-id's + boekstuknummers) en één tijdlijnregel op het bron-document die beide
     kanten noemt (de spiegel heeft in de module geen eigen documentrij); ligt de spiegel in een vastgoed-doel, dan gaat
     er een nieuw boekstand-event (`factuur_geboekt`, volgnummer + 1, koppelcontract v1.14) met de gecorrigeerde regels
     naar de outbox; niet-vastgoed = alleen audit;
  4. verschil > € 0,05, verkoop ≠ spiegel in RLZ of RLZ-netto ≠ onze netto + provisie → NIET aanpassen: regel `AFWIJKING`
     (het dagelijkse blok maakt er de bevinding `doorbelasting_bedrag_afwijking` van).
Dry-run is de default: alleen `--uitvoeren` schrijft (de echte run pas ná Peters "ja" op de dry-run-telling, op de
job-image: `gcloud run jobs execute rlz-reconciliatie --args=…`). In `scripts/gcp/nameting.sh` alleen zonder `--uitvoeren`.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

COMMANDO = "doorbelasting-bedragen-gelijktrekken"
AUDIT_GELIJKGETROKKEN = "doorbelasting_bedrag_gelijkgetrokken"
TIJDLIJN_GEBEURTENIS = "doorbelasting_bedrag_gelijkgetrokken"

UITKOMST_GELIJK = "gelijk"
UITKOMST_ZOU = "zou_gelijktrekken"
UITKOMST_GELIJKGETROKKEN = "gelijkgetrokken"
UITKOMST_AFWIJKING = "afwijking"
UITKOMST_NIET_LEESBAAR = "niet_leesbaar"

CENT = Decimal("0.01")


@dataclass
class Rij:
    administratie: str
    administratie_id: str
    boeking_id: str
    document_id: str
    status: str
    doelentiteit: str
    verkoop_referentie: str | None
    ons_netto: str
    ons_provisie: str
    ons_btw: str
    ons_incl: str
    rlz_verkoop_incl: str | None
    rlz_verkoop_btw: str | None
    rlz_verkoop_boekstuk: str | None
    rlz_spiegel_incl: str | None
    rlz_spiegel_btw: str | None
    rlz_spiegel_boekstuk: str | None
    verschil_ct: int | None
    uitkomst: str
    detail: str
    nieuw_btw: str | None = None
    webhook_event: bool = False
    fout: str | None = None


@dataclass
class Resultaat:
    dry_run: bool
    rijen: list[Rij] = field(default_factory=list)
    fouten: list[str] = field(default_factory=list)
    administraties: int = 0

    def telling(self) -> dict[str, int]:
        uit = {k: 0 for k in (UITKOMST_GELIJK, UITKOMST_ZOU, UITKOMST_GELIJKGETROKKEN, UITKOMST_AFWIJKING, UITKOMST_NIET_LEESBAAR)}
        for r in self.rijen:
            uit[r.uitkomst] = uit.get(r.uitkomst, 0) + 1
        uit["webhook_events"] = sum(1 for r in self.rijen if r.webhook_event)
        return uit


def _lees(client, pad: str, rlz_id: uuid.UUID):  # noqa: ANN001, ANN202
    """(bedragen, boekstuk, fout) — alleen GET; een 404/fout is een zichtbare reden, nooit een crash."""
    from app.doorbelasting.reconciliatie import _rlz_bedragen
    from app.rlz.client import RlzApiError

    try:
        doc = client.get(f"{pad}/{rlz_id}")
    except RlzApiError as exc:
        return None, None, f"{pad}/{rlz_id}: RLZ {exc.status_code}"
    except Exception as exc:  # noqa: BLE001
        return None, None, f"{pad}/{rlz_id}: {exc.__class__.__name__}: {str(exc)[:120]}"
    return _rlz_bedragen(doc), doc.get("ReceiptNumber"), None


def _standaard_client(administratie_id: uuid.UUID):  # noqa: ANN202
    from app.documenten.boeken import _rlz_client_voor

    return _rlz_client_voor(administratie_id)


def _gecorrigeerde_webhook_payload(vorige: dict, *, nieuw_volgnummer: int, btw_pct: Decimal) -> dict | None:
    """Nieuw `factuur_geboekt`-boekstand-event (v1.14) uit de laatste stand: dezelfde kop, volgnummer + 1, de regels in
    de RLZ-vorm (`geld.btw_rlz_vorm` over de netto's van de regels — kostenregels + provisie). Draagt geen enkele regel btw
    (niet-btw-plichtig doel: bruto als kosten), dan valt er niets te corrigeren → None."""
    from app.doorbelasting.geld import btw_rlz_vorm

    payload = copy.deepcopy(vorige)
    data = payload.get("data") or {}
    regels = data.get("regels") or []
    if not regels or all(Decimal(str(r.get("btw_bedrag") or 0)) == 0 for r in regels):
        return None
    _totaal, per_regel = btw_rlz_vorm([Decimal(str(r["netto_bedrag"])) for r in regels], btw_pct)
    if [Decimal(str(r["btw_bedrag"])) for r in regels] == per_regel:
        return None
    for r, btw in zip(regels, per_regel, strict=True):
        r["btw_bedrag"] = str(btw)
    data["volgnummer"] = nieuw_volgnummer
    payload["data"] = data
    return payload


def verwerk(
    *,
    administratie: str | None,
    uitvoeren: bool,
    actor_id: uuid.UUID,
    client_factory: Callable[[uuid.UUID], object] | None = None,
) -> Resultaat | None:
    from sqlalchemy import select

    from app.beheer.bua_cli import _administraties
    from app.db.session import scoped_session
    from app.doorbelasting.boeken import _btw_percentage
    from app.doorbelasting.models import (
        DoorbelastingBoeking,
        DoorbelastingBoekingStatus,
        DoorbelastingInstelling,
        DoorbelastingMapping,
    )
    from app.doorbelasting.reconciliatie import BEDRAG_TOLERANTIE, toets_bedragen
    from app.rlz.credentials import GeenRlzCredentials

    adms = _administraties(administratie)
    if adms is None:
        return None
    factory = client_factory or _standaard_client
    resultaat = Resultaat(dry_run=not uitvoeren)
    for aid, naam in adms:
        try:
            with scoped_session(aid) as session:
                boekingen = session.scalars(
                    select(DoorbelastingBoeking)
                    .where(
                        DoorbelastingBoeking.administratie_id == aid,
                        DoorbelastingBoeking.status.in_(
                            (DoorbelastingBoekingStatus.GEBOEKT.value, DoorbelastingBoekingStatus.SPIEGEL_OPEN.value)
                        ),
                    )
                    .order_by(DoorbelastingBoeking.aangemaakt_op)
                ).all()
                mappings = {
                    m.id: m
                    for m in session.scalars(select(DoorbelastingMapping).where(DoorbelastingMapping.administratie_id == aid))
                }
                instelling = session.get(DoorbelastingInstelling, aid)
                btw_pct: Decimal | None = None
                if instelling is not None and instelling.btw_taxrate_id is not None:
                    try:
                        btw_pct = _btw_percentage(session, administratie_id=aid, taxrate_id=instelling.btw_taxrate_id)
                    except Exception:  # noqa: BLE001 — geen tarief in de cache: webhook-regels dan niet herrekend
                        btw_pct = None
                session.expunge_all()
            if not boekingen:
                continue
            resultaat.administraties += 1
            bron_client = factory(aid)
            doel_clients: dict[uuid.UUID, object] = {}
            try:
                for b in boekingen:
                    mapping = mappings.get(b.mapping_id)
                    ons_netto = (b.netto_totaal + b.provisie_bedrag).quantize(CENT)
                    ons_incl = (ons_netto + b.btw_bedrag).quantize(CENT)
                    rij = Rij(
                        administratie=naam,
                        administratie_id=str(aid),
                        boeking_id=str(b.id),
                        document_id=str(b.document_id),
                        status=b.status,
                        doelentiteit=mapping.doelentiteit_naam if mapping else "?",
                        verkoop_referentie=b.verkoop_referentie,
                        ons_netto=str(ons_netto),
                        ons_provisie=str(b.provisie_bedrag),
                        ons_btw=str(b.btw_bedrag),
                        ons_incl=str(ons_incl),
                        rlz_verkoop_incl=None,
                        rlz_verkoop_btw=None,
                        rlz_verkoop_boekstuk=None,
                        rlz_spiegel_incl=None,
                        rlz_spiegel_btw=None,
                        rlz_spiegel_boekstuk=None,
                        verschil_ct=None,
                        uitkomst=UITKOMST_NIET_LEESBAAR,
                        detail="",
                    )
                    verkoop, boekstuk_v, fout_v = _lees(bron_client, "SalesInvoices", b.verkoop_rlz_id)
                    spiegel = boekstuk_s = None
                    fout_s: str | None = None
                    if b.status == DoorbelastingBoekingStatus.GEBOEKT.value and b.doel_administratie_id is not None:
                        try:
                            if b.doel_administratie_id not in doel_clients:
                                doel_clients[b.doel_administratie_id] = factory(b.doel_administratie_id)
                            spiegel, boekstuk_s, fout_s = _lees(
                                doel_clients[b.doel_administratie_id], "PurchaseInvoices", b.spiegel_rlz_id
                            )
                        except GeenRlzCredentials as exc:
                            fout_s = f"doel-administratie zonder RLZ-credential ({exc.__class__.__name__})"
                    if verkoop is not None:
                        rij.rlz_verkoop_incl, rij.rlz_verkoop_btw = _str(verkoop.incl), _str(verkoop.btw)
                        rij.rlz_verkoop_boekstuk = boekstuk_v
                    if spiegel is not None:
                        rij.rlz_spiegel_incl, rij.rlz_spiegel_btw = _str(spiegel.incl), _str(spiegel.btw)
                        rij.rlz_spiegel_boekstuk = boekstuk_s
                    fouten = [f for f in (fout_v, fout_s) if f]
                    if verkoop is None or (b.status == DoorbelastingBoekingStatus.GEBOEKT.value and spiegel is None):
                        rij.fout = "; ".join(fouten) or "geen RLZ-bedragen"
                        rij.detail = f"niet leesbaar: {rij.fout}"
                        resultaat.rijen.append(rij)
                        continue
                    uitkomst, detail = toets_bedragen(ons_incl=ons_incl, ons_btw=b.btw_bedrag, verkoop=verkoop, spiegel=spiegel)
                    # netto-toets bovenop de incl-toets: een ander netto is nooit een afrondingskwestie.
                    if uitkomst != "afwijking" and verkoop.netto is not None and verkoop.netto != ons_netto:
                        uitkomst, detail = "afwijking", f"RLZ-netto {verkoop.netto} ≠ module netto + provisie {ons_netto}"
                    rij.detail = detail
                    if verkoop.incl is not None:
                        rij.verschil_ct = int(((verkoop.incl - ons_incl) / CENT).to_integral_value())
                    if uitkomst is None:
                        rij.uitkomst = UITKOMST_GELIJK
                    elif uitkomst == "afwijking":
                        rij.uitkomst = UITKOMST_AFWIJKING
                    else:
                        nieuw_btw = verkoop.btw if verkoop.btw is not None else (verkoop.incl - ons_netto).quantize(CENT)
                        rij.nieuw_btw = str(nieuw_btw)
                        if abs(nieuw_btw - b.btw_bedrag) > BEDRAG_TOLERANTIE:
                            rij.uitkomst = UITKOMST_AFWIJKING
                            rij.detail = f"btw-verschil {nieuw_btw - b.btw_bedrag} > tolerantie — {detail}"
                        elif not uitvoeren:
                            rij.uitkomst = UITKOMST_ZOU
                        else:
                            rij.webhook_event = _trek_gelijk(
                                aid,
                                b.id,
                                actor_id=actor_id,
                                nieuw_btw=nieuw_btw,
                                rlz_bron={
                                    "verkoop_rlz_id": str(b.verkoop_rlz_id),
                                    "verkoop_boekstuk": boekstuk_v,
                                    "spiegel_rlz_id": str(b.spiegel_rlz_id),
                                    "spiegel_boekstuk": boekstuk_s,
                                    "rlz_verkoop_incl": rij.rlz_verkoop_incl,
                                    "rlz_spiegel_incl": rij.rlz_spiegel_incl,
                                },
                                doelentiteit=rij.doelentiteit,
                                btw_pct=btw_pct,
                            )
                            rij.uitkomst = UITKOMST_GELIJKGETROKKEN
                    resultaat.rijen.append(rij)
            finally:
                for c in [bron_client, *doel_clients.values()]:
                    sluit = getattr(c, "close", None)
                    if callable(sluit):
                        sluit()
        except GeenRlzCredentials as exc:
            resultaat.fouten.append(f"{naam}: geen RLZ-credential ({exc.__class__.__name__})")
        except Exception as exc:  # noqa: BLE001 — één kapotte administratie stopt de run niet
            resultaat.fouten.append(f"{naam}: {exc.__class__.__name__}: {str(exc)[:200]}")
    return resultaat


def _str(x: Decimal | None) -> str | None:
    return None if x is None else str(x)


def _trek_gelijk(
    administratie_id: uuid.UUID,
    boeking_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    nieuw_btw: Decimal,
    rlz_bron: dict,
    doelentiteit: str,
    btw_pct: Decimal | None,
) -> bool:
    """Eén boeking gelijktrekken in ÉÉN transactie: btw_bedrag, audit, tijdlijn (bron-document, beide kanten genoemd)
    en — vastgoed-doel — het boekstand-event. Retourneert of er een webhook-event is aangemaakt."""
    from app.db.audit import record_audit_event
    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.documenten.boekstand import laatste_boekstand_rij, stand_van_rij
    from app.documenten.models import Document, WebhookUitgaand
    from app.documenten.webhook import FACTUUR_GEBOEKT_EVENT
    from app.doorbelasting.boeken import _tijdlijn
    from app.doorbelasting.models import DoorbelastingBoeking, DoorbelastingBoekingStatus

    webhook = False
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        boeking = session.get(DoorbelastingBoeking, boeking_id)
        oud_btw = boeking.btw_bedrag
        oud_incl = boeking.netto_totaal + boeking.provisie_bedrag + oud_btw
        boeking.btw_bedrag = nieuw_btw
        nieuw_incl = boeking.netto_totaal + boeking.provisie_bedrag + nieuw_btw
        # Boekstand-event (v1.14) voor een spiegel in een vastgoed-doel: nieuwe stand mét de gecorrigeerde regels.
        if boeking.status == DoorbelastingBoekingStatus.GEBOEKT.value and boeking.doel_administratie_id is not None:
            doel = session.get(Administratie, boeking.doel_administratie_id)
            if doel is not None and doel.is_vastgoed and btw_pct is not None:
                rij = laatste_boekstand_rij(session, document_id=boeking.document_id, rlz_document_id=boeking.spiegel_rlz_id)
                if rij is not None and rij.event == FACTUUR_GEBOEKT_EVENT:
                    payload = _gecorrigeerde_webhook_payload(rij.payload, nieuw_volgnummer=stand_van_rij(rij) + 1, btw_pct=btw_pct)
                    if payload is not None:
                        session.add(
                            WebhookUitgaand(
                                document_id=boeking.document_id,
                                administratie_id=boeking.doel_administratie_id,
                                event=payload["event"],
                                payload=payload,
                            )
                        )
                        webhook = True
        document = session.get(Document, boeking.document_id)
        if document is not None:
            _tijdlijn(
                session,
                document=document,
                actor_id=actor_id,
                detail={
                    "gebeurtenis": TIJDLIJN_GEBEURTENIS,
                    "doelentiteit": doelentiteit,
                    "verkoop_referentie": boeking.verkoop_referentie,
                    "btw_oud": str(oud_btw),
                    "btw_nieuw": str(nieuw_btw),
                    "incl_oud": str(oud_incl),
                    "incl_nieuw": str(nieuw_incl),
                    "kanten": "verkoopfactuur (bron) én spiegel-inkoopfactuur (doel) — registratie op de RLZ-waarde gezet",
                    **{k: v for k, v in rlz_bron.items() if v},
                    "webhook_event": webhook,
                },
            )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="doorbelasting_boeking",
            record_id=boeking.id,
            actie=AUDIT_GELIJKGETROKKEN,
            correlatie_id=boeking.document_id,
            oude_waarde={"btw_bedrag": str(oud_btw), "incl": str(oud_incl)},
            nieuwe_waarde={
                "btw_bedrag": str(nieuw_btw),
                "incl": str(nieuw_incl),
                "bron": "RLZ-record (btw per tarief over het subtotaal, RLZ-vorm — STAP-0 24-09)",
                "webhook_event": webhook,
                **{k: v for k, v in rlz_bron.items() if v},
            },
            administratie_id=administratie_id,
        )
    return webhook


# ---- CLI ---------------------------------------------------------------------------------------------------------------


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    p = subparsers.add_parser(
        COMMANDO,
        help="Data-stap 24-09 (RLZ-vorm): zet doorbelasting_boeking.btw_bedrag op de RLZ-waarde bij een verschil ≤ € 0,05 "
        "(audit + tijdlijn + boekstand-event voor vastgoed); > € 0,05 of verkoop ≠ spiegel = AFWIJKING, niet aangepast. "
        "Alleen ONZE database; nooit een write in RLZ. Dry-run default, --uitvoeren schrijft.",
    )
    p.add_argument("--dry-run", action="store_true", dest="dry_run", help="Alleen tellen/tonen (default).")
    p.add_argument("--uitvoeren", action="store_true", dest="uitvoeren", help="Échte run (schrijft in onze database).")
    p.add_argument("--administratie", default=None, help="Beperk tot één bron-administratie (uuid of naamdeel).")
    p.add_argument("--beheerder-id", default=None, dest="beheerder_id", help="Actor voor audit/tijdlijn (default systeem-actor).")
    p.add_argument("--json-uit", action="store_true", dest="json_uit", help="Machineleesbare uitvoer (JSON).")


def dispatch(args: argparse.Namespace) -> int | None:
    if getattr(args, "commando", None) != COMMANDO:
        return None
    return run(args)


def run(args: argparse.Namespace, *, uit=None, client_factory=None) -> int:  # noqa: ANN001
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    uit = uit or sys.stdout
    actor = uuid.UUID(args.beheerder_id) if getattr(args, "beheerder_id", None) else SYSTEEM_ACTOR_ID
    resultaat = verwerk(
        administratie=args.administratie, uitvoeren=bool(getattr(args, "uitvoeren", False)), actor_id=actor, client_factory=client_factory
    )
    if resultaat is None:
        print(f"{COMMANDO}: --administratie {args.administratie!r} onbekend of niet eenduidig", file=sys.stderr)
        return 2
    t = resultaat.telling()
    if getattr(args, "json_uit", False):
        print(
            json.dumps(
                {"dry_run": resultaat.dry_run, "rijen": [asdict(r) for r in resultaat.rijen], "telling": t, "fouten": resultaat.fouten},
                indent=2,
                ensure_ascii=False,
            ),
            file=uit,
        )
        return 0
    modus = "DRY-RUN (niets geschreven)" if resultaat.dry_run else "UITGEVOERD (alleen onze database; RLZ ongewijzigd)"
    print(f"== {COMMANDO} — {modus} · {datetime.now(UTC):%Y-%m-%d %H:%M} UTC ==", file=uit)
    for r in resultaat.rijen:
        if r.uitkomst == UITKOMST_GELIJK:
            continue  # gelijk = alleen in de telling; de lijst toont wat er te doen/te melden is
        kop = {UITKOMST_ZOU: "ZOU GELIJKTREKKEN", UITKOMST_GELIJKGETROKKEN: "GELIJKGETROKKEN", UITKOMST_AFWIJKING: "AFWIJKING", UITKOMST_NIET_LEESBAAR: "NIET LEESBAAR"}[r.uitkomst]
        print(
            f"{kop:18} {r.administratie} → {r.doelentiteit} · verkoop {r.verkoop_referentie or '?'} · {r.status} · module "
            f"{r.ons_incl} (btw {r.ons_btw}) · RLZ verkoop {r.rlz_verkoop_incl} (btw {r.rlz_verkoop_btw}, {r.rlz_verkoop_boekstuk}) · "
            f"spiegel {r.rlz_spiegel_incl} (btw {r.rlz_spiegel_btw}, {r.rlz_spiegel_boekstuk})"
            + (f" · nieuw btw {r.nieuw_btw}" if r.nieuw_btw else "")
            + (" · boekstand-event vastgoed" if r.webhook_event else "")
            + f" · {r.detail}",
            file=uit,
        )
    for f in resultaat.fouten:
        print(f"FOUT {f}", file=uit)
    print(
        f"TOTAAL: {len(resultaat.rijen)} doorbelasting(en) in {resultaat.administraties} administratie(s) · gelijk {t[UITKOMST_GELIJK]} · "
        f"cent-verschil ≤ 0,05: {t[UITKOMST_ZOU] + t[UITKOMST_GELIJKGETROKKEN]} ({'zou gelijktrekken' if resultaat.dry_run else 'gelijkgetrokken'}) · "
        f"afwijking > 0,05 of verkoop ≠ spiegel: {t[UITKOMST_AFWIJKING]} · niet leesbaar {t[UITKOMST_NIET_LEESBAAR]} · "
        f"boekstand-events vastgoed {t['webhook_events']} · fouten {len(resultaat.fouten)}",
        file=uit,
    )
    return 0
