"""Bevindingssoorten: stand `meten` vs `actie` (SPOED 17-09, melding Peter op de actiemail van 17-09 ochtend:
"Mogelijk dubbel betaald … en 1204 andere — dit moet anders want hier doe ik niks mee").

Wortel: de soort `dubbele_betaling_vermoed` (16-09) liep op dag één over 400 dagen historie van álle administraties heen
rechtstreeks in de ACTIEMAIL. Kernprincipe 7(2): een signaal zonder handeling is niet af — 1.214 signalen zonder
handeling zijn erger dan geen. Twee structurele regels (blok C van de spoedopdracht):

1. **Élke nieuwe bevindingssoort start in stand `meten`:** ze telt alleen (systeemmail/rapport + Inzicht › Reconciliatie
   onder het facet "in meting") en komt pas in de actiemail ná een expliciete PROMOTIE (Beheerder via `PUT
   /reconciliatie/instelling`, of CLI `bevindingssoort-stand <soort> --stand actie`) mét de meting erbij. De code-default per
   soort staat in `REGISTRY`: de soorten die vóór 17-09 bestonden zijn `actie` (dat was hun feitelijke stand), nieuwe
   soorten krijgen `sinds` + `meten`. Een soort die in teksten.py een tekst heeft maar hier ontbreekt = rood (guard).
2. **Explosie-rem:** produceert één soort in één run méér dan `EXPLOSIE_DREMPEL` afwijkingen, dan gaat die soort
   automatisch (terug) naar `meten` (DB-override + audit `bevindingssoort_naar_meten`) en komt er een systeemfout-LET-OP
   "bevindingssoort X explodeert (N)" — nooit meer "en 1204 andere" in een actiemail.

De DB-override (`reconciliatie_instelling.soort_standen`, migratie 0153) wint altijd van de code-default. Puur code, geen AI."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

METEN = "meten"
ACTIE = "actie"
STANDEN = (METEN, ACTIE)
#: Meer afwijkingen van één soort in één run dan dit = de soort gaat (terug) naar `meten`.
EXPLOSIE_DREMPEL = 50
#: Categorie van de LET-OP (blok `automatisering`, regressie → systeemmail, nooit actiemail).
EXPLOSIE_CATEGORIE = "bevindingssoort_explodeert"
#: Datum waarop de registry is ingevoerd: alles van daarvóór stond feitelijk al in de actiemail.
REGISTRY_SINDS = date(2026, 9, 17)


@dataclass(frozen=True)
class SoortDefinitie:
    soort: str
    blok: str
    sinds: date
    #: Code-default. Nieuwe soorten (sinds ≥ 17-09) horen op `meten` te starten (guard-test).
    default: str
    #: Promotie in code (ná een meting): datum + korte verwijzing (rapport). Leeg = alleen via DB-override.
    gepromoveerd_op: date | None = None
    meting: str | None = None
    #: Uitzondering op "nieuw start in meten" (alleen op een expliciet besluit van Peter, mét reden — guard-test): een
    #: soort
    #: die een bestaande harde check herhaalt en een bestaand boekstuk als bewijs draagt (geen nieuwe domeinhypothese)
    #: mag direct in `actie` starten. De explosie-rem (> 50/run → meten) geldt onverkort.
    direct_actie_reden: str | None = None


def _oud(soort: str, blok: str) -> SoortDefinitie:
    return SoortDefinitie(soort=soort, blok=blok, sinds=date(2026, 9, 1), default=ACTIE)


#: Alle afwijkingssoorten die een leesbare tekst hebben (app/reconciliatie/teksten.py) — één bron voor de stand.
REGISTRY: dict[str, SoortDefinitie] = {
    d.soort: d
    for d in (
        # documenten
        _oud("ontbreekt_in_rlz", "documenten"),
        _oud("ontbreekt_in_odoo", "documenten"),
        _oud("bedrag_wijkt_af", "documenten"),
        _oud("status_niet_definitief", "documenten"),
        _oud("status_wijkt_af", "documenten"),
        _oud("boekstuknummer_wijkt_af", "documenten"),
        _oud("controle_mislukt", "documenten"),
        _oud("niet_geboekt_in_odoo", "documenten"),
        _oud("teruggedraaid_in_odoo", "documenten"),
        _oud("half_geboekt", "documenten"),
        # boeken sneller (18-09): achtergrond-schrijver gestrand (> herstelgrens op wordt_geboekt) — startte in meten.
        # 21-09: niet meer als afwijking geproduceerd — het is een REGRESSIE-LET-OP op blok automatisering (categorie
        # `boek_wachtrij_gestrand`, systeemmail + audit + probe); de soortnaam reist mee in `detail.afwijking_soort` van
        # die LET-OP (actie "Opnieuw indienen" op de rij). Entry blijft voor de tekst-guard en oude bevindingen.
        SoortDefinitie(
            soort="wordt_geboekt_verouderd",
            blok="documenten",
            sinds=date(2026, 9, 18),
            default=METEN,
            gepromoveerd_op=date(2026, 9, 21),
            meting="21-09: drie dagen gestrand zonder signaal (fout --command python) → LET-OP via automatiseringen, "
            "rapport docs/rapporten/2026-09-21-f3-jobs-command-python-job-smoketest-wordt-geboekt-let-op.md",
        ),
        # hercontrole "intussen buiten de module geboekt" (Peter 22-09, casus Bouwadvies F/2026/01235): dezelfde harde
        # check Duplicaatcheck, dagelijks vers op élk open document; het bewijs is een bestaand RLZ-/Odoo-boekstuk.
        # Besluit Peter in de opdracht: "start in meten? NEE — direct actie-bevinding mét actiemail".
        SoortDefinitie(
            soort="intussen_extern_geboekt",
            blok="documenten",
            sinds=date(2026, 9, 22),
            default=ACTIE,
            direct_actie_reden="Peter 22-09 (opdracht ter-accordering-bestaanscheck): bestaande harde-check-soort mét "
            "een bestaand boekstuk als bewijs — geen meetfase; explosie-rem blijft",
        ),
        # bank
        _oud("document_ontbreekt_in_rlz", "bank"),
        _oud("boeking_teruggedraaid_in_rlz", "bank"),
        _oud("mutatie_ontbreekt_in_rlz", "bank"),
        _oud("aflettering_teruggedraaid_in_rlz", "bank"),
        SoortDefinitie(
            soort="dubbele_betaling_vermoed",
            blok="bank",
            sinds=date(2026, 9, 16),
            default=METEN,  # 17-09: herdefinitie (betaling zonder factuur) — eerst meten, promotie ná de nameting
        ),
        # omzet
        _oud("verkoop_categorie_afwijkt", "omzet"),
        _oud("omzet_in_inkoopstroom", "omzet"),
        _oud("kassarapport_in_werkvoorraad", "omzet"),
        _oud("tussenrekening_open", "omzet"),
        # doorbelasting
        _oud("spiegel_open_verouderd", "doorbelasting"),
        _oud("da_ontbreekt_in_doel", "doorbelasting_aansluiting"),
        _oud("da_bedrag_afwijkt", "doorbelasting_aansluiting"),
        _oud("da_status_verschilt", "doorbelasting_aansluiting"),
        _oud("da_doel_niet_in_module", "doorbelasting_aansluiting"),
        _oud("da_inkoop_zonder_verkoop", "doorbelasting_aansluiting"),
        # intercompany + RC
        _oud("ic_ontbreekt_bij_ontvanger", "intercompany"),
        _oud("ic_ontbreekt_bij_verkoper", "intercompany"),
        _oud("ic_bedrag_verschilt", "intercompany"),
        _oud("ic_status_verschilt", "intercompany"),
        _oud("ic_spiegel_rood", "intercompany"),
        _oud("ic_tegenrelatie_onbekend", "intercompany"),
        _oud("rc_sluit_niet", "rekening_courant"),
        _oud("rc_zonder_tegenrekening", "rekening_courant"),
        _oud("rc_koppeling_gewijzigd", "rekening_courant"),
        # rlz_dubbel
        _oud("dubbel_in_rlz", "rlz_dubbel"),
        # projecten (blok 3 18-09): dubbel projectnummer in één administratie (ook buiten de module om) — meten.
        SoortDefinitie(soort="project_nummer_dubbel", blok="projecten", sinds=date(2026, 9, 18), default=METEN),
        # projecten (opdracht 19-09): actief project mét een "Afgesloten"-naam — LET-OP "afsluiten?" (blok projecten).
        SoortDefinitie(
            soort="project_naam_afgesloten_status_actief", blok="projecten", sinds=date(2026, 9, 19), default=METEN
        ),
        # activa (fase 1, Peter 21-09): aansluiting module-boekingen ↔ RLZ-activaregister — alles eerst meten.
        SoortDefinitie(soort="activa_register_niet_leesbaar", blok="activa", sinds=date(2026, 9, 21), default=METEN),
        SoortDefinitie(soort="mva_boeking_zonder_activum", blok="activa", sinds=date(2026, 9, 21), default=METEN),
        SoortDefinitie(soort="activum_zonder_boeking", blok="activa", sinds=date(2026, 9, 21), default=METEN),
        SoortDefinitie(soort="afschrijving_niet_gelopen", blok="activa", sinds=date(2026, 9, 21), default=METEN),
        SoortDefinitie(soort="activum_aanmaken_mislukt", blok="activa", sinds=date(2026, 9, 21), default=METEN),
        # intake (Peter 22-09): berichten in het postvak sinds gisteren zonder verwerking — het bewijs is de Message-ID
        # in de mailbox zelf, de handeling is deterministisch ("Nu verwerken" = de intake-job opnieuw starten). Besluit
        # Peter in de opdracht: "verschil > 0 = actie-bevinding mét de Message-ID's en knop Nu verwerken".
        SoortDefinitie(
            soort="intake_postvak_verschil",
            blok="intake",
            sinds=date(2026, 9, 23),
            default=ACTIE,
            direct_actie_reden="Peter 22-09 (opdracht intake tweede postvak): verschil postvak ↔ verwerkt is een "
            "telling aan de bron mét de Message-ID's als bewijs en één deterministische handeling (Nu verwerken); "
            "explosie-rem blijft",
        ),
    )
}


def code_default(soort: str) -> str:
    """Stand uit de registry; een ONBEKENDE soort is per definitie nieuw → `meten` (fail-closed richting actiemail)."""
    d = REGISTRY.get(soort)
    return d.default if d is not None else METEN


def stand_van(soort: str, overrides: dict[str, Any] | None) -> str:
    """DB-override wint van de code-default. Onbekende override-waarden tellen niet."""
    ov = (overrides or {}).get(soort)
    if ov in STANDEN:
        return str(ov)
    return code_default(soort)


def afwijking_soort_van(detail: dict | None) -> str | None:
    d = detail or {}
    s = d.get("afwijking_soort")
    return str(s) if s else None


def lees_overrides() -> dict[str, str]:
    """`reconciliatie_instelling.soort_standen` (0153); ontbreekt de rij/kolom → geen overrides (code-defaults)."""
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID
    from app.reconciliatie.models import ReconciliatieInstelling

    try:
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            rij = session.get(ReconciliatieInstelling, True)
            if rij is None:
                return {}
            return {str(k): str(v) for k, v in (rij.soort_standen or {}).items() if v in STANDEN}
    except Exception:  # noqa: BLE001 — een leesfout mag de run niet stoppen; zonder overrides = code-defaults
        return {}


def zet_stand(*, soort: str, stand: str, actor_id: uuid.UUID, reden: str, meting: str | None = None) -> dict[str, str]:
    """Promotie/degradatie van één soort (Beheerder of systeem) mét audit oud→nieuw. → alle overrides ná de wijziging."""
    from app.db.audit import record_audit_event
    from app.db.session import scoped_session
    from app.reconciliatie.models import ReconciliatieInstelling

    if stand not in STANDEN:
        raise ValueError(f"onbekende stand {stand!r} (meten | actie)")
    if soort not in REGISTRY:
        raise ValueError(f"onbekende bevindingssoort {soort!r} — eerst registreren in app/reconciliatie/soort_stand.py")
    with scoped_session(None, actor_id=actor_id) as session:
        rij = session.get(ReconciliatieInstelling, True)
        if rij is None:
            raise ValueError("boekhouding.reconciliatie_instelling heeft geen rij — migratie 0114 niet toegepast?")
        oud = dict(rij.soort_standen or {})
        nieuw = {**oud, soort: stand}
        rij.soort_standen = nieuw
        rij.gewijzigd_door = actor_id
        rij.gewijzigd_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="reconciliatie_instelling",
            record_id=uuid.UUID(int=0),
            actie="bevindingssoort_naar_actie" if stand == ACTIE else "bevindingssoort_naar_meten",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"soort": soort, "stand": stand_van(soort, oud)},
            nieuwe_waarde={"soort": soort, "stand": stand, "reden": reden, "meting": meting},
        )
        return {k: str(v) for k, v in nieuw.items()}


def tel_per_soort(bevindingen: Any) -> dict[str, int]:
    """Aantal AFWIJKING-bevindingen per afwijkingssoort in één run."""
    from app.reconciliatie.models import BevindingSoort

    uit: dict[str, int] = {}
    for b in bevindingen:
        if b.soort != BevindingSoort.AFWIJKING.value:
            continue
        s = afwijking_soort_van(b.detail)
        if s:
            uit[s] = uit.get(s, 0) + 1
    return uit


def geexplodeerd(tellers: dict[str, int], overrides: dict[str, Any] | None) -> dict[str, int]:
    """Soorten die in déze run méér dan EXPLOSIE_DREMPEL afwijkingen produceerden én nog op `actie` staan."""
    return {s: n for s, n in tellers.items() if n > EXPLOSIE_DREMPEL and stand_van(s, overrides) == ACTIE}


def in_meting(b: Any, overrides: dict[str, Any] | None) -> bool:
    """Een AFWIJKING waarvan de soort op `meten` staat: telt, maar vraagt geen handeling (actiemail/KPI)."""
    from app.reconciliatie.models import BevindingSoort

    if b.soort != BevindingSoort.AFWIJKING.value:
        return False
    s = afwijking_soort_van(b.detail)
    return bool(s) and stand_van(s, overrides) == METEN


def overzicht(overrides: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Voor DTO/CLI: per geregistreerde soort blok, sinds, code-default, override en effectieve stand."""
    return [
        {
            "soort": d.soort,
            "blok": d.blok,
            "sinds": d.sinds.isoformat(),
            "default": d.default,
            "override": (overrides or {}).get(d.soort),
            "stand": stand_van(d.soort, overrides),
        }
        for d in sorted(REGISTRY.values(), key=lambda x: (x.blok, x.soort))
    ]
