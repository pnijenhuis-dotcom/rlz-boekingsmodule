// App-slot met 5-cijferige toegangscode (besluit Peter 31-08, mockup app-lock-pincode.html =
// norm, ING-patroon, gedeeld met Vastly; sinds 08-09 hét tweede-factor-model van de app, native én
// PWA). De code is het ANKER: hij ontgrendelt lokaal een toestel-gebonden sleutel (het "anker") die
// het refresh-token versleutelt — de code gaat NOOIT naar de server, er is geen server-side
// pinopslag en de kill-switch per toestel blijft onverkort werken (het toestel-token blijft de
// echte credential eronder).
//
// Biometrie (Face ID / BiometricPrompt) is puur gemak: een kopie van het anker leeft achter de
// biometrie-poort van het OS (AppSlot-plugin — iOS Keychain SecAccessControl .biometryAny,
// Android Keystore mét setInvalidatedByBiometricEnrollment(false)). HARDE EIS (mockup-notitie
// ②): biometrie-falen of een nieuw ingeschreven gezicht sluit nooit uit — het code-pad is pure
// lokale crypto (PBKDF2 → AES-GCM-unwrap) en werkt altijd.
//
// Realistische dreigingsafweging (bewust, geen tekortkoming): een 5-cijferige code heeft 100.000
// combinaties — wie de opslag van het toestel kan uitlezen, kan de wrap offline kraken ongeacht
// de KDF. Het slot beschermt tegen meekijken/even-pakken (het ING-model); de échte
// beveiligingslaag blijft het langlevende toestel-token + de server-side kill-switch (5× fout =
// toestel uitgesloten, herstel = nieuwe uitnodiging van het kantoor).
//
// Zelfde toegangspatroon als nativeSessie: bridge-globals, geen @capacitor-import, fail-closed. De statische import-cyclus met nativeSessie is bewust en veilig: beide modules
// gebruiken elkaars functies uitsluitend ín functie-bodies (geen top-level uitvoering).

import { veiligeOpslagPlugin } from './nativeSessie'
import { bewaarLaatsteSlotfout, type SlotHandeling } from './slotDiagnose'

/** Sinds 10-09 (bugfix toegangscode wijzigen) staan salt + wrap als ÉÉN waarde onder één sleutel, zodat het
 * slot nooit half geschreven kan zijn: `v2.<salt-b64>.<iv-b64>.<cipher-b64>`. */
const SLOT_SLEUTEL = 'appslot_slot'
const SLOT_VERSIE_PREFIX = 'v2'
/** Legacy (tot 10-09): salt en wrap onder twee losse sleutels — alleen nog LEZEN (migratie-op-lezen), zodat een
 * bestaand toestel nooit buitengesloten raakt; ná de eerste geslaagde ontgrendeling staat alles onder SLOT_SLEUTEL. */
const LEGACY_SALT_SLEUTEL = 'appslot_salt'
const LEGACY_WRAP_SLEUTEL = 'appslot_wrap'
const FOUTEN_SLEUTEL = 'appslot_fouten'
const BIOMETRIE_AAN_SLEUTEL = 'appslot_biometrie'
const DIRECT_SLEUTEL = 'appslot_direct'
const CREDENTIAL_SLEUTEL = 'appslot_credential_id'
const REFRESH_SLEUTEL = 'refresh_token'

/** Waarde-prefix van een op het slot versleuteld refresh-token in de VeiligeOpslag. */
const SLOT_PREFIX = 'slot.v1.'

export const MAX_FOUTEN = 5
export const CODE_LENGTE = 5
/** "Direct vergrendelen" uit = pas ná 5 minuten achtergrond opnieuw het slot (mockup scherm 7). */
export const ACHTERGROND_VERGRENDEL_MS = 5 * 60 * 1000

const KDF_ITERATIES = 200_000

/** Het ontgrendelde anker leeft alleen in het geheugen van deze module — nooit in storage
 * zonder wrap (code) of biometrie-poort (plugin). */
