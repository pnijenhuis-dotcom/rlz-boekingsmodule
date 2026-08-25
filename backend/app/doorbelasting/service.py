"""Servicelaag doorbelasting: instellingen + mapping-whitelist (beheer), runs + verdeling
(review) en de open spiegel-taken. De boekmotor zelf leeft in boeken.py.

Alle mutaties dragen een audit_event (besluit 0004); de mapping-whitelist wordt hier —
server-side — afgedwongen (mockup #centraleinkoopmodal: "doorbelasten buiten deze lijst is
technisch onmogelijk"). Verdeelregels zijn werkstaat zolang de run concept is; zodra er een
niet-gestorneerde boeking bestaat is de verdeling bevroren (de geboekte werkelijkheid mag
nooit stil verschuiven onder een nieuwe berekening)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select

from app.db.audit import record_audit_event
from app.db.models import Administratie, Gebruiker, GebruikerAdministratie, GebruikerRol
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.checks import CheckRapport
from app.documenten.models import BoekvoorstelRegel, Document, DocumentSoort, DocumentStatus
from app.doorbelasting.checks import (
    MappingInvoer,
    VerdeelRegelInvoer,
    voer_doorbelasting_checks_uit,
)
from app.doorbelasting.geld import provisie_over, verdeel_grootste_rest
from app.doorbelasting.models import (
    INACTIEVE_RUN_STATUSSEN,
    DoorbelastingBoeking,
    DoorbelastingBoekingStatus,
    DoorbelastingInstelling,
    DoorbelastingMapping,
    DoorbelastingRegel,
    DoorbelastingRun,
    DoorbelastingRunStatus,
    IntercompanyTegenpartij,
)
from app.projecten.anker import anker_customer_id


def upsert_intercompany_tegenpartij(
    session,
    *,
    administratie_id: uuid.UUID,
    entity_guid: uuid.UUID,
    naam: str,
    mapping_id: uuid.UUID | None,
    actief: bool,
) -> None:
    """Onderhoudt één IC-rij in de gegeven scope (blok 2, RC-consequentie): uniek op
    (administratie, entity_guid), deactiveren i.p.v. verwijderen. Aangeroepen voor de
    bron-kant (doel_customer_guid) bij seed/mapping-wijziging en voor de doel-kant
    (crediteur-GUID) zodra de motor die kent."""
    bestaand = session.scalars(
        select(IntercompanyTegenpartij).where(
            IntercompanyTegenpartij.administratie_id == administratie_id,
            IntercompanyTegenpartij.entity_guid == entity_guid,
        )
    ).one_or_none()
    if bestaand is None:
        session.add(
            IntercompanyTegenpartij(
                administratie_id=administratie_id,
                entity_guid=entity_guid,
                naam=naam,
                mapping_id=mapping_id,
                actief=actief,
            )
        )
    else:
        bestaand.naam = naam
        bestaand.actief = actief
        if mapping_id is not None:
            bestaand.mapping_id = mapping_id


_MODULE = "boekhouding"


class DoorbelastingFout(Exception):
    """Basisfout — de router vertaalt naar 409/404 met de melding als detail."""


class RunNietGevonden(DoorbelastingFout):
    pass


class VerdelingBevroren(DoorbelastingFout):
    """De run heeft al een niet-gestorneerde boeking: verdeling wijzigen kan niet meer."""


# --- Kempen-seed (verkenning §1 — de acht herkende groepsentiteiten; losse expliciete stap,
# --- geen migratie-data: draaien zodra de Facilities-administratie onboarded is).
KEMPEN_SEED: tuple[tuple[str, str], ...] = (
    ("Veldhoven Recreatie B.V.", "c997e324-bfda-4a84-afc7-a416d367db3a"),
    ("Oirschot Recreatie B.V.", "f0ce5e77-ca6b-48e1-bd00-325cf635c7ec"),
    ("Molenhof Beheer B.V.", "cc58e167-4c6b-4d31-91ea-573ad6b616fa"),
    ("Molenhof Verhuur B.V.", "5027c79b-f6de-4b67-80db-867028ac35c0"),
    ("Kempen Chalets B.V.", "f5d427fa-2d63-4b19-bdb0-e3120fcbd92b"),
    ("Oirschot Vastgoed Beheer B.V.", "c945e48e-b92f-4328-97f8-7c088155989e"),
    ("Mantelzorgwoning Midden Nederland B.V.", "90dbadcb-5066-4822-a374-0b454a4a9180"),
    ("Rubicon Investments B.V.", "2f432363-127b-40e4-b331-ea8c03d4653d"),
)


def seed_kempen_mappings(*, administratie_id: uuid.UUID, actor_id: uuid.UUID) -> int:
    """Idempotente seed van de whitelist uit verkenning §1 (uniek op doel_customer_guid):
    bestaande rijen blijven onaangeroerd, alleen ontbrekende worden toegevoegd. Koppelt
    doel_administratie_id automatisch waar de doelentiteit al onboarded is (naam-match op
    platform.administratie — Rubicon is dat al)."""
    toegevoegd = 0
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        bestaande = {
            m.doel_customer_guid
            for m in session.scalars(
                select(DoorbelastingMapping).where(DoorbelastingMapping.administratie_id == administratie_id)
            )
        }
        onboarded = {a.naam: a.id for a in session.scalars(select(Administratie))}
        for naam, guid_str in KEMPEN_SEED:
            guid = uuid.UUID(guid_str)
            if guid in bestaande:
                continue
            mapping = DoorbelastingMapping(
                administratie_id=administratie_id,
                doelentiteit_naam=naam,
                doel_customer_guid=guid,
                doel_administratie_id=onboarded.get(naam),
                aangemaakt_door=actor_id,
            )
            session.add(mapping)
            session.flush()
            # bron-kant IC-rij: de doelentiteit-als-debiteur in de bron is intercompany (blok 2)
            upsert_intercompany_tegenpartij(
                session,
                administratie_id=administratie_id,
                entity_guid=guid,
                naam=naam,
                mapping_id=mapping.id,
                actief=True,
            )
            record_audit_event(
                session,
                actor_id=actor_id,
                module=_MODULE,
                tabel="doorbelasting_mapping",
                record_id=mapping.id,
                actie="doorbelasting_mapping_geseed",
                correlatie_id=mapping.id,
                nieuwe_waarde={"doelentiteit": naam, "doel_customer_guid": guid_str},
                administratie_id=administratie_id,
            )
            toegevoegd += 1
    return toegevoegd


def lijst_mappings(*, administratie_id: uuid.UUID) -> list[DoorbelastingMapping]:
    with scoped_session(administratie_id) as session:
        rijen = list(
            session.scalars(
                select(DoorbelastingMapping)
                .where(DoorbelastingMapping.administratie_id == administratie_id)
                .order_by(DoorbelastingMapping.doelentiteit_naam)
            )
        )
        session.expunge_all()
        return rijen


def wijzig_mapping(
    *,
    administratie_id: uuid.UUID,
    mapping_id: uuid.UUID,
    actor_id: uuid.UUID,
    doel_administratie_id: uuid.UUID | None | object = ...,
    intercompany: bool | object = ...,
    provisie_kosten_ledger_id: uuid.UUID | None | object = ...,
    actief: bool | object = ...,
) -> DoorbelastingMapping:
    """Gerichte mapping-mutatie (Beheerder-only via de router); `...` = veld niet wijzigen.
    Elke wijziging in het audit_event met oude én nieuwe waarde (whitelist-mutaties zijn
    autorisatie-gevoelig — mockup: 'Elke wijziging van deze lijst staat in het audit log')."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        mapping = session.get(DoorbelastingMapping, mapping_id)
        if mapping is None or mapping.administratie_id != administratie_id:
            raise DoorbelastingFout("Onbekende mapping voor deze administratie")
        oud = {
            "doel_administratie_id": str(mapping.doel_administratie_id) if mapping.doel_administratie_id else None,
            "intercompany": mapping.intercompany,
            "provisie_kosten_ledger_id": (
                str(mapping.provisie_kosten_ledger_id) if mapping.provisie_kosten_ledger_id else None
            ),
            "actief": mapping.actief,
        }
        if doel_administratie_id is not ...:
            mapping.doel_administratie_id = doel_administratie_id  # type: ignore[assignment]
        if intercompany is not ...:
            mapping.intercompany = bool(intercompany)
        if provisie_kosten_ledger_id is not ...:
            mapping.provisie_kosten_ledger_id = provisie_kosten_ledger_id  # type: ignore[assignment]
        if actief is not ...:
            mapping.actief = bool(actief)
        nieuw = {
            "doel_administratie_id": str(mapping.doel_administratie_id) if mapping.doel_administratie_id else None,
            "intercompany": mapping.intercompany,
            "provisie_kosten_ledger_id": (
                str(mapping.provisie_kosten_ledger_id) if mapping.provisie_kosten_ledger_id else None
            ),
            "actief": mapping.actief,
        }
        # bron-kant IC-rij volgt de vlaggen (blok 2): actief zolang de mapping actief én
        # intercompany is — deactiveren, nooit verwijderen
        upsert_intercompany_tegenpartij(
            session,
            administratie_id=administratie_id,
            entity_guid=mapping.doel_customer_guid,
            naam=mapping.doelentiteit_naam,
            mapping_id=mapping.id,
            actief=mapping.actief and mapping.intercompany,
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module=_MODULE,
            tabel="doorbelasting_mapping",
            record_id=mapping.id,
            actie="doorbelasting_mapping_gewijzigd",
            correlatie_id=mapping.id,
            oude_waarde=oud,
            nieuwe_waarde=nieuw,
            administratie_id=administratie_id,
        )
        session.flush()
        session.expunge(mapping)
        return mapping


