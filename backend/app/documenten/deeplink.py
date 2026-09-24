"""Server-spiegel van `frontend/src/werkvoorraad/format.ts::documentPad` — DE ENE plek waar de backend een kantoor-web-
pad naar een document bouwt (BUG 23-09: de vraag-thread linkte hard naar `/documenten/…` en opende een kassarapport in
een leeg inkoopformulier). De route volgt de SOORT: kassarapport → omzetreview, verkoopfactuur → verkoopreview,
waarborg → waarborg, verplichting → verplichting-review, al het andere → inkoop-controlescherm; een open vraag opent de
vráág op de klantpagina. Guard `tests/unit/test_documentlink_deeplink_guard.py`: nergens anders in `backend/app` een
letterlijke `/documenten/{…}`-link. Mails/push naar kantoor die een document noemen bouwen hun pad hierlangs (relatief;
de aanroeper zet `settings.app_basis_url` ervoor)."""

from __future__ import annotations

import uuid

REVIEW_ROUTE_PER_SOORT: dict[str, str] = {
    "kassarapport": "omzet",
    "verkoopfactuur": "verkoop",
    "waarborg": "waarborg",
    "verplichting": "verplichting",
}
STATUS_VRAAG_OPEN = "vraag_open"
STATUS_VERWIJDERD = "verwijderd"


def heeft_eigen_reviewscherm(soort: str | None) -> bool:
    return bool(soort and soort in REVIEW_ROUTE_PER_SOORT)


def document_pad(
    administratie_id: uuid.UUID | str,
    document_id: uuid.UUID | str,
    soort: str | None = None,
    status: str | None = None,
) -> str:
    """Relatief kantoor-web-pad voor "open dit document" — identiek aan de frontend-functie."""
    if status == STATUS_VRAAG_OPEN:
        return f"/?administratie={administratie_id}&sectie=vragen&document={document_id}"
    review = REVIEW_ROUTE_PER_SOORT.get(soort or "")
    if review:
        return f"/{review}/{administratie_id}/{document_id}"
    return f"/documenten/{administratie_id}/{document_id}"