let ankerInGeheugen: Uint8Array | null = null

interface AppSlotPlugin {
  beschikbaar(): Promise<{ beschikbaar: boolean; soort: string }>
  zetSleutel(opties: { waarde: string }): Promise<void>
  haalSleutel(opties: { reden: string }): Promise<{ waarde: string | null }>
  wisSleutel(): Promise<void>
}

interface CapacitorGlobal {
  isNativePlatform?: () => boolean
  Plugins?: Record<string, unknown>
}

export function appSlotPlugin(): AppSlotPlugin | null {
  if (typeof window === 'undefined') return null
  const capacitor = (window as { Capacitor?: CapacitorGlobal }).Capacitor
  if (!capacitor?.isNativePlatform?.()) return null
  const plugin = capacitor.Plugins?.AppSlot as AppSlotPlugin | undefined
  if (
    !plugin ||
    typeof plugin.beschikbaar !== 'function' ||
    typeof plugin.zetSleutel !== 'function' ||
    typeof plugin.haalSleutel !== 'function' ||
    typeof plugin.wisSleutel !== 'function'
  ) {
    return null
  }
  return plugin
}

/** Het slot bestaat overal waar een veilige opslag is: de native schil (Keychain/Keystore) én de
 * PWA-slotmodus (IndexedDB + WebCrypto, api/webVeiligeOpslag.ts — contract §5a). De biometrie-
 * plugin is optioneel gemak (alleen native): zonder AppSlot-plugin werkt de code-flow gewoon. */
export function appSlotBeschikbaar(): boolean {
  return veiligeOpslagPlugin() !== null
}

// ---- opslag-helpers ------------------------------------------------------------------------------
// Een mislukte brug-aanroep crasht nooit, maar verdwijnt sinds 10-09 ook niet meer stil: de reden gaat (zonder
// waarde) naar de lokale slot-diagnose en `schrijf` zegt met true/false of het gelukt is.

function noteerSlotfout(handeling: SlotHandeling, sleutel: string, reden: unknown): void {
  bewaarLaatsteSlotfout({ handeling, sleutel, reden })
}

async function lees(sleutel: string): Promise<string | null> {
  const plugin = veiligeOpslagPlugin()
  if (!plugin) return null
  try {
    return (await plugin.haal({ sleutel })).waarde
  } catch (fout) {
    noteerSlotfout('lees', sleutel, fout)
    return null
  }
}

async function schrijf(sleutel: string, waarde: string): Promise<boolean> {
  const plugin = veiligeOpslagPlugin()
  if (!plugin) return false
  try {
    await plugin.zet({ sleutel, waarde })
    return true
  } catch (fout) {
    noteerSlotfout('schrijf', sleutel, fout)
    return false
  }
}

async function verwijder(sleutel: string): Promise<void> {
  const plugin = veiligeOpslagPlugin()
  if (!plugin) return
  try {
    await plugin.verwijder({ sleutel })
  } catch (fout) {
    noteerSlotfout('verwijder', sleutel, fout)
  }
}

// ---- crypto (WebCrypto — de Capacitor-webview is een secure context) -----------------------------

function b64(bytes: Uint8Array): string {
  let bin = ''
  for (const byte of bytes) bin += String.fromCharCode(byte)
  return btoa(bin)
}

function vanB64(s: string): Uint8Array {
  const bin = atob(s)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return bytes
}

async function kdfSleutel(code: string, salt: Uint8Array): Promise<CryptoKey> {
  const materiaal = await crypto.subtle.importKey('raw', new TextEncoder().encode(code), 'PBKDF2', false, [
    'deriveKey',
  ])
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: salt as BufferSource, iterations: KDF_ITERATIES, hash: 'SHA-256' },
    materiaal,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  )
}

