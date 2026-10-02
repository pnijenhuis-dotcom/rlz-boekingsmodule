"""Intercompany-tegenpartijen (accordering overslaan) AUTOMATISCH uit de actieve IC-relaties — run D 02-10 blok D
(Peter 02-10; casus Universal: `intercompany_tegenpartij` had 0 rijen voor de vier BV's, de eenmalige rij van 08-09
was nooit gezet, dus élke onderlinge factuur ging bij Steigerbouw gewoon ter klant-accordering).

Regel: élke ACTIEVE crediteur-relatie (A, entity_in_a, B) — "B levert aan A", basis kvk/btw/doorbelasting of een
(automatisch dan wel door een mens) bevestigde naam-relatie — krijgt in de scope van A een rij in
`boekhouding.intercompany_tegenpartij` mét bron `intercompany_relatie`. Daarmee geldt voor die crediteur de bestaande
regel "intercompany slaat klant-accordering over" (08-09) zonder klik. Generiek: niet alleen Universal — élke groep
eigen administraties die elkaars crediteur zijn.

Idempotent en nooit stil:
- bestaande ACTIEVE rij (welke bron ook) = ongewijzigd;
- bestaande INACTIEVE rij mét bron `handmatig` of `doorbelasting_mapping` = een mens/mapping heeft 'm bewust uitgezet
  → overgeslagen (teller + regel), nooit heractiveren over een mens heen;
- inactieve rij mét bron `intercompany_relatie` = door een eerdere run gezet en daarna uitgezet via de relatie-route
  (uitgesloten relatie) → alleen opnieuw actief als de relatie nu weer actief is (zelfde bron);
- een relatie die NIET meer actief is (Beheerder sloot 'm uit) zet een rij mét bron `intercompany_relatie` op
  `actief=False` (nooit delete) — de accordering loopt dan weer gewoon.
Elke mutatie: audit `intercompany_leverancier_gewijzigd` (dezelfde actie als de Beheerder-instelling, zodat de
tijdlijn op Instellingen › Klant-accordering 'm toont) in `scoped_session(A, actor=systeem)`. Afwezig-pad: geen actieve
crediteur-
relaties = "0 kandidaten", geen fout, geen rij (guard-test)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.doorbelasting.intercompany_beheer import AUDIT_ACTIE, BRON_HANDMATIG
from app.doorbelasting.models import IntercompanyTegenpartij
from app.intercompany.models import IntercompanyRelatie
from app.intercompany.relaties import is_actief
from app.sync.models import VendorCache

BRON_INTERCOMPANY_RELATIE = "intercompany_relatie"
_TABEL = "intercompany_tegenpartij"
_MODULE = "boekhouding"


@dataclass
class TegenpartijUitkomst:
    kandidaten: int = 0
    nieuw: int = 0
    geheractiveerd: int = 0
    gedeactiveerd: int = 0
    ongewijzigd: int = 0
    #: Inactieve rij van een mens/mapping — bewust niet aangeraakt (zichtbaar).
    mens_uit_overgeslagen: int = 0
    regels: list[str] = field(default_factory=list)
    fouten: list[tuple[uuid.UUID, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kandidaten": self.kandidaten,
            "nieuw": self.nieuw,
            "geheractiveerd": self.geheractiveerd,
            "gedeactiveerd": self.gedeactiveerd,
            "ongewijzigd": self.ongewijzigd,
            "mens_uit_overgeslagen": self.mens_uit_overgeslagen,
            "regels": list(self.regels),
            "fouten": [f"{aid}: {m}" for aid, m in self.fouten],
        }


def _crediteur_relaties() -> tuple[list[IntercompanyRelatie], list[IntercompanyRelatie]]:
    """(actieve crediteur-relaties, niet-actieve crediteur-relaties) — gedetacheerd."""
    with scoped_session(None) as session:
        rijen = list(session.scalars(select(IntercompanyRelatie).where(IntercompanyRelatie.richting == "crediteur")))
        session.expunge_all()
    actief = [r for r in rijen if is_actief(r.status, r.basis)]
    inactief = [r for r in rijen if not is_actief(r.status, r.basis)]
    return actief, inactief


def _snapshot(rij: IntercompanyTegenpartij | None) -> dict | None:
    if rij is None:
        return None
    return {"entity_guid": str(rij.entity_guid), "naam": rij.naam, "bron": rij.bron, "actief": rij.actief}


def _audit(session, *, administratie_id: uuid.UUID, rij: IntercompanyTegenpartij, oud: dict | None, reden: str) -> None:  # noqa: ANN001
    record_audit_event(
        session,
        actor_id=SYSTEEM_ACTOR_ID,
        module=_MODULE,
        tabel=_TABEL,
        record_id=rij.entity_guid,
        actie=AUDIT_ACTIE,
        correlatie_id=uuid.uuid4(),
        oude_waarde=oud,
        nieuwe_waarde={**(_snapshot(rij) or {}), "reden": reden},
        administratie_id=administratie_id,
    )


def leid_tegenpartijen_af(administratie_ids: list[uuid.UUID] | None = None) -> TegenpartijUitkomst:
    """Per actieve crediteur-relatie één actieve IC-rij in de administratie van de crediteur (A). Zie module-doc."""
    uit = TegenpartijUitkomst()
    actief, inactief = _crediteur_relaties()
    keuze = set(administratie_ids) if administratie_ids is not None else None
    if keuze is not None:
        actief = [r for r in actief if r.administratie_a_id in keuze]
        inactief = [r for r in inactief if r.administratie_a_id in keuze]
    uit.kandidaten = len(actief)
    if not actief and not inactief:
        uit.regels.append("0 kandidaten — geen (actieve) crediteur-relaties tussen eigen administraties")
        return uit

    per_administratie: dict[uuid.UUID, list[IntercompanyRelatie]] = {}
    for r in actief:
        per_administratie.setdefault(r.administratie_a_id, []).append(r)
    inactief_per_administratie: dict[uuid.UUID, list[IntercompanyRelatie]] = {}
    for r in inactief:
        inactief_per_administratie.setdefault(r.administratie_a_id, []).append(r)

    for aid in sorted(set(per_administratie) | set(inactief_per_administratie), key=str):
        try:
            _verwerk_administratie(
                aid,
                actief=per_administratie.get(aid, []),
                inactief=inactief_per_administratie.get(aid, []),
                uit=uit,
            )
        except Exception as exc:  # noqa: BLE001 — één administratie mag de rest niet stoppen; zichtbaar
            uit.fouten.append((aid, f"{type(exc).__name__}: {exc}"))
    return uit


def _verwerk_administratie(
    aid: uuid.UUID, *, actief: list[IntercompanyRelatie], inactief: list[IntercompanyRelatie], uit: TegenpartijUitkomst
) -> None:
    actieve_entities = {r.entity_in_a for r in actief}
    with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
        bestaand: dict[uuid.UUID, IntercompanyTegenpartij] = {
            rij.entity_guid: rij
            for rij in session.scalars(
                select(IntercompanyTegenpartij).where(IntercompanyTegenpartij.administratie_id == aid)
            )
        }
        for r in sorted(actief, key=lambda x: (str(x.entity_naam or ""), str(x.entity_in_a))):
            rij = bestaand.get(r.entity_in_a)
            naam = r.entity_naam or _vendor_naam(session, aid, r.entity_in_a) or str(r.entity_in_a)
            if rij is None:
                rij = IntercompanyTegenpartij(
                    administratie_id=aid,
                    entity_guid=r.entity_in_a,
                    naam=naam,
                    bron=BRON_INTERCOMPANY_RELATIE,
                    actief=True,
                )
                session.add(rij)
                session.flush()
                uit.nieuw += 1
                uit.regels.append(f"{aid}: {naam} — intercompany-leverancier gezet (basis {r.basis}, {r.status})")
                reden = f"afgeleid uit IC-relatie ({r.basis}, {r.status})"
                _audit(session, administratie_id=aid, rij=rij, oud=None, reden=reden)
                continue
            if rij.actief:
                uit.ongewijzigd += 1
                continue
            if rij.bron != BRON_INTERCOMPANY_RELATIE:
                # Een mens (handmatig) of de doorbelasting-mapping zette 'm uit — dat besluit wint, zichtbaar.
                uit.mens_uit_overgeslagen += 1
                uit.regels.append(
                    f"{aid}: {rij.naam} — inactieve rij mét bron {rij.bron} niet heractiveerd (mens/mapping wint)"
                )
                continue
            oud = _snapshot(rij)
            rij.actief = True
            rij.naam = naam
            uit.geheractiveerd += 1
            uit.regels.append(f"{aid}: {naam} — intercompany-leverancier opnieuw actief (relatie weer actief)")
            reden = f"IC-relatie weer actief ({r.basis}, {r.status})"
            _audit(session, administratie_id=aid, rij=rij, oud=oud, reden=reden)
        # Relatie niet (meer) actief → een rij die WIJ zetten gaat uit; andere bronnen nooit aangeraakt.
        for r in inactief:
            if r.entity_in_a in actieve_entities:
                continue
            rij = bestaand.get(r.entity_in_a)
            if rij is None or not rij.actief or rij.bron != BRON_INTERCOMPANY_RELATIE:
                continue
            oud = _snapshot(rij)
            rij.actief = False
            uit.gedeactiveerd += 1
            uit.regels.append(
                f"{aid}: {rij.naam} — intercompany-leverancier uitgezet (relatie {r.status}: {r.reden or 'geen reden'})"
            )
            _audit(session, administratie_id=aid, rij=rij, oud=oud, reden=f"IC-relatie niet meer actief ({r.status})")


def _vendor_naam(session, aid: uuid.UUID, vendor_id: uuid.UUID) -> str | None:  # noqa: ANN001
    vendor = session.get(VendorCache, (vendor_id, aid))
    return vendor.naam if vendor is not None else None


__all__ = ["BRON_HANDMATIG", "BRON_INTERCOMPANY_RELATIE", "TegenpartijUitkomst", "leid_tegenpartijen_af"]
