"""CLI (deploy-workflow op de job-image): `app-bundel-registreren --runtime 1.1 --bundel-id <sha-stempel> --pad
bundels/1.1/<id>.zip --sha256 <hex> --bytes N [--platform alle] [--verplicht]`; lees-only `app-bundels [--runtime]`."""

from __future__ import annotations

import argparse

from app.appupdate import service

COMMANDO_REGISTREREN = "app-bundel-registreren"
COMMANDO_LIJST = "app-bundels"


def register(subparsers) -> None:  # noqa: ANN001
    p = subparsers.add_parser(COMMANDO_REGISTREREN, help="OTA: een gebouwde webbundel registreren voor een runtime (deploy-workflow)")
    p.add_argument("--runtime", required=True)
    p.add_argument("--bundel-id", required=True)
    p.add_argument("--pad", required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--bytes", type=int, required=True)
    p.add_argument("--platform", default="alle", choices=list(service.PLATFORMS))
    p.add_argument("--verplicht", action="store_true")
    q = subparsers.add_parser(COMMANDO_LIJST, help="OTA lees-only: geregistreerde bundels (nieuwste eerst)")
    q.add_argument("--runtime", default=None)


def dispatch(args: argparse.Namespace) -> int | None:
    if args.commando == COMMANDO_REGISTREREN:
        try:
            rij = service.registreer_bundel(
                bundel_id=args.bundel_id, runtime=args.runtime, pad=args.pad, sha256=args.sha256, bytes_=args.bytes,
                platform=args.platform, verplicht=args.verplicht,
            )
        except service.AppUpdateFout as exc:
            print(f"FOUT: {exc}")
            return 2
        print(f"GEREGISTREERD bundel={rij.bundel_id} runtime={rij.runtime} platform={rij.platform} bytes={rij.bytes} verplicht={rij.verplicht}")
        return 0
    if args.commando == COMMANDO_LIJST:
        rijen = service.bundels(runtime=args.runtime)
        print(f"kill-switch: env={'aan' if service.settings.ota_uitgeschakeld else 'uit'}; {len(rijen)} bundel(s)")
        for b in rijen:
            print(f"  {b.aangemaakt_op:%Y-%m-%d %H:%M} {b.runtime:>5} {b.platform:>7} {'actief' if b.actief else 'UIT':>6} {b.bundel_id} sha={b.sha256[:12]} bytes={b.bytes}{' VERPLICHT' if b.verplicht else ''}")
        return 0
    return None