async function aesVersleutel(sleutel: CryptoKey, data: Uint8Array): Promise<string> {
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const cipher = await crypto.subtle.encrypt({ name: 'AES-GCM', iv: iv as BufferSource }, sleutel, data as BufferSource)
  return `${b64(iv)}.${b64(new Uint8Array(cipher))}`
}

/** null = verkeerde sleutel (GCM-tag klopt niet) of kapotte waarde — nooit een exception. */
async function aesOntsleutel(sleutel: CryptoKey, waarde: string): Promise<Uint8Array | null> {
  const delen = waarde.split('.')
  if (delen.length !== 2) return null
  try {
    const klaar = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: vanB64(delen[0]) as BufferSource },
      sleutel,
      vanB64(delen[1]) as BufferSource,
    )
    return new Uint8Array(klaar)
  } catch {
    return null
  }
}

async function ankerAlsCryptoKey(anker: Uint8Array): Promise<CryptoKey> {
  return crypto.subtle.importKey('raw', anker as BufferSource, { name: 'AES-GCM' }, false, ['encrypt', 'decrypt'])
}

// ---- zwakke reeksen (mockup-notitie ⑥) -----------------------------------------------------------

/** Weigert constante reeksen (00000, 11111) en strikt op-/aflopende reeksen inclusief
 * wrap-around (12345, 54321, 90123, 09876). */
export function isZwakkeCode(code: string): boolean {
  if (!/^\d+$/.test(code) || code.length !== CODE_LENGTE) return true
  const cijfers = [...code].map(Number)
  const constant = cijfers.every((c) => c === cijfers[0])
  const oplopend = cijfers.every((c, i) => i === 0 || c === (cijfers[i - 1] + 1) % 10)
  const aflopend = cijfers.every((c, i) => i === 0 || c === (cijfers[i - 1] + 9) % 10)
  return constant || oplopend || aflopend
}

// ---- slot-waarde (salt + wrap als één geheel) ----------------------------------------------------

interface SlotWaarde {
  saltB64: string
  wrap: string
  /** True als de waarde nog uit de twee losse legacy-sleutels kwam (migratie-op-lezen volgt bij 'ok'). */
  legacy: boolean
}

function maakSlotWaarde(saltB64: string, wrap: string): string {
  return `${SLOT_VERSIE_PREFIX}.${saltB64}.${wrap}`
}

/** null = ontbreekt of kapot (verkeerd aantal delen / andere versie) — de aanroeper valt dan terug op legacy. */
function ontleedSlotWaarde(waarde: string | null): { saltB64: string; wrap: string } | null {
  if (!waarde) return null
  const delen = waarde.split('.')
  if (delen.length !== 4 || delen[0] !== SLOT_VERSIE_PREFIX || delen.some((d) => d.length === 0)) return null
  return { saltB64: delen[1], wrap: `${delen[2]}.${delen[3]}` }
}

async function leesSlot(): Promise<SlotWaarde | null> {
  const gecombineerd = ontleedSlotWaarde(await lees(SLOT_SLEUTEL))
  if (gecombineerd) return { ...gecombineerd, legacy: false }
  const salt = await lees(LEGACY_SALT_SLEUTEL)
  const wrap = await lees(LEGACY_WRAP_SLEUTEL)
  if (salt && wrap) return { saltB64: salt, wrap, legacy: true }
  return null
}

/** Schrijft de slot-waarde en BEWIJST dat ze staat: terug lezen moet byte-gelijk zijn. De schrijffout zelf
 * is dan al genoteerd (schrijf); een afwijkende terugleeswaarde krijgt hier zijn eigen notitie. */
async function schrijfSlotTerugGelezen(waarde: string, handeling: SlotHandeling): Promise<boolean> {
  if (!(await schrijf(SLOT_SLEUTEL, waarde))) return false
  const terug = await lees(SLOT_SLEUTEL)
  if (terug === waarde) return true
  noteerSlotfout(handeling, SLOT_SLEUTEL, 'terugleescontrole mislukt: opslag geeft niet terug wat geschreven is')
  return false
}

