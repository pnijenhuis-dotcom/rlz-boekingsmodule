"""Rechtsgeldige factuur-PDF bij de doorbelasting (blok A gecombineerde run 26-08, besluit
Peter 26-08 — fiscaal: art. 35a Wet OB).

Aanleiding: de spiegel-inkoopfactuur in het DOEL droeg als bijlage alleen de originele
leveranciersbon (op naam van de bron). Zonder factuur op naam van de doelentiteit is er geen
geldige voorbelasting-aftrek — de cijfers klopten, het document ontbrak.

ROUTE A (STAP-0 26-08, verkenning/api-verkenning.md "Factuur-PDF-rendering"): RLZ rendert de
verkoopfactuur zélf via `GET SalesInvoices/{id}/Download` (Accept: application/pdf) — afzender
(adres, KvK, btw-nummer, IBAN uit de RLZ-lay-out), geadresseerde, factuurnummer (= de spiegel-
Reference), datum (= boekdatum), regels, btw-specificatie per tarief, totaal. Een eigen generator
(route B) zou het btw-nummer van afzender én afnemer niet eens uit de API kunnen halen.

HARD: deze module REKENT NOOIT. De PDF presenteert wat RLZ boekte; wij toetsen alleen
deterministisch of de gerenderde tekst de GEBOEKTE bedragen (netto, btw-som, totaal incl. —
centen identiek aan de boeking) en het factuurnummer draagt, plus KvK- en btw-nummer-vermelding.
Ontbreekt iets (lay-out in de RLZ-UI niet compleet, download mislukt, geen PDF): de boeking
krijgt zichtbaar `factuur_pdf_status = ontbreekt` mét reden — nooit een onvolledige factuur als
bijlage, en de boeking zelf gaat gewoon door (herstel via `make doorbelasting-facturen-herstel`).

Bijlage-plaatsing: de factuur-PDF gaat op BEIDE kanten (verkoopfactuur bron + spiegel-inkoop
doel) via `zorg_voor_bijlage(..., op_bestandsnaam=True)` — idempotent op bestandsnaam, eigen
basis-GUID's (`rlz_doorbelasting_factuur_upload_id`), cyclus-GUID's bij herstart. Aan de
doel-kant (waar de aftrek speelt) is de factuur de EERSTE bijlage, de originele bon de tweede.
"""

from __future__ import annotations

import base64
import logging
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO

from app.rlz.bijlage import zorg_voor_bijlage
from app.rlz.client import RlzApiError, RlzClient

logger = logging.getLogger(__name__)

FACTUUR_STATUS_AANWEZIG = "aanwezig"
FACTUUR_STATUS_ONTBREEKT = "ontbreekt"

_BTW_NUMMER = re.compile(r"nl\d{9}b\d{2}")


class FactuurNietBeschikbaar(Exception):
    """Render/toets/upload van de factuur-PDF lukte niet — alleen gebruikt door het herstel-commando
    (de boekmotor zelf werpt nooit: daar wordt de reden op de boeking gezet)."""


@dataclass(frozen=True)
class FactuurVerwachting:
    """Wat de gerenderde factuur MOET tonen — uitsluitend geboekte waarden (nooit herberekend):
    het RLZ-verkoopnummer (= spiegel-Reference), netto kosten, provisie en de btw-som zoals de
    motor ze boekte (grootste-rest-centen per regel)."""

    referentie: str
    netto_totaal: Decimal
    provisie: Decimal
    btw_totaal: Decimal

    @property
    def subtotaal_excl(self) -> Decimal:
        return self.netto_totaal + self.provisie

    @property
    def totaal_incl(self) -> Decimal:
        return self.netto_totaal + self.provisie + self.btw_totaal


def nl_bedrag(bedrag: Decimal) -> str:
    """NL-notatie zoals RLZ rendert: duizendtallen met punt, twee decimalen met komma
    (1607.05 → '1.607,05'; -12.5 → '-12,50')."""
    q = bedrag.quantize(Decimal("0.01"))
    teken = "-" if q < 0 else ""
    hele, _, cent = f"{abs(q):.2f}".partition(".")
    groepen: list[str] = []
    while len(hele) > 3:
        groepen.insert(0, hele[-3:])
        hele = hele[:-3]
    groepen.insert(0, hele)
    return f"{teken}{'.'.join(groepen)},{cent}"


def normaliseer_tekst(tekst: str) -> str:
    """pypdf breekt de RLZ-render in losse fragmenten ('NL\\n199235764\\nB\\n01', '€ 60,50'
    over twee regels) — álle witruimte weg en casefold maakt de toets deterministisch."""
    return re.sub(r"\s+", "", tekst).casefold()


def pdf_tekst(pdf: bytes) -> str:
    from pypdf import PdfReader

    lezer = PdfReader(BytesIO(pdf))
    return "\n".join((pagina.extract_text() or "") for pagina in lezer.pages)


