import type { CapacitorConfig } from '@capacitor/cli'

/* Capacitor-schil accordeur-app (voorverkenning 2026-08-16, besluit Peter 2026-08-14:
 * store-apps met de PWA-webcode als basis — geen tweede codebase).
 *
 * - appId = bundle-id-VOORSTEL (beslispunt c in verkenning/17): definitief pas bij het
 *   aanmaken van de store-accounts onder de juiste entiteit (PDL).
 * - webDir wijst naar de bestaande frontend-build — deze map raakt de webcode niet.
 *   `npm run bouw-web && npx cap sync` bundelt de actuele PWA in de native projecten.
 * - BEWUST GEEN server.url naar productie: een remote-loading webview is een App Store-
 *   reviewrisico (minimal-functionality) en maakt de app een lege huls zonder netwerk.
 *   De API-base-URL-kwestie (alle fetches zijn root-relatief) is beslispunt (d) in het
 *   rapport en vergt een kleine webcode-aanpassing vóór een echte release. */
const config: CapacitorConfig = {
  /* Naamgeving (besluit Peter 2026-08-19): productnaam "Nijenhuis Boekingsmodule",
   * beginscherm-weergavenaam kort "Nijenhuis" (CFBundleDisplayName/Android-label —
   * dáár staat de korte vorm i.v.m. afkapping onder het icoon). appId blijft
   * ongewijzigd: wijzigen zou signing/AASA raken. */
  appId: 'nl.aknijenhuis.goedkeuren',
  appName: 'Nijenhuis Boekingsmodule',
  webDir: '../frontend/dist',
  ios: {
    // De accordeur-PWA is dark-first; de webview mag niet wit flitsen bij het opstarten.
    backgroundColor: '#0e1514',
  },
  android: {
    backgroundColor: '#0e1514',
  },
}

export default config