/** Nieuwe salt + wrap voor `code` op `anker`, atomair weggeschreven en bewezen: terug gelezen én met de code
 * ontsleuteld tot precies dit anker. false = de opslag staat NIET aantoonbaar — de aanroeper herstelt. */
async function schrijfSlotBewezen(code: string, anker: Uint8Array, handeling: SlotHandeling): Promise<boolean> {
  const salt = crypto.getRandomValues(new Uint8Array(16))
  const wrap = await aesVersleutel(await kdfSleutel(code, salt), anker)
  const waarde = maakSlotWaarde(b64(salt), wrap)
  if (!(await schrijfSlotTerugGelezen(waarde, handeling))) return false
  const controle = await aesOntsleutel(await kdfSleutel(code, salt), wrap)
  if (!controle || !bytesGelijk(controle, anker)) {
    noteerSlotfout(handeling, SLOT_SLEUTEL, 'ontsleutelcontrole mislukt ná schrijven')
    return false
  }
  return true
}

function bytesGelijk(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false
  let verschil = 0
  for (let i = 0; i < a.length; i++) verschil |= a[i] ^ b[i]
  return verschil === 0
}

/** Zet de vorige stand terug ná een mislukte schrijfpoging: de oude gecombineerde waarde, of — bij een legacy-
 * toestel zonder gecombineerde waarde — géén gecombineerde sleutel, zodat de legacy-sleutels weer leidend zijn. */
async function herstelSlotWaarde(vorige: string | null): Promise<void> {
  if (vorige) await schrijf(SLOT_SLEUTEL, vorige)
  else await verwijder(SLOT_SLEUTEL)
}

async function verwijderLegacySleutels(): Promise<void> {
  await verwijder(LEGACY_SALT_SLEUTEL)
  await verwijder(LEGACY_WRAP_SLEUTEL)
}

// ---- slot-levenscyclus ---------------------------------------------------------------------------

export async function isAppSlotIngesteld(): Promise<boolean> {
  return (await leesSlot()) !== null
}

export function isOntgrendeld(): boolean {
  return ankerInGeheugen !== null
}

export function vergrendel(): void {
  ankerInGeheugen = null
}

/** Nieuw slot: vers anker + code-wrap; een eventueel al aanwezig (plain) refresh-token gaat
 * direct achter het slot. Laat het slot ONTGRENDELD achter (het anker in geheugen), zodat de
 * lopende sessie gewoon doorwerkt en rotaties versleuteld opgeslagen worden. Sinds 10-09 met
 * bewezen opslag: false = de slot-waarde staat niet aantoonbaar in de opslag (de sessie werkt
 * dan wél, maar de volgende koude start kent geen slot — de aanroeper mag dat melden). */
export async function stelCodeIn(code: string): Promise<boolean> {
  const anker = crypto.getRandomValues(new Uint8Array(32))
  const vorige = await lees(SLOT_SLEUTEL)
  const gelukt = await schrijfSlotBewezen(code, anker, 'instellen')
  if (!gelukt) await herstelSlotWaarde(vorige)
  else await verwijderLegacySleutels()
  await verwijder(FOUTEN_SLEUTEL)
  ankerInGeheugen = anker
  // Bestaand plain token (legacy-sessie van vóór het slot) meteen omzetten.
  const bestaand = await lees(REFRESH_SLEUTEL)
  if (bestaand && !bestaand.startsWith(SLOT_PREFIX)) {
    const versleuteld = await versleutelAlsSlotActief(bestaand)
    if (versleuteld) await schrijf(REFRESH_SLEUTEL, versleuteld)
  }
  return gelukt
}

export type OntgrendelUitkomst = 'ok' | 'fout' | 'uitgesloten'

