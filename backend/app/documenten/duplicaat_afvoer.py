"""Duplicaat-afvoer — duplicaten automatisch uit de werklijst (medewerker-wens, besluit Peter 04-09; HERZIEN
07-09, besluit Peter: "duplicaten eruit, hoef ik niet in een lijst te zien; moet er toch een geboekt worden, dan zoek
ik hem in het archief"). Kernprincipe 7 "minimale mens, maximale autonomie": signalering zonder handeling is niet af.

Bij een HARDE duplicaat-match voert het systeem een inkoopfactuur af naar Afgewezen met reden
"Duplicaat van ‹referentie› (…)" — mét persistente kruisverwijzing naar het origineel (beide kanten
zichtbaar), audit en tijdlijn. Nooit verwijderen, nooit stil; terughalen = de bestaande heropenen-route
(Archief › filter "Afgevoerd als duplicaat" → "Terug naar werkvoorraad").

HARDE MATCH sinds 07-09 = de module-motor `app/documenten/duplicaat_module.py` (één verzameling per administratie,
dezelfde motor als de harde check "Duplicaat (module)" en de backfill-CLI):
  (a) zelfde sha256 van het bestand;
  (b) zelfde genormaliseerde referentie (`normaliseer_referentie` — de ENIGE normalisatie: hoofdletters, witruimte,
      leestekens, voorloopnullen, voorvoegsels factuur/factuurnr/factuurnummer/inv/invoice/nr/no/#) + totaalbedrag
      cent-exact, over ÁLLE crediteur-records (herziet 04-09 "alleen zelfde crediteur op btw-nummer": referentie +
      bedrag bij een andere crediteur-record was een zacht signaal en is nu een hard duplicaat);
  plus (ongewijzigd) een gecachete RLZ-/Odoo-treffer van `duplicaatsignaal.py` (origineel geboekt buiten de app).
Categorie (c) van de motor — zelfde crediteur + referentie bij een ANDER bedrag — voert NOOIT automatisch af: die
blijft als vlag `mogelijk_duplicaat_van_id` op de Mogelijk-duplicaat-tab (mens kijkt: deelfactuur? creditnota?).
UBL-XML + PDF van dezelfde factuur is een BUNDEL, geen duplicaat (`duplicaat_module.is_bundelpaar`) en wordt nooit
afgevoerd. Een mens-afmelding "Geen duplicaat" (`duplicaat_module.meld_af`, reden verplicht) wordt gerespecteerd.

Wie is het origineel binnen zo'n groep? Deterministisch: eerst een in de app GEBOEKT document (oudste — geboekt wint
altijd, ook als het jonger is), dan een RLZ-/Odoo-treffer zónder app-document, dan het document waarop al een
boekpoging liep (boeken_mislukt / wacht_op_iban_accordering), dan het document bij de klant-accordeur
(ter_accordering), dan het document met een open vraag (vraag_open), dan het OUDSTE (`aangemaakt_op`, daarna id).
Alle andere groepsleden in een afvoerbare status zijn duplicaten — SINDS BLOK A2 04-09 (besluit Peter "geen
dubbeling") óók een document dat bij de klant-accordeur ligt of een open vraag draagt: de lopende
accorderingsronde wordt dan INGETROKKEN mét reden "afgevoerd als duplicaat van ‹ref›" (bestaand
vervallen-patroon, `accordering.service.laat_ronde_vervallen_bij_duplicaat`) en élke open vraag wordt
zichtbaar GESLOTEN met dezelfde reden als slotbericht in de thread (`vragen.sluit_vraag_wegens_duplicaat`),
alles in tijdlijn + audit — nooit stil. Alleen boeken_mislukt / wacht_op_iban_accordering (er liep al een
boekpoging) en geboekt worden nooit automatisch afgevoerd.

Drie ingangen, één motor (`_voer_af`):
- automatisch (`verwerk_na_signaal_stil`, post-commit ná `bereken_duplicaatsignaal`; en de backfill-CLI
  `duplicaten-backfill`): STANDAARD AAN voor de hele module (blok A1 04-09) achter één platformbrede noodrem
  `platform.duplicaat_afvoer_instelling` (Beheerder, Instellingen › Boeken, `make duplicaat-autoafvoer-uit`);
  systeem-actor; elke poging geauditeerd (`duplicaat_afgevoerd` / `duplicaat_afvoer_geweigerd` + reden). De
  volumerem `max_duplicaat_afvoer_per_dag_per_administratie` geldt sinds 07-09 ALLEEN nog voor twijfelgevallen —
  een origineel dat uitsluitend uit de RLZ-cache komt (kan verouderd zijn); een module-match (a)/(b) met een
  app-document als origineel gaat DIRECT, buiten de rem. De per-administratie-opt-in van 0105 is vervallen
  (kolom blijft staan, wordt niet meer gelezen);
- één-klik (`voer_af_als_duplicaat`, altijd — ook mét de noodrem aan) en bulk (B2): actor = de mens,
  `automatisch=False`, idempotent (al afgevoerd = zelfde data terug), 409 zonder harde match of bij een status die het
  niet toelaat.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie, DuplicaatAfvoerInstelling
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import afwijzen, duplicaat_module, vragen
from app.documenten.models import (
    Afwijzing,
    AfwijzingStatus,
    Boekvoorstel,
    Document,
    DocumentGebeurtenis,
    DocumentSoort,
    DocumentStatus,
    DuplicaatSignaal,
    DuplicaatSignaalUitkomst,
)
from app.documenten.rlz_ids import rlz_herboeking_id
from app.documenten.statusmachine import OngeldigeStatusovergang
from app.documenten.vragen import ToegewezeneBuitenScope

logger = logging.getLogger(__name__)

# Statussen waaruit een duplicaat automatisch óf met één klik afgevoerd mag worden. De drie herstelbare
# herkomsten van afwijzen.py (heropenen keert er naar terug) plús — blok A2 04-09, besluit Peter "geen
# dubbeling" — ter_accordering en vraag_open: die worden vóór de afwijzing netjes afgewikkeld (ronde
# ingetrokken, vraag gesloten, beide mét reden) zodat de herkomst-status voor heropenen weer een van de drie
# is. Nooit geboekt, boeken_mislukt of wacht_op_iban_accordering (er liep al een boekpoging).
AFVOERBARE_STATUSSEN = frozenset(
    {
        DocumentStatus.TE_CONTROLEREN,
        DocumentStatus.HANDMATIG_AFMAKEN,
        DocumentStatus.KLAAR_OM_TE_BOEKEN,
        DocumentStatus.TER_ACCORDERING,
        DocumentStatus.VRAAG_OPEN,
    }
)

# Statussen die een app-document uitsluiten als origineel én als duplicaat: het bestaat niet (meer) als
# zelfstandig werkstuk. Afgewezen hoort erbij: een al afgevoerd/afgewezen document is geen origineel
# meer (anders zou een heropend origineel nooit terugkomen). Afgevoerd_duplicaat idem sinds blok 3
# (fixrun 08-09, eigen terminale status i.p.v. een afwijzen-substatus).
_UITGESLOTEN_STATUSSEN = frozenset(
    {
        DocumentStatus.VERWIJDERD,
        DocumentStatus.GESPLITST,
        DocumentStatus.SAMENGEVOEGD,
        DocumentStatus.AFGEWEZEN,
        DocumentStatus.AFGEVOERD_DUPLICAAT,
        DocumentStatus.NIET_TOEGEWEZEN,
    }
)

# Rangorde "wie is het origineel": lager = eerder origineel. Geboekt wint altijd; daarna het document waarop
# al een boekpoging liep; dan het document bij de klant-accordeur (ronde intrekken is duurder dan een
# te_controleren-exemplaar afvoeren); dan het document met een open vraag; dan de rest op leeftijd. Binnen
# één rang wint een GEBUNDELD document (UBL + PDF-beeld) van een los exemplaar, daarna het oudste (blok D 07-09).
# Sinds blok A2 zijn rang 2 en 3 wél afvoerbaar als er een hoger origineel is.
_STATUS_RANG: dict[DocumentStatus, int] = {
    DocumentStatus.GEBOEKT: 0,
    DocumentStatus.BOEKEN_MISLUKT: 1,
    DocumentStatus.WACHT_OP_IBAN_ACCORDERING: 1,
    DocumentStatus.TER_ACCORDERING: 2,
    DocumentStatus.VRAAG_OPEN: 3,
}
_RANG_OVERIG = 4

# RLZ kapt Reference op 30 tekens — alleen nog relevant voor de RLZ-leesroute, niet voor de module-match.
_REFERENTIE_MAX = 30

# Gangbare voorvoegsels die leveranciers vóór hun factuurnummer zetten — verschijnen in de ene extractie wél en in de
# andere niet ("Factuur 2026-0042" vs "2026-0042"). Langste eerst, zodat "factuurnummer" niet als "factuur" + "nummer"
# wordt gelezen. Alleen aan het BEGIN van de referentie, alleen als er iets na komt.
_REFERENTIE_VOORVOEGSELS = (
    "factuurnummer",
    "factuurnr",
    "factuur",
    "invoice",
    "inv",
    "nr",
    "no",
)
_VOORVOEGSEL_PATROON = re.compile(
    r"^(?:(?:" + "|".join(_REFERENTIE_VOORVOEGSELS) + r")\b\s*[.:#\-]?\s*|#\s*)+",
    re.IGNORECASE,
)
_NIET_ALFANUMERIEK = re.compile(r"[^0-9a-z]+")


class DuplicaatAfvoerFout(Exception):
    """Basis voor domeinfouten in de duplicaat-afvoer (router → 409 mét de tekst)."""


class GeenHardeMatch(DuplicaatAfvoerFout):
    """Geen (actuele) harde duplicaat-match voor dit document — of dit document is zélf het origineel."""


class AfvoerNietMogelijk(DuplicaatAfvoerFout):
    """De status van het document laat afvoeren niet toe (ter accordering, geboekt, open vraag, al
    afgewezen om een andere reden, …)."""


def normaliseer_referentie(referentie: str | None) -> str | None:
    """DE vergelijkingsvorm van een factuurreferentie — één functie voor de harde check "Duplicaat (module)",
    de auto-afvoer, de bulk-afvoer en de backfill (besluit Peter 07-09: nooit twee normalisaties naast elkaar).

    Stappen (deterministisch, geen AI): (1) hoofdletterongevoelig; (2) gangbare voorvoegsels vooraan weg —
    factuur / factuurnr / factuurnummer / inv / invoice / nr / no / "#", ook gecombineerd ("Factuur nr. 42");
    (3) alle leestekens en witruimte weg — alleen letters en cijfers blijven; (4) voorloopnullen weg per
    cijfergroep zoals die in de oorspronkelijke tekst gescheiden stond ("2026-0042" ≡ "2026-42" ≡ "F 2026 0042"
    → "202642"; een aaneengesloten "20260042" blijft "20260042" — een scheidingsteken weglaten is géén gangbare
    variant, cijfers weglaten wel). Leeg ná normalisatie (bv. alleen "#") = None = niet toetsbaar.

    Bewust NIET meer afgekapt op 30 tekens: de match loopt tegen onze eigen database, RLZ's Reference-lengte is
    daar irrelevant (de RLZ-leesroute kapt zelf, zie `RlzClient.find_purchase_invoices_by_reference`)."""
    if not referentie:
        return None
    tekst = referentie.strip().lower()
    tekst = _VOORVOEGSEL_PATROON.sub("", tekst)
    if not tekst:
        # Alleen een voorvoegsel ("Factuur") is geen referentie; maar een kale "#42" is er wél één.
        return None
    tokens = [t for t in _NIET_ALFANUMERIEK.split(tekst) if t]
    delen: list[str] = []
    for token in tokens:
        if token.isdigit():
            token = token.lstrip("0") or "0"
        delen.append(token)
    schoon = "".join(delen)
    return schoon or None


@dataclass(frozen=True)
class Origineel:
    """Het origineel waarvan een document een duplicaat is — genoeg voor de reden-tekst, de
    kruisverwijzing en de UI (nooit een kale UUID zonder leesbare aanduiding)."""

    bron: str  # 'geboekt' (RLZ/Odoo of in de app geboekt) | 'werkvoorraad' (ouder app-document)
    referentie: str
    document_id: uuid.UUID | None = None
    rlz_document_id: uuid.UUID | None = None
    boekstuknummer: str | None = None
    bestandsnaam: str | None = None
    aangemaakt_op: datetime | None = None
    status: str | None = None

    def reden(self) -> str:
        """Deterministische afwijsreden — 'Duplicaat van ‹referentie› (…)'."""
        if self.document_id is not None and self.bestandsnaam:
            datum = f" van {self.aangemaakt_op.date().isoformat()}" if self.aangemaakt_op else ""
            if self.bron == "geboekt":
                boekstuk = f"boekstuk {self.boekstuknummer} / " if self.boekstuknummer else ""
                return f"Duplicaat van {self.referentie} ({boekstuk}document {self.bestandsnaam}{datum}, al geboekt)"
            return f"Duplicaat van {self.referentie} (document {self.bestandsnaam}{datum} in de werkvoorraad)"
        boekstuk = f"boekstuk {self.boekstuknummer}" if self.boekstuknummer else "al geboekt in de boekhouding"
        return f"Duplicaat van {self.referentie} ({boekstuk})"


@dataclass(frozen=True)
class _Lid:
    document_id: uuid.UUID
    status: DocumentStatus
    bestandsnaam: str
    aangemaakt_op: datetime
    vendor_id: uuid.UUID | None
    referentie: str | None
    totaalbedrag: Decimal | None
    #: Gebundeld document (UBL-data + PDF-beeld): wint binnen dezelfde status-rang van een los exemplaar (blok D).
    heeft_beeld: bool = False


@dataclass(frozen=True)
class Groep:
    """Eén duplicaatgroep rond een document: het origineel + de leden die afgevoerd mogen worden. `hard` = de groep
    rust op een module-match (a)/(b) met een app-document als origineel (07-09: direct afvoeren, buiten de rem);
    False = uitsluitend een gecachete RLZ-/Odoo-treffer (twijfelgeval: rem blijft gelden)."""

    origineel: Origineel
    duplicaten: list[_Lid]
    hard: bool = True


@dataclass(frozen=True)
class AfgevoerdDuplicaat:
    """Origineel-kant van de kruisverwijzing: één afgevoerd duplicaat van dít document."""

    afwijzing_id: uuid.UUID
    document_id: uuid.UUID
    bestandsnaam: str
    aangemaakt_op: datetime
    referentie: str | None
    automatisch: bool
    afgewezen_op: datetime
    afgewezen_door: uuid.UUID


@dataclass(frozen=True)
class DuplicaatAfvoerStand:
    """Wat het controlescherm nodig heeft: kandidaat (knop + bevestiging), de eigen afvoer (afgevoerd-
    kant) en de afgevoerde duplicaten (origineel-kant)."""

    kandidaat: Origineel | None
    afgevoerd_als_duplicaat_van: Origineel | None
    afgevoerde_duplicaten: list[AfgevoerdDuplicaat]
    # 07-09: álle module-tegenhangers (a/b/c, niet afgemeld) + de laatste mens-afmelding "Geen duplicaat".
    module_treffers: list[duplicaat_module.Treffer] = field(default_factory=list)
    afmelding: duplicaat_module.Afmelding | None = None


@dataclass(frozen=True)
class AfvoerResultaat:
    afwijzing: afwijzen.AfwijzingData
    origineel: Origineel
    al_afgevoerd: bool


# ----------------------------------------------------------------------------- groepsbepaling (module-motor 07-09)


def _vendor_sleutel(vendor_id: uuid.UUID | None, btw: dict[str, str]) -> str | None:
    """Crediteur-identiteit op btw-nummer (anders de vendor zelf) — sinds 07-09 alleen nog gebruikt door
    `duplicaat_historie.py` (RLZ-era-historie ná een Odoo-overstap) en `verplichting/match_pipeline.py`; de
    module-motor zelf werkt met `duplicaat_module.Verzameling.identiteit` (vendor/voorkeur + btw + KvK)."""
    if vendor_id is None:
        return None
    nummer = btw.get(str(vendor_id))
    return f"btw:{nummer}" if nummer else f"vendor:{vendor_id}"


def _lid_uit_kop(kop: duplicaat_module.Kop) -> _Lid:
    return _Lid(
        document_id=kop.document_id,
        status=kop.status,
        bestandsnaam=kop.bestandsnaam,
        aangemaakt_op=kop.aangemaakt_op,
        vendor_id=kop.vendor_id,
        referentie=kop.referentie,
        totaalbedrag=kop.totaalbedrag,
        heeft_beeld=kop.heeft_beeld,
    )


def _referentie_label(kop_of_lid: duplicaat_module.Kop | _Lid) -> str:
    """Leesbare aanduiding in de afwijsreden/chip: de referentie, of bij een kale bestandsmatch (sha256 zonder kop)
    het bestand zelf — nooit een lege string."""
    return kop_of_lid.referentie or f"bestand {kop_of_lid.bestandsnaam}"


def _rang(lid: _Lid) -> tuple[int, int, datetime, str]:
    """Rangorde origineel: status-rang, dan GEBUNDELD vóór los (blok D 07-09, regel Peter: het losse PDF-exemplaar is
    het duplicaat van de al gebundelde factuur — ook als het toevallig ouder is), dan het oudste, dan id."""
    gebundeld_eerst = 0 if lid.heeft_beeld else 1
    return (_STATUS_RANG.get(lid.status, _RANG_OVERIG), gebundeld_eerst, lid.aangemaakt_op, str(lid.document_id))


def _rlz_treffers(session: Session, document_id: uuid.UUID) -> list[dict]:
    rij = session.get(DuplicaatSignaal, document_id)
    if rij is None or rij.uitkomst != DuplicaatSignaalUitkomst.MOGELIJK_DUPLICAAT.value:
        return []
    return list(rij.treffers or [])


def _als_uuid(waarde: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(waarde)) if waarde else None
    except ValueError:
        return None


def _origineel_uit_geboekt_lid(session: Session, lid: _Lid, treffers: list[dict]) -> Origineel:
    """In de app geboekt origineel: koppel het RLZ-/Odoo-id (uit de treffers als die er zijn, anders het
    deterministische herboek-GUID) en het boekstuknummer uit het boekvoorstel."""
    voorstel = session.get(Boekvoorstel, lid.document_id)
    cyclus = voorstel.boek_cyclus if voorstel is not None else 0
    eigen_ids = {str(rlz_herboeking_id(lid.document_id, c)) for c in range(cyclus + 1)}
    treffer = next((t for t in treffers if str(t.get("id")) in eigen_ids), None)
    rlz_id = _als_uuid(treffer.get("id")) if treffer else rlz_herboeking_id(lid.document_id, cyclus)
    boekstuk = (voorstel.rlz_boekstuknummer if voorstel is not None else None) or (
        treffer.get("invoice_number") if treffer else None
    )
    return Origineel(
        bron="geboekt",
        referentie=_referentie_label(lid),
        document_id=lid.document_id,
        rlz_document_id=rlz_id,
        boekstuknummer=boekstuk,
        bestandsnaam=lid.bestandsnaam,
        aangemaakt_op=lid.aangemaakt_op,
        status=lid.status.value,
    )


def _origineel_uit_historie_treffer(session: Session, t: dict, referentie: str) -> Origineel | None:
    """Odoo-slotstuk 04-09: een treffer uit de eigen RLZ-era-historie (`duplicaat_historie.py`, bron
    `app_historie`) ís een app-document — koppel het als volwaardig geboekt origineel (bestandsnaam, datum,
    boekstuk), ook als dat document zelf geen duplicaat_signaal-kop (meer) heeft."""
    if t.get("bron") != "app_historie":
        return None
    document_id = _als_uuid(t.get("document_id"))
    document = session.get(Document, document_id) if document_id is not None else None
    if document is None:
        return None
    voorstel = session.get(Boekvoorstel, document.id)
    return Origineel(
        bron="geboekt",
        referentie=str(t.get("reference") or referentie),
        document_id=document.id,
        rlz_document_id=_als_uuid(t.get("id")),
        boekstuknummer=(voorstel.rlz_boekstuknummer if voorstel is not None else None)
        or (str(t["invoice_number"]) if t.get("invoice_number") else None),
        bestandsnaam=document.bestandsnaam,
        aangemaakt_op=document.aangemaakt_op,
        status=document.status.value,
    )


def _bepaal_origineel(session: Session, *, groep: list[_Lid], treffers: list[dict], referentie: str) -> Origineel:
    geboekt = sorted((lid for lid in groep if lid.status == DocumentStatus.GEBOEKT), key=_rang)
    if geboekt:
        return _origineel_uit_geboekt_lid(session, geboekt[0], treffers)
    if treffers:
        t = treffers[0]
        uit_historie = _origineel_uit_historie_treffer(session, t, referentie)
        if uit_historie is not None:
            return uit_historie
        return Origineel(
            bron="geboekt",
            referentie=str(t.get("reference") or referentie),
            rlz_document_id=_als_uuid(t.get("id")),
            boekstuknummer=(str(t["invoice_number"]) if t.get("invoice_number") else None),
        )
    eerste = sorted(groep, key=_rang)[0]
    return Origineel(
        bron="werkvoorraad",
        referentie=_referentie_label(eerste),
        document_id=eerste.document_id,
        bestandsnaam=eerste.bestandsnaam,
        aangemaakt_op=eerste.aangemaakt_op,
        status=eerste.status.value,
    )


def _leden_rond(
    verzameling: duplicaat_module.Verzameling, eigen: duplicaat_module.Kop
) -> tuple[list[_Lid], list[duplicaat_module.Treffer]]:
    """Het document + zijn module-tegenhangers in de AFVOER-categorieën (a)/(b); (c) en afgemelde paren en
    UBL+PDF-bundelparen zitten er per definitie niet in."""
    treffers = [t for t in verzameling.treffers_voor(eigen) if t.categorie in duplicaat_module.AFVOER_CATEGORIEEN]
    leden = [_lid_uit_kop(eigen)]
    for t in treffers:
        kop = verzameling.kop(t.document_id)
        if kop is not None:
            leden.append(_lid_uit_kop(kop))
    return leden, treffers


def bepaal_groep(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    verzameling: duplicaat_module.Verzameling | None = None,
) -> Groep | None:
    """De duplicaatgroep rond één document, of None als het document niet toetsbaar is (uitgesloten status, geen
    inkoopfactuur) of geen harde match heeft. Sessie van de aanroeper, al gescoopt op de administratie; een
    aanroeper die veel documenten langsloopt (backfill, lijst) geeft één geladen `verzameling` door."""
    if verzameling is None:
        verzameling = duplicaat_module.laad_verzameling(session, administratie_id=administratie_id)
    eigen = verzameling.kop(document_id)
    if eigen is None:
        return None
    leden, module_treffers = _leden_rond(verzameling, eigen)
    treffers = _rlz_treffers(session, document_id)
    if len(leden) < 2 and not treffers:
        return None
    origineel = _bepaal_origineel(session, groep=leden, treffers=treffers, referentie=_referentie_label(eigen))

    def _is_duplicaat_van_origineel(lid: _Lid) -> bool:
        """Een lid gaat alleen af als het óók een echte (a)/(b)-match van het GEKOZEN origineel is — nooit een
        UBL+PDF-bundelpartner van dat origineel of een afgemeld paar (de groep is een ster rond `eigen`; een derde
        exemplaar mag het bundelpaar van een ander niet uit elkaar trekken)."""
        if origineel.document_id is None:
            return True  # RLZ-/Odoo-origineel zonder app-document: alle leden zijn matches van `eigen`
        kop_lid = verzameling.kop(lid.document_id)
        kop_origineel = verzameling.kop(origineel.document_id)
        if kop_lid is None or kop_origineel is None:
            return True
        if verzameling.afgemeld(lid.document_id, origineel.document_id):
            return False
        categorie = duplicaat_module.categorie_van(kop_lid, kop_origineel, verzameling)
        return categorie in duplicaat_module.AFVOER_CATEGORIEEN

    duplicaten = sorted(
        (
            lid
            for lid in leden
            if lid.document_id != origineel.document_id
            and lid.status in AFVOERBARE_STATUSSEN
            and _is_duplicaat_van_origineel(lid)
        ),
        key=_rang,
    )
    return Groep(origineel=origineel, duplicaten=duplicaten, hard=bool(module_treffers))


def werkvoorraad_matches_bulk(
    *, administratie_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Origineel]:
    """Lijst-lezer (geen N+1): per document dat níét het origineel van zijn groep is, het origineel binnen
    de werkvoorraad/app (RLZ-treffers lopen al via de duplicaatsignaal-chip). Alleen module-matches (a)/(b)."""
    if not document_ids:
        return {}
    with scoped_session(administratie_id) as session:
        verzameling = duplicaat_module.laad_verzameling(session, administratie_id=administratie_id)
        resultaat: dict[uuid.UUID, Origineel] = {}
        for document_id in set(document_ids):
            eigen = verzameling.kop(document_id)
            if eigen is None:
                continue
            leden, _ = _leden_rond(verzameling, eigen)
            if len(leden) < 2:
                continue
            origineel = _bepaal_origineel(session, groep=leden, treffers=[], referentie=_referentie_label(eigen))
            if origineel.document_id != document_id:
                resultaat[document_id] = origineel
        return resultaat


# ----------------------------------------------------------------------------- lezen (UI)


def _origineel_uit_afwijzing(session: Session, afwijzing: Afwijzing) -> Origineel | None:
    if not (
        afwijzing.duplicaat_van_document_id
        or afwijzing.duplicaat_van_rlz_document_id
        or afwijzing.duplicaat_van_referentie
    ):
        return None
    document = (
        session.get(Document, afwijzing.duplicaat_van_document_id) if afwijzing.duplicaat_van_document_id else None
    )
    voorstel = session.get(Boekvoorstel, document.id) if document is not None else None
    return Origineel(
        bron="geboekt" if (document is None or document.status == DocumentStatus.GEBOEKT) else "werkvoorraad",
        referentie=afwijzing.duplicaat_van_referentie or "",
        document_id=afwijzing.duplicaat_van_document_id,
        rlz_document_id=afwijzing.duplicaat_van_rlz_document_id,
        boekstuknummer=voorstel.rlz_boekstuknummer if voorstel is not None else None,
        bestandsnaam=document.bestandsnaam if document is not None else None,
        aangemaakt_op=document.aangemaakt_op if document is not None else None,
        status=document.status.value if document is not None else None,
    )


def afgevoerde_duplicaten_van(session: Session, *, document_id: uuid.UUID) -> list[AfgevoerdDuplicaat]:
    """Origineel-kant: alle OPEN afwijzingen die naar dít document verwijzen (heropend = niet meer
    'afgevoerd', de historie blijft in de rij staan)."""
    rijen = session.execute(
        select(Afwijzing, Document)
        .join(Document, Afwijzing.document_id == Document.id)
        .where(
            Afwijzing.duplicaat_van_document_id == document_id,
            Afwijzing.status == AfwijzingStatus.OPEN.value,
        )
        .order_by(Afwijzing.afgewezen_op)
    ).all()
    return [
        AfgevoerdDuplicaat(
            afwijzing_id=a.id,
            document_id=d.id,
            bestandsnaam=d.bestandsnaam,
            aangemaakt_op=d.aangemaakt_op,
            referentie=a.duplicaat_van_referentie,
            automatisch=bool(a.automatisch),
            afgewezen_op=a.afgewezen_op,
            afgewezen_door=a.afgewezen_door,
        )
        for a, d in rijen
    ]


def _open_afwijzing(session: Session, document_id: uuid.UUID) -> Afwijzing | None:
    return session.scalars(
        select(Afwijzing).where(Afwijzing.document_id == document_id, Afwijzing.status == AfwijzingStatus.OPEN.value)
    ).first()


def stand_voor_document(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> DuplicaatAfvoerStand:
    """Voedt het controlescherm; geen RLZ-/Odoo-calls (alleen cache + DB)."""
    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.administratie_id != administratie_id:
            return DuplicaatAfvoerStand(kandidaat=None, afgevoerd_als_duplicaat_van=None, afgevoerde_duplicaten=[])
        kandidaat: Origineel | None = None
        module_treffers: list[duplicaat_module.Treffer] = []
        verzameling: duplicaat_module.Verzameling | None = None
        if document.soort == DocumentSoort.INKOOPFACTUUR.value and document.status not in _UITGESLOTEN_STATUSSEN:
            verzameling = duplicaat_module.laad_verzameling(session, administratie_id=administratie_id)
            eigen = verzameling.kop(document_id)
            module_treffers = verzameling.treffers_voor(eigen) if eigen is not None else []
        if document.status in AFVOERBARE_STATUSSEN and document.soort == DocumentSoort.INKOOPFACTUUR.value:
            groep = bepaal_groep(
                session, administratie_id=administratie_id, document_id=document_id, verzameling=verzameling
            )
            if groep is not None and any(lid.document_id == document_id for lid in groep.duplicaten):
                kandidaat = groep.origineel
        afgevoerd_van: Origineel | None = None
        # Blok 3 (fixrun 08-09): de eigen status; AFGEWEZEN blijft als terugval voor niet-gebackfilde
        # legacy-rijen (vóór deze deploy geschreven) die nog met een kruisverwijzing op afgewezen staan.
        if document.status in (DocumentStatus.AFGEVOERD_DUPLICAAT, DocumentStatus.AFGEWEZEN):
            afwijzing = _open_afwijzing(session, document_id)
            if afwijzing is not None:
                afgevoerd_van = _origineel_uit_afwijzing(session, afwijzing)
        return DuplicaatAfvoerStand(
            kandidaat=kandidaat,
            afgevoerd_als_duplicaat_van=afgevoerd_van,
            afgevoerde_duplicaten=afgevoerde_duplicaten_van(session, document_id=document_id),
            module_treffers=module_treffers,
            afmelding=duplicaat_module.laatste_afmelding(session, document_id=document_id),
        )


# ----------------------------------------------------------------------------- afvoeren


def afwikkel_reden(origineel: Origineel) -> str:
    """Reden op de ingetrokken ronde / gesloten vraag — de kortere vorm van `Origineel.reden()`."""
    return f"afgevoerd als duplicaat van {origineel.referentie}"


def _wikkel_af_voor_afvoer(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, origineel: Origineel
) -> None:
    """Blok A2 04-09: een duplicaat dat bij de klant-accordeur ligt of een open vraag draagt wordt vóór de
    afwijzing netjes afgewikkeld — nooit stil. (1) élke open vraag op het document zichtbaar gesloten mét
    de reden als slotbericht in de thread (vraagsteller ziet 'm; document op vraag_open keert terug naar
    zijn herkomst); (2) de lopende accorderingsronde ingetrokken/vervallen mét dezelfde reden (bestaand
    vervallen-patroon, document terug naar klaar_om_te_boeken). Daarna is de status weer een herstelbare
    herkomst voor `afwijzen.wijs_af` (heropenen keert er naar terug). Elke stap = eigen transactie, tijdlijn +
    audit; een fout stopt de afvoer vóór de afwijzing."""
    from app.accordering import service as accordering_service

    reden = afwikkel_reden(origineel)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        status = document.status if document is not None else None
    if status is None:
        return
    if status in (DocumentStatus.VRAAG_OPEN, DocumentStatus.TER_ACCORDERING):
        for vraag_id in vragen.open_vraag_ids_van_document(administratie_id=administratie_id, document_id=document_id):
            vragen.sluit_vraag_wegens_duplicaat(
                administratie_id=administratie_id, vraag_id=vraag_id, actor_id=actor_id, reden=reden
            )
    if status == DocumentStatus.TER_ACCORDERING:
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            accordering_service.laat_ronde_vervallen_bij_duplicaat(
                session, administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, reden=reden
            )


def _toegewezene_voor_afvoer(*, administratie_id: uuid.UUID, actor_id: uuid.UUID) -> uuid.UUID | None:
    """"Ter controle naar" voor een duplicaat-afvoer — geen persoon NODIG (herstelrun 07-09 blok 2, "leeg =
    doorlopen", migratie 0121; herziet de Beheerder-terugval van eerder die dag). Volgorde: (1) de administratie-
    eigenaar (None teruggeven → de bestaande default van `afwijzen.wijs_af` vult 'm); (2) de mens die afvoert
    (één-klik/bulk: hij heeft scope, anders kwam hij niet bij het endpoint); (3) voor de systeem-actor NIEMAND —
    de afwijzing landt niet-toegewezen in de kantoorbrede werkvoorraad/Mogelijk-duplicaat-tab. Een afvoer strandt
    dus nooit meer op een ontbrekende instelling."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is not None and administratie.eigenaar_gebruiker_id is not None:
            return None
    return actor_id if actor_id != SYSTEEM_ACTOR_ID else None


def _voer_af(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, origineel: Origineel, automatisch: bool
) -> afwijzen.AfwijzingData:
    """Eén motor voor beide ingangen: eerst de afwikkeling van ronde/vraag (A2), dan de bestaande afwijs-route
    mét kruisverwijzing. Schrijft sinds blok 3 (fixrun 08-09, feedback Peter) de eigen TERMINALE status
    `afgevoerd_duplicaat` i.p.v. `afgewezen` — geen afwijzen-substatus meer: telt niet mee in "Afgewezen —
    ter controle" of de Mogelijk-duplicaat-tab, wél terugvindbaar in Archief/Zoeken en via heropenen. De
    `Afwijzing`-rij (reden, kruisverwijzing, toewijzing, tijdlijn, audit) is ONGEWIJZIGD hergebruikt."""
    _wikkel_af_voor_afvoer(
        administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, origineel=origineel
    )
    return afwijzen.wijs_af(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        toegewezen_aan=_toegewezene_voor_afvoer(administratie_id=administratie_id, actor_id=actor_id),
        reden=origineel.reden(),
        duplicaat_van_document_id=origineel.document_id,
        duplicaat_van_rlz_document_id=origineel.rlz_document_id,
        duplicaat_van_referentie=origineel.referentie,
        automatisch=automatisch,
        naar_status=DocumentStatus.AFGEVOERD_DUPLICAAT,
    )


def _origineel_json(origineel: Origineel) -> dict:
    return {
        "bron": origineel.bron,
        "referentie": origineel.referentie,
        "document_id": str(origineel.document_id) if origineel.document_id else None,
        "rlz_document_id": str(origineel.rlz_document_id) if origineel.rlz_document_id else None,
        "boekstuknummer": origineel.boekstuknummer,
        "bestandsnaam": origineel.bestandsnaam,
    }


def voer_af_als_duplicaat(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> AfvoerResultaat:
    """Één-klik "Afvoeren als duplicaat" (altijd beschikbaar, ook zonder opt-in). Idempotent: een document
    dat al als duplicaat is afgevoerd geeft dezelfde data terug (`al_afgevoerd=True`)."""
    from app.documenten.service import DocumentNietGevonden

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.administratie_id != administratie_id:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if document.status == DocumentStatus.AFGEVOERD_DUPLICAAT:
            # Blok 3 (fixrun 08-09): dit is sindsdien de normale idempotentie-route.
            afwijzing = _open_afwijzing(session, document_id)
            origineel = _origineel_uit_afwijzing(session, afwijzing) if afwijzing is not None else None
            if afwijzing is not None and origineel is not None:
                return AfvoerResultaat(
                    afwijzing=afwijzen._naar_data(afwijzing, document), origineel=origineel, al_afgevoerd=True
                )
            raise AfvoerNietMogelijk(
                "Dit document staat al geregistreerd als afgevoerd duplicaat, maar de kruisverwijzing ontbreekt — "
                "neem contact op met het kantoor"
            )
        if document.status == DocumentStatus.AFGEWEZEN:
            # Legacy: vóór blok 3 (08-09) schreef een duplicaat-afvoer ook naar afgewezen — niet-gebackfilde
            # rijen blijven zo idempotent herkenbaar (zie CLI `duplicaat-status-backfill`).
            afwijzing = _open_afwijzing(session, document_id)
            origineel = _origineel_uit_afwijzing(session, afwijzing) if afwijzing is not None else None
            if afwijzing is not None and origineel is not None:
                return AfvoerResultaat(
                    afwijzing=afwijzen._naar_data(afwijzing, document), origineel=origineel, al_afgevoerd=True
                )
            raise AfvoerNietMogelijk(
                "Dit document is al afgewezen om een andere reden — heropen het eerst als je het als duplicaat "
                "wilt afvoeren"
            )
        if document.soort != DocumentSoort.INKOOPFACTUUR.value:
            raise AfvoerNietMogelijk("Alleen inkoopfacturen kunnen als duplicaat afgevoerd worden")
        if document.status not in AFVOERBARE_STATUSSEN:
            raise AfvoerNietMogelijk(
                f"Vanuit status {document.status.value} kan een document niet als duplicaat afgevoerd worden — "
                "alleen vanuit te controleren, handmatig afmaken, klaar om te boeken, ter accordering of met een "
                "open vraag"
            )
        groep = bepaal_groep(session, administratie_id=administratie_id, document_id=document_id)
        if groep is None:
            raise GeenHardeMatch(
                "Geen harde duplicaat-match (meer): geen ander document met hetzelfde bestand of dezelfde "
                "referentie + totaalbedrag (een zelfde referentie bij een ander bedrag is een signaal, geen afvoer)"
            )
        if not any(lid.document_id == document_id for lid in groep.duplicaten):
            raise GeenHardeMatch(
                "Dit document is zelf het origineel van deze duplicaatgroep — voer het nieuwere document af, niet dit"
            )
        origineel = groep.origineel
    data = _voer_af(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        origineel=origineel,
        automatisch=False,
    )
    return AfvoerResultaat(afwijzing=data, origineel=origineel, al_afgevoerd=False)


def _afgevoerd_vandaag(session: Session, *, administratie_id: uuid.UUID) -> int:
    """Volumerem-teller: automatische afvoer-overgangen van vandaag (tijdlijn-detail `automatisch_afgevoerd`).
    Blok 3 (fixrun 08-09): de doelstatus is sindsdien `afgevoerd_duplicaat`, niet meer `afgewezen` — een
    "vandaag"-teller hoeft geen legacy-terugval (alles ná deze deploy schrijft de nieuwe status)."""
    vandaag_begin = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    return (
        session.scalar(
            select(func.count())
            .select_from(DocumentGebeurtenis)
            .join(Document, DocumentGebeurtenis.document_id == Document.id)
            .where(
                Document.administratie_id == administratie_id,
                DocumentGebeurtenis.naar_status == DocumentStatus.AFGEVOERD_DUPLICAAT,
                DocumentGebeurtenis.detail.has_key("automatisch_afgevoerd"),
                DocumentGebeurtenis.tijdstip >= vandaag_begin,
            )
        )
        or 0
    )


def _audit(*, administratie_id: uuid.UUID, document_id: uuid.UUID, actie: str, waarde: dict) -> None:
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie=actie,
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde=waarde,
            administratie_id=administratie_id,
        )


def platformbreed_ingeschakeld(session: Session) -> bool:
    """De platformbrede noodrem (blok A1 04-09, migratie 0109): standaard AAN. Ontbreekt de rij dan
    fail-closed UIT (zelfde lijn als de boeken-noodstop)."""
    instelling = session.get(DuplicaatAfvoerInstelling, True)
    return instelling is not None and instelling.platformbreed_ingeschakeld


def verwerk_na_signaal(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> list[uuid.UUID]:
    """Automatisch pad, post-commit ná de duplicaatsignaal-berekening (extractie én veldopslag). Standaard
    AAN (blok A1) achter de platformbrede noodrem; systeem-actor; elke poging geauditeerd. Geeft de afgevoerde
    document-id's terug (test-/log-doel). Mét de noodrem UIT bewust géén audit-ruis.

    07-09: een module-match (a)/(b) — `groep.hard` — gaat DIRECT, buiten de 20/dag-rem; alleen een groep die
    uitsluitend op de RLZ-cache rust valt nog onder de rem. Wat na de ronde blijft staan mét tegenhangers (categorie
    (c), niet-afvoerbare status, geweigerd) krijgt de vlag `mogelijk_duplicaat_van_id` → Mogelijk-duplicaat-tab."""
    with scoped_session(administratie_id) as session:
        if not platformbreed_ingeschakeld(session):
            return []
        verzameling = duplicaat_module.laad_verzameling(session, administratie_id=administratie_id)
        eigen = verzameling.kop(document_id)
        alle_treffers = verzameling.treffers_voor(eigen) if eigen is not None else []
        groep = bepaal_groep(
            session, administratie_id=administratie_id, document_id=document_id, verzameling=verzameling
        )
        limiet = settings.max_duplicaat_afvoer_per_dag_per_administratie
        al_vandaag = _afgevoerd_vandaag(session, administratie_id=administratie_id)

    afgevoerd: list[uuid.UUID] = []
    if groep is not None and groep.duplicaten:
        origineel = groep.origineel
        for lid in list(groep.duplicaten):
            if not groep.hard and al_vandaag + len(afgevoerd) >= limiet:
                _audit(
                    administratie_id=administratie_id,
                    document_id=lid.document_id,
                    actie="duplicaat_afvoer_geweigerd",
                    waarde={
                        "reden": (
                            f"Volumerem: dagelijkse limiet van {limiet} automatische duplicaat-afvoeren bereikt — "
                            "document blijft in de werkvoorraad"
                        ),
                        "origineel": _origineel_json(origineel),
                    },
                )
                continue
            try:
                _voer_af(
                    administratie_id=administratie_id,
                    document_id=lid.document_id,
                    actor_id=SYSTEEM_ACTOR_ID,
                    origineel=origineel,
                    automatisch=True,
                )
            except (
                ToegewezeneBuitenScope,
                OngeldigeStatusovergang,
                afwijzen.AfwijzingFout,
                vragen.VraagFout,
            ) as exc:
                _audit(
                    administratie_id=administratie_id,
                    document_id=lid.document_id,
                    actie="duplicaat_afvoer_geweigerd",
                    waarde={"reden": str(exc), "origineel": _origineel_json(origineel)},
                )
                continue
            afgevoerd.append(lid.document_id)
            _audit(
                administratie_id=administratie_id,
                document_id=lid.document_id,
                actie="duplicaat_afgevoerd",
                waarde={"reden": origineel.reden(), "origineel": _origineel_json(origineel), "automatisch": True},
            )

    # Zichtbaar houden wat blijft staan (nooit stil): het document zelf, als het niet afgevoerd is maar wél
    # tegenhangers heeft die nog bestaan.
    if document_id not in afgevoerd:
        rest = [t for t in alle_treffers if t.document_id not in afgevoerd]
        if rest:
            with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
                document = session.get(Document, document_id)
                if document is not None and document.status not in _UITGESLOTEN_STATUSSEN:
                    duplicaat_module.markeer_mogelijk_duplicaat(
                        session,
                        document=document,
                        treffers=rest,
                        administratie_id=administratie_id,
                        actor_id=SYSTEEM_ACTOR_ID,
                    )
    return afgevoerd


def verwerk_na_signaal_stil(*, administratie_id: uuid.UUID | None, document_id: uuid.UUID) -> None:
    """Hook-variant: een fout is een gelogde waarschuwing — de afvoer is een optimalisatie bovenop de
    normale flow, nooit een blokkade van extractie of opslag."""
    if administratie_id is None:
        return
    try:
        verwerk_na_signaal(administratie_id=administratie_id, document_id=document_id)
    except Exception:  # noqa: BLE001 — automatisering mag de upload/worker/opslag nooit laten falen
        logger.exception("Duplicaat-afvoer mislukt voor document %s", document_id)


# ----------------------------------------------------------------------------- bulk (B2 07-09)


@dataclass(frozen=True)
class BulkAfvoerUitkomst:
    """Eén rij van de bulk-afvoer: `afgevoerd` (nu afgevoerd), `al_afgevoerd` (idempotente herhaling — was al
    als duplicaat afgevoerd, niets gewijzigd) of `overgeslagen` mét leesbare reden (status laat het niet toe,
    geen harde match, zelf het origineel, onbekend document, geen toewijzing mogelijk, …)."""

    document_id: uuid.UUID
    bestandsnaam: str | None
    uitkomst: str
    reden: str | None
    origineel: Origineel | None


def selecteer_alle_bulk_kandidaten(*, administratie_id: uuid.UUID, actor_id: uuid.UUID) -> list[uuid.UUID]:
    """Server-side "alle N" voor de Mogelijk-duplicaat-tab (B2 07-09): dezelfde tab-definitie als de frontend
    (`lijstContext.isMogelijkDuplicaat` — gecachet RLZ-/Odoo-signaal `mogelijk_duplicaat` óf het sha256-
    bestandsduplicaat `mogelijk_duplicaat_van_id`) beperkt tot wat de één-klik überhaupt kan afvoeren
    (inkoopfactuur in een AFVOERBARE status). Geen client-side id-lijst van duizenden; RLS via de gescoopte
    sessie van de actor. Volgorde: oudste eerst (deterministisch, zelfde als de groepsrangorde)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rijen = session.scalars(
            select(Document.id)
            .outerjoin(DuplicaatSignaal, DuplicaatSignaal.document_id == Document.id)
            .where(
                Document.administratie_id == administratie_id,
                Document.soort == DocumentSoort.INKOOPFACTUUR.value,
                Document.status.in_(list(AFVOERBARE_STATUSSEN)),
                or_(
                    DuplicaatSignaal.uitkomst == DuplicaatSignaalUitkomst.MOGELIJK_DUPLICAAT.value,
                    Document.mogelijk_duplicaat_van_id.isnot(None),
                ),
            )
            .order_by(Document.aangemaakt_op, Document.id)
        ).all()
    return list(rijen)


def _bestandsnaam_van(*, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID) -> str | None:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        return document.bestandsnaam if document is not None else None


def _audit_bulk(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    actie: str,
    correlatie_id: uuid.UUID,
    waarde: dict,
) -> None:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie=actie,
            correlatie_id=correlatie_id,
            nieuwe_waarde=waarde,
            administratie_id=administratie_id,
        )


def voer_af_in_bulk(
    *, administratie_id: uuid.UUID, document_ids: list[uuid.UUID], actor_id: uuid.UUID
) -> list[BulkAfvoerUitkomst]:
    """Bulk-afvoer vanaf de Mogelijk-duplicaat-tab (B2 07-09): expliciete MENSACTIE over de BESTAANDE
    één-klik-route per document (`voer_af_als_duplicaat` — zelfde harde match, kruisverwijzing, afwikkeling
    ronde/vraag, heropenen-terugweg, afwijs-audit + tijdlijn). Valt bewust BUITEN de 20/dag-automatiseringsrem:
    die telt alleen `automatisch_afgevoerd`-overgangen (systeem-actor), de mens-afvoer schrijft dat detail niet.

    Nooit stil: élke rij komt terug met een uitkomst; wat niet kan (status, geen harde match, zelf het
    origineel, onbekend) wordt OVERGESLAGEN mét de reden uit de motor. Idempotent: dubbel klikken geeft
    `al_afgevoerd` zonder tweede afwijzing. Eén bulk-run = één `correlatie_id` in het audit-event per rij
    (`duplicaat_afgevoerd` resp. `duplicaat_afvoer_geweigerd`, actor = de mens, `bulk: true`)."""
    from app.documenten.service import DocumentNietGevonden

    correlatie_id = uuid.uuid4()
    uitkomsten: list[BulkAfvoerUitkomst] = []
    gezien: set[uuid.UUID] = set()
    for document_id in document_ids:
        if document_id in gezien:
            continue  # dubbel in de selectie = één keer verwerken
        gezien.add(document_id)
        bestandsnaam = _bestandsnaam_van(administratie_id=administratie_id, document_id=document_id, actor_id=actor_id)
        try:
            resultaat = voer_af_als_duplicaat(
                administratie_id=administratie_id, document_id=document_id, actor_id=actor_id
            )
        except DocumentNietGevonden:
            uitkomsten.append(
                BulkAfvoerUitkomst(
                    document_id=document_id,
                    bestandsnaam=bestandsnaam,
                    uitkomst="overgeslagen",
                    reden="Onbekend document (of buiten je scope)",
                    origineel=None,
                )
            )
            continue
        except (
            DuplicaatAfvoerFout,
            OngeldigeStatusovergang,
            ToegewezeneBuitenScope,
            afwijzen.AfwijzingFout,
            vragen.VraagFout,
        ) as exc:
            reden = str(exc)
            _audit_bulk(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=actor_id,
                actie="duplicaat_afvoer_geweigerd",
                correlatie_id=correlatie_id,
                waarde={"reden": reden, "bulk": True, "automatisch": False},
            )
            uitkomsten.append(
                BulkAfvoerUitkomst(
                    document_id=document_id,
                    bestandsnaam=bestandsnaam,
                    uitkomst="overgeslagen",
                    reden=reden,
                    origineel=None,
                )
            )
            continue
        if resultaat.al_afgevoerd:
            uitkomsten.append(
                BulkAfvoerUitkomst(
                    document_id=document_id,
                    bestandsnaam=bestandsnaam,
                    uitkomst="al_afgevoerd",
                    reden=resultaat.afwijzing.reden,
                    origineel=resultaat.origineel,
                )
            )
            continue
        _audit_bulk(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor_id,
            actie="duplicaat_afgevoerd",
            correlatie_id=correlatie_id,
            waarde={
                "reden": resultaat.afwijzing.reden,
                "origineel": _origineel_json(resultaat.origineel),
                "automatisch": False,
                "bulk": True,
            },
        )
        uitkomsten.append(
            BulkAfvoerUitkomst(
                document_id=document_id,
                bestandsnaam=bestandsnaam,
                uitkomst="afgevoerd",
                reden=resultaat.afwijzing.reden,
                origineel=resultaat.origineel,
            )
        )
    return uitkomsten


# ----------------------------------------------------------------------------- backfill (blok 1 07-09)


@dataclass
class BackfillAdministratie:
    """Uitkomst van de backfill voor één administratie — cijfers PER ADMINISTRATIE (dry-run én echt)."""

    administratie_id: uuid.UUID
    naam: str
    documenten: int = 0  # toetsbare inkoopfacturen in de verzameling
    kandidaten: int = 0  # met ≥ 1 tegenhanger in categorie (a)/(b)
    af_te_voeren: int = 0
    afgevoerd: int = 0
    bundelparen_beschermd: int = 0  # documenten met een UBL+PDF-tegenhanger die daardoor NIET meetelt
    afgemeld: int = 0  # documenten met een mens-afmelding die een tegenhanger uitschakelt
    overgeslagen: dict[str, int] = field(default_factory=dict)
    regels: list[str] = field(default_factory=list)
    gestopt_reden: str | None = None

    def tel(self, reden: str) -> None:
        self.overgeslagen[reden] = self.overgeslagen.get(reden, 0) + 1


def backfill(*, dry_run: bool, administratie_id: uuid.UUID | None = None) -> list[BackfillAdministratie]:
    """CLI `duplicaten-backfill` (blok 1 07-09, GO Peter): over álle actieve administraties (of één) élk toetsbaar
    inkoopfactuur-document door DEZELFDE motor als het automatische pad halen — module-match (a)/(b), zelfde
    origineel-regel, zelfde uitsluitingen (bundelparen UBL+PDF, afmeldingen, uitgesloten statussen) — en de
    duplicaten afvoeren (systeem-actor, `automatisch=True`, BUITEN de dagrem, mét de platformbrede noodrem).
    Geen RLZ-/Odoo-calls, geen bestandslezing: puur database. Idempotent: een tweede run vindt 0 af te voeren
    (afgevoerd = afgewezen = uitgesloten). `dry_run=True` toetst alles en schrijft niets."""
    from app.db.models import Administratie

    with scoped_session(None) as session:
        admins = session.execute(
            select(Administratie.id, Administratie.naam)
            .where(Administratie.actief.is_(True))
            .order_by(Administratie.naam)
        ).all()
    if administratie_id is not None:
        admins = [a for a in admins if a[0] == administratie_id]

    uitkomsten: list[BackfillAdministratie] = []
    for aid, naam in admins:
        u = BackfillAdministratie(administratie_id=aid, naam=naam)
        plan: dict[uuid.UUID, Origineel] = {}
        with scoped_session(aid) as session:
            if not platformbreed_ingeschakeld(session):
                u.gestopt_reden = "platformbrede noodrem duplicaat-afvoer staat UIT — niets afgevoerd"
                uitkomsten.append(u)
                continue
            verzameling = duplicaat_module.laad_verzameling(session, administratie_id=aid)
            u.documenten = len(verzameling.koppen)
            for kop in sorted(verzameling.koppen.values(), key=lambda k: (k.aangemaakt_op, str(k.document_id))):
                if verzameling.bundelparen_voor(kop):
                    u.bundelparen_beschermd += 1
                if verzameling.afgemelde_tegenhangers(kop):
                    u.afgemeld += 1
                treffers = [
                    t for t in verzameling.treffers_voor(kop) if t.categorie in duplicaat_module.AFVOER_CATEGORIEEN
                ]
                if not treffers:
                    continue
                u.kandidaten += 1
                groep = bepaal_groep(
                    session, administratie_id=aid, document_id=kop.document_id, verzameling=verzameling
                )
                if groep is None:
                    u.tel("geen groep te bepalen")
                    continue
                if groep.origineel.document_id == kop.document_id:
                    u.tel("zelf het origineel van zijn groep")
                    continue
                if kop.status not in AFVOERBARE_STATUSSEN:
                    u.tel(f"status laat afvoeren niet toe ({kop.status.value})")
                    continue
                if not any(lid.document_id == kop.document_id for lid in groep.duplicaten):
                    u.tel("niet in de duplicatenlijst van zijn groep")
                    continue
                plan[kop.document_id] = groep.origineel
                doel = groep.origineel.bestandsnaam or groep.origineel.boekstuknummer or "?"
                u.regels.append(
                    f"{kop.bestandsnaam} [{kop.status.value}, {treffers[0].categorie}] → duplicaat van "
                    f"{groep.origineel.referentie} ({doel}, {groep.origineel.bron})"
                )
        u.af_te_voeren = len(plan)
        if not dry_run:
            for document_id, origineel in plan.items():
                try:
                    _voer_af(
                        administratie_id=aid,
                        document_id=document_id,
                        actor_id=SYSTEEM_ACTOR_ID,
                        origineel=origineel,
                        automatisch=True,
                    )
                except (
                    ToegewezeneBuitenScope,
                    OngeldigeStatusovergang,
                    afwijzen.AfwijzingFout,
                    vragen.VraagFout,
                ) as exc:
                    u.tel(f"geweigerd: {exc}")
                    _audit(
                        administratie_id=aid,
                        document_id=document_id,
                        actie="duplicaat_afvoer_geweigerd",
                        waarde={"reden": str(exc), "origineel": _origineel_json(origineel), "backfill": True},
                    )
                    continue
                u.afgevoerd += 1
                _audit(
                    administratie_id=aid,
                    document_id=document_id,
                    actie="duplicaat_afgevoerd",
                    waarde={
                        "reden": origineel.reden(),
                        "origineel": _origineel_json(origineel),
                        "automatisch": True,
                        "backfill": True,
                    },
                )
        uitkomsten.append(u)
    return uitkomsten


# ----------------------------------------------------------------------------- status-backfill (blok 3, fixrun 08-09)

#: Zelfde criterium als het archief-statusfilter "afgevoerd" vóór deze deploy (`zoeken/service.py::_archief_basis`,
#: legacy-tak): een AFGEWEZEN document met een OPEN afwijzing die een duplicaat-kruisverwijzing draagt.
_STATUS_BACKFILL_REDEN = (
    "Duplicaten-UI blok 3 (fixrun 08-09): deze afwijzing droeg al een duplicaat-kruisverwijzing — het document "
    "krijgt met terugwerkende kracht de eigen status afgevoerd_duplicaat (geen afwijzen-substatus meer)."
)


@dataclass
class StatusBackfillAdministratie:
    """Uitkomst van `duplicaat-status-backfill` voor één administratie."""

    administratie_id: uuid.UUID
    naam: str
    legacy_gevonden: int = 0
    omgezet: int = 0
    fouten: dict[str, int] = field(default_factory=dict)

    def tel_fout(self, reden: str) -> None:
        self.fouten[reden] = self.fouten.get(reden, 0) + 1


def _legacy_afgevoerd_document_ids(session: Session, *, administratie_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        session.scalars(
            select(Document.id)
            .join(Afwijzing, Afwijzing.document_id == Document.id)
            .where(
                Document.administratie_id == administratie_id,
                Document.status == DocumentStatus.AFGEWEZEN,
                Afwijzing.status == AfwijzingStatus.OPEN.value,
                or_(
                    Afwijzing.duplicaat_van_document_id.isnot(None),
                    Afwijzing.duplicaat_van_rlz_document_id.isnot(None),
                    Afwijzing.duplicaat_van_referentie.isnot(None),
                ),
            )
            .order_by(Document.aangemaakt_op)
        )
    )


def status_backfill(*, dry_run: bool, administratie_id: uuid.UUID | None = None) -> list[StatusBackfillAdministratie]:
    """CLI `duplicaat-status-backfill` (blok 3, fixrun 08-09, feedback Peter — screenshot Universal Steigerbouw):
    LOSSE, eenmalige data-stap ná migratie 0122. Vóór deze deploy schreef élke duplicaat-afvoer (automatisch,
    één-klik, bulk, backfill) naar `document.status = 'afgewezen'` mét een open `Afwijzing`-rij die een
    duplicaat-kruisverwijzing draagt (`duplicaat_van_document_id`/`_rlz_document_id`/`_referentie`) — precies het
    criterium dat het archief-statusfilter "afgevoerd" al gebruikte. Deze functie zet zulke rijen alsnog om naar
    de eigen terminale status `afgevoerd_duplicaat`, via de statusmachine (`_schrijf_overgang`: valideert de
    overgang, schrijft de tijdlijnregel én het audit-event `status_afgevoerd_duplicaat` in dezelfde transactie —
    systeem-actor, reden verplicht). De `Afwijzing`-rij zelf (reden, kruisverwijzing, toewijzing) blijft
    ONGEWIJZIGD; alleen `document.status` verandert. Eén transactie per document — een fout stopt de rest niet
    en blijft zichtbaar in `fouten`. Idempotent: een tweede run vindt 0 legacy-rijen (ze staan dan al op
    afgevoerd_duplicaat, dus buiten het AFGEWEZEN-criterium hierboven). Geen RLZ-/Odoo-calls.
    `dry_run=True` telt alles en schrijft niets. Loopt over alle ACTIEVE administraties (of één, `--administratie`)."""
    from app.db.models import Administratie

    with scoped_session(None) as session:
        admins = session.execute(
            select(Administratie.id, Administratie.naam)
            .where(Administratie.actief.is_(True))
            .order_by(Administratie.naam)
        ).all()
    if administratie_id is not None:
        admins = [a for a in admins if a[0] == administratie_id]

    uitkomsten: list[StatusBackfillAdministratie] = []
    for aid, naam in admins:
        u = StatusBackfillAdministratie(administratie_id=aid, naam=naam)
        with scoped_session(aid) as session:
            legacy_ids = _legacy_afgevoerd_document_ids(session, administratie_id=aid)
        u.legacy_gevonden = len(legacy_ids)
        if not dry_run:
            from app.documenten.service import _schrijf_overgang

            for document_id in legacy_ids:
                with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as tx:
                    document = tx.get(Document, document_id)
                    if document is None or document.status != DocumentStatus.AFGEWEZEN:
                        continue  # race: intussen heropend of anders gewijzigd sinds de leesronde hierboven
                    try:
                        _schrijf_overgang(
                            tx,
                            document=document,
                            naar=DocumentStatus.AFGEVOERD_DUPLICAAT,
                            actor_id=SYSTEEM_ACTOR_ID,
                            detail={"status_backfill": True, "reden": _STATUS_BACKFILL_REDEN},
                        )
                    except OngeldigeStatusovergang as exc:
                        u.tel_fout(str(exc))
                        continue
                    u.omgezet += 1
        uitkomsten.append(u)
    return uitkomsten
