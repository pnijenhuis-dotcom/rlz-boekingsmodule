# Regels — Activa / MVA

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Ontwerp ter akkoord (Peter 16-09, geen bouw): register in RLZ `FixedAssets`/Odoo, detectie + voorvullen bij boeken, fiscale toetsing zonder zelf rekenen, reconciliatieblok `activa`; lees-only nulmeting `activa-nulmeting`.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Activa / MVA — STAP-0 + ontwerp (Peter 16-09; ONTWERP TER AKKOORD, geen bouw):** RLZ `FixedAssets` is een volwaardig register (document-DTO, DepreciationMethodHeaders "Lineair N jaar", actie-route; géén regel-koppeling naar de inkoopfactuur; enumeraties root-only → `rlz-lezen --root`; `IsFixedAssetAccount` te breed → MVA = vlag ÉN AccountType 3 ÉN 0xxx; Universal 403 = probe verplicht); Odoo `account_asset` ongebruikt; ontwerp = register in RLZ/Odoo, detectie + voorvullen bij boeken, fiscale toetsing zonder zelf rekenen, reconciliatieblok `activa`; lees-only nulmeting `activa-nulmeting` — zie `docs/ONTWERP_ACTIVA_MVA.md` + BESLISSINGEN "ACTIVA / MVA — STAP-0 + ONTWERP (Peter 16-09)".
