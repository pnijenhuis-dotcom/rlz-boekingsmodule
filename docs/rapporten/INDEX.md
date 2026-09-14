# Rapporten — index (nieuwste bovenaan)

Élk Claude Code-eindrapport staat hier als `<jjjj-mm-dd>-<blok-slug>.md` (zelfde inhoud als het chat-eindrapport, incl.
"werkt in productie: ja/nee/niet gemeten") en gaat mee in de laatste commit van de run. Guard:
`backend/tests/unit/test_rapporten_index.py` (elke regel = bestand, elk bestand = regel, nieuwste bovenaan). Regel: CLAUDE.md
§ Werkwijze "Werkloop automatisch (14-09)".

- [2026-09-14 — Nazorg 7d + CC-inbox standaard auto](2026-09-14-nazorg-7d.md) — DOCUMENT_EVENTIDS 21/240 (hulzen apart), CreditOrDebit op lezen 1=credit/2=debet, api-verkenning STAP-0 gevuld, stap-e-datums als NL-dag in UTC, modelpunt 1001→suspense, flake ORDER BY-fix; werkt in productie: niet gemeten (geen productiegedrag geraakt)
- [2026-09-14 — Werkloop automatisch: nameting-workflow, rapporten-/opdrachtenmap, CC-inbox](2026-09-14-werkloop-automatisch.md) — nameting dagelijks via GitHub Actions als nameting-bot (WIF, geen key); docs/rapporten + opdrachten/inbox + launchd-agent; werkt in productie: niet gemeten, wacht op IAM (--apply)