def controleer_factuur_tekst(tekst: str, verwachting: FactuurVerwachting) -> list[str]:
    """Deterministische compleetheids-toets op de gerenderde factuurtekst. Retourneert de
    ontbrekende onderdelen (leeg = compleet). Bedragen worden als NL-tekst gezocht — dat is
    de enige manier om te bewijzen dat de PDF exact de geboekte centen toont."""
    t = normaliseer_tekst(tekst)
    ontbrekend: list[str] = []
    if normaliseer_tekst(verwachting.referentie) not in t:
        ontbrekend.append(f"factuurnummer {verwachting.referentie}")
    if "kvk" not in t:
        ontbrekend.append("KvK-nummer afzender")
    if not _BTW_NUMMER.search(t):
        ontbrekend.append("btw-nummer (NL…B..)")
    if "btw" not in t:
        ontbrekend.append("btw-specificatie")
    for label, bedrag in (
        ("subtotaal excl.", verwachting.subtotaal_excl),
        ("btw-som", verwachting.btw_totaal),
        ("totaal incl.", verwachting.totaal_incl),
    ):
        if normaliseer_tekst(f"€ {nl_bedrag(bedrag)}") not in t:
            ontbrekend.append(f"{label} € {nl_bedrag(bedrag)}")
    return ontbrekend


def factuur_bestandsnaam(referentie: str, doelentiteit_naam: str) -> str:
    """'Factuur RLZ-247123 Molenhof Verhuur BV.pdf' — herkenbaar naast de originele bon in de
    RLZ-bijlagenlijst; ook de idempotentie-sleutel (op_bestandsnaam) van de upload."""
    veilig = re.sub(r"[^A-Za-z0-9 ._-]+", "", doelentiteit_naam).strip()
    return f"Factuur {referentie} {veilig}".strip()[:120] + ".pdf"


def factuur_opslag_pad(*, administratie_id: uuid.UUID, document_id: uuid.UUID, mapping_id: uuid.UUID) -> str:
    return f"doorbelasting/factuur/{administratie_id}/{document_id}/{mapping_id}.pdf"


def haal_en_controleer_factuur(
    bron_client: RlzClient, *, verkoop_rlz_id: uuid.UUID, verwachting: FactuurVerwachting
) -> tuple[bytes | None, str | None]:
    """Render via RLZ + toets. Retourneert (pdf, None) bij een complete factuur, anders
    (None, reden). Werpt nooit: de boeking mag hier niet op stranden — de reden wordt
    zichtbaar op de boeking en het herstel-commando pakt 'm later op."""
    try:
        pdf = bron_client.download_sales_invoice_pdf(verkoop_rlz_id)
    except RlzApiError as exc:
        return None, f"RLZ-factuurrender mislukt ({exc.status_code}) — opnieuw via doorbelasting-facturen-herstel"
    except Exception as exc:  # noqa: BLE001 — netwerk/onbekend: zichtbaar, nooit blokkerend
        return None, f"RLZ-factuurrender mislukt ({exc.__class__.__name__}: {str(exc)[:120]})"
    if not pdf or not pdf.startswith(b"%PDF"):
        return None, "RLZ gaf geen PDF terug voor de verkoopfactuur"
    try:
        tekst = pdf_tekst(pdf)
    except Exception as exc:  # noqa: BLE001
        return None, f"factuur-PDF onleesbaar ({exc.__class__.__name__})"
    ontbrekend = controleer_factuur_tekst(tekst, verwachting)
    if ontbrekend:
        return None, (
            "factuur-PDF onvolledig: "
            + ", ".join(ontbrekend)
            + " — lay-out/stamgegevens in de RLZ-UI (Instellingen › Factuurlay-out) aanvullen, "
            "daarna doorbelasting-facturen-herstel"
        )
    return pdf, None


def voeg_factuur_als_bijlage_toe(
    client: RlzClient,
    entity_path: str,
    entity_id: uuid.UUID,
    *,
    upload_id: uuid.UUID,
    bestandsnaam: str,
    pdf: bytes,
) -> str | None:
    """Eén kant: factuur-PDF als bijlage (idempotent op bestandsnaam). Retourneert None bij
    succes/al-aanwezig, anders de reden — nooit een exception richting de boekmotor."""
    try:
        zorg_voor_bijlage(
            client,
            entity_path,
            entity_id,
            upload_id=upload_id,
            filename=bestandsnaam,
            content_base64=base64.b64encode(pdf).decode(),
            op_bestandsnaam=True,
        )
    except RlzApiError as exc:
        return f"bijlage-upload op {entity_path}/{entity_id} mislukt ({exc.status_code})"
    except Exception as exc:  # noqa: BLE001
        return f"bijlage-upload op {entity_path}/{entity_id} mislukt ({exc.__class__.__name__})"
    return None