/** Code-pad (scherm 5): pure lokale crypto — de GCM-tag van de wrap is de verificatie. 5×
 * fout = slot + sessie lokaal gewist (mockup-notitie ④); de aanroeper meldt de uitsluiting
 * daarna aan de server (credential_id blijft daarvoor bewaard). Een legacy-toestel (twee losse
 * sleutels) wordt bij de eerste geslaagde ontgrendeling geruisloos naar de gecombineerde
 * sleutel gebracht — de legacy-sleutels gaan pas weg als de nieuwe waarde bewezen staat. */
export async function ontgrendelMetCode(code: string): Promise<OntgrendelUitkomst> {
  const slot = await leesSlot()
  if (!slot) return 'fout'
  const anker = await aesOntsleutel(await kdfSleutel(code, vanB64(slot.saltB64)), slot.wrap)
  if (anker) {
    ankerInGeheugen = anker
    await verwijder(FOUTEN_SLEUTEL)
    if (slot.legacy && (await schrijfSlotTerugGelezen(maakSlotWaarde(slot.saltB64, slot.wrap), 'schrijf'))) {
      await verwijderLegacySleutels()
    }
    return 'ok'
  }
  const fouten = Number((await lees(FOUTEN_SLEUTEL)) ?? '0') + 1
  if (fouten >= MAX_FOUTEN) {
    await wisAppSlotLokaal()
    return 'uitgesloten'
  }
  await schrijf(FOUTEN_SLEUTEL, String(fouten))
  return 'fout'
}

export async function resterendePogingen(): Promise<number> {
  return MAX_FOUTEN - Number((await lees(FOUTEN_SLEUTEL)) ?? '0')
}

export type WijzigCodeUitkomst = 'ok' | 'fout' | 'niet_ontgrendeld'

/** Code wijzigen (scherm 7). De verificatie van de huidige code is de taak van de aanroeper
 * (ToegangInstellingen stap 1 = `ontgrendelMetCode`); hier wordt NIET opnieuw tegen de opslag
 * geverifieerd — het anker staat al in het geheugen en wordt direct opnieuw gewrapt (bugfix 10-09:
 * de tweede verificatie was het enige pad naar "wijzigen is niet gelukt" en telde bovendien mee in
 * de foutenteller). 'niet_ontgrendeld' = het slot is tussendoor dichtgegaan (achtergrond, koude
 * start) — eigen uitkomst, telt niet als foute code. 'fout' = de nieuwe wrap staat niet aantoonbaar
 * in de opslag; de oude stand is teruggezet en de oude code blijft gelden. 'ok' alleen ná terug lezen
 * + ontsleutelen van de nieuwe waarde. */
export async function wijzigCode(nieuw: string): Promise<WijzigCodeUitkomst> {
  const anker = ankerInGeheugen
  if (!anker) return 'niet_ontgrendeld'
  const vorige = await lees(SLOT_SLEUTEL)
  if (await schrijfSlotBewezen(nieuw, anker, 'wijzig')) {
    await verwijderLegacySleutels()
    return 'ok'
  }
  await herstelSlotWaarde(vorige)
  return 'fout'
}

/** Lokale wissing (5× fout, loskoppelen, dode sessie): slot + sessie weg; het credential_id
 * blijft staan — dat is de sleutel waarmee de uitsluiting/hulpvraag zich bij de server meldt. */
export async function wisAppSlotLokaal(): Promise<void> {
  ankerInGeheugen = null
  await verwijder(SLOT_SLEUTEL)
  await verwijderLegacySleutels()
  await verwijder(FOUTEN_SLEUTEL)
  await verwijder(BIOMETRIE_AAN_SLEUTEL)
  await verwijder(REFRESH_SLEUTEL)
  const plugin = appSlotPlugin()
  if (plugin) {
    try {
      await plugin.wisSleutel()
    } catch {
      // biometrie-kopie niet wisbaar = geen blokkade; zonder wrap is het anker toch onbruikbaar
    }
  }
}

// ---- biometrie (gemakslaag over het anker) -------------------------------------------------------

export async function biometrieBeschikbaar(): Promise<boolean> {
  const plugin = appSlotPlugin()
  if (!plugin) return false
  try {
    return (await plugin.beschikbaar()).beschikbaar
  } catch {
    return false
  }
}

