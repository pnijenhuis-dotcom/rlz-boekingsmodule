"""Backfill van de factuurperiode-kolommen op `boekvoorstel` (blok 7 bundel 08-09; BESLISSINGEN "FACTUURPERIODE
WEEKNIVEAU — DATALAAG" beslispunt 4: "backfill al geboekte documenten vóór 0120").

Migratie 0120 (07-09) voegde `periode_jaar/-week_van/-week_tot/-herkomst/-tekst` toe zónder backfill: de kolommen
vullen zich pas bij het openen (A10-autosave) of opslaan van een voorstel. Documenten die vóór 0120 GEBOEKT zijn,
worden nooit meer geopend/opgeslagen → hun periode blijft leeg en de latere weekweergave "kosten per project × week"
mist precies de historie. Deze module vult die kolommen DETERMINISTISCH met exact dezelfde regel als de datalaag:

    periode = bepaal_periode(veldvoorstel["periode_tekst"], factuurdatum)

- het AI-veld `periode` uit het LAATST opgeslagen veldvoorstel (tijdlijn, `_laatste_veldvoorstel`) als het er is
  (herkomst `factuur`/`factuur_maand`) — oudere veldvoorstellen (vóór 07-09) kennen het veld niet → None;
- anders de terugval: ISO-week van de factuurdatum (herkomst `afgeleid_van_factuurdatum`);
- zonder factuurdatum én zonder herkenbare tekst: niets (geen gok) — geteld als overgeslagen mét reden.

Harde regels: alleen rijen waarvan ALLE periode-kolommen leeg zijn worden geraakt (een gevulde stand — automatisch
óf `mens` — wordt NOOIT overschreven; `mens` wint altijd); geen RLZ-/Odoo-/AI-calls, puur database; idempotent (een
tweede run vindt 0 te vullen); per gewijzigd document één tijdlijn-notitie (status ongewijzigd, systeem-actor) + één
append-only audit-event (`boekvoorstel_periode_backfill`, oud = leeg → nieuw = de stand). `dry_run=True` toetst alles
en schrijft niets. Cijfers per administratie (dry-run én echt): toetsbaar / al gevuld (waarvan mens) / te vullen uit
AI-veld / te vullen uit terugval / overgeslagen mét reden / gevuld.

Standaard alleen GEBOEKTE documenten (de "bevroren" voorstellen die het A10-pad nooit meer raakt); `alle_statussen`
neemt ook open documenten mee (alles behalve verwijderd/niet_toegewezen) — die krijgen de afleiding anders pas bij de
eerstvolgende opslag, wat voor de dekking van een weekweergave te laat kan zijn.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import periode as periode_regels
from app.documenten.boekvoorstel import _laatste_veldvoorstel, _periode_snapshot
from app.documenten.models import Boekvoorstel, Document, DocumentGebeurtenis, DocumentStatus

AUDIT_ACTIE = "boekvoorstel_periode_backfill"
TIJDLIJN_SLEUTEL = "periode_backfill"
# Statussen die ook mét `alle_statussen` nooit meedoen: soft-deleted en verzamelbak (geen administratie).
UITGESLOTEN_STATUSSEN = frozenset({DocumentStatus.VERWIJDERD, DocumentStatus.NIET_TOEGEWEZEN})

REDEN_GEEN_FACTUURDATUM = "geen factuurdatum en geen herkenbare periode-tekst"


@dataclass
class PeriodeBackfillAdministratie:
    """Cijfers voor één administratie — dry-run én echt dezelfde velden; `gevuld` is 0 bij een dry-run."""

    administratie_id: uuid.UUID
    naam: str
    toetsbaar: int = 0  # boekvoorstel-rijen binnen het status-filter
    al_gevuld: int = 0  # periode-kolommen al gezet (automatisch of mens) — nooit aangeraakt
    mens: int = 0  # deel van al_gevuld met herkomst `mens`
    uit_ai_veld: int = 0  # te vullen/gevuld uit het AI-veld `periode` (factuur / factuur_maand)
    uit_terugval: int = 0  # te vullen/gevuld uit de factuurdatum-week
    gevuld: int = 0  # daadwerkelijk geschreven (0 bij dry-run)
    overgeslagen: dict[str, int] = field(default_factory=dict)
    regels: list[str] = field(default_factory=list)

    @property
    def te_vullen(self) -> int:
        return self.uit_ai_veld + self.uit_terugval

    def tel(self, reden: str) -> None:
        self.overgeslagen[reden] = self.overgeslagen.get(reden, 0) + 1


def _is_leeg(bv: Boekvoorstel) -> bool:
    return (
        bv.periode_jaar is None
        and bv.periode_week_van is None
        and bv.periode_week_tot is None
        and bv.periode_herkomst is None
    )


def backfill(
    *, dry_run: bool, administratie_id: uuid.UUID | None = None, alle_statussen: bool = False
) -> list[PeriodeBackfillAdministratie]:
    """CLI `periode-backfill`. Zie de module-docstring voor de regels; hier alleen de loop."""
    with scoped_session(None) as session:
        admins = session.execute(
            select(Administratie.id, Administratie.naam)
            .where(Administratie.actief.is_(True))
            .order_by(Administratie.naam)
        ).all()
    if administratie_id is not None:
        admins = [a for a in admins if a[0] == administratie_id]

    uitkomsten: list[PeriodeBackfillAdministratie] = []
    for aid, naam in admins:
        u = PeriodeBackfillAdministratie(administratie_id=aid, naam=naam)
        with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
            stmt = (
                select(Boekvoorstel, Document)
                .join(Document, Document.id == Boekvoorstel.document_id)
                .where(Document.administratie_id == aid)
                .order_by(Document.aangemaakt_op, Document.id)
            )
            if alle_statussen:
                stmt = stmt.where(Document.status.not_in(list(UITGESLOTEN_STATUSSEN)))
            else:
                stmt = stmt.where(Document.status == DocumentStatus.GEBOEKT)
            for bv, doc in session.execute(stmt).all():
                u.toetsbaar += 1
                if not _is_leeg(bv):
                    u.al_gevuld += 1
                    if bv.periode_herkomst == periode_regels.HERKOMST_MENS:
                        u.mens += 1
                    continue
                veldvoorstel = _laatste_veldvoorstel(session, doc.id)
                tekst = (veldvoorstel or {}).get("periode_tekst")
                periode = periode_regels.bepaal_periode(tekst, factuurdatum=bv.factuurdatum)
                if periode is None:
                    u.tel(REDEN_GEEN_FACTUURDATUM)
                    continue
                bron = "ai_veld" if periode.herkomst in periode_regels.HERKOMSTEN_UIT_FACTUUR else "factuurdatum"
                if bron == "ai_veld":
                    u.uit_ai_veld += 1
                else:
                    u.uit_terugval += 1
                u.regels.append(
                    f"{doc.bestandsnaam} [{doc.status.value}] → {periode_regels.label(periode)} ({periode.herkomst})"
                )
                if dry_run:
                    continue
                bv.periode_jaar = periode.jaar
                bv.periode_week_van = periode.week_van
                bv.periode_week_tot = periode.week_tot
                bv.periode_herkomst = periode.herkomst
                bv.periode_tekst = periode.tekst
                snapshot = _periode_snapshot(periode)
                session.add(
                    DocumentGebeurtenis(
                        document_id=doc.id,
                        van_status=doc.status,
                        naar_status=doc.status,
                        actor_id=SYSTEEM_ACTOR_ID,
                        detail={TIJDLIJN_SLEUTEL: {"periode": snapshot, "bron": bron}},
                    )
                )
                record_audit_event(
                    session,
                    actor_id=SYSTEEM_ACTOR_ID,
                    module="boekhouding",
                    tabel="boekvoorstel",
                    record_id=doc.id,
                    actie=AUDIT_ACTIE,
                    correlatie_id=uuid.uuid4(),
                    oude_waarde={"periode": None},
                    nieuwe_waarde={"periode": snapshot, "bron": bron},
                    administratie_id=aid,
                )
                u.gevuld += 1
        uitkomsten.append(u)
    return uitkomsten
