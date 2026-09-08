// Vertaling van platformfouten bij de passkey-REGISTRATIE naar een eerlijke melding (blok 13,
// 07-09 — Google Play-afwijzing variant B, BESLISSINGEN "GOOGLE PLAY AFWIJZING 07-09").
//
// Android Credential Manager biedt op een toestel zónder passkey-beheerder (geen aangemeld
// Google-account → Google Password Manager kan geen account-gebonden passkey maken; en/of geen
// schermvergrendeling) géén aanmaak-optie. De native plugin (`NatievePasskeyPlugin.java`)
// rejectt dan met `"Passkey-registratie mislukt: " + fout.getMessage()` — bv.
// `CreateCredentialNoCreateOptionException` → "No create options available." (gereproduceerd
// 07-09 in de kale Pixel-7-emulator; logcat GMS-codes 28433/28434, "CANCELED, source
// REMOTE_PROVIDER"). Voor de gebruiker/reviewer is dat een kale, onbegrijpelijke fout — hier
// wordt 'm een handelingsperspectief. Alleen Android; iOS en web zijn ongewijzigd (daar bestaat
// deze foutklasse niet). Geen alternatieve loginroute: passkeys-eerst (platformbesluit 0020)
// blijft onverkort — de melding zegt wat het toestel mist, niet hoe je eromheen komt.

export const GEEN_PASSKEY_BEHEERDER_MELDING =
  'Op dit toestel is geen passkey-beheerder actief — voeg een Google-account toe of zet schermvergrendeling aan; ' +
  'of gebruik een ander toestel.'

/** Herkenbare fragmenten uit de Credential-Manager-keten. Case-insensitief getoetst op het ruwe
 * foutbericht van de plugin. Bewust geen match op alleen "geannuleerd"/"cancel" — een door de
 * gebruiker weggetikte sheet is een gewone annulering, geen ontbrekende beheerder. */
const ANDROID_GEEN_BEHEERDER_FRAGMENTEN = [
  'no create options available',
  'nocreateoption',
  'no provider dependencies found',
  'providerconfiguration',
  'remote_provider',
  '28433',
  '28434',
]

/** True als het foutbericht wijst op "geen passkey-beheerder beschikbaar" (Android Credential
 * Manager). Pure functie, los getest. */
export function isAndroidGeenPasskeyBeheerder(bericht: string): boolean {
  const b = bericht.toLowerCase()
  if (ANDROID_GEEN_BEHEERDER_FRAGMENTEN.some((f) => b.includes(f))) return true
  // "CANCELED" mét bron REMOTE_PROVIDER is de provider die afhaakt, niet de mens — maar alleen als
  // de plugin 'm als "mislukt" (niet "geannuleerd") doorgaf.
  return b.includes('mislukt') && b.includes('canceled')
}

/** iOS (blok 2a 08-09, incident 07-09 22:01: vijf wachtwoord-logins, vijf registratie-opties, nul voltooiingen):
 * de Swift-plugin geeft elke niet-annulering door als "Passkey-verzoek mislukt: <localizedDescription>" — voor de
 * gebruiker een kale Apple-tekst ("The operation couldn't be completed. (…AuthorizationError error 1004.)"). De
 * meest voorkomende oorzaak is een uitgeschakelde iCloud-sleutelhanger (of geen toegangscode op het toestel); die
 * krijgt hier een handelingsperspectief. Een weggetikte sheet blijft "Passkey-verzoek geannuleerd". */
export const IOS_PASSKEY_MISLUKT_MELDING =
  'Passkey aanmaken is op dit iPhone/iPad niet gelukt. Controleer of iCloud-sleutelhanger aan staat ' +
  '(Instellingen › je naam › iCloud › Wachtwoorden en sleutelhanger) en of het toestel een toegangscode heeft; ' +
  'probeer het daarna opnieuw of vraag het kantoor om hulp.'

const IOS_MISLUKT_FRAGMENTEN = ['passkey-verzoek mislukt', 'authenticationservices', 'authorizationerror']

/** True als het foutbericht de iOS-plugin-/ASAuthorization-fout is (géén annulering). Pure functie. */
export function isIosPasskeyMislukt(bericht: string): boolean {
  const b = bericht.toLowerCase()
  if (b.includes('geannuleerd')) return false
  return IOS_MISLUKT_FRAGMENTEN.some((f) => b.includes(f))
}

function huidigPlatform(): string {
  if (typeof window === 'undefined') return 'web'
  const cap = (window as { Capacitor?: { isNativePlatform?: () => boolean; getPlatform?: () => string } }).Capacitor
  if (!cap?.isNativePlatform?.()) return 'web'
  return cap.getPlatform?.() ?? 'native'
}

/** Foutbericht voor het login-scherm: op Android wordt de Credential-Manager-fout de eerlijke
 * melding; elk ander platform en elke andere fout blijft het oorspronkelijke bericht. */
export function loginFoutmelding(err: unknown, platform: string = huidigPlatform()): string {
  const bericht = err instanceof Error ? err.message : 'Inloggen mislukt.'
  if (platform === 'android' && isAndroidGeenPasskeyBeheerder(bericht)) return GEEN_PASSKEY_BEHEERDER_MELDING
  // De technische melding blijft (kort) zichtbaar: het kantoor herkent er de Apple-foutcode aan.
  if (platform === 'ios' && isIosPasskeyMislukt(bericht)) {
    return `${IOS_PASSKEY_MISLUKT_MELDING} (${bericht.replace(/^passkey-verzoek mislukt:\s*/i, '').slice(0, 160)})`
  }
  return bericht
}
