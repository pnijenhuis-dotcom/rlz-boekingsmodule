"""Contract-/offerte-ontleding — AUTO-FIRST (blok D6 07-09, besluit Peter 06-09; herziet de 22-08-regel
"voorstel + bevestigen per regel" uit mockup projecten-invoer.html).

Wat de AI (app/extractie/contract.py) leest wordt DIRECT en deterministisch ingevuld in
project_specificatie (kopvelden soort_werk/contract_m2/doorlopende_huur + looptijd/huurtijd/opdrachtgever/
werknummer) en project_staffel (verrekenstaffels), mét herkomst 'contract' (UI-chip "uit contract").
Corrigeren kan altijd via de gewone schrijfpaden in app/projecten/kantoor.py → herkomst 'mens' + audit;
een her-ontleding overschrijft een mens-veld/mens-staffel NOOIT (uitkomst `mens_behouden`, zichtbaar).
Elke gelezen regel laat een leesspoor achter in project_ontleding_regel (citaat, zekerheid, uitkomst:
overgenomen / niet_aangetroffen / ongeldig / mens_behouden) — "niet in contract aangetroffen" is een
expliciete uitkomst, geen stilte. Eén audit_event per ontleding met oud→nieuw (spec + contract-staffels).

Geldpaden houden hun poort: het meerwerk-prijsvoorstel uit de staffels (app/uren/service.py::contract_toets)
blijft een VOORSTEL — de mens vult bij `keur_meerwerk_goed` prijs én bedrag zelf in. Een staffel met
herkomst 'contract' mag als voorstel dienen; het voorstel zelf vereist mens-akkoord.

Gates ongewijzigd: per-administratie AVG-gate `administratie.ai_extractie_ingeschakeld` + de AI-kostengrens
(harde poort ín de Claude-client; boven de limiet is dat een zichtbare fout). Zonder AI blijft alles
handmatig invulbaar."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.storage import standaard_opslag
from app.extractie.contract import (
    ContractOntleding,
    ContractRegel,
    extraheer_contract,
    leid_doorlopende_huur_af,
    map_eenheid,
    parse_getal,
)
from app.projecten.kantoor import (
    HERKOMST_CONTRACT,
    HERKOMST_MENS,
    OngeldigeInvoer,
    ProjectNietGevonden,
    _vereis_schrijfrol,
    spec_snapshot,
    staffel_snapshot,
)
from app.projecten.models import OntledingRegelSoort, OntledingRegelStatus, ProjectOntledingRegel
from app.uren.models import MeerwerkEenheid, ProjectDocument, ProjectSpecificatie, ProjectStaffel

_EENHEDEN = tuple(e.value for e in MeerwerkEenheid)

# Statussen van vóór D6 die een mens expliciet besliste — blijven als vastlegging staan bij her-ontleding.
_LEGACY_BESLIST = (OntledingRegelStatus.BEVESTIGD.value, OntledingRegelStatus.AFGEWEZEN.value)

# Regelsoort → spec-veld (tekstvelden).
_TEKSTVELD_PER_SOORT = {
    OntledingRegelSoort.SOORT_WERK.value: "soort_werk",
    OntledingRegelSoort.HUURTIJD.value: "huurtijd_omschrijving",
    OntledingRegelSoort.DOORLOPENDE_HUUR.value: "doorlopende_huur_omschrijving",
    OntledingRegelSoort.OPDRACHTGEVER.value: "opdrachtgever",
    OntledingRegelSoort.WERKNUMMER.value: "werknummer_opdrachtgever",
}


class OntledingUitgeschakeld(Exception):
    """De per-administratie AVG-gate (ai_extractie_ingeschakeld) staat uit, of er is geen
    API-key — handmatig invullen blijft gewoon werken (mockup-notitie)."""


@dataclass(frozen=True)
class OntleedResultaat:
    project_document_id: uuid.UUID
    aantal_regels: int
    overgenomen: int = 0
    niet_aangetroffen: int = 0
    ongeldig: int = 0
    mens_behouden: int = 0
    doorlopende_huur_afgeleid: bool = False


def _laad_project_document(
    session: Session, *, administratie_id: uuid.UUID, project_id: uuid.UUID, project_document_id: uuid.UUID
) -> ProjectDocument:
    document = session.get(ProjectDocument, project_document_id)
    if document is None or document.administratie_id != administratie_id or document.project_id != project_id:
        raise ProjectNietGevonden("Onbekend projectdocument")
    return document


def _als_datum(waarde: object) -> date | None:
    if not isinstance(waarde, str) or len(waarde) < 10:
        return None
    try:
        return date.fromisoformat(waarde[:10])
    except ValueError:
        return None


def _zorg_voor_spec(
    session: Session, *, administratie_id: uuid.UUID, project_id: uuid.UUID, actor_id: uuid.UUID
) -> ProjectSpecificatie:
    spec = session.get(ProjectSpecificatie, (project_id, administratie_id))
    if spec is None:
        spec = ProjectSpecificatie(project_id=project_id, administratie_id=administratie_id, bijgewerkt_door=actor_id)
        session.add(spec)
    return spec


def _zet_veld_herkomst(spec: ProjectSpecificatie, veld: str, herkomst: str) -> None:
    # Nieuwe dict toewijzen (geen in-place mutatie) zodat SQLAlchemy de JSONB-wijziging ziet.
    spec.veld_herkomst = {**(spec.veld_herkomst or {}), veld: herkomst}


def mag_contract_schrijven(spec: ProjectSpecificatie, veld: str) -> bool:
    """Auto-first-regel: de ontleding vult een spec-veld alleen als het leeg is óf al herkomst 'contract'
    draagt (her-lezing van hetzelfde soort gegeven). Een gevuld veld met herkomst 'mens' — óf met
    onbekende herkomst (rij van vóór 0118: door een mens ingevuld of destijds bevestigd) — wint altijd."""
    if getattr(spec, veld) is None:
        return True
    return (spec.veld_herkomst or {}).get(veld) == HERKOMST_CONTRACT


@dataclass
class _Schrijver:
    """Verzamelt per ontleding de leesspoor-rijen + tellers; schrijft spec/staffels direct weg."""

    session: Session
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    project_document_id: uuid.UUID
    actor_id: uuid.UUID
    spec: ProjectSpecificatie
    tellers: dict[str, int] = field(
        default_factory=lambda: {"overgenomen": 0, "niet_aangetroffen": 0, "ongeldig": 0, "mens_behouden": 0}
    )
    aantal: int = 0

    def _spoor(
        self,
        *,
        soort: str,
        omschrijving: str,
        citaat: str | None,
        waarde: dict | None,
        zekerheid: float | None,
        status: OntledingRegelStatus,
    ) -> None:
        self.aantal += 1
        if status.value in self.tellers:
            self.tellers[status.value] += 1
        self.session.add(
            ProjectOntledingRegel(
                administratie_id=self.administratie_id,
                project_id=self.project_id,
                project_document_id=self.project_document_id,
                soort=soort,
                omschrijving=omschrijving,
                citaat=citaat,
                waarde=waarde or None,
                zekerheid=Decimal(str(round(zekerheid, 3))) if zekerheid is not None else None,
                status=status.value,
                beslist_door=None,
                beslist_op=datetime.now(UTC),
            )
        )

    def _schrijf_spec(self, *, veld: str, waarde: object) -> OntledingRegelStatus:
        if not mag_contract_schrijven(self.spec, veld):
            return OntledingRegelStatus.MENS_BEHOUDEN
        setattr(self.spec, veld, waarde)
        _zet_veld_herkomst(self.spec, veld, HERKOMST_CONTRACT)
        self.spec.bijgewerkt_door = self.actor_id
        return OntledingRegelStatus.OVERGENOMEN

    # --- kopvelden (sentinel: None = niet in contract aangetroffen) --------------------------------

    def kop_tekst(self, *, soort: str, label: str, tekst: str | None, citaat: str | None) -> None:
        veld = _TEKSTVELD_PER_SOORT[soort]
        if tekst is None:
            self._spoor(soort=soort, omschrijving=label, citaat=citaat, waarde=None, zekerheid=None,
                        status=OntledingRegelStatus.NIET_AANGETROFFEN)
            return
        status = self._schrijf_spec(veld=veld, waarde=tekst)
        self._spoor(soort=soort, omschrijving=label, citaat=citaat, waarde={"waarde": tekst}, zekerheid=None,
                    status=status)

    def kop_contract_m2(self, *, tekst: str | None, citaat: str | None) -> None:
        soort = OntledingRegelSoort.CONTRACT_M2.value
        if tekst is None:
            self._spoor(soort=soort, omschrijving="Contract-m²", citaat=citaat, waarde=None, zekerheid=None,
                        status=OntledingRegelStatus.NIET_AANGETROFFEN)
            return
        getal = parse_getal(tekst)
        if getal is None or getal < 0:
            self._spoor(soort=soort, omschrijving="Contract-m²", citaat=citaat,
                        waarde={"waarde": tekst, "reden": "geen leesbaar getal — vul handmatig in"},
                        zekerheid=None, status=OntledingRegelStatus.ONGELDIG)
            return
        status = self._schrijf_spec(veld="contract_m2", waarde=getal)
        self._spoor(soort=soort, omschrijving="Contract-m²", citaat=citaat, waarde={"waarde": str(getal)},
                    zekerheid=None, status=status)

    # --- regels ------------------------------------------------------------------------------------

    def regel(self, regel: ContractRegel) -> None:
        soort = regel.soort
        waarde: dict = {k: v for k, v in (("waarde", regel.waarde), ("eenheid", regel.eenheid),
                                          ("van", regel.van), ("tot", regel.tot)) if v is not None}
        if soort == OntledingRegelSoort.STAFFEL.value:
            self._staffel(regel, waarde)
        elif soort == OntledingRegelSoort.LOOPTIJD.value:
            van, tot = _als_datum(regel.van), _als_datum(regel.tot)
            if van is None and tot is None:
                waarde["reden"] = "geen leesbare datums — vul handmatig in"
                self._spoor(soort=soort, omschrijving=regel.omschrijving, citaat=regel.citaat, waarde=waarde,
                            zekerheid=regel.zekerheid, status=OntledingRegelStatus.ONGELDIG)
                return
            if van is not None and tot is not None and tot < van:
                waarde["reden"] = "einde ligt vóór de start — vul handmatig in"
                self._spoor(soort=soort, omschrijving=regel.omschrijving, citaat=regel.citaat, waarde=waarde,
                            zekerheid=regel.zekerheid, status=OntledingRegelStatus.ONGELDIG)
                return
            statussen = []
            if van is not None:
                statussen.append(self._schrijf_spec(veld="looptijd_van", waarde=van))
            if tot is not None:
                statussen.append(self._schrijf_spec(veld="looptijd_tot", waarde=tot))
            status = (OntledingRegelStatus.OVERGENOMEN if OntledingRegelStatus.OVERGENOMEN in statussen
                      else OntledingRegelStatus.MENS_BEHOUDEN)
            self._spoor(soort=soort, omschrijving=regel.omschrijving, citaat=regel.citaat, waarde=waarde,
                        zekerheid=regel.zekerheid, status=status)
        elif soort in _TEKSTVELD_PER_SOORT:
            if regel.waarde is None:
                waarde["reden"] = "geen leesbare waarde — vul handmatig in"
                self._spoor(soort=soort, omschrijving=regel.omschrijving, citaat=regel.citaat, waarde=waarde,
                            zekerheid=regel.zekerheid, status=OntledingRegelStatus.ONGELDIG)
                return
            status = self._schrijf_spec(veld=_TEKSTVELD_PER_SOORT[soort], waarde=regel.waarde)
            self._spoor(soort=soort, omschrijving=regel.omschrijving, citaat=regel.citaat, waarde=waarde,
                        zekerheid=regel.zekerheid, status=status)
        else:
            # BOETE: alleen vastgelegd (info/projectsignaal) — geen spec-/staffelveld.
            self._spoor(soort=soort, omschrijving=regel.omschrijving, citaat=regel.citaat, waarde=waarde,
                        zekerheid=regel.zekerheid, status=OntledingRegelStatus.OVERGENOMEN)

    def _staffel(self, regel: ContractRegel, waarde: dict) -> None:
        soort = OntledingRegelSoort.STAFFEL.value
        eenheid = map_eenheid(regel.eenheid)
        prijs = parse_getal(regel.waarde)
        if eenheid is None:
            waarde["reden"] = (
                f"eenheid {regel.eenheid!r} niet herkend (m²/m¹/stuks/manuren) — voeg de staffel handmatig toe"
            )
        elif prijs is None or prijs < 0:
            waarde["reden"] = "geen leesbare prijs — voeg de staffel handmatig toe"
        if "reden" in waarde:
            self._spoor(soort=soort, omschrijving=regel.omschrijving, citaat=regel.citaat, waarde=waarde,
                        zekerheid=regel.zekerheid, status=OntledingRegelStatus.ONGELDIG)
            return
        assert eenheid in _EENHEDEN and prijs is not None
        self.session.add(
            ProjectStaffel(
                administratie_id=self.administratie_id,
                project_id=self.project_id,
                omschrijving=regel.omschrijving,
                eenheid=eenheid,
                prijs_per_eenheid=prijs,
                verrekenbaar=True,
                bron=regel.citaat or "contract-ontleding",
                herkomst=HERKOMST_CONTRACT,
                herkomst_document_id=self.project_document_id,
                aangemaakt_door=self.actor_id,
            )
        )
        waarde["eenheid_code"] = eenheid
        waarde["prijs"] = str(prijs)
        self._spoor(soort=soort, omschrijving=regel.omschrijving, citaat=regel.citaat, waarde=waarde,
                    zekerheid=regel.zekerheid, status=OntledingRegelStatus.OVERGENOMEN)


def _contract_staffels_van_document(
    session: Session, *, administratie_id: uuid.UUID, project_document_id: uuid.UUID
) -> list[ProjectStaffel]:
    return list(
        session.scalars(
            select(ProjectStaffel)
            .where(
                ProjectStaffel.administratie_id == administratie_id,
                ProjectStaffel.herkomst == HERKOMST_CONTRACT,
                ProjectStaffel.herkomst_document_id == project_document_id,
            )
            .order_by(ProjectStaffel.aangemaakt_op)
        )
    )


def verwerk_ontleding(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    project_document_id: uuid.UUID,
    actor_id: uuid.UUID,
    ontleding: ContractOntleding,
) -> OntleedResultaat:
    """Deterministisch wegschrijven van één ontleding (auto-first) binnen een bestaande scoped
    sessie. Los aanroepbaar (tests, CLI-heraanbieding): geen AI, geen gates — die zitten in
    `ontleed_document`."""
    spec = _zorg_voor_spec(session, administratie_id=administratie_id, project_id=project_id, actor_id=actor_id)
    oude_spec = spec_snapshot(spec)
    oude_staffels = _contract_staffels_van_document(
        session, administratie_id=administratie_id, project_document_id=project_document_id
    )
    oude_staffels_snapshot = [staffel_snapshot(s) for s in oude_staffels]

    # 1. Eigen leesspoor van dit document vervangen (legacy mens-beslissingen blijven als vastlegging).
    session.execute(
        delete(ProjectOntledingRegel).where(
            ProjectOntledingRegel.administratie_id == administratie_id,
            ProjectOntledingRegel.project_document_id == project_document_id,
            ProjectOntledingRegel.status.not_in(_LEGACY_BESLIST),
        )
    )
    # 2. Eigen contract-staffels van dit document vervangen — mens-staffels (herkomst 'mens'/NULL) blijven.
    for oud in oude_staffels:
        session.delete(oud)
    session.flush()

    schrijver = _Schrijver(
        session=session,
        administratie_id=administratie_id,
        project_id=project_id,
        project_document_id=project_document_id,
        actor_id=actor_id,
        spec=spec,
    )
    kop = ontleding.kop
    # 3. Kopvelden (expliciet uitgevraagd; None = niet in contract aangetroffen).
    schrijver.kop_tekst(soort=OntledingRegelSoort.SOORT_WERK.value, label="Soort werk",
                        tekst=kop.soort_werk, citaat=kop.soort_werk_citaat)
    schrijver.kop_contract_m2(tekst=kop.contract_m2, citaat=kop.contract_m2_citaat)
    # 4. Regels (looptijd, huurtijd, opdrachtgever, werknummer, staffels, boete).
    for regel in ontleding.regels:
        schrijver.regel(regel)
    # 5. Doorlopende huur: kopveld wint; anders CODE-afleiding uit de huurstaffel ("€ 150/week uitgaande
    #    van 9 weken" → vanaf week 10); anders expliciet niet aangetroffen.
    afgeleid = False
    if kop.doorlopende_huur_na is not None:
        schrijver.kop_tekst(soort=OntledingRegelSoort.DOORLOPENDE_HUUR.value, label="Doorlopende huur daarna",
                            tekst=kop.doorlopende_huur_na, citaat=kop.doorlopende_huur_na_citaat)
    else:
        teksten = [
            t
            for r in ontleding.regels
            if r.soort == OntledingRegelSoort.STAFFEL.value
            for t in (r.citaat, " ".join(x for x in (r.omschrijving, r.waarde, r.eenheid) if x))
            if t
        ]
        afleiding = leid_doorlopende_huur_af(teksten)
        if afleiding is None:
            schrijver.kop_tekst(soort=OntledingRegelSoort.DOORLOPENDE_HUUR.value, label="Doorlopende huur daarna",
                                tekst=None, citaat=kop.doorlopende_huur_na_citaat)
        else:
            afgeleid = True
            schrijver.kop_tekst(soort=OntledingRegelSoort.DOORLOPENDE_HUUR.value,
                                label="Doorlopende huur daarna (afgeleid uit huurstaffel)",
                                tekst=afleiding.omschrijving, citaat=afleiding.bron)
    session.flush()

    nieuwe_staffels = _contract_staffels_van_document(
        session, administratie_id=administratie_id, project_document_id=project_document_id
    )
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="project_ontleding_regel",
        record_id=project_document_id,
        actie="contract_ontleed",
        correlatie_id=project_id,
        oude_waarde={"specificatie": oude_spec, "staffels_contract": oude_staffels_snapshot},
        nieuwe_waarde={
            "specificatie": spec_snapshot(spec),
            "staffels_contract": [staffel_snapshot(s) for s in nieuwe_staffels],
            "aantal_regels": schrijver.aantal,
            "doorlopende_huur_afgeleid": afgeleid,
            **schrijver.tellers,
        },
        administratie_id=administratie_id,
    )
    return OntleedResultaat(
        project_document_id=project_document_id,
        aantal_regels=schrijver.aantal,
        doorlopende_huur_afgeleid=afgeleid,
        **schrijver.tellers,
    )


def ontleed_document(
    *,
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    project_document_id: uuid.UUID,
    actor_id: uuid.UUID,
    extraheer=extraheer_contract,
) -> OntleedResultaat:
    """Draait de AI-ontleding en vult specs/staffels DIRECT (auto-first, herkomst 'contract').
    `extraheer` is de test-seam (geeft een ContractOntleding terug)."""
    with scoped_session(administratie_id) as session:
        _vereis_schrijfrol(session, actor_id)
        document = _laad_project_document(
            session, administratie_id=administratie_id, project_id=project_id, project_document_id=project_document_id
        )
        opslag_pad = document.opslag_pad
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not administratie.ai_extractie_ingeschakeld:
            raise OntledingUitgeschakeld(
                "AI-extractie staat uit voor deze administratie (AVG-gate) — vul specs en staffels handmatig in"
            )
    if not settings.anthropic_api_key:
        raise OntledingUitgeschakeld("Geen Claude-API-key geconfigureerd — vul specs en staffels handmatig in")

    from app.aikosten.service import AiVerbruikReferentie

    inhoud = standaard_opslag().lezen(pad=opslag_pad)
    ontleding = extraheer(
        inhoud, verbruik_referentie=AiVerbruikReferentie(bron="contract_ontleding", document_id=project_document_id)
    )
    if not isinstance(ontleding, ContractOntleding):
        raise OngeldigeInvoer("De ontleding gaf geen bruikbaar resultaat terug")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        return verwerk_ontleding(
            session,
            administratie_id=administratie_id,
            project_id=project_id,
            project_document_id=project_document_id,
            actor_id=actor_id,
            ontleding=ontleding,
        )


def _als_decimal(waarde: object) -> Decimal:
    try:
        return Decimal(str(waarde))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OngeldigeInvoer(f"Onbruikbare getalswaarde in het voorstel: {waarde!r}") from exc


def beslis_regel(
    *,
    administratie_id: uuid.UUID,
    regel_id: uuid.UUID,
    actor_id: uuid.UUID,
    bevestigen: bool,
    eenheid: str | None = None,
    verrekenbaar: bool = True,
) -> None:
    """LEGACY (vóór D6): ✓/✗ op een rij die nog in status `voorstel` staat (ontleed vóór 07-09).
    Sinds auto-first ontstaan er geen nieuwe voorstel-rijen meer; dit pad blijft alleen zodat oude
    voorstellen nog afgewikkeld kunnen worden (of: opnieuw ontleden → direct ingevuld). Bevestigen
    schrijft deterministisch door mét herkomst 'contract'."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_schrijfrol(session, actor_id)
        regel = session.get(ProjectOntledingRegel, regel_id)
        if regel is None or regel.administratie_id != administratie_id:
            raise ProjectNietGevonden("Onbekende voorstel-regel")
        if regel.status != OntledingRegelStatus.VOORSTEL.value:
            raise OngeldigeInvoer("Deze regel is al beslist")

        if bevestigen:
            waarde = regel.waarde or {}
            if regel.soort == OntledingRegelSoort.STAFFEL.value:
                if eenheid not in _EENHEDEN:
                    raise OngeldigeInvoer(
                        f"Kies bij een staffel-regel de eenheid ({', '.join(_EENHEDEN)}) — de "
                        "AI-eenheid is alleen een voorstel"
                    )
                prijs = _als_decimal(waarde.get("waarde"))
                if prijs < 0:
                    raise OngeldigeInvoer("Staffelprijs kan niet negatief zijn")
                session.add(
                    ProjectStaffel(
                        administratie_id=administratie_id,
                        project_id=regel.project_id,
                        omschrijving=regel.omschrijving,
                        eenheid=eenheid,
                        prijs_per_eenheid=prijs,
                        verrekenbaar=verrekenbaar,
                        bron=regel.citaat or "contract-ontleding",
                        herkomst=HERKOMST_CONTRACT,
                        herkomst_document_id=regel.project_document_id,
                        aangemaakt_door=actor_id,
                    )
                )
            elif regel.soort == OntledingRegelSoort.CONTRACT_M2.value:
                spec = _zorg_voor_spec(
                    session, administratie_id=administratie_id, project_id=regel.project_id, actor_id=actor_id
                )
                spec.contract_m2 = _als_decimal(waarde.get("waarde"))
                _zet_veld_herkomst(spec, "contract_m2", HERKOMST_CONTRACT)
                spec.bijgewerkt_door = actor_id
            elif regel.soort == OntledingRegelSoort.LOOPTIJD.value:
                spec = _zorg_voor_spec(
                    session, administratie_id=administratie_id, project_id=regel.project_id, actor_id=actor_id
                )
                van = _als_datum(waarde.get("van"))
                tot = _als_datum(waarde.get("tot"))
                if van is None and tot is None:
                    raise OngeldigeInvoer("Looptijd-voorstel zonder leesbare datums — vul handmatig in")
                if van is not None:
                    spec.looptijd_van = van
                    _zet_veld_herkomst(spec, "looptijd_van", HERKOMST_CONTRACT)
                if tot is not None:
                    spec.looptijd_tot = tot
                    _zet_veld_herkomst(spec, "looptijd_tot", HERKOMST_CONTRACT)
                spec.bijgewerkt_door = actor_id
            elif regel.soort in _TEKSTVELD_PER_SOORT:
                tekst = waarde.get("waarde")
                if not tekst:
                    raise OngeldigeInvoer("Voorstel zonder leesbare waarde — vul handmatig in")
                spec = _zorg_voor_spec(
                    session, administratie_id=administratie_id, project_id=regel.project_id, actor_id=actor_id
                )
                veld = _TEKSTVELD_PER_SOORT[regel.soort]
                setattr(spec, veld, str(tekst))
                _zet_veld_herkomst(spec, veld, HERKOMST_CONTRACT)
                spec.bijgewerkt_door = actor_id
            # BOETE: alleen vastleggen (status bevestigd) — ter info, wordt projectsignaal.

        regel.status = (
            OntledingRegelStatus.BEVESTIGD.value if bevestigen else OntledingRegelStatus.AFGEWEZEN.value
        )
        regel.beslist_door = actor_id
        regel.beslist_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="project_ontleding_regel",
            record_id=regel_id,
            actie="ontleding_regel_bevestigd" if bevestigen else "ontleding_regel_afgewezen",
            correlatie_id=regel.project_id,
            nieuwe_waarde={"soort": regel.soort, "omschrijving": regel.omschrijving, "eenheid": eenheid},
            administratie_id=administratie_id,
        )


def open_voorstellen(
    session: Session, *, administratie_id: uuid.UUID, project_id: uuid.UUID
) -> list[ProjectOntledingRegel]:
    """Legacy voorstel-rijen (vóór D6) die nog niet beslist zijn."""
    return list(
        session.scalars(
            select(ProjectOntledingRegel).where(
                ProjectOntledingRegel.administratie_id == administratie_id,
                ProjectOntledingRegel.project_id == project_id,
                ProjectOntledingRegel.status == OntledingRegelStatus.VOORSTEL.value,
            )
        )
    )


__all__ = [
    "HERKOMST_CONTRACT",
    "HERKOMST_MENS",
    "OntleedResultaat",
    "OntledingUitgeschakeld",
    "beslis_regel",
    "mag_contract_schrijven",
    "ontleed_document",
    "open_voorstellen",
    "verwerk_ontleding",
]