def haal_instelling_op(*, administratie_id: uuid.UUID) -> DoorbelastingInstelling:
    """Get-or-default (niet persisted tot de eerste zet): default provisie 5,00%, rest leeg —
    de checks blokkeren boeken zolang btw-tarief/omzet-GB ontbreken."""
    with scoped_session(administratie_id) as session:
        instelling = session.get(DoorbelastingInstelling, administratie_id)
        if instelling is None:
            return DoorbelastingInstelling(administratie_id=administratie_id)
        session.expunge(instelling)
        return instelling


def zet_instelling(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    provisie_percentage: Decimal,
    btw_taxrate_id: uuid.UUID | None,
    omzet_ledger_id: uuid.UUID | None,
    provisie_omzet_ledger_id: uuid.UUID | None,
) -> DoorbelastingInstelling:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        instelling = session.get(DoorbelastingInstelling, administratie_id)
        oud = None
        if instelling is None:
            instelling = DoorbelastingInstelling(administratie_id=administratie_id)
            session.add(instelling)
        else:
            oud = {
                "provisie_percentage": str(instelling.provisie_percentage),
                "btw_taxrate_id": str(instelling.btw_taxrate_id) if instelling.btw_taxrate_id else None,
                "omzet_ledger_id": str(instelling.omzet_ledger_id) if instelling.omzet_ledger_id else None,
                "provisie_omzet_ledger_id": (
                    str(instelling.provisie_omzet_ledger_id) if instelling.provisie_omzet_ledger_id else None
                ),
            }
        instelling.provisie_percentage = provisie_percentage
        instelling.btw_taxrate_id = btw_taxrate_id
        instelling.omzet_ledger_id = omzet_ledger_id
        instelling.provisie_omzet_ledger_id = provisie_omzet_ledger_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module=_MODULE,
            tabel="doorbelasting_instelling",
            record_id=administratie_id,
            actie="doorbelasting_instelling_gewijzigd",
            correlatie_id=administratie_id,
            oude_waarde=oud,
            nieuwe_waarde={
                "provisie_percentage": str(provisie_percentage),
                "btw_taxrate_id": str(btw_taxrate_id) if btw_taxrate_id else None,
                "omzet_ledger_id": str(omzet_ledger_id) if omzet_ledger_id else None,
                "provisie_omzet_ledger_id": str(provisie_omzet_ledger_id) if provisie_omzet_ledger_id else None,
            },
            administratie_id=administratie_id,
        )
        session.flush()
        session.expunge(instelling)
        return instelling


