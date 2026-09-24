"""Documentlink volgt de soort (BUG 23-09, bundelrun 24-09 blok 7a): één bron `app/documenten/deeplink.py::document_pad`
voor élk kantoor-web-pad naar een document in de backend; een letterlijke `/documenten/{…}`-link elders is rood. Plus de
gedragstoets van de spiegel (identiek aan `frontend/src/werkvoorraad/format.ts::documentPad`)."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from app.documenten import deeplink

APP = Path(__file__).resolve().parents[2] / "app"
LINK_RE = re.compile(r"""["']/documenten/\{""")
TOEGESTAAN = {APP / "documenten" / "deeplink.py"}


def test_geen_letterlijke_documentlink_buiten_deeplink() -> None:
    fouten: list[str] = []
    for pad in APP.rglob("*.py"):
        if pad in TOEGESTAAN:
            continue
        for nr, regel in enumerate(pad.read_text(encoding="utf-8").splitlines(), 1):
            if LINK_RE.search(regel):
                fouten.append(f"{pad.relative_to(APP.parent)}:{nr}: {regel.strip()}")
    assert not fouten, "letterlijke /documenten/{…}-link buiten app/documenten/deeplink.py:\n" + "\n".join(fouten)


def test_document_pad_volgt_de_soort() -> None:
    adm, doc = uuid.uuid4(), uuid.uuid4()
    assert deeplink.document_pad(adm, doc) == f"/documenten/{adm}/{doc}"
    assert deeplink.document_pad(adm, doc, soort="inkoopfactuur") == f"/documenten/{adm}/{doc}"
    assert deeplink.document_pad(adm, doc, soort="kassarapport") == f"/omzet/{adm}/{doc}"
    assert deeplink.document_pad(adm, doc, soort="verkoopfactuur") == f"/verkoop/{adm}/{doc}"
    assert deeplink.document_pad(adm, doc, soort="waarborg") == f"/waarborg/{adm}/{doc}"
    assert deeplink.document_pad(adm, doc, soort="verplichting") == f"/verplichting/{adm}/{doc}"
    assert deeplink.document_pad(adm, doc, soort="kassarapport", status="vraag_open") == (
        f"/?administratie={adm}&sectie=vragen&document={doc}"
    )
    assert deeplink.heeft_eigen_reviewscherm("kassarapport") and not deeplink.heeft_eigen_reviewscherm("inkoopfactuur")
