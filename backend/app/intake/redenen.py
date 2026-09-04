"""Intake-redenen: één deterministische vertaling van de technische verzamelbak-reden (zoals de
intake 'm in de tijdlijn en het intake-bericht vastlegt) naar wat de mens op de verzamelbak-rij
ziet (spoedopdracht 02-09, diagnose punt 1 — de UI toonde tot dan bij élke lege tenaamstelling
"geen tenaamstelling gelezen", ook als de AI wél las en de code het voorstel verwierp).

Regel: "geen tenaamstelling gelezen" UITSLUITEND als de AI werkelijk niets las; een verworpen of
mislukte AI-lezing benoemt de échte reden. Geen enum-jargon richting de gebruiker (avondrun 26-08).

Hier leeft óók `is_verworpen_intake_reden`: de gedeelde definitie "dit intake-voorstel is verworpen/
mislukt" voor de bewakingsprobe (intake-verwerpingsratio) — één bron, zodat de UI en de bewaking
nooit uit de pas lopen."""

from __future__ import annotations

_SPLITSING_MISLUKT = "splitsingsdetectie_mislukt:"
_HERLEZEN_MISLUKT = "intake_herlezen_mislukt:"
_VOORSTEL_ONGELDIG = "Splitsingsvoorstel ongeldig:"
# Blok B 04-09 — gelijk aan `app/intake/splitsing_uitsluiting.REDEN_PREFIX` (hier letterlijk, geen import:
# redenen.py blijft afhankelijkheidsvrij voor de bewaking).
_NOOIT_SPLITSEN = "splitsing_overgeslagen_nooit_splitsen:"
_MAX_DETAIL = 140


def _kort(tekst: str) -> str:
    tekst = " ".join(tekst.split())
    return tekst if len(tekst) <= _MAX_DETAIL else tekst[: _MAX_DETAIL - 1].rstrip() + "…"


def is_verworpen_intake_reden(reden: str | None) -> bool:
    """Waar voor élke intake-uitkomst waarbij een AI-voorstel (deels) door code is verworpen of de
    AI-lezing mislukte — de teller van de bewakingsprobe `intake_verwerpingsratio`. Gate-uit en
    limiet-bereikt zijn géén pogingen; "tenaamstelling niet eenduidig" is een correcte uitkomst."""
    if not reden:
        return False
    if reden.startswith(_SPLITSING_MISLUKT) or reden.startswith(_HERLEZEN_MISLUKT):
        return True
    return reden.startswith("splitsingsvoorstel_ter_controle") and "ongeldig" in reden


def omschrijf_intake_reden(reden: str | None, *, tenaamstelling: str | None) -> str | None:
    """Leesbaar label voor de verzamelbak-rij; None = niets extra te melden (bv. een gewoon
    splitsingsvoorstel — dat toont de rij al zelf)."""
    if reden is None or not reden.strip():
        return None if tenaamstelling else "geen tenaamstelling gelezen"
    reden = reden.strip()

    if reden == "intake_ai_uitgeschakeld":
        return "intake-AI staat uit — handmatig toewijzen"
    if reden == "ai_limiet_bereikt":
        return "AI-limiet bereikt — handmatig verwerken"
    if reden.startswith(_SPLITSING_MISLUKT) or reden.startswith(_HERLEZEN_MISLUKT):
        prefix = _SPLITSING_MISLUKT if reden.startswith(_SPLITSING_MISLUKT) else _HERLEZEN_MISLUKT
        detail = reden[len(prefix) :].strip()
        if detail.startswith(_VOORSTEL_ONGELDIG):
            kern = detail[len(_VOORSTEL_ONGELDIG) :].strip()
            if kern.startswith("geen facturen herkend"):
                return "AI herkende geen factuur in dit document"
            # Oude rijen (vóór de fix van 02-09): het hele voorstel verworpen op een bereik-fout;
            # de gelezen tenaamstelling ging daarbij verloren — benoem dát, niet "niet gelezen".
            return f"AI-voorstel verworpen door code: {_kort(kern)} — tenaamstelling niet overgenomen"
        return f"AI-lezing mislukt: {_kort(detail) or 'onbekende fout'}"
    if reden.startswith("tenaamstelling_niet_eenduidig"):
        if tenaamstelling:
            return "tenaamstelling matcht geen administratie of geleerde regel"
        return "geen tenaamstelling gelezen"
    if reden.startswith(_NOOIT_SPLITSEN):
        # Blok B 04-09: de AI is bewust overgeslagen — er is dus niets "gelezen"; de mens wijst toe
        # (of het afzender-geheugen deed het al, dan staat de rij niet in de bak).
        afzender = reden[len(_NOOIT_SPLITSEN) :].strip() or "deze afzender"
        return f"splitsing overgeslagen: regel 'nooit splitsen' voor {_kort(afzender)} — handmatig toewijzen"
    if reden.startswith("ubl_invalide"):
        return f"UBL ongeldig: {_kort(reden.split(':', 1)[1]) if ':' in reden else 'niet te lezen'}"
    if reden.startswith("vastly_nlcius_invalide"):
        return "Vastly-UBL mist NLCIUS-kernvelden"
    if reden == "vastly_verkoop_zonder_eenduidige_entiteit":
        return "Vastly-verkoopfactuur: eigen entiteit niet eenduidig"
    if reden.startswith("creditnote_381_gate_uit"):
        return "creditnota-herkenning staat uit"
    if reden.startswith("afbeelding_onbruikbaar"):
        return f"afbeelding onbruikbaar: {_kort(reden.split(':', 1)[1]) if ':' in reden else 'niet te lezen'}"
    if reden.startswith("splitsingsvoorstel_ter_controle"):
        if "ongeldig" in reden:
            return "splitsingsvoorstel bevat een ongeldig deel — beoordeel de bereiken"
        return None
    if reden.startswith("intake_herlezen"):
        if tenaamstelling:
            return "opnieuw gelezen: tenaamstelling matcht geen administratie of geleerde regel"
        return "opnieuw gelezen: geen tenaamstelling gelezen"
    if reden.startswith("waarborg"):
        return f"waarborgbericht: {_kort(reden.split(':', 1)[1]) if ':' in reden else reden}"
    # Onbekende technische reden: liever de ruwe tekst dan een verzonnen label.
    return _kort(reden.replace("_", " "))
