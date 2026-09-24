"""Corrigeren vanuit de module — storno (actie 19) + opnieuw klaarzetten (opdracht Peter 21-09).

Aanleiding: twee BLOW-boekingen met een fout btw-bedrag (RLZ-04-00000357 / -358) moesten in de RLZ-UI gecorrigeerd
worden — "ik kan de storno-knop niet meer vinden". Die knop bestond niet: GEBOEKT was lokaal terminaal-zonder-uitweg
(storno_detectie.py: "uitsluitend via actie 19 in de RLZ-UI"). Dat is een gat tegen kernprincipe 7 (minimale mens):
een fout die de module zelf heeft geboekt moet de module zelf kunnen herstellen. Peter 21-09: "laten we die terugboeken
meenemen".

Wat het doet — op een GEBOEKT inkoop-, verkoop- of kassarapport-document, mét verplichte reden (≥ 5 tekens), in één
handeling en één rijvergrendeling (twee keer klikken = één storno):

1. POORTEN (alles vóór de eerste externe write, alles-of-niets):
   - aangiftepoort (`app/rlz/aangifte.py`): valt de boekdatum van een nog geboekt extern stuk in een ingediende
     btw-periode (of is de aangiftestatus niet leesbaar — fail-closed), dan géén storno maar het TEGENBOEK-PAD
     (bestaande knop op een inkoopfactuur; verkoop/kassarapport = creditnota in RLZ) mét uitleg waarom;
   - afgeletterd: een (deels) betaalde inkoop-/verkoopfactuur (`BasePaidAmount` ≠ 0) laat ná actie 19 huls-koppelingen
     achter (api-verkenning actie 15/19) → blokkeren mét "eerst afletteren terugdraaien in de bankmodule" + link. Een
     kassarapport is een entity-loze Receipt mét tegenzijde (geen open post, geen PaymentItem) — de poort geldt daar
     niet;
   - doorbelasting-bron mét spiegel: beide kanten of geen — de bestaande motor `storno_doorbelasting_boeking` toetst
     BEIDE kanten op de aangifte (`storno_toets_voor_document`), één geblokkeerde kant blokkeert de hele correctie;
   - backend: Odoo kent geen storno op hetzelfde document (besluit Peter 02-09) → `NietOndersteund` zichtbaar,
     tegenboek-pad als route (capability-contract 0016 §4);
   - verdwenen extern stuk (404) → niet deze route maar "Opnieuw boeken" vanuit Inzicht › Reconciliatie.
2. STORNO extern: eerst de doorbelasting-spiegels (bestaande motor, spiegel → bron-verkoop), dan het eigen stuk via de
   port (`InkoopPort.storneer`; verkoop = `correct_sales_invoice`; kassarapport = memoriaal én Receipt), terug-lezen dat
   het op Status 1 staat. Al concept (in de RLZ-UI gestorneerd) = niets schrijven, lokaal wél klaarzetten.
3. LOKAAL (bestaand herboek-mechanisme, `herboeken.py`/`tegenboeken.py` 'vervang'): inkoop `boek_cyclus += 1` (de
   herboeking krijgt een VERS deterministisch GUID; de duplicaatcheck kent de hele keten als uitgezonderd —
   `boekvoorstel.py` `keten`), `rlz_boekstuknummer` leeg, GEBOEKT → KLAAR_OM_TE_BOEKEN, neveneffecten terug
   (verplichting-verbruik, mini-voorraad, autoboek-leren), webhook `factuur_gestorneerd` (bron `module_storno`) voor
   vastgoed-administraties, tijdlijnregel `gecorrigeerd` + audit `document_gecorrigeerd` (reden, oud extern id, oud
   boekstuknummer). Verkoop/kassarapport: registratierij(en) → `gestorneerd`, kop-boekstuknummer leeg; de motoren
   her-PUTten op hetzelfde GUID (her-PUT op een concept vervangt de regels — api-verkenning "Her-PUT op een bestaand
   concept") en sluiten hun eigen GUID uit van de duplicaatcheck.
4. Het document opent direct in het controlescherm mét een gele balk "Gecorrigeerd — reden … · vorige boeking …" (uit de
   tijdlijnregel), regels zoals ze waren; harde checks draaien vers (de vingerafdruk van de checks-cache draagt de
   boek_cyclus). Klant-accordering: het akkoord gold de factuur, niet de boekingsregels — géén nieuwe ronde.

Rechten: élke kantoorrol (router-brede `vereis_kantoorrol` + administratie-scope). Nooit een delete in RLZ.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backends import inkoop_port_voor
from app.backends.port import Backend, BackendBoekFout, InkoopPort, NietOndersteund, ToetsMislukt
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.boekstand import laatste_boekstand_rij, stand_van_rij
from app.documenten.models import Boekvoorstel, Document, DocumentSoort, DocumentStatus, WebhookUitgaand
from app.documenten.rlz_ids import rlz_herboeking_id, rlz_kostprijs_memoriaal_id, rlz_sales_invoice_id
from app.documenten.service import DocumentNietGevonden, _schrijf_overgang
from app.documenten.webhook import FACTUUR_GEBOEKT_EVENT, GESTORNEERD_BRON_MODULE, bouw_factuur_gestorneerd_payload
from app.rlz.aangifte import AangiftePoort, KantToets
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id, rlz_admin_id_voor

logger = logging.getLogger(__name__)

MIN_REDEN_LENGTE = 5  # zelfde ondergrens als tegenboeken/herboeken/acceptaties

#: Documentsoorten met een eigen boekmotor die actie 19 kent.
CORRIGEERBARE_SOORTEN: frozenset[str] = frozenset(
    {DocumentSoort.INKOOPFACTUUR.value, DocumentSoort.VERKOOPFACTUUR.value, DocumentSoort.KASSARAPPORT.value}
)

#: Blokkade-codes (frontend leest ze uit het 409-detail en de toets).
BLOKKADE_AANGIFTE = "aangifte"
BLOKKADE_AFGELETTERD = "afgeletterd"
BLOKKADE_DOORBELASTING = "doorbelasting"
BLOKKADE_VERDWENEN = "verdwenen"
BLOKKADE_NIET_ONDERSTEUND = "niet_ondersteund"
BLOKKADE_NIET_LEESBAAR = "niet_leesbaar"
BLOKKADE_STATUS = "status"
AL_GECORRIGEERD_CODE = "al_gecorrigeerd"

AUDIT_ACTIE = "document_gecorrigeerd"
AUDIT_ACTIE_MISLUKT = "document_correctie_mislukt"


class CorrigerenFout(Exception):
    """Basis voor alle domeinfouten (409 in de router)."""


class CorrigerenNietToegestaan(CorrigerenFout):
    """Eén of meer poorten blokkeren — `blokkades` zegt per poort waarom en wat de route dan wél is."""

    def __init__(self, blokkades: list[Blokkade]) -> None:
        self.blokkades = blokkades
        super().__init__("Corrigeren is hier niet mogelijk: " + " · ".join(b.melding for b in blokkades))

    def als_detail(self) -> dict[str, Any]:
        return {
            "code": self.blokkades[0].code if self.blokkades else BLOKKADE_STATUS,
            "bericht": str(self),
            "blokkades": [b.als_dict() for b in self.blokkades],
        }


class AlGecorrigeerd(CorrigerenFout):
    """Idempotentie: het document staat niet (meer) op GEBOEKT — een tweede klik doet niets extra."""

    code = AL_GECORRIGEERD_CODE

    def __init__(self, status: DocumentStatus) -> None:
        self.status = status
        super().__init__(
            f"Het document staat op status {status.value} — alleen een geboekt document kan gecorrigeerd worden "
            "(een eerdere correctie is al verwerkt)"
        )

    def als_detail(self) -> dict[str, Any]:
        return {"code": self.code, "bericht": str(self), "status": self.status.value}


class CorrigerenMislukt(CorrigerenFout):
    """De backend gaf een fout tijdens de storno — lokaal is niets gewijzigd (502 in de router). `str(exc)` benoemt
    exact welke kant al wél teruggedraaid is (doorbelasting-spiegels, kostprijsmemoriaal)."""


@dataclass(frozen=True)
class Blokkade:
    code: str
    melding: str
    #: handelingsperspectief voor het scherm: "tegenboeken" | "bank" | "opnieuw_boeken" | None
    actie: str | None = None
    actie_pad: str | None = None

    def als_dict(self) -> dict[str, Any]:
        return {"code": self.code, "melding": self.melding, "actie": self.actie, "actie_pad": self.actie_pad}


@dataclass(frozen=True)
class ExternStuk:
    """Stand van één extern document dat bij de boeking hoort (inkoop: 1; verkoop: 1; kassarapport: Receipt +
    optioneel kostprijsmemoriaal)."""

    label: str
    extern_id: uuid.UUID
    kant: KantToets
    bestaat: bool
    nog_geboekt: bool
    boekstuknummer: str | None = None
    betaald_bedrag: Decimal | None = None
    #: RLZ-collectie voor de storno-aanroep ("PurchaseInvoices" | "SalesInvoices" | "ManualJournals")
    collectie: str = "PurchaseInvoices"


@dataclass(frozen=True)
class DoorbelastingKant:
    boeking_id: uuid.UUID
    doelentiteit: str
    toegestaan: bool
    reden: str | None


@dataclass(frozen=True)
class CorrigeerToets:
    document_id: uuid.UUID
    soort: str
    backend: str
    beschikbaar: bool
    blokkades: list[Blokkade]
    oud_boekstuknummer: str | None
    stukken: list[ExternStuk]
    doorbelasting: list[DoorbelastingKant] = field(default_factory=list)

    @property
    def tegenboeken_beschikbaar(self) -> bool:
        """Het tegenboek-pad is de route als de aangifte (of Odoo) de storno blokkeert — alleen inkoop heeft die
        knop."""
        return self.soort == DocumentSoort.INKOOPFACTUUR.value and any(b.actie == "tegenboeken" for b in self.blokkades)


@dataclass(frozen=True)
class CorrigeerResultaat:
    document_id: uuid.UUID
    status: DocumentStatus
    soort: str
    boek_cyclus: int | None
    oud_boekstuknummer: str | None
    oud_extern_id: str | None
    gestorneerd: list[str]
    al_concept: list[str]
    doorbelasting_gestorneerd: int
    doel_pad: str


def review_pad(soort: str, administratie_id: uuid.UUID, document_id: uuid.UUID) -> str:
    """Dunne laag op de ene bron `app/documenten/deeplink.py::document_pad` (24-09, BUG 23-09) — spiegel van
    `frontend/src/werkvoorraad/format.ts::documentPad`."""
    from app.documenten.deeplink import document_pad

    return document_pad(administratie_id, document_id, soort)


# --- hulpfuncties -------------------------------------------------------------------------------------------------


def _rlz_client_voor(administratie_id: uuid.UUID) -> RlzClient:
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    return client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)


def _port_voor(administratie_id: uuid.UUID) -> InkoopPort:
    return inkoop_port_voor(administratie_id, rlz_client_factory=lambda: _rlz_client_voor(administratie_id))


def _als_decimal(waarde: object) -> Decimal | None:
    if waarde is None:
        return None
    try:
        return Decimal(str(waarde))
    except (ArithmeticError, ValueError):
        return None


def _laad_document(
    session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID, vergrendel: bool
) -> Document:
    stmt = select(Document).where(Document.id == document_id, Document.administratie_id == administratie_id)
    if vergrendel:
        # FOR NO KEY UPDATE (key_share=True): een tweede klik wacht op onze commit en ziet daarna een andere status
        # (→ AlGecorrigeerd); tegelijk blijft een FK-insert op deze rij (tijdlijn/webhook door de doorbelasting-storno
        # in een eigen transactie) mogelijk — FOR UPDATE zou dáár op deadlocken.
        stmt = stmt.with_for_update(key_share=True)
    document = session.scalars(stmt).one_or_none()
    if document is None:
        raise DocumentNietGevonden(f"Onbekend document: {document_id}")
    if document.soort not in CORRIGEERBARE_SOORTEN:
        raise CorrigerenFout(
            f"Document heeft soort {document.soort} — corrigeren kent alleen inkoopfactuur, verkoopfactuur en "
            "kassarapport"
        )
    return document


def _stuk_via_rlz(
    poort: AangiftePoort, client: RlzClient, *, collectie: str, extern_id: uuid.UUID, label: str
) -> ExternStuk:
    """Eén GET per stuk: de aangiftepoort leest hetzelfde antwoord (404 = vrij; niet leesbaar = fail-closed)."""
    document: dict | None = None

    def ophalen() -> dict:
        nonlocal document
        document = client.get(f"{collectie}/{extern_id}")
        return document

    kant = poort.toets_document(ophalen, kant=label)
    if document is None:
        # 404 → de poort zegt 'vrij' en er is niets: verdwenen. Elke andere leesfout → de poort is fail-closed
        # (toegestaan=False); het stuk telt dan als bestaand én geboekt zodat de blokkade 'niet leesbaar' verschijnt
        # in plaats van een valse 'verdwenen'.
        onleesbaar = not kant.toegestaan
        return ExternStuk(
            label=label, extern_id=extern_id, kant=kant, bestaat=onleesbaar, nog_geboekt=onleesbaar, collectie=collectie
        )
    status = document.get("Status")
    return ExternStuk(
        label=label,
        extern_id=extern_id,
        kant=kant,
        bestaat=True,
        nog_geboekt=status in (2, 3),
        boekstuknummer=document.get("ReceiptNumber"),
        betaald_bedrag=_als_decimal(document.get("BasePaidAmount")),
        collectie=collectie,
    )


def _stuk_via_port(port: InkoopPort, *, document_id: uuid.UUID, boek_cyclus: int) -> ExternStuk:
    """Inkoop via de port: `origineel_stand` (aangifte + betaald) en `toets_geboekt` (bestaat + boekstuk)."""
    extern_id = rlz_herboeking_id(document_id, boek_cyclus)
    stand = port.origineel_stand(document_id=document_id, boek_cyclus=boek_cyclus)
    try:
        toets = port.toets_geboekt(document_id=document_id, boek_cyclus=boek_cyclus)
        bestaat, boekstuk = toets.bestaat, toets.boekstuknummer
    except ToetsMislukt as exc:
        return ExternStuk(
            label="inkoopfactuur",
            extern_id=extern_id,
            kant=KantToets(kant="inkoopfactuur", toegestaan=False, reden=f"document niet leesbaar: {exc}"),
            bestaat=True,
            nog_geboekt=stand.nog_geboekt,
            betaald_bedrag=stand.betaald_bedrag,
        )
    return ExternStuk(
        label="inkoopfactuur",
        extern_id=extern_id,
        kant=stand.kant,
        bestaat=bestaat,
        nog_geboekt=stand.nog_geboekt,
        boekstuknummer=boekstuk,
        betaald_bedrag=stand.betaald_bedrag,
    )


def _omzet_ids(
    session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID | None]:
    from app.omzet.models import OmzetBoeking, OmzetBoekingStatus

    rij = session.scalars(
        select(OmzetBoeking)
        .where(
            OmzetBoeking.administratie_id == administratie_id,
            OmzetBoeking.document_id == document_id,
            OmzetBoeking.status.in_((OmzetBoekingStatus.GEBOEKT.value, OmzetBoekingStatus.HALF_GEBOEKT.value)),
        )
        .order_by(OmzetBoeking.id)
    ).first()
    if rij is None:
        return rlz_sales_invoice_id(document_id), rlz_kostprijs_memoriaal_id(document_id)
    return rij.verkoop_rlz_id, rij.memoriaal_rlz_id


def _doorbelasting_kanten(
    administratie_id: uuid.UUID, document_id: uuid.UUID, *, toets_fn: Callable[..., dict[uuid.UUID, list[KantToets]]]
) -> list[DoorbelastingKant]:
    """De bestaande leesroute van de doorbelasting-storno (beide kanten, fail-closed) per niet-gestorneerde boeking."""
    from app.doorbelasting.models import DoorbelastingBoeking, DoorbelastingMapping

    toetsen = toets_fn(administratie_id=administratie_id, document_id=document_id)
    if not toetsen:
        return []
    with scoped_session(administratie_id) as session:
        namen: dict[uuid.UUID, str] = {}
        for boeking in session.scalars(select(DoorbelastingBoeking).where(DoorbelastingBoeking.id.in_(list(toetsen)))):
            mapping = session.get(DoorbelastingMapping, boeking.mapping_id)
            namen[boeking.id] = mapping.doelentiteit_naam if mapping else "?"
    kanten: list[DoorbelastingKant] = []
    for boeking_id, lijst in toetsen.items():
        geblokkeerd = [k for k in lijst if not k.toegestaan]
        kanten.append(
            DoorbelastingKant(
                boeking_id=boeking_id,
                doelentiteit=namen.get(boeking_id, "?"),
                toegestaan=not geblokkeerd,
                reden="; ".join(f"{k.kant}: {k.reden}" for k in geblokkeerd) or None,
            )
        )
    return kanten


def _bepaal_blokkades(
    *,
    administratie_id: uuid.UUID,
    soort: str,
    backend: str,
    stukken: list[ExternStuk],
    doorbelasting: list[DoorbelastingKant],
    referentie: str | None,
) -> list[Blokkade]:
    blokkades: list[Blokkade] = []
    if stukken and not any(s.bestaat for s in stukken):
        blokkades.append(
            Blokkade(
                code=BLOKKADE_VERDWENEN,
                melding="Het externe document bestaat niet meer in de boekhouding — dit is de route 'Opnieuw boeken' "
                "vanuit Inzicht › Reconciliatie (bevinding ontbreekt in RLZ/Odoo), niet corrigeren",
                actie="opnieuw_boeken",
                actie_pad="/reconciliatie",
            )
        )
    tegenboek_actie = "tegenboeken" if soort == DocumentSoort.INKOOPFACTUUR.value else None
    for stuk in stukken:
        if not stuk.bestaat or not stuk.nog_geboekt or stuk.kant.toegestaan:
            continue
        if backend == Backend.ODOO.value:
            blokkades.append(
                Blokkade(
                    code=BLOKKADE_NIET_ONDERSTEUND,
                    melding=(
                        f"{stuk.kant.reden or 'Odoo kent geen storno op hetzelfde document'} — gebruik Tegenboeken…"
                    ),
                    actie=tegenboek_actie,
                )
            )
            continue
        niet_leesbaar = stuk.kant.periode_start is None and stuk.kant.periode_eind is None
        route = (
            "gebruik Tegenboeken… (nieuwe boeking mét negatieve regels, boekdatum vandaag)"
            if soort == DocumentSoort.INKOOPFACTUUR.value
            else "corrigeer via een creditnota in Reeleezee in de eerstvolgende open periode"
        )
        blokkades.append(
            Blokkade(
                code=BLOKKADE_NIET_LEESBAAR if niet_leesbaar else BLOKKADE_AANGIFTE,
                melding=(
                    f"Storno van de {stuk.label} is geblokkeerd door de btw-aangifte ({stuk.kant.reden}) — {route}"
                    if not niet_leesbaar
                    else f"Storno van de {stuk.label} is uit voorzorg geblokkeerd ({stuk.kant.reden}) — {route}"
                ),
                actie=tegenboek_actie,
            )
        )
    if soort in (DocumentSoort.INKOOPFACTUUR.value, DocumentSoort.VERKOOPFACTUUR.value):
        for stuk in stukken:
            if stuk.bestaat and stuk.nog_geboekt and stuk.betaald_bedrag not in (None, Decimal(0)):
                zoek = f"?zoek={referentie}" if referentie else ""
                blokkades.append(
                    Blokkade(
                        code=BLOKKADE_AFGELETTERD,
                        melding=(
                            f"De {stuk.label} is (deels) betaald/afgeletterd (€ {stuk.betaald_bedrag}) — een storno laat "
                            "dan "
                            "huls-koppelingen achter; draai eerst het afletteren terug in de bankmodule (storno van de "
                            "bankboeking) en corrigeer daarna"
                        ),
                        actie="bank",
                        actie_pad=f"/bank/{administratie_id}{zoek}",
                    )
                )
    for kant in doorbelasting:
        if not kant.toegestaan:
            blokkades.append(
                Blokkade(
                    code=BLOKKADE_DOORBELASTING,
                    melding=(
                        f"Doorbelasting naar {kant.doelentiteit} kan niet mee terug ({kant.reden}) — beide kanten of "
                        "geen: "
                        "corrigeren is geblokkeerd tot die kant vrij is"
                    ),
                )
            )
    return blokkades


# --- leesroute ----------------------------------------------------------------------------------------------------


def _toets_in_sessie(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document: Document,
    port: InkoopPort | None,
    client: RlzClient | None,
    doorbelasting_toets: Callable[..., dict[uuid.UUID, list[KantToets]]],
) -> tuple[CorrigeerToets, dict[str, Any]]:
    """Gedeeld door `toets` en `corrigeer` (die roept 'm binnen de vergrendelde transactie aan). Retourneert óók een
    contextdict (boek_cyclus, referentie, ids) die de schrijfstap hergebruikt."""
    soort = document.soort
    ctx: dict[str, Any] = {"boek_cyclus": None, "referentie": None, "oud_boekstuknummer": None}
    stukken: list[ExternStuk] = []
    backend = Backend.RLZ.value
    if soort == DocumentSoort.INKOOPFACTUUR.value:
        voorstel = session.get(Boekvoorstel, document.id)
        if voorstel is None:
            raise CorrigerenFout("Het document heeft geen boekvoorstel — corrigeren kan niet")
        ctx["boek_cyclus"] = int(voorstel.boek_cyclus or 0)
        ctx["referentie"] = voorstel.referentie
        ctx["oud_boekstuknummer"] = voorstel.rlz_boekstuknummer
        assert port is not None
        backend = port.backend.value
        stukken.append(_stuk_via_port(port, document_id=document.id, boek_cyclus=ctx["boek_cyclus"]))
    elif soort == DocumentSoort.VERKOOPFACTUUR.value:
        from app.verkoop.models import VerkoopVoorstel

        kop = session.get(VerkoopVoorstel, document.id)
        ctx["referentie"] = kop.factuurnummer if kop is not None else None
        ctx["oud_boekstuknummer"] = kop.rlz_boekstuknummer if kop is not None else None
        assert client is not None
        poort = AangiftePoort(client)
        stukken.append(
            _stuk_via_rlz(
                poort,
                client,
                collectie="SalesInvoices",
                extern_id=rlz_sales_invoice_id(document.id),
                label="verkoopfactuur",
            )
        )
    else:  # kassarapport
        verkoop_id, memoriaal_id = _omzet_ids(session, administratie_id=administratie_id, document_id=document.id)
        assert client is not None
        poort = AangiftePoort(client)
        stukken.append(
            _stuk_via_rlz(
                poort, client, collectie="SalesInvoices", extern_id=verkoop_id, label="omzetboeking (Receipt)"
            )
        )
        if memoriaal_id is not None:
            stukken.append(
                _stuk_via_rlz(
                    poort, client, collectie="ManualJournals", extern_id=memoriaal_id, label="kostprijsmemoriaal"
                )
            )
        ctx["oud_boekstuknummer"] = next((s.boekstuknummer for s in stukken if s.boekstuknummer), None)
    doorbelasting = (
        _doorbelasting_kanten(administratie_id, document.id, toets_fn=doorbelasting_toets)
        if soort == DocumentSoort.INKOOPFACTUUR.value
        else []
    )
    blokkades = _bepaal_blokkades(
        administratie_id=administratie_id,
        soort=soort,
        backend=backend,
        stukken=stukken,
        doorbelasting=doorbelasting,
        referentie=ctx["referentie"],
    )
    toets = CorrigeerToets(
        document_id=document.id,
        soort=soort,
        backend=backend,
        beschikbaar=not blokkades,
        blokkades=blokkades,
        oud_boekstuknummer=ctx["oud_boekstuknummer"]
        or next((s.boekstuknummer for s in stukken if s.boekstuknummer), None),
        stukken=stukken,
        doorbelasting=doorbelasting,
    )
    return toets, ctx


def _standaard_doorbelasting_toets(**kwargs: Any) -> dict[uuid.UUID, list[KantToets]]:
    from app.doorbelasting.boeken import storno_toets_voor_document

    return storno_toets_voor_document(**kwargs)


def _standaard_doorbelasting_storno(**kwargs: Any) -> Any:
    from app.doorbelasting.boeken import storno_doorbelasting_boeking

    return storno_doorbelasting_boeking(**kwargs)


def toets(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    port: InkoopPort | None = None,
    client: RlzClient | None = None,
    doorbelasting_toets: Callable[..., dict[uuid.UUID, list[KantToets]]] | None = None,
) -> CorrigeerToets:
    """Leesroute voor de dialoog: is corrigeren beschikbaar, en zo niet, welke poort blokkeert en wat is dan de route
    (tegenboeken / bank / opnieuw boeken). Een niet-GEBOEKT document geeft één blokkade `status`."""
    with scoped_session(administratie_id) as session:
        document = _laad_document(session, administratie_id=administratie_id, document_id=document_id, vergrendel=False)
        if document.status != DocumentStatus.GEBOEKT:
            return CorrigeerToets(
                document_id=document_id,
                soort=document.soort,
                backend=Backend.RLZ.value,
                beschikbaar=False,
                blokkades=[
                    Blokkade(
                        code=BLOKKADE_STATUS,
                        melding=f"Alleen een geboekt document kan gecorrigeerd worden (status {document.status.value})",
                    )
                ],
                oud_boekstuknummer=None,
                stukken=[],
            )
        soort = document.soort
        eigen_port = port is None and soort == DocumentSoort.INKOOPFACTUUR.value
        eigen_client = client is None and soort != DocumentSoort.INKOOPFACTUUR.value
        if eigen_port:
            port = _port_voor(administratie_id)
        if eigen_client:
            client = _rlz_client_voor(administratie_id)
        try:
            resultaat, _ctx = _toets_in_sessie(
                session,
                administratie_id=administratie_id,
                document=document,
                port=port,
                client=client,
                doorbelasting_toets=doorbelasting_toets or _standaard_doorbelasting_toets,
            )
        finally:
            if eigen_port and port is not None:
                port.__exit__(None, None, None)
            if eigen_client and client is not None:
                with contextlib.suppress(Exception):
                    client.close()
    return resultaat


# --- schrijfroute -------------------------------------------------------------------------------------------------


def _meld_gestorneerd_voor_vastgoed(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    rlz_document_id: uuid.UUID,
    reden: str,
) -> bool:
    """Koppelcontract §3b: alleen als de boeking ooit als `factuur_geboekt` gemeld is en de laatste stand 'geboekt'
    zegt — idempotent per boekstand-reeks (zelfde anker als storno_detectie/herboeken), bron `module_storno`."""
    administratie = session.get(Administratie, administratie_id)
    if administratie is None or not administratie.is_vastgoed:
        return False
    rij = laatste_boekstand_rij(session, document_id=document_id, rlz_document_id=rlz_document_id)
    if rij is None or rij.event != FACTUUR_GEBOEKT_EVENT:
        return False
    data = (rij.payload or {}).get("data") or {}
    payload = bouw_factuur_gestorneerd_payload(
        administratie_id=administratie_id,
        rlz_admin_id=administratie.rlz_admin_id,
        rlz_document_id=rlz_document_id,
        rlz_boekstuknummer=data.get("rlz_boekstuknummer"),
        referentie=data.get("referentie"),
        volgnummer=stand_van_rij(rij) + 1,
        bron=GESTORNEERD_BRON_MODULE,
        reden=f"gecorrigeerd vanuit de module (storno + opnieuw klaarzetten): {reden}",
        gestorneerd_op=datetime.now(UTC),
    )
    session.add(WebhookUitgaand(document_id=document_id, event=payload["event"], payload=payload))
    return True


def _storneer_stuk_rlz(client: RlzClient, stuk: ExternStuk) -> None:
    """Actie 19 op één RLZ-stuk + terug-lezen (Status 1); 404 = al weg (niets te doen)."""
    try:
        if stuk.collectie == "SalesInvoices":
            client.correct_sales_invoice(stuk.extern_id)
        elif stuk.collectie == "ManualJournals":
            client.correct_manual_journal(stuk.extern_id)
        else:
            client.correct_purchase_invoice(stuk.extern_id)
        na = client.get(f"{stuk.collectie}/{stuk.extern_id}")
    except RlzApiError as exc:
        if exc.status_code == 404:
            return
        raise CorrigerenMislukt(
            f"Storno (actie 19) van de {stuk.label} in Reeleezee mislukte ({exc.status_code}): {exc}"
        ) from exc
    if isinstance(na, dict) and na.get("Status") not in (1, None):
        raise CorrigerenMislukt(
            f"Reeleezee meldt ná actie 19 op de {stuk.label} status {na.get('Status')!r} in plaats van concept (1) — "
            "storno niet bevestigd"
        )


def _audit_mislukt(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, reden: str, fout: str, stand: dict
) -> None:
    """Zichtbaar spoor van een half gelukte correctie (bijv. spiegel al terug, eigen stuk niet) — eigen transactie."""
    try:
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="document",
                record_id=document_id,
                actie=AUDIT_ACTIE_MISLUKT,
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={"reden": reden, "fout": fout, **stand},
                administratie_id=administratie_id,
            )
    except Exception:  # noqa: BLE001 — het audit-spoor mag de foutmelding zelf nooit verhullen
        logger.exception("audit van mislukte correctie kon niet geschreven worden (document %s)", document_id)


def corrigeer(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    reden: str,
    port: InkoopPort | None = None,
    client: RlzClient | None = None,
    doorbelasting_toets: Callable[..., dict[uuid.UUID, list[KantToets]]] | None = None,
    doorbelasting_storno: Callable[..., Any] | None = None,
) -> CorrigeerResultaat:
    """De actie (zie moduledocstring). Eén vergrendelde transactie: poorten → doorbelasting-spiegels terug → storno
    eigen stuk → lokaal klaarzetten. Faalt een externe stap, dan rolt het lokale deel terug en benoemt de fout wat er
    wél al teruggedraaid is (audit `document_correctie_mislukt`)."""
    if len((reden or "").strip()) < MIN_REDEN_LENGTE:
        raise CorrigerenFout(f"Reden is verplicht (minimaal {MIN_REDEN_LENGTE} tekens)")
    reden = reden.strip()
    doorbelasting_toets = doorbelasting_toets or _standaard_doorbelasting_toets
    doorbelasting_storno = doorbelasting_storno or _standaard_doorbelasting_storno

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = _laad_document(session, administratie_id=administratie_id, document_id=document_id, vergrendel=True)
        if document.status != DocumentStatus.GEBOEKT:
            raise AlGecorrigeerd(document.status)
        soort = document.soort
        eigen_port = port is None and soort == DocumentSoort.INKOOPFACTUUR.value
        eigen_client = client is None and soort != DocumentSoort.INKOOPFACTUUR.value
        if eigen_port:
            port = _port_voor(administratie_id)
        if eigen_client:
            client = _rlz_client_voor(administratie_id)
        try:
            toets_uitkomst, ctx = _toets_in_sessie(
                session,
                administratie_id=administratie_id,
                document=document,
                port=port,
                client=client,
                doorbelasting_toets=doorbelasting_toets,
            )
            if toets_uitkomst.blokkades:
                raise CorrigerenNietToegestaan(toets_uitkomst.blokkades)

            # 1. Doorbelasting-spiegels eerst (bestaande motor: spiegel → bron-verkoop, aangiftepoort beide kanten,
            #    eigen transacties). Faalt het eigen stuk daarna, dan zegt de fout dat deze kant al terug is.
            doorbelasting_terug: list[str] = []
            for kant in toets_uitkomst.doorbelasting:
                try:
                    doorbelasting_storno(
                        administratie_id=administratie_id,
                        boeking_id=kant.boeking_id,
                        actor_id=actor_id,
                        reden=f"correctie bron-inkoopfactuur: {reden}",
                    )
                except Exception as exc:  # noqa: BLE001 — leesbaar en zichtbaar, nooit half stil
                    fout = f"Storno van de doorbelasting naar {kant.doelentiteit} mislukte: {exc}" + (
                        f" (al teruggedraaid: {', '.join(doorbelasting_terug)})" if doorbelasting_terug else ""
                    )
                    _audit_mislukt(
                        administratie_id=administratie_id,
                        document_id=document_id,
                        actor_id=actor_id,
                        reden=reden,
                        fout=fout,
                        stand={"doorbelasting_teruggedraaid": doorbelasting_terug},
                    )
                    raise CorrigerenMislukt(fout) from exc
                doorbelasting_terug.append(kant.doelentiteit)

            # 2. Storno van het eigen stuk / de eigen stukken.
            gestorneerd: list[str] = []
            al_concept: list[str] = []
            try:
                if soort == DocumentSoort.INKOOPFACTUUR.value:
                    assert port is not None
                    try:
                        uitkomst = port.storneer(document_id=document_id, boek_cyclus=ctx["boek_cyclus"])
                    except NietOndersteund as exc:
                        raise CorrigerenNietToegestaan(
                            [Blokkade(code=BLOKKADE_NIET_ONDERSTEUND, melding=str(exc), actie="tegenboeken")]
                        ) from exc
                    except BackendBoekFout as exc:
                        raise CorrigerenMislukt(str(exc)) from exc
                    if uitkomst.verdwenen:
                        raise CorrigerenNietToegestaan(
                            [
                                Blokkade(
                                    code=BLOKKADE_VERDWENEN,
                                    melding="Het externe document bestaat niet meer — gebruik 'Opnieuw boeken' vanuit "
                                    "Inzicht › Reconciliatie",
                                    actie="opnieuw_boeken",
                                    actie_pad="/reconciliatie",
                                )
                            ]
                        )
                    (gestorneerd if uitkomst.gestorneerd else al_concept).append(str(uitkomst.extern_document_id))
                else:
                    assert client is not None
                    # Kassarapport: memoriaal eerst, dan de Receipt — faalt de Receipt, dan is de stand exact
                    # HALF_GEBOEKT (verkoop geboekt, memoriaal niet) en meldt de omzet-reconciliatie 'm.
                    volgorde = sorted(toets_uitkomst.stukken, key=lambda s: 0 if s.collectie == "ManualJournals" else 1)
                    for stuk in volgorde:
                        if not stuk.bestaat:
                            continue
                        if not stuk.nog_geboekt:
                            al_concept.append(str(stuk.extern_id))
                            continue
                        _storneer_stuk_rlz(client, stuk)
                        gestorneerd.append(str(stuk.extern_id))
            except CorrigerenMislukt as exc:
                stand = {"doorbelasting_teruggedraaid": doorbelasting_terug, "gestorneerd": gestorneerd}
                if soort == DocumentSoort.KASSARAPPORT.value and gestorneerd:
                    _markeer_omzet_half(
                        administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, reden=reden
                    )
                fout = str(exc) + (
                    f" — LET OP, al wél teruggedraaid: {', '.join(doorbelasting_terug + gestorneerd)}"
                    if doorbelasting_terug or gestorneerd
                    else " — niets teruggedraaid, niets lokaal gewijzigd"
                )
                _audit_mislukt(
                    administratie_id=administratie_id,
                    document_id=document_id,
                    actor_id=actor_id,
                    reden=reden,
                    fout=fout,
                    stand=stand,
                )
                raise CorrigerenMislukt(fout) from exc
        finally:
            if eigen_port and port is not None:
                port.__exit__(None, None, None)
            if eigen_client and client is not None:
                with contextlib.suppress(Exception):
                    client.close()

        # 3. Lokaal klaarzetten — dezelfde transactie als de rijvergrendeling.
        oud_boekstuknummer = toets_uitkomst.oud_boekstuknummer
        oud_extern_id = str(toets_uitkomst.stukken[0].extern_id) if toets_uitkomst.stukken else None
        nieuwe_cyclus: int | None = None
        detail_corr: dict[str, Any] = {
            "reden": reden,
            "soort": soort,
            "oud_boekstuknummer": oud_boekstuknummer,
            "oud_extern_id": oud_extern_id,
            "gestorneerd": gestorneerd,
            "al_concept": al_concept,
            "doorbelasting_teruggedraaid": doorbelasting_terug,
            "backend": toets_uitkomst.backend,
        }
        if soort == DocumentSoort.INKOOPFACTUUR.value:
            voorstel = session.get(Boekvoorstel, document_id)
            assert voorstel is not None
            oude_cyclus = ctx["boek_cyclus"]
            nieuwe_cyclus = oude_cyclus + 1
            voorstel.boek_cyclus = nieuwe_cyclus
            voorstel.rlz_boekstuknummer = None
            detail_corr.update({"oude_cyclus": oude_cyclus, "nieuwe_cyclus": nieuwe_cyclus})
        elif soort == DocumentSoort.VERKOOPFACTUUR.value:
            from app.verkoop.models import VerkoopBoeking, VerkoopBoekingStatus, VerkoopVoorstel

            kop = session.get(VerkoopVoorstel, document_id)
            if kop is not None:
                kop.rlz_boekstuknummer = None
            for rij in session.scalars(
                select(VerkoopBoeking).where(
                    VerkoopBoeking.document_id == document_id,
                    VerkoopBoeking.status == VerkoopBoekingStatus.GEBOEKT.value,
                )
            ):
                rij.status = VerkoopBoekingStatus.GESTORNEERD.value
                rij.storno_reden = reden
                rij.gestorneerd_op = datetime.now(UTC)
                rij.gestorneerd_door = actor_id
        else:
            from app.omzet.models import OmzetBoeking, OmzetBoekingStatus

            for rij in session.scalars(
                select(OmzetBoeking).where(
                    OmzetBoeking.document_id == document_id,
                    OmzetBoeking.status.in_((OmzetBoekingStatus.GEBOEKT.value, OmzetBoekingStatus.HALF_GEBOEKT.value)),
                )
            ):
                rij.status = OmzetBoekingStatus.GESTORNEERD.value
                rij.storno_reden = reden
                rij.gestorneerd_op = datetime.now(UTC)
                rij.gestorneerd_door = actor_id

        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
            actor_id=actor_id,
            detail={
                "gecorrigeerd": detail_corr,
                "reden": (
                    f"gecorrigeerd — vorige boeking {oud_boekstuknummer or (oud_extern_id or '')[:8]} gestorneerd "
                    f"(actie 19), opnieuw klaargezet: {reden}"
                ),
            },
        )
        # Neveneffecten van de oorspronkelijke boeking terugdraaien (zelfde drieluik als tegenboeken/herboeken) zodat de
        # herboeking ze opnieuw registreert. Lazy imports: geen kring.
        from app.documenten import autoboeken as autoboeken_service
        from app.mini_voorraad import instroom as mini_voorraad_instroom
        from app.verplichting import match_pipeline as verplichting_match

        verplichting_match.draai_verbruik_terug_in_sessie(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor_id,
            reden=f"gecorrigeerd vanuit de module: {reden}",
        )
        if ctx["boek_cyclus"] is not None:
            mini_voorraad_instroom.registreer_storno(
                session,
                administratie_id=administratie_id,
                document_id=document_id,
                boek_cyclus=ctx["boek_cyclus"],
                actor_id=actor_id,
                reden=f"gecorrigeerd vanuit de module: {reden}",
            )
        autoboeken_service.reset_na_correctie_in_sessie(
            session, administratie_id=administratie_id, document_id=document_id, reden="correctie", actor_id=actor_id
        )
        webhook = False
        if soort in (DocumentSoort.INKOOPFACTUUR.value, DocumentSoort.VERKOOPFACTUUR.value) and oud_extern_id:
            webhook = _meld_gestorneerd_voor_vastgoed(
                session,
                administratie_id=administratie_id,
                document_id=document_id,
                rlz_document_id=uuid.UUID(oud_extern_id),
                reden=reden,
            )
        detail_corr["webhook_gestorneerd"] = webhook
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie=AUDIT_ACTIE,
            correlatie_id=uuid.uuid4(),
            oude_waarde={
                "status": DocumentStatus.GEBOEKT.value,
                "rlz_boekstuknummer": oud_boekstuknummer,
                "extern_id": oud_extern_id,
                "boek_cyclus": ctx["boek_cyclus"],
            },
            nieuwe_waarde={
                **detail_corr,
                "status": DocumentStatus.KLAAR_OM_TE_BOEKEN.value,
                "boek_cyclus": nieuwe_cyclus,
            },
            administratie_id=administratie_id,
        )

    return CorrigeerResultaat(
        document_id=document_id,
        status=DocumentStatus.KLAAR_OM_TE_BOEKEN,
        soort=soort,
        boek_cyclus=nieuwe_cyclus,
        oud_boekstuknummer=oud_boekstuknummer,
        oud_extern_id=oud_extern_id,
        gestorneerd=gestorneerd,
        al_concept=al_concept,
        doorbelasting_gestorneerd=len(doorbelasting_terug),
        doel_pad=review_pad(soort, administratie_id, document_id),
    )


def _markeer_omzet_half(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, reden: str
) -> None:
    """Kassarapport: memoriaal al terug, Receipt niet → de bestaande zichtbare foutstatus HALF_GEBOEKT (verkoop
    geboekt, memoriaal niet) op de registratierij, zodat de omzet-reconciliatie 'm meldt. Eigen transactie."""
    from app.omzet.models import OmzetBoeking, OmzetBoekingStatus

    try:
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            for rij in session.scalars(
                select(OmzetBoeking).where(
                    OmzetBoeking.document_id == document_id, OmzetBoeking.status == OmzetBoekingStatus.GEBOEKT.value
                )
            ):
                rij.status = OmzetBoekingStatus.HALF_GEBOEKT.value
                rij.half_geboekt_detail = {
                    "bron": "correctie",
                    "reden": f"correctie half gelukt (memoriaal terug, Receipt niet): {reden}",
                    "memoriaal_gestorneerd": True,
                    "verkoop_gestorneerd": False,
                    "tijdstip": datetime.now(UTC).isoformat(),
                }
    except Exception:  # noqa: BLE001
        logger.exception("HALF_GEBOEKT-markering ná mislukte correctie kon niet geschreven worden (%s)", document_id)


__all__ = [
    "AL_GECORRIGEERD_CODE",
    "AUDIT_ACTIE",
    "CORRIGEERBARE_SOORTEN",
    "MIN_REDEN_LENGTE",
    "AlGecorrigeerd",
    "Blokkade",
    "CorrigeerResultaat",
    "CorrigeerToets",
    "CorrigerenFout",
    "CorrigerenMislukt",
    "CorrigerenNietToegestaan",
    "GeenRlzCredentials",
    "corrigeer",
    "review_pad",
    "toets",
]
