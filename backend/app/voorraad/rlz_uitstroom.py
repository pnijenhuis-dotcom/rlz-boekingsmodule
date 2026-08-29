"""Voorraad-uitstroom uit RLZ-verkoopfacturen — dagelijkse LEESROUTE (opdracht 29-08 blok A; STAP-0
groen, api-verkenning "Voorraad-uitstroom STAP-0"; migratie 0087).

Universal Verkoop factureert in RLZ zelf (UI/import), niet via de app. Fase 1 las uitstroom alleen uit
in-app-geboekte verkoopdocumenten; deze module leest de regels van de EIGEN RLZ-verkoopfacturen van
elke voorraad-administratie en zet ze als feiten (`mi.voorraad_regel`, richting 'uit', bron
`rlz_verkoop`) in de feitenlaag — door dezelfde volautomatische normalisatie (onzeker-vlag) als de
instroom. STRIKT READ-ONLY tegen RLZ (uitsluitend GET's), nooit een write.

Bewezen RLZ-feiten waarop dit bouwt (29-08, Universal Verkoop, 84 facturen / 189 regels):
- regelveld `Quantity` altijd gevuld (nooit null/0 in de steekproef), `Price` per regel,
  `Quantity × Price = NetAmount` cent-exact op alle regels; géén eenheidsveld op de regel
  (alleen de lay-outvlag `ShowUOM`) → eenheid blijft leeg, de normalisatie levert 'm;
- creditfactuur (`IsCreditInvoice`): het TEKEN zit in `Quantity` (−30 × 65,00 = −1.950,00) — een
  retour is dus zonder extra omkering een negatieve uitstroom; vangnet voor de spiegelvorm
  (positief aantal × negatieve prijs) zit in `_aantal`;
- `Status` 1 = concept → niet tellen (én eerder geregistreerde regels van een intussen
  gestorneerde factuur verdwijnen); 2/3 = geboekt;
- `$filter=Date ge <iso>T00:00:00Z` (tijdzone-suffix verplicht), `$orderby=Date asc,id asc`,
  `$top/$skip`, `$expand=Entity` (debiteurnaam) werken op de SalesInvoices-collectie; de
  collectie ziet UI-/importfacturen (12.103 sinds 2020; 1.290 in 2026).

Cadans: meelopend in `sync-alles` (rlz-sync-job 07:00) incrementeel vanaf max(datum) − 14 dagen
(her-lezing vangt latere storno's/correcties; een afgebroken run hervat vanzelf), eerste run vanaf
1 januari van het lopende jaar; `--volledig` leest het jaar opnieuw. Dedupe met de app: een
RLZ-factuur die de app zelf boekte (`verkoop_boeking.verkoop_rlz_id`) wordt overgeslagen — die regels
staan al onder bron `verkoop_regel`."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, func, select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.rlz.client import RlzClient
from app.rlz.credentials import GeenRlzCredentials
from app.voorraad import normalisatie
from app.voorraad.models import VoorraadRegel

logger = logging.getLogger(__name__)

BRON = "rlz_verkoop"
GEBOEKT_STATUSSEN = {2, 3}
PAGINA = 200
HERLEES_VENSTER = timedelta(days=14)


@dataclass(frozen=True)
class RlzUitstroomTelling:
    vanaf: date | None
    facturen_gelezen: int = 0
    facturen_verwerkt: int = 0
    regels: int = 0
    overgeslagen_concept: int = 0
    overgeslagen_in_app: int = 0
    verwijderd_na_storno: int = 0

    def als_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["vanaf"] = self.vanaf.isoformat() if self.vanaf else None
        return d


def _dec(waarde: object) -> Decimal | None:
    if waarde is None or isinstance(waarde, bool):
        return None
    try:
        return Decimal(str(waarde))
    except InvalidOperation:
        return None


def _aantal(regel: dict[str, Any]) -> Decimal | None:
    """Quantity zoals RLZ 'm levert (teken inbegrepen — creditregels dragen een negatieve Quantity).
    Vangnet voor de spiegelvorm: negatief nettobedrag bij een positief aantal én negatieve prijs =
    retour uitgedrukt via de prijs → aantal negatief maken. Nooit gokken bij ontbrekende velden."""
    q = _dec(regel.get("Quantity"))
    if q is None:
        return None
    netto = _dec(regel.get("NetAmount"))
    prijs = _dec(regel.get("Price"))
    if netto is not None and netto < 0 and q > 0 and prijs is not None and prijs < 0:
        return -q
    return q


def _datum(kop: dict[str, Any]) -> date | None:
    for veld in ("Date", "BookDate"):
        waarde = kop.get(veld)
        if isinstance(waarde, str) and len(waarde) >= 10:
            try:
                return date.fromisoformat(waarde[:10])
            except ValueError:
                continue
    return None


def _debiteur(kop: dict[str, Any]) -> str | None:
    entity = kop.get("Entity")
    if isinstance(entity, dict):
        naam = entity.get("Name") or entity.get("SearchName")
        return str(naam) if naam else None
    return None


def _open_client(administratie_id: uuid.UUID, client: RlzClient | None) -> tuple[RlzClient, bool]:
    from app.sync.service import _open_client_indien_nodig

    return _open_client_indien_nodig(administratie_id, client)


def _vanaf_datum(administratie_id: uuid.UUID, *, volledig: bool) -> date:
    """Eerste run / volledig: 1 januari van het lopende jaar. Incrementeel: de jongste al
    geregistreerde factuurdatum minus het herlees-venster (een afgebroken run — gesorteerd op
    Date asc — hervat daarmee vanzelf; latere storno's/correcties binnen 14 dagen worden gezien)."""
    jaarstart = date(date.today().year, 1, 1)
    if volledig:
        return jaarstart
    with scoped_session(administratie_id) as session:
        laatste = session.scalar(
            select(func.max(VoorraadRegel.datum)).where(
                VoorraadRegel.administratie_id == administratie_id, VoorraadRegel.bron == BRON
            )
        )
    if laatste is None:
        return jaarstart
    return min(laatste - HERLEES_VENSTER, date.today())


def lees_koppen(client: RlzClient, *, vanaf: date) -> Iterator[dict[str, Any]]:
    """Gepagineerd door de SalesInvoices-collectie (nooit de volledige collectie in één request —
    les cijfers-sync 23-08). Alleen GET."""
    skip = 0
    while True:
        pagina = client.get(
            "SalesInvoices",
            params={
                "$filter": f"Date ge {vanaf.isoformat()}T00:00:00Z",
                "$orderby": "Date asc,id asc",
                "$top": str(PAGINA),
                "$skip": str(skip),
                "$expand": "Entity",
            },
        ).get("value", [])
        yield from pagina
        if len(pagina) < PAGINA:
            return
        skip += PAGINA


def lees_regels(client: RlzClient, factuur_id: str) -> list[dict[str, Any]]:
    regels = client.get(f"SalesInvoices/{factuur_id}/Lines").get("value", [])
    return sorted(regels, key=lambda r: (r.get("Sequence") is None, r.get("Sequence") or 0))


def _in_app_geboekte_rlz_ids(administratie_id: uuid.UUID) -> set[uuid.UUID]:
    from app.verkoop.models import VerkoopBoeking

    with scoped_session(administratie_id) as session:
        return set(
            session.scalars(
                select(VerkoopBoeking.verkoop_rlz_id).where(VerkoopBoeking.administratie_id == administratie_id)
            )
        )


def _verwijder_factuur(administratie_id: uuid.UUID, rlz_document_id: uuid.UUID) -> int:
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        resultaat = session.execute(
            delete(VoorraadRegel).where(
                VoorraadRegel.administratie_id == administratie_id,
                VoorraadRegel.rlz_document_id == rlz_document_id,
            )
        )
        return int(resultaat.rowcount or 0)


def registreer_rlz_factuur(
    *, administratie_id: uuid.UUID, kop: dict[str, Any], regels: list[dict[str, Any]]
) -> int:
    """Eén geboekte RLZ-verkoopfactuur → haar regels als 'uit'-feiten (bron rlz_verkoop), vervangen
    per factuur (idempotent). Normalisatie via dezelfde motor als de instroom (leverancier = onze
    eigen verkoop → sentinel). Geeft het aantal regels terug."""
    rlz_id = uuid.UUID(str(kop["id"]))
    datum = _datum(kop)
    if datum is None:
        raise ValueError(f"RLZ-factuur {rlz_id} zonder bruikbare Date/BookDate")
    referentie = kop.get("Reference") or (str(kop["InvoiceNumber"]) if kop.get("InvoiceNumber") else None)
    debiteur = _debiteur(kop)
    bruikbaar = [r for r in regels if str(r.get("Description") or "").strip()]
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        normalisaties = normalisatie.normaliseer_regels(
            session,
            administratie_id=administratie_id,
            document_id=None,
            regels=[(str(r["Description"]).strip(), None, None) for r in bruikbaar],
        )
        nieuwe: list[VoorraadRegel] = []
        for volgnummer, (r, n) in enumerate(zip(bruikbaar, normalisaties, strict=True), start=1):
            nieuwe.append(
                VoorraadRegel(
                    administratie_id=administratie_id,
                    document_id=None,
                    rlz_document_id=rlz_id,
                    rlz_referentie=str(referentie) if referentie else None,
                    richting="uit",
                    bron=BRON,
                    datum=datum,
                    vendor_id=None,
                    relatie_naam=debiteur,
                    regel_volgnummer=volgnummer,
                    artikeltekst=str(r["Description"]).strip()[:500],
                    aantal=_aantal(r),
                    eenheid=None,
                    prijs=_dec(r.get("Price")),
                    netto_bedrag=_dec(r.get("NetAmount")),
                    artikelgroep_id=n.artikelgroep_id,
                    normalisatie_status=n.status,
                    normalisatie_zekerheid=n.zekerheid,
                )
            )
        session.execute(
            delete(VoorraadRegel).where(
                VoorraadRegel.administratie_id == administratie_id, VoorraadRegel.rlz_document_id == rlz_id
            )
        )
        for rij in nieuwe:
            session.add(rij)
        return len(nieuwe)


def sync_rlz_verkoopregels(
    *, administratie_id: uuid.UUID, client: RlzClient | None = None, volledig: bool = False
) -> RlzUitstroomTelling:
    """De leesroute voor één administratie. Opt-in uit = niets (stil, zoals elke opt-in). Per factuur
    één transactie: een fout halverwege laat de al verwerkte facturen staan en de volgende run hervat
    vanaf max(datum) − venster. Audit per run (systeem-actor)."""
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not administratie.voorraad_ingeschakeld:
            return RlzUitstroomTelling(vanaf=None)
    vanaf = _vanaf_datum(administratie_id, volledig=volledig)
    in_app = _in_app_geboekte_rlz_ids(administratie_id)
    rlz, eigen_client = _open_client(administratie_id, client)
    gelezen = verwerkt = regels = concept = in_app_n = verwijderd = 0
    try:
        for kop in lees_koppen(rlz, vanaf=vanaf):
            gelezen += 1
            rlz_id = uuid.UUID(str(kop["id"]))
            if rlz_id in in_app:
                in_app_n += 1
                continue
            if int(kop.get("Status") or 0) not in GEBOEKT_STATUSSEN:
                concept += 1
                verwijderd += _verwijder_factuur(administratie_id, rlz_id)
                continue
            regels += registreer_rlz_factuur(
                administratie_id=administratie_id, kop=kop, regels=lees_regels(rlz, str(kop["id"]))
            )
            verwerkt += 1
    finally:
        if eigen_client:
            rlz.close()
    telling = RlzUitstroomTelling(
        vanaf=vanaf,
        facturen_gelezen=gelezen,
        facturen_verwerkt=verwerkt,
        regels=regels,
        overgeslagen_concept=concept,
        overgeslagen_in_app=in_app_n,
        verwijderd_na_storno=verwijderd,
    )
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="mi",
            tabel="voorraad_regel",
            record_id=administratie_id,
            actie="voorraad_rlz_uitstroom_gesynct",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={**telling.als_dict(), "volledig": volledig},
            administratie_id=administratie_id,
        )
    return telling


