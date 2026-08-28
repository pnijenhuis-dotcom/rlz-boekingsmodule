// Kantoor-web: eenmalige banner "Passkey toevoegen op dit apparaat?" (besluit Peter 28-08,
// mockup activatie-mobiel.html §3 — GEEN eigen push-login; de native QR-cross-device-passkey
// van de browser is de route). De banner verschijnt alléén ná een geslaagde cross-device-login
// (het moment waarop de gebruiker het nut net ervaren heeft) en hooguit 1× per apparaat.
// Puur + klein zodat de regel los van React getest wordt; storage-toegang altijd in try/catch
// (privéstand/uitgeschakelde storage = gewoon geen banner).

const CROSS_DEVICE_VLAG = 'passkey-crossdevice-login'
const BANNER_AFGEHANDELD = 'passkey-banner-afgehandeld'

/** LoginScreen roept dit aan als de assertion van een ánder apparaat kwam (QR-flow). */
export function markeerCrossDeviceLogin(): void {
  try {
    window.sessionStorage.setItem(CROSS_DEVICE_VLAG, '1')
  } catch {
    /* geen storage = geen banner */
  }
}

export function moetPasskeyBannerTonen(): boolean {
  try {
    return window.sessionStorage.getItem(CROSS_DEVICE_VLAG) === '1' && window.localStorage.getItem(BANNER_AFGEHANDELD) === null
  } catch {
    return false
  }
}

/** Beide keuzes ("Passkey toevoegen" én "Niet nu") sluiten de banner definitief voor dit apparaat. */
export function markeerPasskeyBannerAfgehandeld(): void {
  try {
    window.localStorage.setItem(BANNER_AFGEHANDELD, new Date().toISOString())
    window.sessionStorage.removeItem(CROSS_DEVICE_VLAG)
  } catch {
    /* idem */
  }
}
