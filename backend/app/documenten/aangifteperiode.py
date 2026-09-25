"""Factuurdatum in een ingediende btw-aangifteperiode — ORANJE check, bewuste keuze, tijdlijn (feedbackrun A 25-09,
blok 4, FV-16 in de aangepaste vorm: géén blokkade).

Feit (api-verkenning "Boekingsdatum = BookDate"): de module geeft `BookDate` = factuurdatum mee; valt die in een
periode waarvan de btw-aangifte al is ingediend (`GET TaxDeclarations`, Status 2/3), dan weigert RLZ de boeking niet
maar verschuift de btw naar het eerstvolgende open tijdvak (TaxSource). Nagekomen facturen zijn legitiem — daarom is dit
een SIGNAAL mét handeling, geen poort (besluit Peter 25-09; FV-16 vroeg een blokkade, dat botst met het besluit 21-09
"corrigeren → klaar_om_te_boeken" en de praktijk van nagekomen facturen).

Drie bouwstenen, allemaal deterministisch en zonder AI:
- de TOETS zelf zit in het EXTERNE deel van de checks (`checks_extern.ExternRapport.aangifte`, parallel, gecachet op
  de vingerafdruk — de factuurdatum zit daar al in): `AangiftePoort.toets_boekdatum(factuurdatum)`; een leesfout is
  geen stilte maar een oranje "niet toetsbaar"; Odoo kent geen RLZ-aangiften → n.v.t. (groen mét tekst);
- de BEWUSTE KEUZE "Boeken (btw in volgend tijdvak)" is een tijdlijn-notitie (`DocumentGebeurtenis.detail[SLEUTEL]`,
  zelfde patroon als `kop_omschrijving`/`toch_verschillend` — geen kolom, geen migratie) + audit
  `aangifteperiode_bevestigd`; daarna toont de check-rij oranje "bevestigd door … op …" zonder actie;
- BOEKEN zonder bevestiging blijft mogelijk (oranje is geen poort), maar de boek-transactie schrijft dan zelf de
  tijdlijnregel "geboekt mét factuurdatum in ingediende aangifte (niet vooraf bevestigd)" — niets verdwijnt stil.
  Het AUTOBOEK-pad boekt nooit op een oranje aangifte-rij (bestaande regel "oranje = niet automatisch boeken").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.documenten.checks import CheckActie, CheckResultaat
from app.documenten.models import DocumentGebeurtenis
from app.rlz.aangifte import AangiftePoort, KantToets

#: Naam van de check-rij (exact — de frontend en de tests lezen 'm letterlijk).
NAAM = "Factuurdatum valt in een ingediende aangifteperiode"
#: Actiecode op de rij (frontend `voerCheckActieUit`): bewuste keuze vastleggen.
ACTIE_CODE = "aangifte_bevestigen"
ACTIE_LABEL = "Boeken (btw in volgend tijdvak)"
#: Tijdlijn-notitie-sleutel (append-only; laatste notitie wint) + audit-actie.
SLEUTEL = "aangifteperiode_bevestigd"
AUDIT_BEVESTIGD = "aangifteperiode_bevestigd"
#: Tijdlijn-sleutel van de boekstap zonder voorafgaande bevestiging.
SLEUTEL_GEBOEKT_ONBEVESTIGD = "aangifteperiode_geboekt_onbevestigd"
#: Kant-label in de KantToets (lees-only toets, geen storno).
KANT = "factuurdatum"


@dataclass(frozen=True)
class AangifteToets:
    """JSON-ronde uitkomst van de toets voor het externe rapport (cache)."""

    toegestaan: bool
    reden: str | None = None
    periode_start: str | None = None
    periode_eind: str | None = None
    #: leesfout = de aangifte-status was niet leesbaar (RLZ-fout) — oranje "niet toetsbaar", nooit stil
    leesfout: str | None = None
    #: n.v.t. (Odoo-administratie, geen factuurdatum): groen mét tekst
    nvt: str | None = None

    @property
    def ingediend(self) -> bool:
        return not self.toegestaan and self.leesfout is None and self.nvt is None

    def periode_tekst(self) -> str:
        if self.periode_start and self.periode_eind:
            return f"{self.periode_start} t/m {self.periode_eind}"
        return "onbekende periode"

    def naar_json(self) -> dict[str, Any]:
        return {
            "toegestaan": self.toegestaan,
            "reden": self.reden,
            "periode_start": self.periode_start,
            "periode_eind": self.periode_eind,
            "leesfout": self.leesfout,
            "nvt": self.nvt,
        }

    @classmethod
    def uit_json(cls, d: dict[str, Any] | None) -> AangifteToets | None:
        if not d:
            return None
        return cls(
            toegestaan=bool(d.get("toegestaan", True)),
            reden=d.get("reden"),
            periode_start=d.get("periode_start"),
            periode_eind=d.get("periode_eind"),
            leesfout=d.get("leesfout"),
            nvt=d.get("nvt"),
        )


def nvt(reden: str) -> AangifteToets:
    return AangifteToets(toegestaan=True, nvt=reden)


def toets_factuurdatum(client: Any, factuurdatum: date | None) -> AangifteToets:
    """Eén RLZ-roundtrip (`TaxDeclarations`) via de bestaande aangiftelezer. `client` = een RlzClient (of duck-typed
    fake mét `list_tax_declarations`). Zonder factuurdatum valt er niets te toetsen (n.v.t.)."""
    if factuurdatum is None:
        return nvt("geen factuurdatum")
    if not hasattr(client, "list_tax_declarations"):
        return nvt("Odoo — geen Reeleezee-aangiften")
    poort = AangiftePoort(client)
    toets: KantToets = poort.toets_boekdatum(factuurdatum, kant=KANT)
    if toets.toegestaan:
        return AangifteToets(toegestaan=True)
    if toets.periode_start is None:
        # De poort meldt "niet leesbaar — storno uit voorzorg geblokkeerd"; hier is dat geen blokkade maar een
        # zichtbaar "niet toetsbaar".
        return AangifteToets(toegestaan=False, leesfout=(toets.reden or "aangifte-status niet leesbaar"))
    return AangifteToets(
        toegestaan=False,
        reden=toets.reden,
        periode_start=toets.periode_start.isoformat(),
        periode_eind=toets.periode_eind.isoformat() if toets.periode_eind else None,
    )


# ---- tijdlijn-notitie (bewuste keuze) ------------------------------------------------------------------------------


def _laatste_notitie(session: Session, document_id: uuid.UUID) -> dict[str, Any] | None:
    rijen = session.scalars(
        select(DocumentGebeurtenis)
        .where(DocumentGebeurtenis.document_id == document_id, DocumentGebeurtenis.detail.has_key(SLEUTEL))
        .order_by(DocumentGebeurtenis.tijdstip.desc())
    ).all()
    for rij in rijen:
        notitie = (rij.detail or {}).get(SLEUTEL)
        if isinstance(notitie, dict):
            return {**notitie, "actor_id": str(rij.actor_id) if rij.actor_id else None, "tijdstip": rij.tijdstip}
    return None


@dataclass(frozen=True)
class Bevestiging:
    periode_start: str | None
    periode_eind: str | None
    boek_cyclus: int
    door_naam: str | None
    op: str | None

    def past_bij(self, toets: AangifteToets, *, boek_cyclus: int) -> bool:
        """Een bevestiging geldt voor DEZE periode en DEZE boekcyclus (ná corrigeren/storno opnieuw kiezen)."""
        return (
            self.boek_cyclus == boek_cyclus
            and self.periode_start == toets.periode_start
            and self.periode_eind == toets.periode_eind
        )


def bevestiging_voor(session: Session, document_id: uuid.UUID) -> Bevestiging | None:
    from app.db.models import Gebruiker

    notitie = _laatste_notitie(session, document_id)
    if notitie is None:
        return None
    naam = None
    if notitie.get("actor_id"):
        try:
            gebruiker = session.get(Gebruiker, uuid.UUID(notitie["actor_id"]))
        except (ValueError, TypeError):
            gebruiker = None
        naam = getattr(gebruiker, "naam", None) or getattr(gebruiker, "email", None)
    tijdstip = notitie.get("tijdstip")
    return Bevestiging(
        periode_start=notitie.get("periode_start"),
        periode_eind=notitie.get("periode_eind"),
        boek_cyclus=int(notitie.get("boek_cyclus") or 0),
        door_naam=naam,
        op=tijdstip.date().isoformat() if hasattr(tijdstip, "date") else None,
    )


class NietsTeBevestigen(Exception):
    """De factuurdatum valt (volgens de laatste toets) niet in een ingediende periode — er is niets te bevestigen."""


def bevestig(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    toets: AangifteToets,
    boek_cyclus: int,
    document_status: Any,
) -> Bevestiging:
    """De bewuste keuze "Boeken (btw in volgend tijdvak)": tijdlijn-notitie + audit oud→nieuw. Idempotent per periode
    × boekcyclus (een tweede klik schrijft niets)."""
    if not toets.ingediend:
        raise NietsTeBevestigen("De factuurdatum valt niet in een ingediende aangifteperiode")
    bestaand = bevestiging_voor(session, document_id)
    if bestaand is not None and bestaand.past_bij(toets, boek_cyclus=boek_cyclus):
        return bestaand
    notitie = {
        "periode_start": toets.periode_start,
        "periode_eind": toets.periode_eind,
        "boek_cyclus": boek_cyclus,
        "reden": (
            f"Factuurdatum in ingediende aangifte {toets.periode_tekst()} — bewust geboekt, btw in volgend tijdvak"
        ),
    }
    gebeurtenis = DocumentGebeurtenis(
        id=uuid.uuid4(),
        document_id=document_id,
        van_status=document_status,
        naar_status=document_status,
        actor_id=actor_id,
        detail={SLEUTEL: notitie, "reden": notitie["reden"]},
    )
    session.add(gebeurtenis)
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="boekvoorstel",
        record_id=document_id,
        actie=AUDIT_BEVESTIGD,
        correlatie_id=gebeurtenis.id,
        oude_waarde={"bevestigd": bestaand is not None, "periode_start": bestaand.periode_start if bestaand else None},
        nieuwe_waarde={"bevestigd": True, **notitie},
        administratie_id=administratie_id,
    )
    session.flush()
    return bevestiging_voor(session, document_id) or Bevestiging(
        periode_start=toets.periode_start,
        periode_eind=toets.periode_eind,
        boek_cyclus=boek_cyclus,
        door_naam=None,
        op=None,
    )


def noteer_geboekt_zonder_bevestiging(
    session: Session, *, document_id: uuid.UUID, actor_id: uuid.UUID, toets: AangifteToets, document_status: Any
) -> None:
    """Boekstap zonder voorafgaande bevestiging: één tijdlijnregel in de boek-transactie (nooit stil)."""
    session.add(
        DocumentGebeurtenis(
            id=uuid.uuid4(),
            document_id=document_id,
            van_status=document_status,
            naar_status=document_status,
            actor_id=actor_id,
            detail={
                SLEUTEL_GEBOEKT_ONBEVESTIGD: {"periode_start": toets.periode_start, "periode_eind": toets.periode_eind},
                "reden": (
                    f"geboekt mét factuurdatum in ingediende aangifte {toets.periode_tekst()} "
                    "(niet vooraf bevestigd) — RLZ verschuift de btw naar het eerstvolgende open tijdvak"
                ),
            },
        )
    )


# ---- check-rij ----------------------------------------------------------------------------------------------------


def check_resultaat(
    *, toets: AangifteToets | None, factuurdatum: date | None, bevestiging: Bevestiging | None, boek_cyclus: int
) -> CheckResultaat:
    """De rij voor het CheckRapport. `toets=None` = het externe deel leverde niets (storings-tak / cache van vóór 25-09)
    → oranje "niet toetsbaar". Nooit blokkerend (ok=True), oranje = `signaal=True`."""
    if factuurdatum is None:
        return CheckResultaat(NAAM, True, "Geen factuurdatum — niets te toetsen")
    if toets is None:
        return CheckResultaat(
            NAAM,
            True,
            "Aangifte-status niet getoetst (Reeleezee niet bereikt) — controleer de periode zelf",
            signaal=True,
        )
    if toets.nvt:
        return CheckResultaat(NAAM, True, f"Niet van toepassing — {toets.nvt}")
    if toets.leesfout:
        return CheckResultaat(
            NAAM, True, f"Aangifte-status niet leesbaar ({toets.leesfout}) — niet toetsbaar", signaal=True
        )
    if toets.toegestaan:
        return CheckResultaat(NAAM, True, f"Factuurdatum {factuurdatum.isoformat()} valt in een open aangifteperiode")
    basis = (
        f"Factuurdatum {factuurdatum.isoformat()} valt in de ingediende btw-aangifte {toets.periode_tekst()} — "
        "RLZ verschuift de btw naar het eerstvolgende open tijdvak"
    )
    if bevestiging is not None and bevestiging.past_bij(toets, boek_cyclus=boek_cyclus):
        wie = f" door {bevestiging.door_naam}" if bevestiging.door_naam else ""
        wanneer = f" op {bevestiging.op}" if bevestiging.op else ""
        return CheckResultaat(
            NAAM, True, f"{basis}; bewust geboekt (btw in volgend tijdvak) — bevestigd{wie}{wanneer}", signaal=True
        )
    return CheckResultaat(
        NAAM, True, basis, signaal=True, acties=(CheckActie(code=ACTIE_CODE, label=ACTIE_LABEL, regel=0),)
    )


def is_onbevestigd_signaal(resultaat: CheckResultaat) -> bool:
    """Oranje rij mét de bevestig-actie = ingediende periode zonder bewuste keuze."""
    return resultaat.naam == NAAM and resultaat.signaal and any(a.code == ACTIE_CODE for a in resultaat.acties)


def rij_uit(rapport_resultaten: tuple[CheckResultaat, ...] | list[CheckResultaat]) -> CheckResultaat | None:
    return next((r for r in rapport_resultaten if r.naam == NAAM), None)
