uitgevoerd 2026-09-24, rapport: docs/rapporten/2026-09-24-bundelrun-zeven-punten.md

Domeinen: werkvoorraad-controlescherm, btw

# BUG 23-09 — Vinkje "Samenvoegen" verdwijnt als de scan geen regelbedragen gaf, ook al staan er 7 opgeslagen regels
# (BLOW, Van Rumpt 2025135, € 1.277,50, document 3405157f-5a1c-46e8-ba16-980e03d79ee4)

**Feit (Peter 23-09 + API-meting Cowork):** `boekvoorstel` van dit document: `opgeslagen: true`, 7 regels (zelfde btw-code
1e44993a-…, btw-bedrag per regel null), `regels_samenvoegen: false`, `samenvoegen_toegestaan: true`, **`samengevoegde_regel: null`**,
`veldvoorstel` leeg. Frontend `BoekvoorstelPanel.tsx:978`: `samenvoegenBeschikbaar = toegestaan && samengevoegd !== null &&
gesplitst.length > 1` → null = geen vinkje. Backend `_samenvoeg_velden`: `samengevoegde_regel = _samengevoegde_regel(veldvoorstel) if
veldvoorstel else None` en `_samengevoegde_regel` geeft None zodra netto/btw uit de SCAN niet te bepalen zijn — de 7 OPGESLAGEN regels
(mét netto/bruto) worden genegeerd. Regressie t.o.v. de bedoeling van 18-09 ("samenvoegen-modus volgt de data"): de data staat er,
alleen niet in het veld waar de berekening kijkt. Peter moet nu handmatig 6 regels wegkruisen.

## Opdracht
1. `_samengevoegde_regel` krijgt een tweede bron: staan er opgeslagen regels (≥ 2), bereken de samengevoegde regel uit díe regels
   (Σ netto, Σ btw-bedrag of btw via tarief per regel, één btw-code als alle regels dezelfde hebben, anders geen samenvoegen mét
   zichtbare reden "verschillende btw-codes"; omschrijving = bestaande regel), scan-uitkomst alleen als er nog geen opgeslagen regels
   zijn. Regelsom-check blijft leidend (Σ = factuurtotaal).
2. Wanneer samenvoegen niet kan, tóónt het scherm dat mét reden (chip "samenvoegen niet mogelijk: …") i.p.v. het vinkje stil weg te
   laten (regel: niets verdwijnt stil).
3. Nazorg-meting (leesreplica): hoeveel open documenten hebben ≥ 2 opgeslagen regels én `samengevoegde_regel = null` — per
   administratie; bevestigt de omvang.
4. Tests (opgeslagen regels zonder scanbedragen → vinkje; verschillende btw-codes → reden; 1 regel → geen vinkje), rapport + INDEX +
   Gelezen regels, BESLISSINGEN "SAMENVOEGEN — BRON = OPGESLAGEN REGELS, NOOIT STIL WEG (23-09)", WAT_IS_NIEUW, CLAUDE.md één regel.
