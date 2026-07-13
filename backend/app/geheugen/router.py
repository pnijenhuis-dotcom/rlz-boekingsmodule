from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.auth.deps import CurrentGebruiker, vereis_administratie_scope
from app.geheugen import schemas, service
from app.geheugen.engine import VeldVoorstel

router = APIRouter(tags=["boekingsgeheugen"])


def _naar_veld_response(veld: VeldVoorstel) -> schemas.VeldVoorstelResponse:
    return schemas.VeldVoorstelResponse(
        waarde=veld.waarde, confidence=veld.confidence, telling=veld.telling, oranje=veld.oranje, reden=veld.reden
    )


@router.post(
    "/administraties/{administratie_id}/boekingsgeheugen/voorstel",
    response_model=schemas.GeheugenVoorstelResponse,
)
def geheugen_voorstel(
    administratie_id: uuid.UUID,
    invoer: schemas.GeheugenVoorstelInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.GeheugenVoorstelResponse:
    """Boekingsgeheugen-voorstel (B6) voor het controlescherm en de latere autoboek-gate: per
    veld (GB/btw/project) een waarde + confidence + oranje-vlag. POST met body — de
    regelomschrijving hoort nooit in een URL. Een voorstel is een default, nooit een beslissing:
    de harde checks (incl. projectplicht) blijven onverkort blokkerend."""
    voorstel = service.voorstel_voor(
        administratie_id=administratie_id,
        vendor_id=invoer.vendor_id,
        regel_omschrijving=invoer.regel_omschrijving,
    )
    return schemas.GeheugenVoorstelResponse(
        gb=_naar_veld_response(voorstel.gb),
        btw=_naar_veld_response(voorstel.btw),
        project=_naar_veld_response(voorstel.project),
    )
