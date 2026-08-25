"""Doorbelasting ín de boekflow (besluit Peter 25-08, RLZ-feedbackronde punt A — herziet het
besluit van 13-08 "actie op een GEBOEKT document"; kliktest-bevinding: een medewerker was twee
keer met dezelfde factuur bezig).

Seam-eis: er komt géén nieuwe boekmotor. Deze module orkestreert uitsluitend de twee bestaande
motoren in vaste volgorde: (1) doorbelasting-checks van de klaargezette run vooraf (samen met
de inkoop-checks moet álles groen zijn vóór de knop actief is — de server hertoetst), (2)
`app.documenten.boeken.boek_document` onverkort (alle poorten: accordering, factuurmatch,
harde checks, kill switch, volumerem), (3) KLAARGEZET → CONCEPT en
`app.doorbelasting.boeken.boek_doorbelasting_run` onverkort (verkoopfacturen bron +
spiegels doel, half-geboekt-patroon). Faalt (3) ná een geslaagde inkoopboeking, dan is dat
ZICHTBAAR (fout op de run + in de response, tijdlijn-detail) en nooit stil: de bestaande
herstel-/stornoroutes van de doorbelasting (reviewscherm "Doorbelasten…", spiegel-taken,
storno per deelboeking) gelden onverkort. Zonder klaargezette run gedraagt de orkestratie
zich exact als een gewone boek_document-aanroep.

Beide ingangen gebruiken deze module: de boekknop ("Boeken + doorbelasten", documenten-router)
én de accorderingsflow (ná het laatste akkoord, systeem-actor).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from app.db.session import scoped_session
from app.documenten import boeken as documenten_boeken
from app.documenten.checks import CheckRapport, CheckResultaat
from app.doorbelasting import boeken as doorbelasting_boeken
from app.doorbelasting import service as doorbelasting_service
from app.doorbelasting.models import DoorbelastingRun
from app.rlz.client import RlzApiError
from app.rlz.credentials import GeenRlzCredentials

logger = logging.getLogger(__name__)


class DoorbelastingChecksNietGroen(Exception):
    """De klaargezette doorbelasting heeft blokkerende checks — boeken (of aanbieden ter
    accordering) gaat niet door; níéts is geschreven. Draagt het rapport voor de UI."""

    def __init__(self, rapport: CheckRapport) -> None:
        super().__init__("Boeken geblokkeerd door doorbelasting-checks")
        self.rapport = rapport


@dataclass(frozen=True)
class BoekMetDoorbelastingResultaat:
    boek: documenten_boeken.BoekResultaat
    # None = er was geen klaargezette doorbelasting (gewone boeking)
    doorbelasting_run_id: uuid.UUID | None
    doorbelasting: dict[str, str] | None
    # Zichtbare fout van de doorbelasting-stap ná een geslaagde inkoopboeking (nooit stil)
    doorbelasting_fout: str | None


def _registreer_run_fout(*, administratie_id: uuid.UUID, run_id: uuid.UUID, fout: str) -> None:
    """Run-brede fout (vóór/buiten een doelentiteit) zichtbaar op de run — zelfde JSONB als de
    per-doelentiteit-fouten van de motor, onder de vaste sleutel "run"."""
    from datetime import UTC, datetime

    with scoped_session(administratie_id) as session:
        run = session.get(DoorbelastingRun, run_id)
        if run is not None:
            laatste = dict(run.laatste_fout or {})
            laatste["run"] = {"fout": fout[:500], "ts": datetime.now(UTC).isoformat()}
            run.laatste_fout = laatste


def klaargezette_run_voor(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> DoorbelastingRun | None:
    with scoped_session(administratie_id) as session:
        run = doorbelasting_service.klaargezette_run(session, document_id=document_id)
        if run is not None:
            session.expunge(run)
        return run


def toets_klaargezette_doorbelasting(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> CheckRapport | None:
    """Doorbelasting-checks van de klaargezette run (None als er geen is). Blokkerend →
    DoorbelastingChecksNietGroen. Gedeeld door boeken én ter-accordering-aanbieden: een
    document met een rode doorbelasting gaat nooit naar de klant. Mét `actor_id` óók de
    doel-scope-toets van de motor (een medewerker doorbelast alleen naar administraties waarop
    hij scope heeft) — hier al, zodat de inkoopboeking níét doorgaat als de doorbelasting straks
    op scope zou stranden (de systeem-actor ná het laatste akkoord leunt op deze toets)."""
    run = klaargezette_run_voor(administratie_id=administratie_id, document_id=document_id)
    if run is None:
        return None
    review = doorbelasting_service.review_data(administratie_id=administratie_id, run_id=run.id)
    if actor_id is not None and review.regels:
        mappings = {m.id: m for m in doorbelasting_service.lijst_mappings(administratie_id=administratie_id)}
        zonder_scope = sorted(
            {
                mappings[r.mapping_id].doelentiteit_naam
                for r in review.regels
                if r.mapping_id in mappings
                and mappings[r.mapping_id].doel_administratie_id is not None
                and not doorbelasting_service.actor_heeft_scope(
                    actor_id=actor_id, administratie_id=mappings[r.mapping_id].doel_administratie_id
                )
            }
        )
        if zonder_scope:
            raise DoorbelastingChecksNietGroen(
                CheckRapport(
                    resultaten=[
                        *review.rapport.resultaten,
                        CheckResultaat(
                            naam="doorbelasting_scope",
                            ok=False,
                            melding="Geen scope op doel-administratie(s): " + ", ".join(zonder_scope),
                        ),
                    ]
                )
            )
    if not review.regels:
        # Vinkje aan maar niets verdeeld: expliciet blokkeren i.p.v. stil "gewoon boeken" —
        # de gebruiker koos "Boeken + doorbelasten".
        raise DoorbelastingChecksNietGroen(
            CheckRapport(
                resultaten=[
                    *review.rapport.resultaten,
                    CheckResultaat(
                        naam="doorbelasting_verdeling",
                        ok=False,
                        melding="Doorbelasten na boeken staat aan, maar er is nog geen verdeling opgeslagen",
                    ),
                ]
            )
        )
    if review.rapport.geblokkeerd:
        raise DoorbelastingChecksNietGroen(review.rapport)
    return review.rapport


def boek_document_met_doorbelasting(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    extra_overgang_detail: dict | None = None,
    match_afwijking_bevestigd: bool = False,
    materiaal_afwijking_bevestigd: bool = False,
    bron_client=None,
    doel_client_factory=None,
) -> BoekMetDoorbelastingResultaat:
    """Boeken + (indien klaargezet) doorbelasten in één gang. `bron_client`/`doel_client_factory`
    zijn de test-seams van de doorbelastingsmotor (doorgegeven, nooit zelf gebruikt). Alle inkoop-poorten en -fouten van
    boek_document reizen ongewijzigd door (de router vertaalt ze al); de doorbelasting-checks
    lopen VÓÓR de inkoopboeking zodat er bij rood niets geschreven is."""
    run = klaargezette_run_voor(administratie_id=administratie_id, document_id=document_id)
    if run is None:
        boek = documenten_boeken.boek_document(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor_id,
            extra_overgang_detail=extra_overgang_detail,
            match_afwijking_bevestigd=match_afwijking_bevestigd,
            materiaal_afwijking_bevestigd=materiaal_afwijking_bevestigd,
        )
        return BoekMetDoorbelastingResultaat(
            boek=boek, doorbelasting_run_id=None, doorbelasting=None, doorbelasting_fout=None
        )

    toets_klaargezette_doorbelasting(administratie_id=administratie_id, document_id=document_id, actor_id=actor_id)

    boek = documenten_boeken.boek_document(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        extra_overgang_detail={**(extra_overgang_detail or {}), "doorbelasting_na_boeken": str(run.id)},
        match_afwijking_bevestigd=match_afwijking_bevestigd,
        materiaal_afwijking_bevestigd=materiaal_afwijking_bevestigd,
    )

    # Inkoopfactuur staat in RLZ. Vanaf hier is elke fout een zichtbare doorbelasting-fout op de
    # run (nooit stil, nooit een exception die de geslaagde boeking verhult).
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        run_in_sessie = session.get(DoorbelastingRun, run.id)
        assert run_in_sessie is not None
        doorbelasting_service.activeer_klaargezette_run(session, run=run_in_sessie, actor_id=actor_id)

    doorbelasting: dict[str, str] | None = None
    fout: str | None = None
    try:
        doorbelasting = doorbelasting_boeken.boek_doorbelasting_run(
            administratie_id=administratie_id,
            run_id=run.id,
            actor_id=actor_id,
            bron_client=bron_client,
            doel_client_factory=doel_client_factory,
        )
    except doorbelasting_boeken.BoekenGeblokkeerdDoorChecks as exc:
        fout = "Doorbelasting geblokkeerd door harde checks: " + "; ".join(
            r.melding for r in exc.rapport.resultaten if not r.ok
        )
    except (
        doorbelasting_service.DoorbelastingFout,
        doorbelasting_boeken.AdministratieNietBereikbaar,
        documenten_boeken.BoekenUitgeschakeld,
        documenten_boeken.VolumeremBereikt,
        GeenRlzCredentials,
        RlzApiError,
    ) as exc:
        fout = str(exc)
    if fout is not None:
        logger.warning("Boeken + doorbelasten: inkoop geboekt, doorbelasting run %s mislukt: %s", run.id, fout)
        _registreer_run_fout(administratie_id=administratie_id, run_id=run.id, fout=fout)
    elif doorbelasting and any(v in ("mislukt", "half_geboekt") for v in doorbelasting.values()):
        fout = "Doorbelasting deels mislukt — zie het resultaat per doelentiteit (herstel via Doorbelasten…)"
    return BoekMetDoorbelastingResultaat(
        boek=boek, doorbelasting_run_id=run.id, doorbelasting=doorbelasting, doorbelasting_fout=fout
    )