def hernormaliseer_rlz_regels(*, administratie_id: uuid.UUID) -> int:
    """"⟳ Verversen"-deel voor de RLZ-bron: de opgeslagen RLZ-regels opnieuw door de normalisatie
    (bekende teksten deterministisch, nieuwe via de AI-gates) — zónder RLZ-calls, zodat de UI-knop
    nooit op een lange RLZ-lees-lus wacht (504-les 23-08). Het lezen zelf hoort bij de dagelijkse sync
    of `voorraad-rlz-sync`."""
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        rijen = list(
            session.scalars(
                select(VoorraadRegel)
                .where(VoorraadRegel.administratie_id == administratie_id, VoorraadRegel.bron == BRON)
                .order_by(VoorraadRegel.datum, VoorraadRegel.regel_volgnummer)
            )
        )
        if not rijen:
            return 0
        normalisaties = normalisatie.normaliseer_regels(
            session,
            administratie_id=administratie_id,
            document_id=None,
            regels=[(r.artikeltekst, None, None) for r in rijen],
        )
        for r, n in zip(rijen, normalisaties, strict=True):
            r.artikelgroep_id = n.artikelgroep_id
            r.normalisatie_status = n.status
            r.normalisatie_zekerheid = n.zekerheid
        return len(rijen)


def sync_alle_voorraad_administraties(
    *, volledig: bool = False
) -> dict[uuid.UUID, RlzUitstroomTelling | GeenRlzCredentials | str]:
    """Voor élke administratie mét de voorraad-opt-in (sync-alles-patroon): één kapotte administratie
    laat de rest niet stuklopen; geen credential = zichtbaar overgeslagen, geen fout."""
    with scoped_session(None) as session:
        ids = [
            a.id for a in session.scalars(select(Administratie).where(Administratie.voorraad_ingeschakeld.is_(True)))
        ]
    resultaten: dict[uuid.UUID, RlzUitstroomTelling | GeenRlzCredentials | str] = {}
    for administratie_id in ids:
        try:
            resultaten[administratie_id] = sync_rlz_verkoopregels(administratie_id=administratie_id, volledig=volledig)
        except GeenRlzCredentials as exc:
            resultaten[administratie_id] = exc
        except Exception as exc:  # noqa: BLE001 — bewust breed: één administratie mag de rest niet raken
            logger.exception("Voorraad-RLZ-uitstroom mislukt voor %s", administratie_id)
            resultaten[administratie_id] = str(exc)
    return resultaten
