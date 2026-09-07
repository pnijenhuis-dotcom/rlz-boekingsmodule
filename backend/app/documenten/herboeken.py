"""Opnieuw boeken ná een VERDWENEN extern document (A11, fixrun 07-09; casus BOOT / Kempen Facilities).

Situatie: een document staat lokaal GEBOEKT, maar het RLZ-/Odoo-document bestaat niet meer (in de RLZ-UI
verwijderd — kliktest-erfenis — of in Odoo verdwenen). De documenten-reconciliatie meldt dat als
`ontbreekt_in_rlz` / `ontbreekt_in_odoo` (zwaarste categorie). Tegenboeken kan niet: er is niets om tegen te
boeken. De herstelroute is het BESTAANDE herboek-mechanisme van het tegenboek-pad (migratie 0061), zónder
tegenboeking:

1. poorten: geboekt inkoopdocument, verplichte reden (≥ 5 tekens), en — hard — de backend kent het document
   LIVE niet meer (`InkoopPort.toets_geboekt` → `bestaat=False`); bestaat het nog, dan is dit niet de route
   (409: storno/tegenboeken);
2. in één transactie: `boekvoorstel.boek_cyclus += 1` (de herboeking krijgt via `rlz_herboeking_id` een VERS
   deterministisch GUID — nooit een her-PUT op het verdwenen GUID), `rlz_boekstuknummer` leeg (het oude nummer
   verwijst naar niets meer; het staat in tijdlijn/audit), statusovergang GEBOEKT → KLAAR_OM_TE_BOEKEN
   (statusmachine), tijdlijn + audit_event mét reden en het oude externe id; de neveneffecten van de
   oorspronkelijke boeking worden teruggedraaid zoals bij tegenboeken (verplichting-verbruik, mini-voorraad-
   instroom), zodat de herboeking ze opnieuw registreert;
3. de mens boekt daarna via het controlescherm (harde checks onverkort — een intussen handmatig in het pakket
   opnieuw ingevoerde factuur blokkeert dan als duplicaat: precies goed, de mens beslist). Volumerem
   ongewijzigd (er staat in het pakket niets meer voor deze cyclus).

AANGIFTE-POORT (correctie Peter 07-09 op A11 beslispunt 2 — HERZIET "gewoon toegestaan"): is het externe document
ná indiening van de btw-aangifte verwijderd, dan zit de voorbelasting al in die aangifte; de herboeking krijgt
`BookDate` = factuurdatum en RLZ verschuift de TaxSource naar de eerstvolgende open periode — de btw wordt dan
OPNIEUW geclaimd. Daarom toetst stap 1 óók de boekdatum van de verdwenen boeking (`InkoopPort.toets_btw_periode`:
RLZ = TaxDeclarations Status 2/3 via `app/rlz/aangifte.py`, Odoo = lock dates) — valt die in een ingediende
periode, of is de aangiftestatus niet leesbaar (fail-closed), dan BLOKKEERT herboeken met code
`btw_mogelijk_aangegeven` (409): "btw mogelijk al aangegeven — suppletie-pad". Alleen een BEHEERDER kan in dezelfde
actie doorzetten met `btw_niet_in_aangifte_bevestigd=True` + verplichte `bevestiging_reden` (≥ 5 tekens) — een
andere rol mét bevestiging = 403; de bevestiging + reden landen in tijdlijn-detail én audit (oud→nieuw).

Vastgoed-administraties: het `factuur_geboekt`-event van de verdwenen boeking wordt gevolgd door een
`factuur_gestorneerd` (bron rlz_ui_detectie, reden = deze actie) in dezelfde boekstand-reeks — de herboeking
vuurt straks haar eigen geboekt-event op het nieuwe rlz_document_id (koppelcontract §3b)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.auth import service as auth_service
from app.backends import inkoop_port_voor
from app.backends.port import InkoopPort, ToetsMislukt
from app.db.audit import record_audit_event
from app.db.models import Administratie, GebruikerRol
from app.db.session import scoped_session
from app.documenten.boekstand import laatste_boekstand_rij, stand_van_rij
from app.documenten.models import Boekvoorstel, Document, DocumentGebeurtenis, DocumentStatus, WebhookUitgaand
from app.documenten.reconciliatie import ONTBREEKT_SOORTEN
from app.documenten.rlz_ids import rlz_herboeking_id
from app.documenten.service import DocumentNietGevonden, _schrijf_overgang
from app.documenten.webhook import FACTUUR_GEBOEKT_EVENT, GESTORNEERD_BRON_RLZ_UI, bouw_factuur_gestorneerd_payload
from app.reconciliatie.models import BevindingSoort, ReconciliatieBevinding
from app.rlz.aangifte import KantToets
from app.rlz.client import RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor

logger = logging.getLogger(__name__)

MIN_REDEN_LENGTE = 5  # zelfde ondergrens als tegenboeken/acceptaties

#: Herkenbare 409-code voor de frontend (tweede stap in dezelfde dialoog, alleen Beheerder).
BTW_BLOKKADE_CODE = "btw_mogelijk_aangegeven"
BTW_BLOKKADE_MELDING = (
    "Btw mogelijk al aangegeven — suppletie-pad: de boekdatum van de verdwenen boeking valt in een ingediende "
    "btw-aangifte; opnieuw boeken zou de voorbelasting opnieuw claimen"
)
BTW_NIET_CONTROLEERBAAR_MELDING = (
    "Btw-aangiftestatus kon niet gecontroleerd worden — opnieuw boeken uit voorzorg geblokkeerd "
    "(btw mogelijk al aangegeven — suppletie-pad)"
)
BTW_BEVESTIGING_TOELICHTING = (
    "Alleen een Beheerder kan doorzetten, met de bevestiging dat de btw van dit document NIET in de ingediende "
    "aangifte zat (verplichte reden; komt in tijdlijn en audit)"
)


class HerboekenFout(Exception):
    """Basis voor alle domeinfouten (422 in de router)."""


class BevindingNietGevonden(HerboekenFout):
    """404."""


class GeenToegang(HerboekenFout):
    """403 — administratie buiten de scope van de actor."""


class NogAanwezigInBackend(HerboekenFout):
    """409 — het externe document bestaat (nog/weer): dan is storno/tegenboeken de route, niet herboeken."""


class BtwMogelijkAangegeven(HerboekenFout):
    """409 `btw_mogelijk_aangegeven` — de boekdatum van de verdwenen boeking valt in een ingediende btw-periode
    (of de aangiftestatus is niet leesbaar: fail-closed). Alleen een Beheerder zet door mét bevestiging + reden."""

    code = BTW_BLOKKADE_CODE

    def __init__(self, *, toets: KantToets, boekdatum: date | None, backend: str) -> None:
        self.toets = toets
        self.boekdatum = boekdatum
        self.backend = backend
        # Geen periode in de toets = niet controleerbaar (leesfout, boekdatum onbekend) — eigen melding.
        self.controleerbaar = toets.periode_start is not None or toets.periode_eind is not None
        basis = BTW_BLOKKADE_MELDING if self.controleerbaar else BTW_NIET_CONTROLEERBAAR_MELDING
        toelichting = f" ({toets.reden})" if toets.reden else ""
        super().__init__(f"{basis}{toelichting}. {BTW_BEVESTIGING_TOELICHTING}.")

    def als_detail(self) -> dict:
        """HTTP-409-detail: herkenbare code + leesbaar `bericht` (frontend `foutmelding` leest die sleutel)."""
        return {
            "code": self.code,
            "bericht": str(self),
            "soort": "ingediende_periode" if self.controleerbaar else "niet_controleerbaar",
            "boekdatum": self.boekdatum.isoformat() if self.boekdatum else None,
            "periode_start": self.toets.periode_start.isoformat() if self.toets.periode_start else None,
            "periode_eind": self.toets.periode_eind.isoformat() if self.toets.periode_eind else None,
            "backend": self.backend,
            "bevestiging_mogelijk": True,
            "bevestiging_rol": GebruikerRol.BEHEERDER.value,
        }


@dataclass(frozen=True)
class HerboekResultaat:
    document_id: uuid.UUID
    status: DocumentStatus
    boek_cyclus: int
    oud_extern_id: str | None
    doel_pad: str


def _rlz_client_voor(administratie_id: uuid.UUID) -> RlzClient:
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    return client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)


def _port_voor(administratie_id: uuid.UUID) -> InkoopPort:
    return inkoop_port_voor(administratie_id, rlz_client_factory=lambda: _rlz_client_voor(administratie_id))


def _laad_geboekt_document(session, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> Document:  # noqa: ANN001
    document = session.get(Document, document_id)
    if document is None or document.administratie_id != administratie_id:
        raise DocumentNietGevonden(f"Onbekend document: {document_id}")
    if document.soort != "inkoopfactuur":
        raise HerboekenFout(f"Document heeft soort {document.soort} — opnieuw boeken is alleen voor inkoopfacturen")
    if document.status != DocumentStatus.GEBOEKT:
        raise HerboekenFout(
            f"Document staat op status {document.status.value} — alleen een geboekt document kan opnieuw geboekt worden"
        )
    return document


def _meld_gestorneerd_voor_vastgoed(
    session,  # noqa: ANN001
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    oud_rlz_document_id: uuid.UUID,
    reden: str,
) -> bool:
    """Koppelcontract §3b: alleen als de verdwenen boeking ooit als `factuur_geboekt` gemeld is en de laatste
    stand nog 'geboekt' zegt — idempotent per boekstand-reeks (zelfde anker als storno_detectie)."""
    administratie = session.get(Administratie, administratie_id)
    if administratie is None or not administratie.is_vastgoed:
        return False
    rij = laatste_boekstand_rij(session, document_id=document_id, rlz_document_id=oud_rlz_document_id)
    if rij is None or rij.event != FACTUUR_GEBOEKT_EVENT:
        return False
    data = (rij.payload or {}).get("data") or {}
    payload = bouw_factuur_gestorneerd_payload(
        administratie_id=administratie_id,
        rlz_admin_id=administratie.rlz_admin_id,
        rlz_document_id=oud_rlz_document_id,
        rlz_boekstuknummer=data.get("rlz_boekstuknummer"),
        referentie=data.get("referentie"),
        volgnummer=stand_van_rij(rij) + 1,
        bron=GESTORNEERD_BRON_RLZ_UI,
        reden=f"extern document verdwenen — opnieuw geboekt: {reden}",
        gestorneerd_op=datetime.now(UTC),
    )
    session.add(WebhookUitgaand(document_id=document_id, event=payload["event"], payload=payload))
    return True


def _parse_datum(waarde: object) -> date | None:
    if not isinstance(waarde, str) or len(waarde) < 10:
        return None
    try:
        return date.fromisoformat(waarde[:10])
    except ValueError:
        return None


def _boekdatum_verdwenen_boeking(
    session,  # noqa: ANN001
    *,
    document_id: uuid.UUID,
    oud_rlz_document_id: uuid.UUID,
    voorstel: Boekvoorstel,
) -> date | None:
    """De BookDate waarmee de verdwenen boeking in het pakket stond — dáár hangt de btw-periode aan.
    RLZ: de adapter zet `BookDate` = factuurdatum (besluit Peter 27-08), dus `boekvoorstel.factuurdatum`.
    Odoo: de boekdatum kan verschoven zijn (`bepaal_boekdatum` → tijdlijn-detail `boekdatum_verschoven.naar` op het
    geboekt-event van déze cyclus) — dan geldt die datum. Het geboekt-event wint als het een datum draagt; anders de
    factuurdatum; None = onbekend (fail-closed in de poort)."""
    events = session.scalars(
        select(DocumentGebeurtenis)
        .where(
            DocumentGebeurtenis.document_id == document_id,
            DocumentGebeurtenis.naar_status == DocumentStatus.GEBOEKT,
        )
        .order_by(DocumentGebeurtenis.tijdstip.desc())
    ).all()
    for e in events:
        d = e.detail or {}
        if d.get("rlz_document_id") != str(oud_rlz_document_id):
            continue
        verschoven = d.get("boekdatum_verschoven")
        if isinstance(verschoven, dict):
            datum = _parse_datum(verschoven.get("naar"))
            if datum is not None:
                return datum
        break
    return voorstel.factuurdatum


def _toets_btw_periode(port: InkoopPort, boekdatum: date | None) -> KantToets:
    """Fail-closed rond de adapter: geen boekdatum, geen port-operatie of een leesfout = geblokkeerd — nooit stil
    doorlaten."""
    if boekdatum is None:
        return KantToets(
            kant="inkoopfactuur",
            toegestaan=False,
            reden="boekdatum van de verdwenen boeking onbekend — herboeken uit voorzorg geblokkeerd",
        )
    try:
        return port.toets_btw_periode(boekdatum=boekdatum)
    except Exception as exc:  # noqa: BLE001 — fail-closed: élke fout in de aangifte-poort blokkeert
        logger.warning("Aangifte-poort herboeken niet uitvoerbaar (%s): %s", port.backend.value, exc)
        return KantToets(
            kant="inkoopfactuur",
            toegestaan=False,
            reden=f"btw-aangiftestatus niet controleerbaar ({exc}) — herboeken uit voorzorg geblokkeerd",
        )


def opnieuw_boeken_na_verdwijnen(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    reden: str,
    port: InkoopPort | None = None,
    rol: GebruikerRol | None = None,
    btw_niet_in_aangifte_bevestigd: bool = False,
    bevestiging_reden: str | None = None,
) -> HerboekResultaat:
    """De kern (zie moduledocstring). `port` = test-seam; standaard de adapter van de administratie.
    `btw_niet_in_aangifte_bevestigd` + `bevestiging_reden` = de Beheerder-doorzet ná een `BtwMogelijkAangegeven`
    (rol server-side getoetst — een andere rol mét bevestiging = `GeenToegang`/403)."""
    if len((reden or "").strip()) < MIN_REDEN_LENGTE:
        raise HerboekenFout(f"Reden is verplicht (minimaal {MIN_REDEN_LENGTE} tekens)")
    reden = reden.strip()
    if btw_niet_in_aangifte_bevestigd:
        if rol != GebruikerRol.BEHEERDER:
            raise GeenToegang(
                "Alleen een Beheerder kan bevestigen dat de btw van dit document niet in de ingediende aangifte zat"
            )
        if len((bevestiging_reden or "").strip()) < MIN_REDEN_LENGTE:
            raise HerboekenFout(
                f"Reden van de bevestiging 'btw niet in aangifte' is verplicht (minimaal {MIN_REDEN_LENGTE} tekens)"
            )
        bevestiging_reden = (bevestiging_reden or "").strip()
    else:
        bevestiging_reden = None

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _laad_geboekt_document(session, administratie_id=administratie_id, document_id=document_id)
        voorstel = session.get(Boekvoorstel, document_id)
        if voorstel is None:
            raise HerboekenFout("Het document heeft geen boekvoorstel — opnieuw boeken kan niet")
        boek_cyclus = int(voorstel.boek_cyclus or 0)
        oud_boekstuknummer = voorstel.rlz_boekstuknummer
        oud_rlz_document_id = rlz_herboeking_id(document_id, boek_cyclus)
        boekdatum = _boekdatum_verdwenen_boeking(
            session, document_id=document_id, oud_rlz_document_id=oud_rlz_document_id, voorstel=voorstel
        )

    # Harde poort 1: de backend kent het document LIVE niet meer. Een nog bestaand stuk = storno/tegenboeken.
    # Harde poort 2 (correctie Peter 07-09): de boekdatum van de verdwenen boeking mag niet in een ingediende
    # btw-periode vallen — tenzij een Beheerder in dezelfde actie bevestigt dat de btw er niet in zat.
    eigen_port = port is None
    port = port or _port_voor(administratie_id)
    try:
        try:
            uitkomst = port.toets_geboekt(
                document_id=document_id, boek_cyclus=boek_cyclus, boekstuknummer=oud_boekstuknummer
            )
        except ToetsMislukt as exc:
            raise HerboekenFout(f"De stand in de boekhouding kon niet gecontroleerd worden: {exc}") from exc
        if not uitkomst.van_toepassing:
            raise HerboekenFout(uitkomst.reden or "Dit document is in deze boekhouding niet te toetsen")
        if uitkomst.bestaat:
            raise NogAanwezigInBackend(
                f"Het externe document bestaat nog ({uitkomst.boekstuknummer or uitkomst.extern_id}, "
                f"status {uitkomst.extern_state}) — corrigeer via storno of tegenboeken, niet via opnieuw boeken"
            )
        btw_toets = _toets_btw_periode(port, boekdatum)
    finally:
        if eigen_port:
            port.__exit__(None, None, None)
    if not btw_toets.toegestaan and not btw_niet_in_aangifte_bevestigd:
        raise BtwMogelijkAangegeven(toets=btw_toets, boekdatum=boekdatum, backend=port.backend.value)
    doorgezet_met_bevestiging = bool(btw_niet_in_aangifte_bevestigd and not btw_toets.toegestaan)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = _laad_geboekt_document(session, administratie_id=administratie_id, document_id=document_id)
        voorstel = session.get(Boekvoorstel, document_id)
        assert voorstel is not None
        if int(voorstel.boek_cyclus or 0) != boek_cyclus:
            raise HerboekenFout("Het document is intussen gewijzigd — laad het scherm opnieuw")
        nieuwe_cyclus = boek_cyclus + 1
        voorstel.boek_cyclus = nieuwe_cyclus
        voorstel.rlz_boekstuknummer = None
        detail = {
            "opnieuw_boeken": {
                "aanleiding": "ontbreekt_in_odoo" if port.backend.value == "odoo" else "ontbreekt_in_rlz",
                "reden": reden,
                "backend": port.backend.value,
                "oud_extern_id": uitkomst.extern_id or str(oud_rlz_document_id),
                "oud_rlz_document_id": str(oud_rlz_document_id),
                "oud_boekstuknummer": oud_boekstuknummer,
                "oude_cyclus": boek_cyclus,
                "nieuwe_cyclus": nieuwe_cyclus,
                "nieuw_rlz_document_id": str(rlz_herboeking_id(document_id, nieuwe_cyclus)),
                "toets": uitkomst.reden,
                "tegenboeking": None,  # bewust: er is niets om tegen te boeken
                # Aangifte-poort (correctie Peter 07-09): wat getoetst is en of een Beheerder 'm heeft doorgezet.
                "btw_poort": {
                    "boekdatum": boekdatum.isoformat() if boekdatum else None,
                    "toegestaan": btw_toets.toegestaan,
                    "reden": btw_toets.reden,
                    "periode_start": btw_toets.periode_start.isoformat() if btw_toets.periode_start else None,
                    "periode_eind": btw_toets.periode_eind.isoformat() if btw_toets.periode_eind else None,
                    "doorgezet_met_bevestiging": doorgezet_met_bevestiging,
                },
                "btw_niet_in_aangifte_bevestigd": (
                    {"door": str(actor_id), "rol": rol.value if rol else None, "reden": bevestiging_reden}
                    if btw_niet_in_aangifte_bevestigd
                    else None
                ),
            },
            "reden": (
                f"opnieuw boeken — extern document verdwenen "
                f"({oud_boekstuknummer or str(oud_rlz_document_id)[:8]}): {reden}"
                + (
                    f" — ná Beheerder-bevestiging 'btw niet in de ingediende aangifte': {bevestiging_reden}"
                    if doorgezet_met_bevestiging
                    else ""
                )
            ),
        }
        _schrijf_overgang(
            session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=actor_id, detail=detail
        )
        # Neveneffecten van de verdwenen boeking terugdraaien — zoals tegenboeken dat doet — zodat de herboeking ze
        # opnieuw registreert (anders dubbel verbruik / dubbele instroom). Lazy imports: geen kring.
        from app.mini_voorraad import instroom as mini_voorraad_instroom
        from app.verplichting import match_pipeline as verplichting_match

        verplichting_match.draai_verbruik_terug_in_sessie(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor_id,
            reden=f"extern document verdwenen — opnieuw boeken: {reden}",
        )
        mini_voorraad_instroom.registreer_storno(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            boek_cyclus=boek_cyclus,
            actor_id=actor_id,
            reden=f"extern document verdwenen — opnieuw boeken: {reden}",
        )
        detail["opnieuw_boeken"]["webhook_gestorneerd"] = _meld_gestorneerd_voor_vastgoed(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            oud_rlz_document_id=oud_rlz_document_id,
            reden=reden,
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="boekvoorstel",
            record_id=document_id,
            actie="opnieuw_boeken_na_verdwijnen",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"boek_cyclus": boek_cyclus, "rlz_boekstuknummer": oud_boekstuknummer, "status": "geboekt"},
            nieuwe_waarde={**detail["opnieuw_boeken"], "status": DocumentStatus.KLAAR_OM_TE_BOEKEN.value},
            administratie_id=administratie_id,
        )

    return HerboekResultaat(
        document_id=document_id,
        status=DocumentStatus.KLAAR_OM_TE_BOEKEN,
        boek_cyclus=nieuwe_cyclus,
        oud_extern_id=uitkomst.extern_id,
        doel_pad=f"/?administratie={administratie_id}&document={document_id}",
    )


def opnieuw_boeken_vanuit_bevinding(
    *,
    bevinding_id: uuid.UUID,
    administratie_id: uuid.UUID,
    reden: str,
    actor_id: uuid.UUID,
    rol: GebruikerRol,
    port: InkoopPort | None = None,
    btw_niet_in_aangifte_bevestigd: bool = False,
    bevestiging_reden: str | None = None,
) -> HerboekResultaat:
    """Ingang vanuit Inzicht › Reconciliatie: de bevinding moet een documenten-afwijking `ontbreekt_in_*` zijn
    binnen de scope van de actor (RLS-les 25-08: lezen in `scoped_session(<adm>, actor_id=…)`)."""
    if administratie_id not in {a.id for a in auth_service.mijn_administraties(actor_id=actor_id, rol=rol)}:
        raise GeenToegang("Geen toegang tot deze administratie")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        b = session.get(ReconciliatieBevinding, bevinding_id)
        if b is None or b.administratie_id != administratie_id:
            raise BevindingNietGevonden("Bevinding niet gevonden")
        d = dict(b.detail or {})
        blok, soort = b.blok, b.soort
    if blok != "documenten" or soort not in (BevindingSoort.AFWIJKING.value, BevindingSoort.UITGESLOTEN.value):
        raise HerboekenFout("Opnieuw boeken geldt alleen voor een documenten-afwijking")
    if d.get("afwijking_soort") not in ONTBREEKT_SOORTEN or not d.get("document_id"):
        raise HerboekenFout("Opnieuw boeken geldt alleen als het externe document verdwenen is (ontbreekt in RLZ/Odoo)")
    return opnieuw_boeken_na_verdwijnen(
        administratie_id=administratie_id,
        document_id=uuid.UUID(str(d["document_id"])),
        actor_id=actor_id,
        reden=reden,
        port=port,
        rol=rol,
        btw_niet_in_aangifte_bevestigd=btw_niet_in_aangifte_bevestigd,
        bevestiging_reden=bevestiging_reden,
    )
