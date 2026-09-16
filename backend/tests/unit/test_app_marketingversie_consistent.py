"""Guard (mini-run 09-09): iOS, Android en web dragen dezelfde marketingversie van de goedkeur-app.

Aanleiding: Apple sloot train 1.0 ná de goedkeuring van build 44 (09-09); Xcode Cloud-build 98 werd geweigerd met
ITMS-90186/ITMS-90062 omdat CFBundleShortVersionString nog 1.0 was. De marketingversie staat op vier plekken
(pbxproj ×2, build.gradle, appVersie.ts) en WAT_IS_NIEUW moet de versie noemen — drift tussen die plekken is hier rood.
Het BUILDnummer (CURRENT_PROJECT_VERSION / versionCode) is bewust niet gelijkgetrokken: iOS krijgt dat van
Xcode Cloud (CI_BUILD_NUMBER), Android telt per Play-upload.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PBXPROJ = REPO / "native" / "ios" / "App" / "App.xcodeproj" / "project.pbxproj"
BUILD_GRADLE = REPO / "native" / "android" / "app" / "build.gradle"
APP_VERSIE_TS = REPO / "frontend" / "src" / "accordeur" / "appVersie.ts"
WAT_IS_NIEUW = REPO / "frontend" / "src" / "changelog" / "WAT_IS_NIEUW.md"
CI_POST_CLONE = REPO / "native" / "ios" / "App" / "ci_scripts" / "ci_post_clone.sh"


def _ios_marketingversies() -> list[str]:
    return re.findall(r"MARKETING_VERSION = ([0-9.]+);", PBXPROJ.read_text(encoding="utf-8"))


def _android_versionname() -> str:
    m = re.search(r'versionName\(.*?: "([0-9.]+)"\)', BUILD_GRADLE.read_text(encoding="utf-8"))
    assert m, "build.gradle: versionName-default niet gevonden"
    return m.group(1)


def _android_versioncode() -> int:
    m = re.search(r"versionCode\(.*?: (\d+)\)", BUILD_GRADLE.read_text(encoding="utf-8"))
    assert m, "build.gradle: versionCode-default niet gevonden"
    return int(m.group(1))


def _web_versie() -> str:
    m = re.search(r"export const APP_MARKETING_VERSIE = '([0-9.]+)'", APP_VERSIE_TS.read_text(encoding="utf-8"))
    assert m, "appVersie.ts: APP_MARKETING_VERSIE niet gevonden"
    return m.group(1)


def test_ios_android_en_web_dragen_dezelfde_marketingversie() -> None:
    ios = _ios_marketingversies()
    assert len(ios) == 2, f"pbxproj hoort MARKETING_VERSION op precies twee plekken (Debug + Release) te dragen: {ios}"
    assert len(set(ios)) == 1, f"pbxproj: Debug en Release lopen uiteen: {ios}"
    web = _web_versie()
    assert ios[0] == web == _android_versionname(), (
        f"marketingversie drift: iOS {ios[0]} · Android {_android_versionname()} · web {web}"
    )


def test_marketingversie_is_1_1_sinds_09_09_en_versioncode_5() -> None:
    # Train-regel: 1.0 is door Apple gesloten ná de goedkeuring van build 44 — terugvallen naar 1.0 is altijd fout.
    assert _web_versie() == "1.1"
    assert _android_versioncode() == 5, "vc4 = 1.0 staat al op de interne Play-track; 1.1 begint bij versionCode 5"


def test_wat_is_nieuw_noemt_de_huidige_marketingversie() -> None:
    assert f"versie {_web_versie()}" in WAT_IS_NIEUW.read_text(encoding="utf-8")


def test_ci_post_clone_raakt_de_marketingversie_niet() -> None:
    script = CI_POST_CLONE.read_text(encoding="utf-8")
    for regel in script.splitlines():
        if regel.strip().startswith("#"):
            continue
        assert "MARKETING_VERSION" not in regel, f"ci_post_clone.sh zet alleen CURRENT_PROJECT_VERSION: {regel!r}"
    assert "CURRENT_PROJECT_VERSION = [0-9]+;/CURRENT_PROJECT_VERSION = ${CI_BUILD_NUMBER}" in script


def test_ota_minimum_runtime_versie_nooit_boven_de_marketingversie() -> None:
    """OTA blok C (16-09): de minimale schilversie (426 eronder) mag nooit hoger zijn dan de versie die we zélf bouwen —
    anders sluit de poort de eigen app uit. Geldt voor de code-default én de waarde in deploy.yml."""
    import re as _re

    from app.config import Settings

    def _t(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split("."))

    web = _t(_web_versie())
    assert _t(Settings.model_fields["app_min_runtime_versie"].default) <= web
    deploy = (REPO / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    m = _re.search(r'APP_MIN_RUNTIME_VERSIE: "([0-9.]+)"', deploy)
    assert m, "deploy.yml draagt APP_MIN_RUNTIME_VERSIE"
    assert _t(m.group(1)) <= web
    assert "app-bundel-registreren" in deploy and "APP_MARKETING_VERSIE" in deploy, "de OTA-stap registreert per runtime"

