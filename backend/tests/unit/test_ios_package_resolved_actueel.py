"""Guard (SPOED 17-09): Package.resolved van de iOS-schil is actueel t.o.v. de SwiftPM-afhankelijkheden.

Aanleiding: Xcode Cloud-build 144 (main, 17-09) rood met "out-of-date resolved file … dependencies were added: 'version'
(mrackwitz/Version), 'zipfoundation' (weichsel/ZIPFoundation)". De OTA-run van 16-09 (`@capgo/capacitor-updater`,
`@capawesome/capacitor-app-update`) voegde lokale plugin-packages toe aan `CapApp-SPM/Package.swift`; hun REMOTE
afhankelijkheden (Version, ZIPFoundation, Alamofire) horen in
`native/ios/App/App.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved` — Xcode Cloud draait met
automatische package-resolutie UIT en weigert een verouderd resolved-bestand. Fix = lokaal
`xcodebuild -resolvePackageDependencies -project native/ios/App/App.xcodeproj -scheme App` en het resultaat committen.

Toets 1: élke `.package(url:` in CapApp-SPM/Package.swift staat als identity in Package.resolved.
Toets 2: élk lokaal plugin-package (`path:` → node_modules) dat zelf een remote `.package(url:` declareert, heeft die
identity óók in Package.resolved — alleen toetsbaar als `native/node_modules` op deze machine staat (anders skip mét
reden, de vaste verwachting in toets 3 vangt de bekende set).
Toets 3: de bekende set van 17-09 (capacitor-swift-pm, version, zipfoundation, alamofire) is aanwezig — een verdwenen
identity zonder bewuste plugin-verwijdering is rood.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
IOS_APP = REPO / "native" / "ios" / "App"
PACKAGE_SWIFT = IOS_APP / "CapApp-SPM" / "Package.swift"
PACKAGE_RESOLVED = IOS_APP / "App.xcodeproj" / "project.xcworkspace" / "xcshareddata" / "swiftpm" / "Package.resolved"
NODE_MODULES = REPO / "native" / "node_modules"

#: Remote identities die sinds de OTA-run (16-09) verplicht in Package.resolved staan (Xcode Cloud build 144, 17-09).
VERWACHTE_IDENTITIES = {"capacitor-swift-pm", "version", "zipfoundation", "alamofire"}


def _identity_uit_url(url: str) -> str:
    # SwiftPM: identity = laatste padsegment, zonder .git, lowercase.
    return re.sub(r"\.git$", "", url.rstrip("/").rsplit("/", 1)[-1]).lower()


def _remote_urls(package_swift: str) -> set[str]:
    return set(re.findall(r'\.package\((?:name:\s*"[^"]*",\s*)?url:\s*"([^"]+)"', package_swift))


def _lokale_paden(package_swift: str) -> list[str]:
    return re.findall(r'\.package\(name:\s*"[^"]*",\s*path:\s*"([^"]+)"\)', package_swift)


def _resolved_identities() -> set[str]:
    data = json.loads(PACKAGE_RESOLVED.read_text(encoding="utf-8"))
    assert data.get("version") in (2, 3), f"onbekende Package.resolved-versie: {data.get('version')}"
    return {pin["identity"].lower() for pin in data["pins"]}


def test_package_resolved_bestaat_en_is_json() -> None:
    assert PACKAGE_RESOLVED.is_file(), "Package.resolved ontbreekt — xcodebuild -resolvePackageDependencies draaien en committen"
    assert _resolved_identities(), "Package.resolved zonder pins"


def test_elke_remote_dependency_van_capapp_spm_staat_in_package_resolved() -> None:
    urls = _remote_urls(PACKAGE_SWIFT.read_text(encoding="utf-8"))
    assert urls, "CapApp-SPM/Package.swift declareert geen remote package — capacitor-swift-pm hoort erin"
    ontbrekend = {_identity_uit_url(u) for u in urls} - _resolved_identities()
    assert not ontbrekend, f"Package.resolved verouderd — ontbreekt: {sorted(ontbrekend)}"


def test_remote_dependencies_van_lokale_plugins_staan_in_package_resolved() -> None:
    lokaal = _lokale_paden(PACKAGE_SWIFT.read_text(encoding="utf-8"))
    assert lokaal, "CapApp-SPM/Package.swift declareert geen lokale plugin-packages"
    if not NODE_MODULES.is_dir():
        pytest.skip("native/node_modules niet aanwezig (npm install in native/) — toets 3 dekt de bekende set")
    ontbrekend: dict[str, set[str]] = {}
    resolved = _resolved_identities()
    for rel in lokaal:
        plugin_swift = (PACKAGE_SWIFT.parent / rel / "Package.swift").resolve()
        if not plugin_swift.is_file():
            continue  # plugin niet geïnstalleerd op deze machine — geen uitspraak
        nodig = {_identity_uit_url(u) for u in _remote_urls(plugin_swift.read_text(encoding="utf-8"))}
        mis = nodig - resolved
        if mis:
            ontbrekend[rel] = mis
    assert not ontbrekend, (
        "Package.resolved verouderd (Xcode Cloud: 'out-of-date resolved file') — per plugin ontbreekt: "
        + "; ".join(f"{k}: {sorted(v)}" for k, v in ontbrekend.items())
        + " — draai: xcodebuild -resolvePackageDependencies -project native/ios/App/App.xcodeproj -scheme App"
    )


def test_bekende_set_sinds_ota_run_aanwezig() -> None:
    ontbrekend = VERWACHTE_IDENTITIES - _resolved_identities()
    assert not ontbrekend, f"verwachte SwiftPM-identities ontbreken in Package.resolved: {sorted(ontbrekend)}"
