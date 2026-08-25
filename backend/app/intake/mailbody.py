"""Tekstuele mail-body bij het intake-bericht (feedbackronde 25-08 deel 3, punt 1 — casus: een
collega mailt een factuur met "dit is voor Oirschot").

Deterministisch, stdlib-only:
- voorkeur text/plain, anders text/html → platte tekst (eigen HTMLParser: blok-elementen worden
  regeleinden, <style>/<script>/<head> vallen weg, entities worden gedecodeerd);
- handtekening-/disclaimer-/quote-ruis wordt gestript waar dat zonder gokken kan: alles vanaf
  de RFC 3676-scheider ("-- "), een groet-regel ("Met vriendelijke groet", "Kind regards", …),
  een geciteerd-antwoord-kop ("Op … schreef …:", "On … wrote:", "Van: …"/"From: …"-blok) of een
  standaard-disclaimer-aanhef ("Dit bericht is uitsluitend bestemd …", "This e-mail and any
  attachments …") wordt afgekapt. Wat vóór de eerste ruis-marker staat is de body;
- witruimte genormaliseerd, begrensd op MAX_TEKENS (niets stil weggooien: de afkap is zichtbaar
  met "[… afgekapt]").

Bewust GEEN AI hier — het is bewaarplicht-/dossier-tekst (7 jaar, AVG-register V2) én een
hint voor toewijzing en extractie; die hint-paden hebben hun eigen BSN-filter vóór verzending."""

from __future__ import annotations

import re
from email.message import EmailMessage
from html import unescape
from html.parser import HTMLParser

MAX_TEKENS = 20_000
_AFKAP_MARKER = "\n[… afgekapt]"

_BLOK_ELEMENTEN = {
    "p", "div", "br", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "pre", "section", "article", "header", "footer", "hr",
}  # fmt: skip
_ONZICHTBAAR = {"style", "script", "head", "title", "meta"}

# Regels waarvandaan de rest van de mail ruis is (handtekening / disclaimer / quote).
_RUIS_START = re.compile(
    r"^(?:"
    r"-- ?$"  # RFC 3676 signature separator
    r"|_{3,}$|-{5,}$"  # visuele scheidingslijn vóór een handtekening/disclaimer
    r"|(?:met\s+)?(?:vriendelijke|hartelijke)\s+groet(?:en)?\b.*"
    r"|(?:mvg|groet(?:en|jes)?|hoogachtend|kind\s+regards|best\s+regards|regards|"
    r"with\s+kind\s+regards|yours\s+sincerely|cheers)\s*[,.!]?\s*$"
    r"|op\s.+\sschreef\s.*:?\s*$"  # "Op 25 aug 2026 schreef Jan <…>:"
    r"|on\s.+\swrote:\s*$"  # "On Mon, Aug 25, 2026 … wrote:"
    r"|(?:van|from):\s+.+$"  # kop van een doorgestuurd/geciteerd bericht
    r"|-{2,}\s*(?:oorspronkelijk|original|doorgestuurd|forwarded)\s+(?:bericht|message)\s*-{2,}.*$"
    r"|verzonden\s+vanaf\s+mijn\s.+$|sent\s+from\s+my\s.+$"
    r"|(?:dit\s+(?:e-?mail)?bericht|deze\s+e-?mail)\s+(?:is\s+uitsluitend|en\s+(?:eventuele|alle)\s+bijlagen|kan\s+vertrouwelijk).*$"
    r"|(?:this\s+(?:e-?mail|message)|the\s+information)\s+(?:and\s+any\s+attachments|is\s+(?:intended|confidential)|may\s+contain).*$"
    r"|de\s+informatie\s+(?:in\s+dit|verzonden\s+met).*$"
    r")",
    re.IGNORECASE,
)
_GECITEERDE_REGEL = re.compile(r"^\s*>")
_WITRUIMTE_IN_REGEL = re.compile(r"[ \t ]+")


class _HtmlNaarTekst(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._delen: list[str] = []
        self._onzichtbaar_diepte = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _ONZICHTBAAR:
            self._onzichtbaar_diepte += 1
        elif tag in _BLOK_ELEMENTEN:
            self._delen.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _ONZICHTBAAR:
            self._onzichtbaar_diepte = max(0, self._onzichtbaar_diepte - 1)
        elif tag in _BLOK_ELEMENTEN:
            self._delen.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._onzichtbaar_diepte:
            self._delen.append(data)

    def tekst(self) -> str:
        return "".join(self._delen)


def html_naar_tekst(html: str) -> str:
    parser = _HtmlNaarTekst()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 — kapotte HTML: dan de tags er ruw uit
        return unescape(re.sub(r"<[^>]+>", " ", html))
    return parser.tekst()


def strip_ruis(tekst: str) -> str:
    """Kapt de tekst af vanaf de eerste ruis-marker en laat geciteerde regels ('> …') weg."""
    schone_regels: list[str] = []
    for regel in tekst.splitlines():
        kaal = regel.strip()
        if _GECITEERDE_REGEL.match(regel):
            continue
        if kaal and _RUIS_START.match(kaal):
            break
        schone_regels.append(regel)
    return "\n".join(schone_regels)


def normaliseer_witruimte(tekst: str) -> str:
    genormaliseerd = tekst.replace("\r\n", "\n").replace("\r", "\n")
    regels = [_WITRUIMTE_IN_REGEL.sub(" ", r).strip() for r in genormaliseerd.split("\n")]
    samengevoegd = "\n".join(regels)
    samengevoegd = re.sub(r"\n{3,}", "\n\n", samengevoegd)
    return samengevoegd.strip()


def begrens(tekst: str, *, max_tekens: int = MAX_TEKENS) -> str:
    if len(tekst) <= max_tekens:
        return tekst
    return tekst[: max_tekens - len(_AFKAP_MARKER)].rstrip() + _AFKAP_MARKER


def body_tekst_uit_bericht(bericht: EmailMessage) -> str | None:
    """Platte tekst van de mail-body, of None als er geen tekstdeel is (of alleen ruis)."""
    deel = bericht.get_body(preferencelist=("plain", "html"))
    if deel is None:
        return None
    try:
        ruw = deel.get_content()
    except Exception:  # noqa: BLE001 — onbekende charset/kapotte transfer-encoding: geen body
        payload = deel.get_payload(decode=True)
        if not isinstance(payload, bytes):
            return None
        ruw = payload.decode("utf-8", errors="replace")
    if not isinstance(ruw, str):
        return None
    if deel.get_content_subtype() == "html":
        ruw = html_naar_tekst(ruw)
    tekst = normaliseer_witruimte(strip_ruis(normaliseer_witruimte(ruw)))
    return begrens(tekst) if tekst else None
