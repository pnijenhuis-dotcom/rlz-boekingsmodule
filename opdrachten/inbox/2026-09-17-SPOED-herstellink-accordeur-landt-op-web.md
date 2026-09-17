# SPOED 17-09 — Herstel-link accordeur (Romy) landt op de web-app; native inloggen lukt niet. NU repareren.

**Melding Peter 17-09 (letterlijk):** "Romy de accordeur heb ik net een herstel-link gestuurd, die wordt nog steeds naar de web app
gelinkt en kan native nog steeds niet inloggen."

**Feiten die Cowork al zag (code, geen aanname over de oorzaak):**
- `berichten/uitnodigingsmail.py::herstellink` = `{app_basis_url}/activeren?token=…&herstel=1` — een web-URL; of die de native app
  opent hangt af van de universal link / app link op dat pad (AASA + assetlinks op de apex, TransIP) én van de geïnstalleerde
  app-versie. `download_blok()` toont de store-link alleen bij `STORE_APP_VERSIE_IOS` ≥ 1.1 (gezet 17-09 — controleer of Romy's mail
  vóór of ná die deploy verstuurd is).
- `auth/service.py::maak_herstel_link` maakt wél een activatiecode aan (`activatiecode_hash`), soort `wachtwoord_herstel`.
- Sandbox kon de AASA niet ophalen (proxy 403) — CC toetst dat zelf.

## Blok A — Diagnose op DATA (lees-only, eerst; geen klikpunt zonder bron)
1. Audit-spoor Romy: `wachtwoord_herstel_link_aangemaakt` (tijdstip), daarna élk `POST /auth/app/activeren`, `/auth/app/toestel-koppeling`,
   legacy-login-pogingen (401 mét update-hint) en `X-App-Versie`/User-Agent van haar requests → welke app-versie draait zij (1.0 legacy
   passkey-auth of 1.1 app-auth), iOS of Android, opende zij de link in een browser (welke) of in de app.
2. Universal/app-link: `curl` AASA + `assetlinks.json` op de apex; staat `/activeren` in de paths? Is de AASA-cache van Apple ververst
   ná de laatste wijziging (CDN-check `app-site-association.cdn-apple.com/a/v1/<domein>`)? Android: `adb shell pm get-app-links` /
   Digital Asset Links-API-check.
3. Web-fallback-scherm van 16-09 ("Open op je telefoon" / "web-versie op dit apparaat"): verschijnt dat op `/activeren?…&herstel=1`
   in een mobiele browser, of gaat de herstel-variant er langs? Test met een verse herstel-link op een testaccount.
4. Legacy-pad: als Romy nog 1.0 heeft → de 1.0-app kent app-auth niet en kan met dit token nooit inloggen (0029, 410 ná 08-10). Dan is
   de fix niet in de link maar "update de app" — en moet de mail én het 401-scherm dat glashelder zeggen mét store-link.
Rapporteer per punt: bron (audit-id/tijdstip/URL/HTTP-antwoord) + bevinding. Geen oorzaak zonder bewijs.

## Blok B — Fix (afhankelijk van A, maar in élk geval):
- De herstel-link volgt exact hetzelfde pad als de uitnodiging van 16-09 (kiezen vóór koppelen; `herstel=1` mag dat nooit omzeilen).
- Herstelmail voor app-rollen = dezelfde genummerde volgorde als `app_activatie_stappen` (1 installeer/update de app — store-link, met
  expliciet "versie ≥ 1.1 nodig, update via de App Store/Play Store", 2 open de link op je telefoon, 3 toegangscode) + activatiecode-blok.
- Legacy-401 in de 1.0-app: tekst "Update de app via de App Store" mét link; kantoor-web Gebruikers & toegang toont bij een
  externe gebruiker de laatst geziene app-versie (uit `X-App-Versie`) als chip, zodat Peter dit zelf ziet.
- Als de AASA `/activeren` niet dekt of niet ververst is: fix + `TESTFLIGHT_DRAAIBOEK`/`PLAY_DRAAIBOEK` klikpunt met exact commando.
- Gouden-set/guard: test dat een `wachtwoord_herstel`-token op `/activeren` het keuzescherm geeft en via `POST /auth/app/activeren`
  een toestel koppelt; test op de mailtekst (store-link + versie-eis) — `tests/berichten/…`.

## Afronding
Deploy → nameting: nieuwe herstel-link naar het review-/testaccount, open op een iPhone mét 1.1 → app opent → toegangscode → ingelogd;
rapport zegt "werkt in productie: ja/nee" + wat Peter voor Romy concreet moet doen (één regel, met de reden uit blok A). Rapport +
INDEX; BESLISSINGEN "HERSTEL-LINK APP-ROL — LANDT OP WEB (SPOED 17-09)"; WAT_IS_NIEUW alleen als gebruikersgedrag wijzigt.