# --- Runs + verdeling -------------------------------------------------------------------


@dataclass(frozen=True)
class VerdeelRegelInvoerData:
    """Eén gewenste verdeelregel zoals de API 'm aanlevert: percentages per (bron-regel,
    doelentiteit); de netto_delen worden hier berekend (grootste-rest), nooit door de client."""

    bron_regel_id: uuid.UUID
    mapping_id: uuid.UUID
    percentage: Decimal
    doel_kosten_ledger_id: uuid.UUID | None


def vind_run(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> DoorbelastingRun | None:
    """Read-only variant (frontend-bevinding 2026-08-13): het documentdetail-scherm moet een
    bestaande run kunnen tonen zónder er bij het louter openen één aan te maken —
    start_of_haal_run is de expliciete gebruikersactie, dit de leesroute."""
    with scoped_session(administratie_id) as session:
        run = session.scalars(
            select(DoorbelastingRun).where(
                DoorbelastingRun.administratie_id == administratie_id,
                DoorbelastingRun.document_id == document_id,
                DoorbelastingRun.status.notin_(INACTIEVE_RUN_STATUSSEN),
            )
        ).one_or_none()
        if run is not None:
            session.expunge(run)
        return run


# Documentstatussen waarop de verdeling al vóór het boeken klaargezet mag worden (besluit
# Peter 25-08): precies de statussen waaruit een boekpoging kan starten (boeken.py) — een
# document met open vraag/afwijzing/accordering krijgt eerst zijn eigen afhandeling.
_KLAARZETBARE_DOCUMENTSTATUSSEN = frozenset(
    {
        DocumentStatus.TE_CONTROLEREN,
        DocumentStatus.KLAAR_OM_TE_BOEKEN,
        DocumentStatus.HANDMATIG_AFMAKEN,
        DocumentStatus.BOEKEN_MISLUKT,
    }
)


def klaargezette_run(session, *, document_id: uuid.UUID) -> DoorbelastingRun | None:
    """De klaargezette (nog niet geboekte) run van een document, of None — de ene leesroute
    voor de orkestratie (boeken + accordering) en de boekvoorstel-herkoppeling."""
    return session.scalars(
        select(DoorbelastingRun).where(
            DoorbelastingRun.document_id == document_id,
            DoorbelastingRun.status == DoorbelastingRunStatus.KLAARGEZET.value,
        )
    ).one_or_none()


def start_of_haal_run(*, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID) -> DoorbelastingRun:
    """Bestaande actieve run teruggeven of een nieuwe aanmaken. Twee ingangen (besluit Peter
    25-08, herziet 13-08): op een GEBOEKT document = de losse actie "Doorbelasten…" (run
    concept, blijft bestaan); op een nog niet geboekt maar boekbaar document = het blok
    "Doorbelasten na boeken" op het controlescherm (run KLAARGEZET — "Boeken + doorbelasten"
    activeert 'm ná de inkoopboeking). Poorten: toggle aan, document van deze administratie,
    inkoopfactuur, status geboekt óf klaarzetbaar."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not administratie.doorbelasting_ingeschakeld:
            raise DoorbelastingFout("Doorbelasting staat uit voor deze administratie")
        document = session.get(Document, document_id)
        if document is None or document.administratie_id != administratie_id:
            raise DoorbelastingFout("Onbekend document voor deze administratie")
        if document.soort != DocumentSoort.INKOOPFACTUUR.value:
            raise DoorbelastingFout("Doorbelasten kan alleen op een inkoopfactuur")
        bestaande = session.scalars(
            select(DoorbelastingRun).where(
                DoorbelastingRun.document_id == document_id,
                DoorbelastingRun.status.notin_(INACTIEVE_RUN_STATUSSEN),
            )
        ).one_or_none()
        if bestaande is not None:
            session.expunge(bestaande)
            return bestaande
        if document.status == DocumentStatus.GEBOEKT:
            status = DoorbelastingRunStatus.CONCEPT.value
            actie = "doorbelasting_run_gestart"
        elif document.status in _KLAARZETBARE_DOCUMENTSTATUSSEN:
            status = DoorbelastingRunStatus.KLAARGEZET.value
            actie = "doorbelasting_run_klaargezet"
        else:
            raise DoorbelastingFout(
                f"Doorbelasten kan niet vanuit status {document.status.value} — alleen op een geboekt "
                "of boekbaar document"
            )
        run = DoorbelastingRun(
            administratie_id=administratie_id, document_id=document_id, aangemaakt_door=actor_id, status=status
        )
        session.add(run)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module=_MODULE,
            tabel="doorbelasting_run",
            record_id=run.id,
            actie=actie,
            correlatie_id=document_id,
            nieuwe_waarde={"document_id": str(document_id), "status": status},
            administratie_id=administratie_id,
        )
        session.expunge(run)
        return run


def laat_run_vervallen(*, administratie_id: uuid.UUID, run_id: uuid.UUID, actor_id: uuid.UUID) -> DoorbelastingRun:
    """Het vinkje "Doorbelasten na boeken" gaat weer uit vóór het boeken: de klaargezette run
    wordt VERVALLEN (nooit een delete — spoor + audit blijven), de verdeelregels blijven eraan
    hangen als historie. Alleen vanaf KLAARGEZET; een run met boekingen kan nooit vervallen."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        run = session.get(DoorbelastingRun, run_id)
        if run is None or run.administratie_id != administratie_id:
            raise RunNietGevonden("Onbekende run voor deze administratie")
        if run.status != DoorbelastingRunStatus.KLAARGEZET.value or _run_heeft_actieve_boeking(session, run_id):
            raise VerdelingBevroren("Alleen een klaargezette (nog niet geboekte) doorbelasting kan vervallen")
        document = session.get(Document, run.document_id)
        if document is not None and document.status == DocumentStatus.TER_ACCORDERING:
            raise VerdelingBevroren("Het document ligt bij de klant ter accordering — verdeling is bevroren")
        run.status = DoorbelastingRunStatus.VERVALLEN.value
        record_audit_event(
            session,
            actor_id=actor_id,
            module=_MODULE,
            tabel="doorbelasting_run",
            record_id=run.id,
            actie="doorbelasting_run_vervallen",
            correlatie_id=run.document_id,
            oude_waarde={"status": DoorbelastingRunStatus.KLAARGEZET.value},
            nieuwe_waarde={"status": run.status},
            administratie_id=administratie_id,
        )
        session.flush()
        session.expunge(run)
        return run


def activeer_klaargezette_run(session, *, run: DoorbelastingRun, actor_id: uuid.UUID) -> None:
    """Ná een geslaagde inkoopboeking: KLAARGEZET → CONCEPT, zodat de bestaande motor de run
    exact behandelt als een run uit de losse "Doorbelasten…"-actie. In de sessie van de
    aanroeper (orkestratie), mét audit."""
    run.status = DoorbelastingRunStatus.CONCEPT.value
    record_audit_event(
        session,
        actor_id=actor_id,
        module=_MODULE,
        tabel="doorbelasting_run",
        record_id=run.id,
        actie="doorbelasting_run_geactiveerd_na_boeken",
        correlatie_id=run.document_id,
        oude_waarde={"status": DoorbelastingRunStatus.KLAARGEZET.value},
        nieuwe_waarde={"status": run.status},
        administratie_id=run.administratie_id,
    )


@dataclass(frozen=True)
class VerdelingSnapshot:
    """Klaargezette verdeling losgekoppeld van regel-id's (per volgnummer) — de brug over de
    delete+insert van de boekvoorstel-regels heen."""

    run_id: uuid.UUID
    administratie_id: uuid.UUID
    regels: tuple[tuple[int | None, uuid.UUID, Decimal, uuid.UUID | None], ...]


def neem_klaargezette_verdeling_los(session, *, document_id: uuid.UUID) -> VerdelingSnapshot | None:
    """Het boekvoorstel vervangt zijn regels bij elke opslag (delete + insert → nieuwe id's).
    Een KLAARGEZETTE verdeling verwijst per regel-id en zou dan op de FK stranden. Deze hook
    (aangeroepen vanuit sla_boekvoorstel_op, vóór de delete) legt de verdeling per VOLGNUMMER
    vast en verwijdert de oude verdeelregels; `zet_klaargezette_verdeling_terug` hangt ze ná
    de insert aan de nieuwe regels. None = geen klaargezette run, niets te doen."""
    run = klaargezette_run(session, document_id=document_id)
    if run is None:
        return None
    oude_regels = list(session.scalars(select(DoorbelastingRegel).where(DoorbelastingRegel.run_id == run.id)))
    if not oude_regels:
        return None
    volgnummer_per_id = {
        r.id: r.volgnummer
        for r in session.scalars(select(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id == document_id))
    }
    snapshot = VerdelingSnapshot(
        run_id=run.id,
        administratie_id=run.administratie_id,
        regels=tuple(
            (volgnummer_per_id.get(r.bron_regel_id), r.mapping_id, r.percentage, r.doel_kosten_ledger_id)
            for r in oude_regels
        ),
    )
    for oud in oude_regels:
        session.delete(oud)
    session.flush()
    return snapshot


def zet_klaargezette_verdeling_terug(
    session, *, snapshot: VerdelingSnapshot | None, nieuwe_regels: dict[int, uuid.UUID]
) -> None:
    """Tweede helft: zelfde volgnummer = zelfde verdeling, netto-delen opnieuw berekend op het
    nieuwe regelbedrag (grootste-rest, als sla_verdeling_op); een verdeelde regel die verdwenen
    is, verliest zijn verdeling ZICHTBAAR (preview/checks tonen dat) — nooit stil."""
    if snapshot is None or not nieuwe_regels:
        return
    bron_regels = {
        r.id: r
        for r in session.scalars(
            select(BoekvoorstelRegel).where(BoekvoorstelRegel.id.in_(list(nieuwe_regels.values())))
        )
    }
    per_bron: dict[uuid.UUID, list[tuple[uuid.UUID, Decimal, uuid.UUID | None]]] = {}
    for volgnummer, mapping_id, percentage, gb in snapshot.regels:
        nieuw_id = nieuwe_regels.get(volgnummer) if volgnummer is not None else None
        if nieuw_id is None:
            continue
        per_bron.setdefault(nieuw_id, []).append((mapping_id, percentage, gb))
    for bron_regel_id, groep in per_bron.items():
        bron_netto = bron_regels[bron_regel_id].netto_bedrag or Decimal(0)
        delen = _bereken_delen(bron_netto, [g[1] for g in groep])
        for (mapping_id, percentage, gb), deel in zip(groep, delen, strict=True):
            session.add(
                DoorbelastingRegel(
                    run_id=snapshot.run_id,
                    administratie_id=snapshot.administratie_id,
                    bron_regel_id=bron_regel_id,
                    mapping_id=mapping_id,
                    percentage=percentage,
                    netto_deel=deel,
                    doel_kosten_ledger_id=gb,
                )
            )
    session.flush()


def _bereken_delen(bron_netto: Decimal, percentages: list[Decimal]) -> list[Decimal]:
    """Grootste-rest bij exact 100%, anders naar rato (werkstaat — de harde check blokkeert)."""
    if sum(percentages) == Decimal(100):
        return verdeel_grootste_rest(bron_netto, percentages)
    return [(bron_netto * pct / Decimal(100)).quantize(Decimal("0.01")) for pct in percentages]


def _run_heeft_actieve_boeking(session, run_id: uuid.UUID) -> bool:
    return (
        session.scalar(
            select(func.count())
            .select_from(DoorbelastingBoeking)
            .where(
                DoorbelastingBoeking.run_id == run_id,
                DoorbelastingBoeking.status != DoorbelastingBoekingStatus.GESTORNEERD.value,
            )
        )
        > 0
    )


def sla_verdeling_op(
    *,
    administratie_id: uuid.UUID,
    run_id: uuid.UUID,
    regels: list[VerdeelRegelInvoerData],
    actor_id: uuid.UUID,
) -> list[DoorbelastingRegel]:
    """Vervangt de verdeelregels van een concept-run. De netto_delen worden hier — en alleen
    hier — berekend met de grootste-rest-methode per bron-regel (mockup: "er raakt nooit een
    cent kwijt"); percentages die niet op 100% sommen zijn géén fout bij opslaan (werkstaat),
    maar blokkeren straks als harde check bij boeken."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        run = session.get(DoorbelastingRun, run_id)
        if run is None or run.administratie_id != administratie_id:
            raise RunNietGevonden("Onbekende run voor deze administratie")
        if run.status not in (
            DoorbelastingRunStatus.CONCEPT.value,
            DoorbelastingRunStatus.KLAARGEZET.value,
        ) or _run_heeft_actieve_boeking(session, run_id):
            raise VerdelingBevroren("Deze doorbelasting is (deels) geboekt — verdeling is bevroren")
        # Klaargezette verdeling bij de klant (A3): de accordeur beoordeelt precies wat hij ziet —
        # tot het besluit is de verdeling bevroren (afwijzen zet het document terug, dan mag het weer).
        document = session.get(Document, run.document_id)
        if document is not None and document.status == DocumentStatus.TER_ACCORDERING:
            raise VerdelingBevroren("Het document ligt bij de klant ter accordering — verdeling is bevroren")

        bron_regels = {
            r.id: r
            for r in session.scalars(
                select(BoekvoorstelRegel).where(
                    BoekvoorstelRegel.document_id == run.document_id,
                )
            )
        }
        mappings = {
            m.id: m
            for m in session.scalars(
                select(DoorbelastingMapping).where(DoorbelastingMapping.administratie_id == administratie_id)
            )
        }
        for invoer in regels:
            if invoer.bron_regel_id not in bron_regels:
                raise DoorbelastingFout(f"Onbekende bron-regel {invoer.bron_regel_id}")
            if invoer.mapping_id not in mappings:
                # Server-side whitelist: een doelentiteit buiten de mapping bestaat niet.
                raise DoorbelastingFout(f"Doelentiteit {invoer.mapping_id} staat niet op de whitelist")

        for oud in session.scalars(select(DoorbelastingRegel).where(DoorbelastingRegel.run_id == run_id)):
            session.delete(oud)
        # De deletes moeten de database bereiken vóór de vervangende rijen: SQLAlchemy flusht
        # inserts vóór deletes, en een heropslag hergebruikt dezelfde (run, bron-regel,
        # mapping)-combinaties — zonder deze flush klapt de unieke index
        # doorbelasting_regel_uniek (kliktest-bevinding Peter 2026-08-16).
        session.flush()

        nieuw: list[DoorbelastingRegel] = []
        # grootste-rest per bron-regel, in stabiele invoervolgorde per regel
        per_bron: dict[uuid.UUID, list[VerdeelRegelInvoerData]] = {}
        for invoer in regels:
            per_bron.setdefault(invoer.bron_regel_id, []).append(invoer)
        for bron_regel_id, groep in per_bron.items():
            bron_netto = bron_regels[bron_regel_id].netto_bedrag
            if bron_netto is None:
                raise DoorbelastingFout(f"Bron-regel {bron_regel_id} heeft geen nettobedrag")
            # grootste-rest bij exact 100%; werkstaat (nog niet op 100%) naar rato — de harde
            # check blokkeert het boeken dan
            delen = _bereken_delen(bron_netto, [g.percentage for g in groep])
            for invoer, deel in zip(groep, delen, strict=True):
                regel = DoorbelastingRegel(
                    run_id=run_id,
                    administratie_id=administratie_id,
                    bron_regel_id=invoer.bron_regel_id,
                    mapping_id=invoer.mapping_id,
                    percentage=invoer.percentage,
                    netto_deel=deel,
                    doel_kosten_ledger_id=invoer.doel_kosten_ledger_id,
                )
                session.add(regel)
                nieuw.append(regel)
        session.flush()
        for regel in nieuw:
            session.expunge(regel)
        return nieuw


@dataclass(frozen=True)
class DoelentiteitPreview:
    mapping_id: uuid.UUID
    doelentiteit_naam: str
    onboarded: bool
    netto_totaal: Decimal
    provisie_bedrag: Decimal
    btw_bedrag: Decimal
    boeking_status: str | None  # status van een bestaande niet-gestorneerde boeking
    boeking_id: uuid.UUID | None  # id daarvan — nodig voor storno/spiegel-acties in de UI


@dataclass(frozen=True)
class RunReviewData:
    run: DoorbelastingRun
    regels: list[DoorbelastingRegel]
    previews: list[DoelentiteitPreview]
    rapport: CheckRapport


def _check_invoer(
    session, run: DoorbelastingRun
) -> tuple[list[VerdeelRegelInvoer], dict[uuid.UUID, MappingInvoer], DoorbelastingInstelling]:
    regels = list(session.scalars(select(DoorbelastingRegel).where(DoorbelastingRegel.run_id == run.id)))
    bron_regels = {
        r.id: r
        for r in session.scalars(select(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id == run.document_id))
    }
    mappings = {
        m.id: MappingInvoer(
            mapping_id=m.id,
            actief=m.actief,
            doel_administratie_id=m.doel_administratie_id,
            provisie_kosten_ledger_id=m.provisie_kosten_ledger_id,
            doel_customer_guid=m.doel_customer_guid,
        )
        for m in session.scalars(
            select(DoorbelastingMapping).where(DoorbelastingMapping.administratie_id == run.administratie_id)
        )
    }
    instelling = session.get(DoorbelastingInstelling, run.administratie_id) or DoorbelastingInstelling(
        administratie_id=run.administratie_id
    )
    invoer = [
        VerdeelRegelInvoer(
            bron_regel_id=r.bron_regel_id,
            bron_netto=bron_regels[r.bron_regel_id].netto_bedrag or Decimal(0),
            mapping_id=r.mapping_id,
            percentage=r.percentage,
            netto_deel=r.netto_deel,
            doel_kosten_ledger_id=r.doel_kosten_ledger_id,
        )
        for r in regels
    ]
    return invoer, mappings, instelling


def review_data(*, administratie_id: uuid.UUID, run_id: uuid.UUID) -> RunReviewData:
    """Alles wat het reviewscherm nodig heeft: verdeelregels, provisie-preview per doelentiteit
    (berekend, mockup: "provisieregel automatisch berekend") en het actuele checks-rapport."""
    with scoped_session(administratie_id) as session:
        run = session.get(DoorbelastingRun, run_id)
        if run is None or run.administratie_id != administratie_id:
            raise RunNietGevonden("Onbekende run voor deze administratie")
        invoer, mappings, instelling = _check_invoer(session, run)
        rapport = voer_doorbelasting_checks_uit(
            regels=invoer,
            mappings=mappings,
            provisie_percentage=instelling.provisie_percentage,
            btw_taxrate_id=instelling.btw_taxrate_id,
            omzet_ledger_id=instelling.omzet_ledger_id,
            anker_customer_guid=anker_customer_id(administratie_id),
        )
        naam_per_mapping = {
            m.id: m
            for m in session.scalars(
                select(DoorbelastingMapping).where(DoorbelastingMapping.administratie_id == administratie_id)
            )
        }
        boekingen = {
            b.mapping_id: (b.status, b.id)
            for b in session.scalars(
                select(DoorbelastingBoeking).where(
                    DoorbelastingBoeking.run_id == run_id,
                    DoorbelastingBoeking.status != DoorbelastingBoekingStatus.GESTORNEERD.value,
                )
            )
        }
        from app.doorbelasting.geld import btw_over  # lokale import: geen kringgevaar, wel dichtbij
        from app.sync.models import TaxRateCache

        # btw-preview op het gecónfigureerde tarief (cache draagt de fractie, 0.2100 → 21,00);
        # geen tarief geconfigureerd/gesynct → preview 0, de harde check blokkeert boeken toch al
        btw_pct = Decimal(0)
        if instelling.btw_taxrate_id is not None:
            tarief = session.get(TaxRateCache, (instelling.btw_taxrate_id, administratie_id))
            if tarief is not None and tarief.percentage is not None:
                btw_pct = (tarief.percentage * Decimal(100)).quantize(Decimal("0.01"))

        previews: list[DoelentiteitPreview] = []
        per_mapping: dict[uuid.UUID, Decimal] = {}
        for r in invoer:
            per_mapping[r.mapping_id] = per_mapping.get(r.mapping_id, Decimal(0)) + r.netto_deel
        for mapping_id, netto in sorted(per_mapping.items(), key=lambda kv: str(kv[0])):
            mapping = naam_per_mapping.get(mapping_id)
            provisie = provisie_over(netto, instelling.provisie_percentage)
            # btw-preview: per regel afgerond, zoals de motor 'm boekt
            btw = sum(
                (btw_over(r.netto_deel, btw_pct) for r in invoer if r.mapping_id == mapping_id),
                Decimal(0),
            ) + btw_over(provisie, btw_pct)
            boeking_status, boeking_id = boekingen.get(mapping_id, (None, None))
            previews.append(
                DoelentiteitPreview(
                    mapping_id=mapping_id,
                    doelentiteit_naam=mapping.doelentiteit_naam if mapping else "?",
                    onboarded=bool(mapping and mapping.doel_administratie_id),
                    netto_totaal=netto,
                    provisie_bedrag=provisie,
                    btw_bedrag=btw,
                    boeking_status=boeking_status,
                    boeking_id=boeking_id,
                )
            )
        regels = list(session.scalars(select(DoorbelastingRegel).where(DoorbelastingRegel.run_id == run_id)))
        session.expunge_all()
        return RunReviewData(run=run, regels=regels, previews=previews, rapport=rapport)


def zet_spiegel_doel_gbs(
    *,
    administratie_id: uuid.UUID,
    boeking_id: uuid.UUID,
    actor_id: uuid.UUID,
    regel_gbs: dict[uuid.UUID, uuid.UUID],
    provisie_kosten_ledger_id: uuid.UUID | None = None,
) -> None:
    """Gerichte GB-toewijzing voor een open spiegel-taak (gaten-scan 2026-08-13): de verdeling
    zelf is bevroren zodra er geboekt is (bedragen mogen nooit meer schuiven), maar de
    doel-kosten-GB's per verdeelregel en de provisie-GB op de mapping zijn juist pas kiesbaar
    ná onboarding van de doel-administratie — zonder deze route zou een spiegel_open-taak
    permanent vastzitten. Muteert uitsluitend GB-velden, nooit percentages of bedragen."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        boeking = session.get(DoorbelastingBoeking, boeking_id)
        if boeking is None or boeking.administratie_id != administratie_id:
            raise DoorbelastingFout("Onbekende doorbelastings-boeking")
        if boeking.status != DoorbelastingBoekingStatus.SPIEGEL_OPEN.value:
            raise DoorbelastingFout("Doel-GB's zijn alleen te zetten op een open spiegel-taak")
        regels = {
            r.id: r
            for r in session.scalars(
                select(DoorbelastingRegel).where(
                    DoorbelastingRegel.run_id == boeking.run_id,
                    DoorbelastingRegel.mapping_id == boeking.mapping_id,
                )
            )
        }
        onbekend = set(regel_gbs) - set(regels)
        if onbekend:
            raise DoorbelastingFout(f"Onbekende verdeelregel(s) voor deze spiegel-taak: {sorted(map(str, onbekend))}")
        oud = {
            str(rid): (str(r.doel_kosten_ledger_id) if r.doel_kosten_ledger_id else None) for rid, r in regels.items()
        }
        for regel_id, ledger_id in regel_gbs.items():
            regels[regel_id].doel_kosten_ledger_id = ledger_id
        if provisie_kosten_ledger_id is not None:
            mapping = session.get(DoorbelastingMapping, boeking.mapping_id)
            if mapping is not None:
                mapping.provisie_kosten_ledger_id = provisie_kosten_ledger_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module=_MODULE,
            tabel="doorbelasting_boeking",
            record_id=boeking_id,
            actie="doorbelasting_spiegel_gbs_gezet",
            correlatie_id=boeking.document_id,
            oude_waarde=oud,
            nieuwe_waarde={
                **{str(rid): str(lid) for rid, lid in regel_gbs.items()},
                **(
                    {"provisie_kosten_ledger_id": str(provisie_kosten_ledger_id)}
                    if provisie_kosten_ledger_id is not None
                    else {}
                ),
            },
            administratie_id=administratie_id,
        )


