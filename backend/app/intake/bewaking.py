"""Reconciliatieblok `intake` — postvak-bewaking "ontvangen vs verwerkt" (Peter 22-09, opdracht C; contract als
`projecten/nummer.cli_blok`). Per kanaal mét IMAP-instellingen op deze job:

- **telling aan de bron**: alle berichten in INBOX + spam-map sinds gisteren 00:00 (NL), gelezen én ongelezen (IMAP
  `SINCE`, dag-granulair; daarna op de Date-kop begrensd) — wat de module niet ontvangt telt ze anders niet;
- **verwerkt**: de verwerkt-administratie (`intake_bericht_verwerkt`) + `intake_bericht.message_id`;
- **verschil > 0** = afwijking `intake_postvak_verschil` (platformbreed, direct in `actie` — besluit Peter: knop
  "Nu verwerken" op de rij, de Message-ID's in het detail);
- **uit Spam verwerkt** (laatste 7 dagen) = LET-OP `intake_uit_spam` per afzender mét domein (handeling: afzender in
  Google Workspace whitelisten / DMARC van de afzender laten fixen);
- **verbinding mislukt** of **kanaal mét job niet geconfigureerd** = FOUT (systeemfout, nooit stil); declaraties@
  (geen job) = zichtbaar overgeslagen;
- overgangsperiode forward: teller "dubbel via forward" apart in de CLI-regel; de dagtellers verwacht/gedaan/
  overgeslagen leven in `automatiseringen.INTAKE_POSTVAK` (audit `intake_postvak_run`).
De vergelijking (`toets`) is pure code — testbaar zonder IMAP of DB."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.documenten.betaalstatus import KANALEN, POSTVAK_ADRES_PER_KANAAL
from app.intake.postvak import (
    INBOX,
    KANALEN_MET_JOB,
    ImapInstellingen,
    PostvakFout,
    PostvakKop,
    PostvakNietGeconfigureerd,
    PostvakVerbinding,
)

BLOK = "intake"
SOORT_VERSCHIL = "intake_postvak_verschil"
REDEN_UIT_SPAM = "intake_uit_spam"
REDEN_NIET_GECONFIGUREERD = "intake_postvak_niet_geconfigureerd"
REDEN_VERBINDING = "intake_postvak_verbinding"
SPAM_VENSTER_DAGEN = 7
MAX_IDS_IN_DETAIL = 50
_AMS = ZoneInfo("Europe/Amsterdam")

Lezer = Callable[[str, datetime], list[PostvakKop]]


@dataclass(frozen=True)
class Verschil:
    kanaal: str
    in_postvak: int
    in_inbox: int
    in_spam: int
    bekend: int
    ontbrekend: tuple[PostvakKop, ...] = field(default_factory=tuple)

    @property
    def aantal(self) -> int:
        return len(self.ontbrekend)


def toets(kanaal: str, koppen: list[PostvakKop], bekend: set[str], *, sinds: datetime) -> Verschil:
    """Pure kern: welke koppen sinds `sinds` (Date-kop; zonder datum telt mee) staan niet in de
    verwerkt-administratie."""
    venster = [k for k in koppen if k.datum is None or _utc(k.datum) >= sinds]
    ontbrekend = tuple(k for k in venster if k.sleutel not in bekend)
    return Verschil(
        kanaal=kanaal,
        in_postvak=len(venster),
        in_inbox=sum(1 for k in venster if k.map == INBOX),
        in_spam=sum(1 for k in venster if k.map != INBOX),
        bekend=len(venster) - len(ontbrekend),
        ontbrekend=ontbrekend,
    )


def _utc(d: datetime) -> datetime:
    return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)


def vingerafdruk(kanaal: str, sleutels: list[str]) -> str:
    """Stabiel per kanaal × set ontbrekende berichten: dezelfde set morgen = dezelfde bevinding (geen dubbele mail)."""
    h = hashlib.sha256("\n".join(sorted(sleutels)).encode()).hexdigest()[:16]
    return f"{BLOK}:{kanaal}:{h}"


def _lees_koppen(kanaal: str, sinds: datetime) -> list[PostvakKop]:
    instellingen = ImapInstellingen.voor_kanaal(kanaal)
    with PostvakVerbinding(instellingen) as verbinding:
        koppen: list[PostvakKop] = []
        for map in PostvakVerbinding.standaard_mappen():
            koppen.extend(verbinding.koppen(map, sinds=sinds.astimezone(_AMS).date()))
    return koppen


def spam_let_ops(*, nu: datetime, treffers=None) -> list[dict]:  # noqa: ANN001
    """LET-OP per (kanaal, afzender) voor berichten die uit de spam-map verwerkt zijn (laatste 7 dagen)."""
    from app.intake import verwerkt

    if treffers is None:
        treffers = verwerkt.spam_treffers(sinds=nu - timedelta(days=SPAM_VENSTER_DAGEN))
    groepen: dict[tuple[str, str], list] = {}
    for t in treffers:
        groepen.setdefault((t.kanaal, (t.afzender or "onbekende afzender").lower()), []).append(t)
    uit: list[dict] = []
    for (kanaal, afzender), items in sorted(groepen.items()):
        domein = afzender.rsplit("@", 1)[-1] if "@" in afzender else afzender
        adres = POSTVAK_ADRES_PER_KANAAL.get(kanaal, kanaal)
        tekst = (
            f"LET-OP     postvak {adres}: {len(items)} bericht(en) van {afzender} kwamen in de spam-map terecht "
            "en zijn "
            f"van daaruit verwerkt — zet de afzender/het domein {domein} in Google Workspace op de toegestane-lijst "
            f"(of laat de afzender zijn DKIM/DMARC herstellen), anders blijft élke factuur van {domein} in Spam landen."
        )
        uit.append(
            {
                "soort": "let_op",
                "administratie_id": None,
                "blok": BLOK,
                "vingerafdruk": f"{BLOK}:spam:{kanaal}:{afzender}",
                "tekst": tekst[:1000],
                "detail": {
                    "reden": REDEN_UIT_SPAM,
                    "kanaal": kanaal,
                    "postvak_adres": adres,
                    "afzender": afzender,
                    "domein": domein,
                    "aantal": len(items),
                    "voorbeelden": [
                        {
                            "onderwerp": (t.onderwerp or "")[:80],
                            "verwerkt_op": t.verwerkt_op.isoformat(),
                            "uitkomst": t.uitkomst,
                        }
                        for t in items[:5]
                    ],
                },
            }
        )
    return uit


def cli_blok(  # noqa: ANN001
    args,
    verzamelaar=None,
    *,
    stdout: Callable[[str], None] = print,
    lezer: Lezer | None = None,
    nu: datetime | None = None,
) -> int:
    """Blokfunctie `intake` voor `reconciliatie-alles`. Exit 1 zodra er een verschil of een fout is."""
    from app.intake import verwerkt

    nu = nu or datetime.now(UTC)
    sinds = verwerkt.gisteren_begin_utc(nu)
    lezer = lezer or _lees_koppen
    exit_code = 0
    for kanaal in KANALEN:
        adres = POSTVAK_ADRES_PER_KANAAL.get(kanaal, kanaal)
        instellingen = ImapInstellingen.voor_kanaal(kanaal)
        if not instellingen.geconfigureerd:
            if kanaal in KANALEN_MET_JOB:
                exit_code = 1
                tekst = (
                    f"FOUT       postvak {adres} ({kanaal}): niet geconfigureerd op de reconciliatie-job "
                    f"({', '.join(instellingen.ontbrekend())} ontbreekt) — de postvak-bewaking kan niet tellen; "
                    "envs + secret "
                    f"{instellingen.env_prefix}_WACHTWOORD op rlz-reconciliatie zetten (deploy.yml)."
                )
                stdout(tekst)
                if verzamelaar is not None:
                    verzamelaar.bevinding(
                        soort="fout",
                        administratie_id=None,
                        vingerafdruk=f"{BLOK}:config:{kanaal}",
                        tekst=tekst,
                        detail={"reden": REDEN_NIET_GECONFIGUREERD, "kanaal": kanaal, "postvak_adres": adres},
                        blok=BLOK,
                    )
            else:
                stdout(f"OVERGESLAGEN postvak {adres} ({kanaal}): geen job/instellingen — niet bewaakt.")
            continue
        try:
            koppen = lezer(kanaal, sinds)
        except (PostvakFout, PostvakNietGeconfigureerd) as exc:
            exit_code = 1
            tekst = f"FOUT       postvak {adres} ({kanaal}): telling mislukt — {exc}"
            stdout(tekst)
            if verzamelaar is not None:
                verzamelaar.bevinding(
                    soort="fout",
                    administratie_id=None,
                    vingerafdruk=f"{BLOK}:verbinding:{kanaal}",
                    tekst=tekst[:1000],
                    detail={
                        "reden": REDEN_VERBINDING,
                        "kanaal": kanaal,
                        "postvak_adres": adres,
                        "fout": str(exc)[:500],
                    },
                    blok=BLOK,
                )
            continue
        if verzamelaar is not None:
            verzamelaar.gecontroleerd(1)
        bekend = verwerkt.bekende_sleutels(kanaal)
        verschil = toets(kanaal, koppen, bekend, sinds=sinds)
        rijen = verwerkt.verwerkt_sinds(kanaal, sinds=sinds)
        per_uitkomst = {
            u: sum(1 for r in rijen.values() if r.uitkomst == u) for u in ("verwerkt", "al_bekend", "niet_verwerkbaar")
        }
        dubbel = sum(1 for r in rijen.values() if (r.detail or {}).get("dubbel_via_forward"))
        docs = _documenten_tellers(kanaal, sinds=sinds)
        stdout(
            f"INTAKE     postvak {adres} ({kanaal}) sinds {sinds.astimezone(_AMS):%d-%m %H:%M}: "
            f"{verschil.in_postvak} in het "
            f"postvak (INBOX {verschil.in_inbox}, spam {verschil.in_spam}), {verschil.bekend} bekend/verwerkt "
            f"(verwerkt {per_uitkomst['verwerkt']}, al bekend {per_uitkomst['al_bekend']}, niet verwerkbaar "
            f"{per_uitkomst['niet_verwerkbaar']}; documenten {docs['toegewezen']}, verzamelbak {docs['verzamelbak']}, "
            f"bijlagen niet verwerkbaar {docs['niet_verwerkbaar']}), dubbel via forward {dubbel}, "
            f"VERSCHIL {verschil.aantal}"
        )
        if verschil.aantal:
            exit_code = 1
            sleutels = [k.sleutel for k in verschil.ontbrekend]
            tekst = (
                f"AFWIJKING  soort={SOORT_VERSCHIL} postvak {adres} ({kanaal}): {verschil.aantal} bericht(en) "
                "sinds gisteren in het "
                f"postvak zonder verwerking — " + "; ".join(
                    f"{k.afzender or '?'} · {(k.onderwerp or '')[:50]} ({k.map}{', gelezen' if k.gelezen else ''})"
                    for k in verschil.ontbrekend[:5]
                )
                + (" …" if verschil.aantal > 5 else "")
            )
            stdout(tekst)
            if verzamelaar is not None:
                verzamelaar.bevinding(
                    soort="afwijking",
                    administratie_id=None,
                    vingerafdruk=vingerafdruk(kanaal, sleutels),
                    tekst=tekst[:1000],
                    detail={
                        "afwijking_soort": SOORT_VERSCHIL,
                        "kanaal": kanaal,
                        "postvak_adres": adres,
                        "aantal": verschil.aantal,
                        "in_postvak": verschil.in_postvak,
                        "in_spam": verschil.in_spam,
                        "sinds": sinds.isoformat(),
                        "berichten": [
                            {
                                "message_id": k.sleutel,
                                "afzender": k.afzender,
                                "onderwerp": (k.onderwerp or "")[:80],
                                "map": k.map,
                                "gelezen": k.gelezen,
                                "datum": k.datum.isoformat() if k.datum else None,
                            }
                            for k in verschil.ontbrekend[:MAX_IDS_IN_DETAIL]
                        ],
                    },
                    blok=BLOK,
                )
    for kw in spam_let_ops(nu=nu):
        stdout(kw["tekst"])
        if verzamelaar is not None:
            verzamelaar.bevinding(**kw)
    return exit_code


def _documenten_tellers(kanaal: str, *, sinds: datetime) -> dict[str, int]:
    """Uitkomsten per bijlage uit `intake_bericht.detail` (platformbreed leesbaar) — géén Document-query over
    RLS heen."""
    from sqlalchemy import select

    from app.db.session import scoped_session
    from app.intake.models import IntakeBericht

    tellers = {"toegewezen": 0, "verzamelbak": 0, "niet_verwerkbaar": 0, "overig": 0}
    with scoped_session(None) as session:
        details = session.scalars(
            select(IntakeBericht.detail).where(IntakeBericht.kanaal == kanaal, IntakeBericht.verwerkt_op >= sinds)
        ).all()
    for d in details:
        for b in (d or {}).get("bijlagen") or []:
            u = b.get("uitkomst") or ""
            if u == "toegewezen":
                tellers["toegewezen"] += 1
            elif u == "verzamelbak":
                tellers["verzamelbak"] += 1
            elif u.startswith("niet_verwerkbaar") or u in ("genegeerd_vgb", "niet_ondersteund"):
                tellers["niet_verwerkbaar"] += 1
            else:
                tellers["overig"] += 1
    return tellers
