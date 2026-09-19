"""Omzet-reconciliatie (failsafe, zelfde patroon als de document- en bank-reconciliatie):
vergelijkt elke lokale omzet-boeking met de werkelijke RLZ-staat van BEIDE documenten
(verkoopfactuur + kostprijsmemoriaal) en rapporteert afwijkingen — in de RLZ-UI teruggedraaide
boekingen (Status 1), verdwenen documenten en alle half_geboekt-rijen (die zíjn de afwijking,
tot een mens ze oplost). Rapporteert alleen; herstellen is mensenwerk."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select

from app.db.session import scoped_session
from app.omzet.models import OmzetBoeking, OmzetBoekingStatus
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.tijd import vandaag_nl

logger = logging.getLogger(__name__)

# Geboekt in RLZ-termen = Status 2 (open) of 3 (afgeletterd/gesloten) — nooit alleen op 2
# toetsen (DocumentStatus-semantiek, geverifieerd 2026-07-13).
_GEBOEKTE_STATUSSEN = {2, 3}


@dataclass(frozen=True)
class OmzetAfwijking:
    administratie_id: uuid.UUID
    boeking_id: uuid.UUID
    document_id: uuid.UUID
    soort: str
    detail: str


def _controleer_rlz_document(
    *, client: RlzClient, pad: str, rlz_id: uuid.UUID, label: str
) -> tuple[str, str] | None:
    """None = in orde; anders (soort, omschrijving).

    De soort was tot 2026-08-12 voor alles `rlz_afwijking` — één emmer voor drie totaal
    verschillende situaties. Nu apart, omdat de vervolgactie per geval verschilt: een verdwenen
    document is boekhoudkundig werk, een teruggedraaide status is beoordelen-en-navolgen, en een
    mislukte controle zegt alleen dat de verbinding stuk was."""
    params = {"$expand": "DocumentCategory($expand=DocumentBinder)"} if pad == "SalesInvoices" else None
    try:
        doc = client.get(f"{pad}/{rlz_id}", params=params) if params else client.get(f"{pad}/{rlz_id}")
    except RlzApiError as exc:
        if exc.status_code == 404:
            return "ontbreekt_in_rlz", f"{label} {rlz_id} bestaat niet (meer) in RLZ"
        return "controle_mislukt", f"{label} {rlz_id} kon niet opgehaald worden: {exc}"
    status = doc.get("Status")
    if status not in _GEBOEKTE_STATUSSEN:
        return (
            "status_niet_definitief",
            f"{label} {rlz_id} staat in RLZ op Status {status} (teruggedraaid naar concept?)",
        )
    # Peter 16-09 (Van Boxtel): een Receipt hoort onder binder Inkomsten — de RLZ-UI groepeert op de binder van de
    # categorie. Zonder expand (oude fake/onbekend) geen oordeel; een andere binder = zichtbare afwijking.
    if pad == "SalesInvoices":
        categorie = doc.get("DocumentCategory") or {}
        binder = (categorie.get("DocumentBinder") or {}).get("Description") if isinstance(categorie, dict) else None
        if binder and binder.casefold() != "inkomsten":
            return (
                "verkoop_categorie_afwijkt",
                f"{label} {rlz_id} staat in RLZ onder '{binder}' (categorie {categorie.get('Name') or '?'}) i.p.v. "
                "Inkomsten — herboeken met de juiste categorie",
            )
    return None


def tussenrekening_open_afwijkingen(
    administratie_id: uuid.UUID, *, vandaag: date | None = None
) -> list[OmzetAfwijking]:
    """Opdracht 4 blok A (16-09): een tegenzijde-post van een geboekte omzetbatch (PIN-/Stripe-ontvangst of storting
    kas → bank) die ná `TUSSENREKENING_OPEN_DAGEN` dagen nog géén bankmatch heeft = bevinding `tussenrekening_open`
    mét handeling (koppel de bankontvangst of accepteer met reden). Puur lokaal: geen RLZ-call."""
    from app.omzet.tegenzijde_posten import TUSSENREKENING_OPEN_DAGEN, open_tussenrekening_posten

    vandaag = vandaag or vandaag_nl()
    with scoped_session(administratie_id) as session:
        standen = open_tussenrekening_posten(session, administratie_id=administratie_id, vandaag=vandaag)
    return [
        OmzetAfwijking(
            administratie_id=administratie_id,
            boeking_id=stand.boeking_id,
            document_id=stand.document_id,
            soort="tussenrekening_open",
            detail=(
                f"Omzetbatch {stand.post.batch_label}: {stand.post.label} € {stand.post.bedrag} staat al "
                f"{stand.dagen_open(vandaag)} dagen zonder bankontvangst (grens {TUSSENREKENING_OPEN_DAGEN} dagen; "
                f"verwacht sinds {stand.post.datum}) — koppel de bankontvangst of accepteer met reden"
            ),
        )
        for stand in standen
    ]


def omzet_in_inkoopstroom_afwijkingen(
    administratie_id: uuid.UUID, *, registreer: bool = False
) -> list[OmzetAfwijking]:
    """Peter 16-09 (Van Boxtel): (1) GEBOEKTE inkoopfacturen waarvan álle regels op een omzetrekening staan = een
    kassarapport dat de inkoopstroom nam (verschijnt in RLZ onder Uitgaven) → `omzet_in_inkoopstroom` mét "Herboeken als
    omzet"; (2) blok C 16-09 avond: ONGEBOEKTE inkoopfactuur-documenten in de werkvoorraad die op inhoud een
    kassarapport zijn (herkende bron op de PDF-tekstlaag — begrensd tot de werkvoorraad — of alle regels op een
    omzetrekening) → `kassarapport_in_werkvoorraad` mét "Type wijzigen → kassarapport". Puur lokaal, geen RLZ-call.
    record_id = document_id. `registreer=True` (alleen in de echte run, nooit lees-only) schrijft één audit-rij
    `kassarapport_inkoopstroom_run` per administratie mét tellers — de bron van de automatiserings-teller."""
    from app.db.audit import record_audit_event
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID
    from app.omzet import autotype, inkoopstroom

    # Peter 19-09: eenduidig = systeem. In de ECHTE run zet de motor élk werkvoorraad-document mét parser-treffer eerst
    # automatisch om (tijdlijn + audit + dagteller); wat overblijft is een melding mét knop: het zachte signaal
    # 'omzetrekeningen' (geen parser) en parser-treffers die bewust zijn overgeslagen (≥ 2 correcties, status, fout).
    # Lees-only (--lees-only / losse CLI) schrijft niets en toont de kandidaten mét "automatisch bij de dagelijkse run".
    autotype_reden: dict[uuid.UUID, str] = {}
    if registreer:
        try:
            run = autotype.verwerk_werkvoorraad(administratie_id)
            autotype_reden = {
                d.document_id: (
                    f"overgeslagen: {d.reden}" + (f" {d.correcties}×" if d.reden == autotype.REDEN_CORRECTIES else "")
                )
                for d in run.documenten
                if d.uitkomst == "overgeslagen"
            }
        except Exception:  # noqa: BLE001 — de motor mag de toets nooit laten omvallen; dan blijven het meldingen
            logger.exception("kassarapport-autotype mislukt voor %s", administratie_id)

    with scoped_session(administratie_id) as session:
        treffers = inkoopstroom.geboekte_kassarapporten_in_inkoopstroom(session, administratie_id=administratie_id)
        ongeboekt = inkoopstroom.ongeboekte_kassarapporten_in_inkoopstroom(session, administratie_id=administratie_id)

    def _automatisch(w) -> str:  # noqa: ANN001
        if w.signaal == "omzetrekeningen":
            return ""
        if not registreer:
            return ", automatisch bij de dagelijkse run"
        return f", automatisch {autotype_reden.get(w.document_id, 'overgeslagen: onbekend')}"
    uit = [
        OmzetAfwijking(
            administratie_id=administratie_id,
            boeking_id=t.document_id,
            document_id=t.document_id,
            soort=inkoopstroom.SOORT,
            detail=(
                f"Inkoopfactuur {t.boekstuknummer or str(t.document_id)[:8]} ({t.bestandsnaam}, "
                f"factuurdatum {t.factuurdatum or '?'}) is omzet: alle {t.regels_totaal} regels staan op een "
                "omzetrekening — verschijnt in RLZ onder Uitgaven; herboeken als omzet (storno + kassarapport)"
            ),
        )
        for t in treffers
    ]
    uit.extend(
        OmzetAfwijking(
            administratie_id=administratie_id,
            boeking_id=w.document_id,
            document_id=w.document_id,
            soort=inkoopstroom.SOORT_WERKVOORRAAD,
            detail=(
                f"Kassarapport {w.bestandsnaam} staat als inkoopfactuur in de werkvoorraad (status {w.status}; "
                f"signaal {w.signaal}"
                + (f", {w.regels_op_omzet}/{w.regels_totaal} regels op een omzetrekening" if w.regels_totaal else "")
                + _automatisch(w)
                + ") — type wijzigen naar kassarapport"
            ),
        )
        for w in ongeboekt
    )
    if registreer and uit:
        try:
            with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
                record_audit_event(
                    session,
                    actor_id=SYSTEEM_ACTOR_ID,
                    module="boekhouding",
                    tabel="document",
                    record_id=administratie_id,
                    actie="kassarapport_inkoopstroom_run",
                    correlatie_id=uuid.uuid4(),
                    nieuwe_waarde={
                        "geboekt": len(treffers),
                        "ongeboekt": len(ongeboekt),
                        "signalen": sorted({w.signaal for w in ongeboekt} | {t.signaal for t in treffers}),
                    },
                    administratie_id=administratie_id,
                )
        except Exception:  # noqa: BLE001 — de teller mag de reconciliatie nooit laten omvallen
            logger.exception("audit kassarapport_inkoopstroom_run mislukt voor %s", administratie_id)
    return uit


def reconcilieer_omzet(administratie_id: uuid.UUID, *, registreer: bool = False) -> list[OmzetAfwijking]:
    with scoped_session(administratie_id) as session:
        boekingen = session.scalars(
            select(OmzetBoeking).where(
                OmzetBoeking.administratie_id == administratie_id,
                OmzetBoeking.status.in_((OmzetBoekingStatus.GEBOEKT.value, OmzetBoekingStatus.HALF_GEBOEKT.value)),
            )
        ).all()
    inkoopstroom_afwijkingen = omzet_in_inkoopstroom_afwijkingen(administratie_id, registreer=registreer)
    if not boekingen:
        return inkoopstroom_afwijkingen

    afwijkingen: list[OmzetAfwijking] = tussenrekening_open_afwijkingen(administratie_id) + inkoopstroom_afwijkingen
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    with client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id) as client:
        for boeking in boekingen:
            if boeking.status == OmzetBoekingStatus.HALF_GEBOEKT.value:
                afwijkingen.append(
                    OmzetAfwijking(
                        administratie_id=administratie_id,
                        boeking_id=boeking.id,
                        document_id=boeking.document_id,
                        soort="half_geboekt",
                        detail=(
                            f"Periode {boeking.periode_start} t/m {boeking.periode_eind}: "
                            f"verkoopfactuur {boeking.verkoop_rlz_id} staat (mogelijk) geboekt zonder "
                            f"kostprijsmemoriaal — {boeking.half_geboekt_detail}"
                        ),
                    )
                )
                continue
            for pad, rlz_id, label in (
                ("SalesInvoices", boeking.verkoop_rlz_id, "verkoopfactuur"),
                ("ManualJournals", boeking.memoriaal_rlz_id, "kostprijsmemoriaal"),
            ):
                if rlz_id is None:
                    continue
                bevinding = _controleer_rlz_document(client=client, pad=pad, rlz_id=rlz_id, label=label)
                if bevinding is not None:
                    soort, detail = bevinding
                    afwijkingen.append(
                        OmzetAfwijking(
                            administratie_id=administratie_id,
                            boeking_id=boeking.id,
                            document_id=boeking.document_id,
                            soort=soort,
                            detail=f"Periode {boeking.periode_start} t/m {boeking.periode_eind}: {detail}",
                        )
                    )
    return afwijkingen


@dataclass(frozen=True)
class OmzetReconciliatieResultaat:
    """Afwijkingen én mislukte administraties. Die tweede helft bestond niet tot 2026-08-12: een
    administratie waarvan de reconciliatie omviel (credentials, RLZ-storing) werd alleen
    weggelogd, waarna het commando vrolijk "geen afwijkingen" meldde en exit 0 gaf. Een vangrail
    die bij een storing groen licht geeft, is erger dan geen vangrail."""

    afwijkingen: list[OmzetAfwijking]
    fouten: dict[uuid.UUID, str]
    #: A12 (07-09): Odoo-administraties — dit blok is RLZ-only en slaat ze zichtbaar over (geen fout).
    overgeslagen: dict[uuid.UUID, str] = field(default_factory=dict)


def reconcilieer_alle_omzet(*, registreer: bool = False) -> OmzetReconciliatieResultaat:
    """Alle administraties; één kapotte administratie (credentials, RLZ-storing) stopt de rest
    niet — zelfde patroon als sync_alle_administraties — maar wordt wél teruggegeven zodat de
    aanroeper hem zichtbaar maakt en de exit-code op 1 zet. Odoo-administraties: het RLZ-deel wordt zichtbaar
    overgeslagen (A12), de LOKALE toets "kassarapport in de inkoopstroom" (blok C 16-09 avond) draait wél — die kent
    geen backend."""
    from app.backends.registry import RLZ_ONLY_OVERGESLAGEN, actieve_administraties_per_backend

    administratie_ids, odoo_ids = actieve_administraties_per_backend()
    alle: list[OmzetAfwijking] = []
    fouten: dict[uuid.UUID, str] = {}
    for administratie_id in administratie_ids:
        try:
            alle.extend(reconcilieer_omzet(administratie_id, registreer=registreer))
        except Exception as exc:  # noqa: BLE001 — rapporteren en door, nooit de hele run stoppen
            logger.exception("Omzet-reconciliatie mislukt voor administratie %s", administratie_id)
            fouten[administratie_id] = str(exc)
    for administratie_id in odoo_ids:
        try:
            alle.extend(omzet_in_inkoopstroom_afwijkingen(administratie_id, registreer=registreer))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Lokale omzet-toets mislukt voor Odoo-administratie %s", administratie_id)
            fouten[administratie_id] = str(exc)
    return OmzetReconciliatieResultaat(
        afwijkingen=alle, fouten=fouten, overgeslagen={aid: RLZ_ONLY_OVERGESLAGEN for aid in odoo_ids}
    )
