uitgevoerd 2026-09-21, rapport: docs/rapporten/2026-09-21-planning-conflictenpaneel-dubbele-veldwerkers.md

Domeinen: uren-planning-veldwerkers, kantoor-frontend

# OPDRACHT 21-09 — Planning: conflictenbalk onleesbaar, toont een verstreken week, dubbele veldwerkers, en signaal zonder handeling

**Feit (Peter 21-09, Universal Steigerbouw, /planning):** "17 conflicten deze week — ma 7-9: M. Demir op 25137 Bergeijk (van Stiphout)
én 26082 Eindhoven (Wijnen Bouw) ma 7-9: R. Demir op … Z.V. Panchev … V. Ponchev … vr 11-9: M. Sanli op 26019 Bennekom (Boon) én 26030
Scherpenzeel én 26129 Hilversum …". Peter: "ik kan er niet uithalen wat het conflict is". Vier problemen:

1. **Onleesbaar.** `ConflictenBalk.tsx` zet 17 `linkbtn`s inline achter elkaar zonder regelstructuur; uitgeklapt is het één lap tekst. De
   tekst zegt ook nergens WAT het conflict is (dubbel gepland op één dag) — alleen wie/waar.
2. **Verstreken week.** De balk zegt "deze week" maar toont ma 7-9 t/m vr 11-9 (week 37) terwijl het week 39 is. Óf de label is fout
   (balk volgt de getoonde week, niet "deze"), óf de grid opent op een oude week. Beide fout: een conflict in een verstreken week is
   geen planningsconflict meer maar historie — hoogstens een urenstaat-toets.
3. **GEEN dubbele veldwerkers — correctie Peter 21-09.** "V. Ponchev"/"Z.V. Panchev" en "M. Demir"/"R. Demir" zijn broers (eigen
   personen) die als ploeg samen gepland staan; Cowork las "zelfde projecten, zelfde dagen" verkeerd als dubbele records. Les:
   planningspatroon ≠ identiteit. Onderdeel C hieronder is daarom teruggebracht tot een lees-only detector op HARDE sleutels alleen.
4. **Signaal zonder handeling** (Kernprincipe 7.2): een conflict-rij biedt alleen "spring naar kaart". De handeling ontbreekt.

## Opdracht
A. **Balk → paneel:** kop "N conflicten in week 39" (getoonde week), gegroepeerd per dag, per rij: persoon · projecten · soort conflict
   ("dubbel gepland" / "afwezig" / "> 5 op kaart" / "ZZP'er zonder dossier") · acties: **"Houd <project A>"**, **"Houd <project B>"**
   (= de andere reservering verwijderen via de bestaande bulkroute-ongedaan, audit), **"Beide (halve dagen)"** = bewust gehouden mét
   reden, rij verdwijnt tot de planning wijzigt. Ingeklapt standaard 3 rijen, uitklap = tabel in `.tabel-scroll`, nooit inline-lap.
   Mockup-toets tegen `mockup/planning-v3-dag-eerst.html` notitie "Conflictenbalk" — past het in de IA? (UX-review-regel 15-08.)
B. **Alleen huidige + toekomstige dagen** tellen als conflict; verstreken dagen niet in de balk (wél in "Per project" lezen). Label
   "deze week" alleen als de getoonde week de huidige is, anders "week N". Fix ook waarom het grid op week 37 stond als dat de oorzaak is
   (laatst bekeken week onthouden = ok, maar dan mét de weekchip zichtbaar).
C. **Dubbele veldwerkers — alleen harde sleutels, geen naamgelijkenis:** lees-only CLI `veldwerkers-dubbelen`: zelfde administratie én
   zelfde KvK, IBAN, e-mail of telefoon → kandidatenrapport. Naam-afstand/planningspatroon NOOIT als signaal (broers in één ploeg zijn
   normaal — correctie Peter 21-09). Geen UI-chip en geen samenvoegen in deze run; alleen het rapport (Universal-meting: verwacht 0).
D. Tests: groepering, week-filter, acties = bulkroute, samenvoegen idempotent; rapport + INDEX + Gelezen regels; BESLISSINGEN
   "PLANNING — CONFLICTENPANEEL MÉT HANDELING + DUBBELE VELDWERKERS (Peter 21-09)"; WAT_IS_NIEUW; CLAUDE.md één verwijsregel.
