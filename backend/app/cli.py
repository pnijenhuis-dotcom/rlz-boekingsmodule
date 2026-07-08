from __future__ import annotations

import argparse
import sys

from app.auth import service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="RLZ Boekingsmodule beheer-CLI")
    subparsers = parser.add_subparsers(dest="commando", required=True)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap-beheerder",
        help="Maak de allereerste Beheerder aan — weigert als er al een Beheerder bestaat.",
    )
    bootstrap_parser.add_argument("--naam", required=True)
    bootstrap_parser.add_argument("--e-mail", required=True, dest="e_mail")

    args = parser.parse_args(argv)

    if args.commando == "bootstrap-beheerder":
        try:
            resultaat = service.bootstrap_eerste_beheerder(naam=args.naam, e_mail=args.e_mail)
        except service.AuthError as exc:
            print(f"FOUT: {exc}", file=sys.stderr)
            return 1
        print(f"Eerste Beheerder aangemaakt: {resultaat.gebruiker_id} ({args.e_mail})")
        print(f"Uitnodigingstoken (eenmalig, verloopt {resultaat.verloopt_op.isoformat()}):")
        print(resultaat.token)
        print("Rond de activatie af via POST /auth/uitnodigingen/accepteren met dit token, "
              "gevolgd door de TOTP-enrollment (POST /auth/totp/bevestigen).")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
