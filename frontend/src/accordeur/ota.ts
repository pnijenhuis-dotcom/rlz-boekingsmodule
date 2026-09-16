// Live updates (OTA) van de web-laag van de native schil (besluit Peter 16-09: "zsm af van TestFlight, de native app moet
// gewoon werken"). De schil is een Capacitor-huls om déze webcode; de plugin `@capgo/capacitor-updater` (self-hosted, geen
// Capgo-cloud) wisselt de gebundelde web-assets voor een gedownloade zip. Alles hier is fail-soft en werkt ALLEEN in de
// schil mét plugin (bridge-global `window.Capacitor.Plugins.CapacitorUpdater` — de webcode kent geen @capacitor/*-import,
// zelfde patroon als nativePush/verversen). Regels:
//   • manifest ophalen bij koude start én bij terugkeer naar de voorgrond, max 1× per 15 min;
//   • het manifest kent alleen bundels van DEZE runtime (APP_MARKETING_VERSIE) — een 1.1-schil krijgt nooit een 1.2-bundel;
//   • download op de achtergrond, toepassen bij de VOLGENDE start (`next`); `verplicht` = direct (`set`) mét melding;
//   • sha256 uit het manifest reist als checksum mee naar de plugin;
//   • rollback (crash/`notifyAppReady` niet binnen 10 s → de plugin valt zelf terug) → melding naar de server (audit
//     `ota_rollback`), nooit stil; de diagnoseregel toont `bundel <id>`.
// Kill-switch server-side (env OTA_UITGESCHAKELD of Beheerder-schakelaar) = manifest `geen_update`; de app raakt dan niets.

import { apiFetch, apiJson } from '../api/client'
import { APP_MARKETING_VERSIE } from './appVersie'
import { huidigPlatform } from './appAuthApi'

export const OTA_INTERVAL_MS = 15 * 60_000
export const OTA_LAATSTE_CHECK_SLEUTEL = 'accordeur-ota-laatste-check'
export const OTA_VERPLICHT_MELDING = 'App bijgewerkt'
const INGEBOUWD = 'builtin'

interface BundleInfo {
  id?: string
  version?: string
  checksum?: string
  status?: string
}

export interface UpdaterPlugin {
  notifyAppReady?: () => Promise<unknown>
  getCurrent?: () => Promise<{ bundle?: BundleInfo; native?: string }>
  download?: (opties: { url: string; version: string; checksum?: string }) => Promise<BundleInfo>
  next?: (opties: { id: string }) => Promise<unknown>
  set?: (opties: { id: string }) => Promise<unknown>
  addListener?: (naam: string, cb: (info: { bundle?: BundleInfo }) => void) => unknown
}

export interface ManifestDto {
  geen_update: boolean
  reden?: string | null
  bundel_id?: string
  url?: string
  sha256?: string
  bytes?: number
  verplicht?: boolean
  runtime?: string
}

let huidigeBundelCache: string | null = null

export function updaterPlugin(): UpdaterPlugin | null {
  const cap = (window as { Capacitor?: { isNativePlatform?: () => boolean; Plugins?: { CapacitorUpdater?: UpdaterPlugin } } })
    .Capacitor
  if (!cap?.isNativePlatform?.()) return null
  const p = cap.Plugins?.CapacitorUpdater
  return p && typeof p.getCurrent === 'function' ? p : null
}

/** Id van de actieve webbundel (`builtin` = de in de winkel-build gebakken bundel); null buiten de schil/zonder plugin. */
export async function huidigeBundelId(): Promise<string | null> {
  const p = updaterPlugin()
  if (!p?.getCurrent) return null
  try {
    const c = await p.getCurrent()
    const id = c?.bundle?.version || c?.bundle?.id || null
    huidigeBundelCache = id
    return id
  } catch {
    return null
  }
}

/** Synchrone laatst-bekende bundel-id (voor request-headers) — gevuld door `huidigeBundelId()`/`otaBijStart()`. */
export function bekendeBundelId(): string | null {
  return huidigeBundelCache
}

function nu(): number {
  return Date.now()
}

function laatsteCheck(): number {
  try {
    return Number(localStorage.getItem(OTA_LAATSTE_CHECK_SLEUTEL) ?? 0) || 0
  } catch {
    return 0
  }
}

function markeerCheck(): void {
  try {
    localStorage.setItem(OTA_LAATSTE_CHECK_SLEUTEL, String(nu()))
  } catch {
    // opslag niet beschikbaar — dan checken we gewoon vaker
  }
}

export interface OtaUitkomst {
  stand: 'geen_plugin' | 'te_vroeg' | 'geen_update' | 'gedownload' | 'toegepast' | 'fout'
  bundel?: string
  reden?: string
}