export async function isBiometrieAan(): Promise<boolean> {
  return (await lees(BIOMETRIE_AAN_SLEUTEL)) === '1'
}

/** Zet een kopie van het (ontgrendelde) anker achter de biometrie-poort van het OS. */
export async function zetBiometrieAan(): Promise<boolean> {
  const plugin = appSlotPlugin()
  if (!plugin || !ankerInGeheugen) return false
  try {
    await plugin.zetSleutel({ waarde: b64(ankerInGeheugen) })
    await schrijf(BIOMETRIE_AAN_SLEUTEL, '1')
    return true
  } catch {
    return false
  }
}

export async function zetBiometrieUit(): Promise<void> {
  await verwijder(BIOMETRIE_AAN_SLEUTEL)
  const plugin = appSlotPlugin()
  if (plugin) {
    try {
      await plugin.wisSleutel()
    } catch {
      // niets — zonder de aan-vlag wordt de kopie niet meer gebruikt
    }
  }
}

/** Biometrie-pad (scherm 4): het OS toont Face ID/vingerafdruk en geeft de anker-kopie vrij.
 * Elke mislukking (weggetikt, gefaald, kopie kwijt) = false → de aanroeper valt terug op de
 * code (scherm 5) — nooit een teller, nooit uitsluiten (mockup-notitie ② en ③). */
export async function ontgrendelMetBiometrie(): Promise<boolean> {
  const plugin = appSlotPlugin()
  if (!plugin || !(await isBiometrieAan())) return false
  try {
    const { waarde } = await plugin.haalSleutel({ reden: 'Ontgrendel de app' })
    if (!waarde) return false
    ankerInGeheugen = vanB64(waarde)
    await verwijder(FOUTEN_SLEUTEL)
    return true
  } catch {
    return false
  }
}

// ---- voorkeuren + credential-id ------------------------------------------------------------------

export async function isDirectVergrendelen(): Promise<boolean> {
  return (await lees(DIRECT_SLEUTEL)) === '1'
}

export async function zetDirectVergrendelen(aan: boolean): Promise<void> {
  await schrijf(DIRECT_SLEUTEL, aan ? '1' : '0')
}

/** Het toestel-credential_id (base64url, geen geheim) van dít toestel — de meldsleutel voor de
 * app-slot-meldingen (/auth/app-lock/uitgesloten en /hulp). */
export async function bewaarCredentialId(idB64url: string): Promise<void> {
  await schrijf(CREDENTIAL_SLEUTEL, idB64url)
}

export async function haalCredentialId(): Promise<string | null> {
  return lees(CREDENTIAL_SLEUTEL)
}

// ---- refresh-token achter het slot (gebruikt door nativeSessie) ----------------------------------

export function isSlotWaarde(waarde: string): boolean {
  return waarde.startsWith(SLOT_PREFIX)
}

/** null zolang het slot dicht is — de stille refresh faalt dan bewust en de app toont het
 * slot-scherm i.p.v. een sessie te starten. */
export async function ontsleutelSlotWaarde(waarde: string): Promise<string | null> {
  if (!ankerInGeheugen) return null
  const klaar = await aesOntsleutel(await ankerAlsCryptoKey(ankerInGeheugen), waarde.slice(SLOT_PREFIX.length))
  return klaar ? new TextDecoder().decode(klaar) : null
}

/** Versleutelt een (nieuw/geroteerd) refresh-token op het anker; null = geen ingesteld slot of
 * slot dicht (rotatie kan dan sowieso niet gebeuren — die vereist een ontsleuteld token). */
export async function versleutelAlsSlotActief(token: string): Promise<string | null> {
  if (!ankerInGeheugen) return null
  const cipher = await aesVersleutel(await ankerAlsCryptoKey(ankerInGeheugen), new TextEncoder().encode(token))
  return `${SLOT_PREFIX}${cipher}`
}