def open_spiegel_taken(*, administratie_id: uuid.UUID) -> list[DoorbelastingBoeking]:
    """De zichtbare open taken "spiegel boeken in <entiteit>" — bron-kant geboekt, doel nog
    niet onboarded op boekmoment (opdracht 1c: nooit stil half)."""
    with scoped_session(administratie_id) as session:
        rijen = list(
            session.scalars(
                select(DoorbelastingBoeking)
                .where(
                    DoorbelastingBoeking.administratie_id == administratie_id,
                    DoorbelastingBoeking.status == DoorbelastingBoekingStatus.SPIEGEL_OPEN.value,
                )
                .order_by(DoorbelastingBoeking.aangemaakt_op)
            )
        )
        session.expunge_all()
        return rijen


def actor_heeft_scope(*, actor_id: uuid.UUID, administratie_id: uuid.UUID) -> bool:
    """Server-side scope-toets voor de DOEL-kant (mockup: "een medewerker kan alleen
    doorbelasten naar administraties waarop hij zelf scope heeft"); Beheerder = alles
    (bestaand rolmodel). Bewust in de platform-scope (scoped_session(None)) — de
    koppeltabel is geen administratie-gescoped gegeven."""
    # Systeem-actor (besluit 25-08, boeken ná het laatste klant-akkoord): geen mens, geen
    # scope-rij — de menselijke trigger (aanbieden ter accordering) is op dat moment al op
    # doel-scope getoetst (orkestratie.toets_klaargezette_doorbelasting), dus hier door.
    if actor_id == SYSTEEM_ACTOR_ID:
        return True
    with scoped_session(None) as session:
        gebruiker = session.get(Gebruiker, actor_id)
        if gebruiker is not None and gebruiker.rol == GebruikerRol.BEHEERDER:
            return True
        koppel = session.scalar(
            select(func.count())
            .select_from(GebruikerAdministratie)
            .where(
                GebruikerAdministratie.gebruiker_id == actor_id,
                GebruikerAdministratie.administratie_id == administratie_id,
            )
        )
        return bool(koppel)