/** Manifest → download → `next` (of `set` bij verplicht). `forceer` negeert de 15-minutengrens (tests/handmatig). */
export async function controleerOta(opties: { forceer?: boolean; melding?: (tekst: string) => void } = {}): Promise<OtaUitkomst> {
  const p = updaterPlugin()
  if (!p?.download) return { stand: 'geen_plugin' }
  if (!opties.forceer && nu() - laatsteCheck() < OTA_INTERVAL_MS) return { stand: 'te_vroeg' }
  markeerCheck()
  const huidig = (await huidigeBundelId()) ?? INGEBOUWD
  const platform = huidigPlatform()
  let manifest: ManifestDto
  try {
    const q = new URLSearchParams({ runtime: APP_MARKETING_VERSIE, platform, huidig })
    manifest = await apiJson<ManifestDto>(`/app/update-manifest?${q.toString()}`)
  } catch (err) {
    return { stand: 'fout', reden: err instanceof Error ? err.message : 'manifest niet gelezen' }
  }
  if (!manifest || manifest.geen_update || !manifest.bundel_id || !manifest.url) return { stand: 'geen_update', reden: manifest.reden ?? undefined }
  if (manifest.runtime && manifest.runtime !== APP_MARKETING_VERSIE) return { stand: 'geen_update', reden: 'andere runtime' }
  try {
    const bundle = await p.download({ url: manifest.url, version: manifest.bundel_id, checksum: manifest.sha256 })
    const id = bundle?.id ?? manifest.bundel_id
    if (manifest.verplicht && p.set) {
      opties.melding?.(OTA_VERPLICHT_MELDING)
      await p.set({ id })
      return { stand: 'toegepast', bundel: manifest.bundel_id }
    }
    if (p.next) await p.next({ id })
    return { stand: 'gedownload', bundel: manifest.bundel_id }
  } catch (err) {
    return { stand: 'fout', reden: err instanceof Error ? err.message : 'download mislukt' }
  }
}

/** Bij koude start: de plugin melden dat de bundel werkt (anders rolt hij ná 10 s terug), rollback-luisteraar zetten,
 * bundel-id cachen en één OTA-check doen. Buiten de schil een no-op. */
export async function otaBijStart(): Promise<void> {
  const p = updaterPlugin()
  if (!p) return
  try {
    await p.notifyAppReady?.()
  } catch {
    // de plugin kan het niet — dan rolt hij eventueel zelf terug, en meldt de luisteraar hieronder dat
  }
  try {
    p.addListener?.('updateFailed', (info) => {
      void meldRollback(info?.bundle?.version || info?.bundle?.id || '?', 'updateFailed')
    })
  } catch {
    // geen luisteraar — de diagnoseregel blijft de terugval tonen
  }
  await huidigeBundelId()
  void controleerOta()
}

/** Rollback → server (audit `ota_rollback`); fail-soft. */
export async function meldRollback(bundelId: string, reden: string): Promise<boolean> {
  try {
    const resp = await apiFetch('/app/update-melding', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bundel_id: bundelId, reden, app_versie: APP_MARKETING_VERSIE }),
    })
    return resp.ok
  } catch {
    return false
  }
}

// ---- Android in-app-update (Google Play, `@capawesome/capacitor-app-update`) --------------------------------------------

interface AppUpdatePlugin {
  getAppUpdateInfo?: () => Promise<{ updateAvailability?: number; immediateUpdateAllowed?: boolean; flexibleUpdateAllowed?: boolean }>
  performImmediateUpdate?: () => Promise<unknown>
  startFlexibleUpdate?: () => Promise<unknown>
  completeFlexibleUpdate?: () => Promise<unknown>
  openAppStore?: () => Promise<unknown>
}

const UPDATE_AVAILABLE = 2
export const INAPP_UPDATE_SLEUTEL = 'accordeur-inapp-update-laatste'
const INAPP_INTERVAL_MS = 24 * 60 * 60_000

export function appUpdatePlugin(): AppUpdatePlugin | null {
  const cap = (window as { Capacitor?: { isNativePlatform?: () => boolean; Plugins?: { AppUpdate?: AppUpdatePlugin } } }).Capacitor
  if (!cap?.isNativePlatform?.() || huidigPlatform() !== 'android') return null
  const p = cap.Plugins?.AppUpdate
  return p && typeof p.getAppUpdateInfo === 'function' ? p : null
}

/** IMMEDIATE als de server 426 gaf (schil onder het minimum), FLEXIBLE als de winkel een nieuwere versie heeft (max 1×/24 u).
 * iOS heeft geen API: daar toont het scherm alleen de winkelknop. */
export async function androidInAppUpdate(modus: 'immediate' | 'flexible'): Promise<'gestart' | 'geen' | 'geen_plugin'> {
  const p = appUpdatePlugin()
  if (!p?.getAppUpdateInfo) return 'geen_plugin'
  try {
    if (modus === 'flexible') {
      let laatst = 0
      try {
        laatst = Number(localStorage.getItem(INAPP_UPDATE_SLEUTEL) ?? 0) || 0
      } catch {
        laatst = 0
      }
      if (nu() - laatst < INAPP_INTERVAL_MS) return 'geen'
      try {
        localStorage.setItem(INAPP_UPDATE_SLEUTEL, String(nu()))
      } catch {
        // zonder opslag vaker proberen is onschuldig
      }
    }
    const info = await p.getAppUpdateInfo()
    if (info?.updateAvailability !== UPDATE_AVAILABLE) return 'geen'
    if (modus === 'immediate' && info.immediateUpdateAllowed !== false && p.performImmediateUpdate) {
      await p.performImmediateUpdate()
      return 'gestart'
    }
    if (info.flexibleUpdateAllowed !== false && p.startFlexibleUpdate) {
      await p.startFlexibleUpdate()
      await p.completeFlexibleUpdate?.()
      return 'gestart'
    }
    return 'geen'
  } catch {
    return 'geen'
  }
}

/** Alleen voor tests. */
export function resetOtaVoorTests(): void {
  huidigeBundelCache = null
  try {
    localStorage.removeItem(OTA_LAATSTE_CHECK_SLEUTEL)
    localStorage.removeItem(INAPP_UPDATE_SLEUTEL)
  } catch {
    // niets
  }
}
