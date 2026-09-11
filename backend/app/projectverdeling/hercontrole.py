"""Hercontrole van geboekte pro-rato-verdelingen (ontwerpnotitie ⑥): de omzetstand van DEZELFDE maand kan ná het
boeken nog wijzigen (nagekomen verkoopfactuur, creditnota). De job rekent de verdeling opnieuw uit tegen de
actuele omzetstand; afwijking = max |deel_nieuw − deel_oud| / restant (in %). Boven de administratie-drempel
(`projectverdeling_drempel_pct`, default 5) = SIGNAAL mét actie: `hercontrole_verdeling` gevuld, tijdlijnregel
`projectverdeling_afwijking` (eenmalig per signaal — idempotent), audit; de rij-chip "verdeling wijkt x % af" en
de banner "Herverdelen…" lezen hieruit. Onder de drempel (óók 0 %) wordt alleen `hercontrole_op` + het percentage
ververst — nooit een signaal.

CADANS — HERZIEN blok 10 herstelrun 08-09 (Universal: 5 valse signalen op de dag van boeken): een verdeling wordt pas
hercontroleerd (1) ná AFSLUITING van de referentieperiode (maand: vanaf de 1e van de volgende maand; jaar: de
afgesloten maanden — altijd "af"), (2) NOOIT in de kalendermaand waarin het document geboekt is (de omzet van die
maand is nog in beweging en de boeking is vers) en (3) hooguit ÉÉN keer per kalendermaand per document
(`hercontrole_op` legt vast wat al gecontroleerd is; `forceer` heft alleen déze regel op). Meeliftend in
`sync-alles` (dagelijks), los via CLI `projectverdeling-hercontrole [--forceer]`. Puur code, geen RLZ-/Odoo-calls.

OMZET ONTBREEKT (blok 10): geen enkel project mét omzet in de referentieperiode = GEEN herverdeling (er valt niets
te berekenen) maar een eigen, zichtbare bevinding `hercontrole_bevinding = 'omzet_ontbreekt'` (migratie 0124) mét
tijdlijnregel "omzetcijfers ontbreken voor ‹periode›" + audit, teller `omzet_ontbreekt`; de actie is de bestaande
cijfers-sync-achtergrondrun (`POST /projecten/{administratie}/cijfers-sync`), herverdelen is geblokkeerd tot er
cijfers zijn. Komen er cijfers, dan vervalt de bevinding bij de eerstvolgende ronde (audit) en telt de gewone
afwijkingsregel."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Document, DocumentGebeurtenis, DocumentStatus, Tegenboeking
from app.projectverdeling import data as pv
from app.projectverdeling.models import Projectverdeling
from app.projectverdeling.omzet import omzet_per_project, projectnamen
from app.tijd import vandaag_nl

logger = logging.getLogger(__name__)

BEVINDING_OMZET_ONTBREEKT = "omzet_ontbreekt"


def _zelfde_maand(a: date | datetime | None, b: date) -> bool:
    return a is not None and (a.year, a.month) == (b.year, b.month)


def moet_herrekenen(
    *,
    hercontrole_op: datetime | None,
    geboekt_op: datetime | None,
    periode: pv.Periode,
    vandaag: date,
    forceer: bool,
) -> bool:
    """Pure cadans-regel (blok 10 08-09): (1) de referentieperiode moet AF zijn — maand: vanaf de 1e van de
    volgende maand; jaar: de afgesloten maanden tellen, dus altijd af zodra er één is; (2) nooit in de kalendermaand
    van het boeken; (3) hooguit één keer per kalendermaand per document — `forceer` heft alleen (3) op."""
    if _zelfde_maand(geboekt_op, vandaag):
        return False
    if not periode.is_jaar and vandaag < pv.periode_eind(periode, vandaag):
        return False
    if periode.is_jaar and pv.laatste_afgesloten_maand(periode, vandaag) == 0:
        return False
    if forceer or hercontrole_op is None:
        return True
    return not _zelfde_maand(hercontrole_op, vandaag)


def _al_tegengeboekt(session: Session, row: Projectverdeling) -> bool:
    if row.boek_cyclus is None:
        return False
    return session.get(Tegenboeking, (row.document_id, row.boek_cyclus)) is not None


def herbereken_administratie(
    *, administratie_id: uuid.UUID, vandaag: date | None = None, forceer: bool = False
) -> dict:
    # `hercontrole_op` volgt de peildatum (in productie = vandaag; een expliciete `vandaag` — CLI/tests — schuift het
    # tijdstip mee zodat de regel "één keer per kalendermaand" tegen dezelfde kalender toetst).
    nu = datetime.now(UTC) if vandaag is None else datetime.combine(vandaag, datetime.now(UTC).timetz())
    vandaag = vandaag or vandaag_nl()
    tellers = {"beoordeeld": 0, "herrekend": 0, "signalen": 0, "overgeslagen": 0, "omzet_ontbreekt": 0}
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        administratie = session.get(Administratie, administratie_id)
        drempel = administratie.projectverdeling_drempel_pct if administratie else Decimal("5.00")
        # Blok 10: rijen van vóór 08-09 dragen JSON `null` (geen SQL NULL) — de ORM laadt dat als None en schrijft een
        # hernieuwde `= None` dus NIET weg. Eén idempotente normalisatie per ronde, zodat ook `IS NOT NULL`-lezers van
        # buiten (rapportages) nooit meer een vals signaal zien.
        session.execute(
            update(Projectverdeling)
            .where(
                Projectverdeling.administratie_id == administratie_id,
                func.jsonb_typeof(Projectverdeling.hercontrole_verdeling) == "null",
            )
            .values(hercontrole_verdeling=None)
        )
        rijen = session.scalars(
            select(Projectverdeling)
            .join(Document, Document.id == Projectverdeling.document_id)
            .where(
                Projectverdeling.administratie_id == administratie_id,
                Projectverdeling.status == pv.STATUS_GEBOEKT,
                Projectverdeling.pro_rato_periode.is_not(None),
                Document.status == DocumentStatus.GEBOEKT,
            )
        ).all()
        omzet_cache: dict[pv.Periode, list[pv.Omzetstand]] = {}
        for row in rijen:
            tellers["beoordeeld"] += 1
            if _al_tegengeboekt(session, row) or row.pro_rato_bedrag is None or row.pro_rato_periode is None:
                tellers["overgeslagen"] += 1
                continue
            periode = pv.Periode.uit_opslag(row.pro_rato_periode, row.pro_rato_soort)
            assert periode is not None
            if not moet_herrekenen(
                hercontrole_op=row.hercontrole_op,
                geboekt_op=row.geboekt_op,
                periode=periode,
                vandaag=vandaag,
                forceer=forceer,
            ):
                tellers["overgeslagen"] += 1
                continue
            # Maand: dezelfde maand, actuele stand. Jaar (D4 07-09, notitie ⑩): de ACTUELE jaarstand — de
            # afgesloten maanden t/m de vorige maand van `vandaag`; er komen dus maanden bij, en die
            # verschuiving wordt met dezelfde drempel zichtbaar.
            if periode not in omzet_cache:
                omzet_cache[periode] = omzet_per_project(
                    session, administratie_id=administratie_id, periode=periode, vandaag=vandaag
                ).standen
            standen = omzet_cache[periode]
            oud = pv.delen_uit_json(row.verdeling)
            vast = [d for d in oud if d.wijze == pv.WIJZE_VAST]
            was_signaal = row.hercontrole_verdeling is not None
            if not standen:
                # Blok 10: geen enkel project mét omzet in die periode → geen herverdeling te berekenen, maar wél een
                # eigen zichtbare bevinding (nooit stil, nooit een vals signaal met een halve/lege verdeling).
                al_bevinding = row.hercontrole_bevinding == BEVINDING_OMZET_ONTBREEKT
                row.hercontrole_op = nu
                row.hercontrole_afwijking_pct = None
                row.hercontrole_verdeling = None
                row.hercontrole_bevinding = BEVINDING_OMZET_ONTBREEKT
                tellers["omzet_ontbreekt"] += 1
                if was_signaal:
                    _signaal_weg(session, administratie_id=administratie_id, row=row, pct=None, drempel=drempel)
                if not al_bevinding:
                    _bevinding_omzet_ontbreekt(
                        session, administratie_id=administratie_id, row=row, periode=periode, vandaag=vandaag
                    )
                continue
            if row.pro_rato_bedrag == 0:
                # Niets pro rato te verdelen (restant 0): geen deling, geen signaal — alleen de controle vastleggen.
                row.hercontrole_op = nu
                row.hercontrole_afwijking_pct = Decimal("0.00")
                row.hercontrole_verdeling = None
                tellers["herrekend"] += 1
                continue
            try:
                nieuw_pro_rato = pv.verdeel_pro_rato(row.pro_rato_bedrag, standen)
            except Exception as exc:  # noqa: BLE001 — één kapotte rij stopt de ronde niet
                logger.warning("Hercontrole overgeslagen voor %s: %s", row.document_id, exc)
                tellers["overgeslagen"] += 1
                continue
            nieuw = [*vast, *nieuw_pro_rato]
            pct = pv.afwijking_pct(oud, nieuw, row.pro_rato_bedrag)
            vorige_pct = row.hercontrole_afwijking_pct
            had_bevinding = row.hercontrole_bevinding is not None
            row.hercontrole_op = nu
            row.hercontrole_afwijking_pct = pct
            row.hercontrole_bevinding = None
            tellers["herrekend"] += 1
            if had_bevinding:
                _bevinding_weg(session, administratie_id=administratie_id, row=row, periode=periode)
            if pct > drempel:
                row.hercontrole_verdeling = pv.delen_naar_json(nieuw)
                tellers["signalen"] += 1
                if not was_signaal or vorige_pct != pct:
                    _signaleer(
                        session,
                        administratie_id=administratie_id,
                        row=row,
                        pct=pct,
                        drempel=drempel,
                        standen=standen,
                        periode=periode,
                        vandaag=vandaag,
                    )
            else:
                row.hercontrole_verdeling = None
                if was_signaal:
                    _signaal_weg(session, administratie_id=administratie_id, row=row, pct=pct, drempel=drempel)
    return tellers


def bevinding_tekst(periode: pv.Periode, vandaag: date | None = None) -> str:
    """Leesbare bevinding — dezelfde zin in tijdlijn, lijst en controlescherm."""
    return f"omzetcijfers ontbreken voor {pv.periode_label(periode, vandaag)}"


def _bevinding_omzet_ontbreekt(
    session: Session, *, administratie_id: uuid.UUID, row: Projectverdeling, periode: pv.Periode, vandaag: date
) -> None:
    document = session.get(Document, row.document_id)
    assert document is not None
    tekst = bevinding_tekst(periode, vandaag)
    reden = (
        f"hercontrole: {tekst} — geen enkel project met omzet in de omzet-cache voor deze periode; er is geen nieuwe "
        "verdeling berekend. Actie: cijfers-sync starten (Projecten › cijfers verversen); herverdelen is geblokkeerd "
        "tot er cijfers zijn"
    )
    detail = {
        "projectverdeling_omzet_ontbreekt": {
            "periode": periode.code,
            "periode_label": pv.periode_label(periode, vandaag),
            "bevinding": BEVINDING_OMZET_ONTBREEKT,
            "tekst": tekst,
        },
        "reden": reden,
    }
    session.add(
        DocumentGebeurtenis(
            document_id=row.document_id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=SYSTEEM_ACTOR_ID,
            detail=detail,
        )
    )
    record_audit_event(
        session,
        actor_id=SYSTEEM_ACTOR_ID,
        module="boekhouding",
        tabel="projectverdeling",
        record_id=row.document_id,
        actie="projectverdeling_omzet_ontbreekt",
        correlatie_id=uuid.uuid4(),
        oude_waarde={"verdeling": row.verdeling},
        nieuwe_waarde=detail["projectverdeling_omzet_ontbreekt"],
        administratie_id=administratie_id,
    )


def _bevinding_weg(
    session: Session, *, administratie_id: uuid.UUID, row: Projectverdeling, periode: pv.Periode
) -> None:
    record_audit_event(
        session,
        actor_id=SYSTEEM_ACTOR_ID,
        module="boekhouding",
        tabel="projectverdeling",
        record_id=row.document_id,
        actie="projectverdeling_omzet_ontbreekt_vervallen",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={"periode": periode.code},
        administratie_id=administratie_id,
    )


def _signaleer(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    row: Projectverdeling,
    pct,
    drempel,
    standen: list[pv.Omzetstand],
    periode: pv.Periode,
    vandaag: date,
) -> None:
    document = session.get(Document, row.document_id)
    assert document is not None
    namen = projectnamen(session, administratie_id=administratie_id, project_ids={s.project_id for s in standen})
    if periode.is_jaar:
        bevroren = pv.periode_label(periode, row.geboekt_op.date() if row.geboekt_op else None)
        omschrijving = (
            f"jaaromzet {periode.code} (bij boeken {bevroren}, nu {pv.periode_label(periode, vandaag)}) is ná het "
            "boeken gewijzigd"
        )
    else:
        omschrijving = f"omzet {pv.periode_label(periode)} is ná het boeken gewijzigd"
    reden = (
        f"hercontrole: {omschrijving} — de projectverdeling wijkt nu {pct} % af "
        f"(drempel {drempel} %); herverdelen = tegenboeken + nieuwe verdeling, mens bevestigt"
    )
    detail = {
        "projectverdeling_afwijking": {
            "afwijking_pct": str(pct),
            "drempel_pct": str(drempel),
            "periode": periode.code,
            "periode_label": pv.periode_label(periode, vandaag),
            "nieuwe_verdeling": row.hercontrole_verdeling,
            "omzetstanden_nu": [
                {"project_id": str(s.project_id), "omzet": str(s.omzet), "naam": namen.get(s.project_id)}
                for s in standen
            ],
        },
        "reden": reden,
    }
    session.add(
        DocumentGebeurtenis(
            document_id=row.document_id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=SYSTEEM_ACTOR_ID,
            detail=detail,
        )
    )
    record_audit_event(
        session,
        actor_id=SYSTEEM_ACTOR_ID,
        module="boekhouding",
        tabel="projectverdeling",
        record_id=row.document_id,
        actie="projectverdeling_afwijking",
        correlatie_id=uuid.uuid4(),
        oude_waarde={"verdeling": row.verdeling},
        nieuwe_waarde=detail["projectverdeling_afwijking"],
        administratie_id=administratie_id,
    )


def _signaal_weg(session: Session, *, administratie_id: uuid.UUID, row: Projectverdeling, pct, drempel) -> None:
    record_audit_event(
        session,
        actor_id=SYSTEEM_ACTOR_ID,
        module="boekhouding",
        tabel="projectverdeling",
        record_id=row.document_id,
        actie="projectverdeling_afwijking_vervallen",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={"afwijking_pct": None if pct is None else str(pct), "drempel_pct": str(drempel)},
        administratie_id=administratie_id,
    )


def herbereken_alle(*, vandaag: date | None = None, forceer: bool = False) -> dict[uuid.UUID, dict | str]:
    """Alle actieve administraties; één kapotte administratie stopt de rest niet (fout = leesbare string)."""
    with scoped_session(None) as session:
        ids = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))))
    resultaten: dict[uuid.UUID, dict | str] = {}
    for administratie_id in ids:
        try:
            resultaten[administratie_id] = herbereken_administratie(
                administratie_id=administratie_id, vandaag=vandaag, forceer=forceer
            )
        except Exception as exc:  # noqa: BLE001 — zichtbaar in het rapport, nooit stil
            logger.exception("Projectverdeling-hercontrole mislukt voor %s", administratie_id)
            resultaten[administratie_id] = str(exc)
    return resultaten
