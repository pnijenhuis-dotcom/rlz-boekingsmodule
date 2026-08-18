"""Eénmalige échte verificatie van de SMTP-mail-terugval (open punt BEWIJS-PUSH-502 NAZORG:
de eerste live-poging faalde met SMTP 535 BadCredentials; ná de rotatie van het
Workspace-app-wachtwoord bewijst één geslaagde verzending dat de 535 weg is).

Stuurt één testmail via exact de productie-instellingen (smtp.gmail.com:465 SSL,
facturen@ak-nijenhuis.nl, Reply-To p.nijenhuis@kempengroep.nl) door `verzend_mail` — hetzelfde
codepad als de uitnodigings-/herinneringsmails. Het wachtwoord komt uit Secret Manager
(`BERICHTEN_SMTP_WACHTWOORD`, dezelfde bron als de cloud-service) of, zonder gcloud-sessie,
via een getpass-prompt (besluit 0012: nooit als procesargument; spaties uit de
Google-weergave worden gestript zoals in notificaties_afronden.sh).

Draaien:  cd backend && .venv/bin/python scripts/verifieer_mailkanaal.py [ontvanger]
Default-ontvanger: p.nijenhuis@kempengroep.nl.

NB dit bewijst het wachtwoord + kanaal; de cloud-service pakt een nieuwe secret-versie pas
op bij de eerstvolgende revisie (deploy). Leg de uitkomst vast in docs/BESLISSINGEN.md."""

from __future__ import annotations

import getpass
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.berichten import mail  # noqa: E402
from app.config import settings  # noqa: E402

ONTVANGER_DEFAULT = "p.nijenhuis@kempengroep.nl"


def _wachtwoord() -> str:
    try:
        uit = subprocess.run(
            ["gcloud", "secrets", "versions", "access", "latest",
             "--secret=BERICHTEN_SMTP_WACHTWOORD", "--project=rlz-boekhouding"],
            capture_output=True, text=True, timeout=30, check=True,
        )
        print("Wachtwoord uit Secret Manager (BERICHTEN_SMTP_WACHTWOORD:latest).")
        return uit.stdout.strip().replace(" ", "")
    except Exception as exc:  # geen gcloud-sessie → handmatige invoer
        print(f"Secret Manager niet bereikbaar ({exc}) — voer het app-wachtwoord handmatig in.")
        return getpass.getpass("App-wachtwoord 'RLZ berichten' (spaties mogen): ").replace(" ", "")


def main() -> int:
    ontvanger = sys.argv[1] if len(sys.argv) > 1 else ONTVANGER_DEFAULT
    settings.berichten_smtp_host = "smtp.gmail.com"
    settings.berichten_smtp_poort = 465
    settings.berichten_smtp_gebruiker = "facturen@ak-nijenhuis.nl"
    settings.berichten_afzender = "facturen@ak-nijenhuis.nl"
    settings.berichten_reply_to = "p.nijenhuis@kempengroep.nl"
    settings.berichten_smtp_wachtwoord = _wachtwoord()
    try:
        mail.verzend_mail(
            naar=ontvanger,
            onderwerp="RLZ mailkanaal-verificatie",
            tekst=(
                "Dit is de eenmalige verificatie van de SMTP-mail-terugval na de rotatie van "
                "het app-wachtwoord (open punt BEWIJS-PUSH-502 NAZORG).\n\n"
                "Komt deze mail aan, dan is de 535 BadCredentials weg en werkt het "
                "gedeelde mailkanaal (uitnodigingen, herinneringen, bundelmeldingen)."
            ),
        )
    except mail.MailFout as exc:
        print(f"MISLUKT: {exc}")
        return 1
    print(f"VERZONDEN aan {ontvanger} — check de inbox; daarmee is de 535 aantoonbaar weg.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
